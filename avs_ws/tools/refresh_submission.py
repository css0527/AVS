#!/usr/bin/env python3
"""Refresh named submission files from one verified continuous recording."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from zipfile import ZIP_DEFLATED, ZipFile

WORKSPACE = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording', type=Path)
    parser.add_argument('--id', default='B09018834')
    args = parser.parse_args()
    if not args.id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in args.id):
        raise ValueError('Submission ID must be a simple filename')
    recording = args.recording.resolve()
    metadata = json.loads((recording / 'recording.json').read_text())
    evidence = recording / 'evidence'
    evaluation = json.loads((evidence / 'evaluation.json').read_text())
    if not (metadata.get('status') == 'complete' and metadata.get('continuous')
            and evaluation.get('passed')):
        raise ValueError('A complete, continuous recording with passed acceptance is required')
    video = Path(metadata['video'])
    probe = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_entries',
        'format=duration,size:stream=codec_type,width,height', '-of', 'json', str(video)], text=True))
    duration = float(probe['format']['duration'])
    if duration > 300 or video.stat().st_size > 100_000_000:
        raise ValueError('Submission video exceeds duration or size limit')
    recorded_hashes = json.loads((evidence / 'source_sha256.json').read_text())
    cache_directories = {'__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache'}
    source_hashes = {name: expected for name, expected in recorded_hashes.items()
        if not set(Path(name).parts) & cache_directories and Path(name).suffix != '.pyc'}
    for name, expected in source_hashes.items():
        if digest(WORKSPACE / name) != expected:
            raise ValueError(f'Source changed after recording: {name}')
    target = WORKSPACE / 'submission'
    target.mkdir(exist_ok=True)
    (target / 'COLCON_IGNORE').touch()
    history = WORKSPACE / 'submission_history'
    history.mkdir(exist_ok=True)
    (history / 'COLCON_IGNORE').touch()
    backup = history / time.strftime('发布前_%Y%m%d_%H%M%S')
    backup.mkdir()
    for suffix in ['.mp4', '.pdf', '.zip']:
        old = target / (args.id + suffix)
        if old.exists():
            shutil.copy2(old, backup / old.name)
    wrapper = ('#!/usr/bin/env bash\nset -euo pipefail\n'
        'SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"\n'
        'chmod +x "$SCRIPT_DIR/start.sh" "$SCRIPT_DIR/avs_ws/start.sh"\n'
        'exec "$SCRIPT_DIR/avs_ws/start.sh" "$@"\n')
    with tempfile.TemporaryDirectory(prefix='avs_submission_') as temp:
        stage = Path(temp)
        generated = stage / 'generated'
        subprocess.run([sys.executable,
            str(WORKSPACE / 'src/avs_rescue_sim/tools/build_submission.py'),
            str(evidence), '--output', str(generated)], check=True)
        package = stage / args.id
        package.mkdir()
        with ZipFile(generated / 'avs_rescue_source.zip') as archive:
            # Last entry wins if an existing docs snapshot was replaced by
            # the explicit selected-run appendix in the source builder.
            entries = {info.filename: info for info in archive.infolist()}
            for name, info in entries.items():
                relative = Path(name)
                if relative.is_absolute() or '..' in relative.parts:
                    raise ValueError(f'Unsafe archive member: {name}')
                dest = package / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(archive.read(info))
                mode = stat.S_IMODE(info.external_attr >> 16)
                if mode:
                    dest.chmod(mode)
        (package / 'start.sh').write_text(wrapper)
        for shell in package.rglob('*.sh'):
            shell.chmod(shell.stat().st_mode | 0o111)
        packaged_ws = package / 'avs_ws'
        # Preserve the repeatable packaging tool, which lives outside ROS src.
        tools = packaged_ws / 'tools'
        tools.mkdir(exist_ok=True)
        for tool in (WORKSPACE / 'tools').glob('*.py'):
            shutil.copy2(tool, tools / tool.name)
        docs = packaged_ws / 'docs'
        recorded = dict(metadata)
        recorded['video'] = args.id + '.mp4'
        recorded['original_recording_directory'] = recording.name
        (docs / 'acceptance/recording.json').write_text(
            json.dumps(recorded, ensure_ascii=False, indent=2))
        result = json.loads((evidence / 'result.json').read_text())
        events = [dict(video_s=(event['wall'] - metadata['recording_started_at'])
            / metadata['playback_speed'], **event) for event in result['events']]
        (docs / 'submission_timeline.json').write_text(
            json.dumps(events, ensure_ascii=False, indent=2))
        for name, expected in source_hashes.items():
            if digest(packaged_ws / name) != expected:
                raise ValueError(f'Packaged source differs from recorded source: {name}')
        for required in ['src/avs_rescue_sim/package.xml',
                         'src/avs_rescue_plugins/package.xml',
                         'src/avs_rescue_sim/behavior_trees/navigate_to_pose_precision.xml',
                         'src/avs_rescue_sim/behavior_trees/turn_at_current_pose_precision.xml',
                         'docs/submission_voiceover.md', 'docs/submission_voiceover.txt']:
            if not (packaged_ws / required).exists():
                raise ValueError(f'Missing package file: {required}')
        manifest = dict(recording_directory=recording.name,
            continuous=True, acceptance_passed=True, playback_speed=metadata['playback_speed'],
            video_duration_s=duration, video_size_bytes=video.stat().st_size,
            source_files=len(source_hashes), source_hashes_match=True,
            recorded_manifest_entries=len(recorded_hashes),
            excluded_recorded_cache_entries=sorted(set(recorded_hashes) - set(source_hashes)),
            video_sha256=digest(video), report_sha256=digest(generated / 'technical_report.pdf'))
        (docs / 'submission_manifest.json').write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2))
        archive_path = stage / (args.id + '.zip')
        with ZipFile(archive_path, 'w', ZIP_DEFLATED) as archive:
            for path in sorted(package.rglob('*')):
                if path.is_file():
                    archive.write(path, path.relative_to(stage))
        with ZipFile(archive_path) as archive:
            if archive.testzip() is not None:
                raise ValueError('ZIP integrity check failed')
        # Back up and replace the extracted development copy as well as the
        # three named deliverables. Keep backups outside package discovery.
        old_package = target / args.id
        if old_package.exists():
            old_package.rename(backup / args.id)
        shutil.copytree(package, old_package)
        for src, suffix in [(video, '.mp4'), (generated / 'technical_report.pdf', '.pdf'),
                            (archive_path, '.zip')]:
            temporary = target / (args.id + suffix + '.tmp')
            shutil.copy2(src, temporary)
            os.replace(temporary, target / (args.id + suffix))
        print(json.dumps(dict(target=str(target), backup=str(backup), **manifest),
                         ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
