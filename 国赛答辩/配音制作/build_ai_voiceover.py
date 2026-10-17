#!/usr/bin/env python3
"""Offline Mandarin narration, placed in verified picture windows. No subtitles.

Requires numpy, sherpa-onnx and ffmpeg. Download the model separately, then run:
  PYTHONPATH=/tmp/avs_tts_deps python3 build_ai_voiceover.py --model-dir MODEL_DIR
The existing film is never overwritten by this script.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
import wave

import numpy as np
import sherpa_onnx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def run(args):
    return subprocess.check_output(args, stderr=subprocess.STDOUT).decode().strip()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda: f.read(2**20), b''):
            h.update(part)
    return h.hexdigest()


def probe(path):
    return json.loads(run(['ffprobe', '-v', 'error', '-show_streams',
                           '-show_format', '-of', 'json', str(path)]))


def video_hash(path):
    return run(['ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:v:0',
                '-c:v', 'copy', '-f', 'hash', '-hash', 'sha256', '-'])


def wav(path, samples, sr):
    pcm = (np.clip(samples, -1, 1) * 32767).astype('<i2')
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes(pcm.tobytes())


def trim(samples, sr):
    """Trim boundary silence, preserving a short lead and the final consonants."""
    samples = np.asarray(samples, dtype=np.float32)
    active = np.flatnonzero(np.abs(samples) > 0.003)
    if len(active) == 0:
        raise ValueError('Synthesis produced silence')
    lo = max(0, int(active[0]) - int(0.055 * sr))
    hi = min(len(samples), int(active[-1]) + int(0.110 * sr))
    return samples[lo:hi].copy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model-dir', type=Path, required=True)
    ap.add_argument('--speaker-id', type=int, default=3)
    ap.add_argument('--voice-name', default='zf_001')
    ap.add_argument('--threads', type=int, default=4)
    args = ap.parse_args()
    plan = json.loads((HERE / '配音时间线.json').read_text())
    model_dir = args.model_dir.resolve()
    candidates = sorted(model_dir.glob('*.onnx'))
    if len(candidates) != 1:
        raise ValueError(f'Expected one ONNX model in {model_dir}')
    model = candidates[0]
    config = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                model=str(model), voices=str(model_dir / 'voices.bin'),
                tokens=str(model_dir / 'tokens.txt'),
                data_dir=str(model_dir / 'espeak-ng-data'),
                lexicon=','.join(str(model_dir / n) for n in
                                 ['lexicon-us-en.txt', 'lexicon-zh.txt']),
            ),
            num_threads=args.threads,
        ),
        max_num_sentences=1,
    )
    if not config.validate():
        raise ValueError('Invalid offline model configuration')
    tts = sherpa_onnx.OfflineTts(config)
    sr = tts.sample_rate
    sentence_pause = float(plan.get('sentence_pause_seconds', 0.40))
    base_speed = float(plan.get('speech_speed', 0.95))

    def speak(text, speed):
        # Render whole sentences. Leave short commas to the voice model, and
        # control full stops explicitly so a sentence cannot run into the next.
        sentences = re.findall(r'[^。！？]+[。！？]?', text)
        parts = []
        for index, sentence in enumerate(sentences):
            generated = tts.generate(sentence, sid=args.speaker_id, speed=speed)
            speech = trim(generated.samples, sr)
            if index:
                # trim() keeps 55 ms before and 110 ms after speech. Include
                # those margins in the measured sentence pause, rather than
                # silently adding them to it.
                parts.append(np.zeros(round(max(0, sentence_pause - 0.165) * sr), dtype=np.float32))
            parts.append(speech)
        return np.concatenate(parts)
    mix = np.zeros(round(plan['video_duration_seconds'] * sr), dtype=np.float32)
    clips = HERE / '分段音频'
    clips.mkdir(exist_ok=True)
    rows = []
    last_end = 0.0
    for seg in plan['segments']:
        start, limit = seg['start'], seg['end']
        if start < last_end or limit > plan['video_duration_seconds']:
            raise ValueError(f'Invalid voice window: {seg["id"]}')
        room = limit - start - 0.10
        speed = base_speed
        samples = None
        # Resynthesize at adjusted speed rather than cutting words or moving video.
        for attempt in range(4):
            samples = speak(seg['text'], speed)
            length = len(samples) / sr
            if length > room:
                speed = round(speed * length / room * 1.025, 4)
                if speed > 1.25:
                    raise ValueError(f'Segment {seg["id"]} needs a shorter script')
                continue
            break
        else:
            raise ValueError(f'Segment {seg["id"]} did not fit its picture window')
        length = len(samples) / sr
        if length > room:
            raise ValueError('Speech overrun')
        # Tiny fades prevent clicks at joins; they do not remove speech content.
        fade = min(round(0.007 * sr), len(samples) // 4)
        samples[:fade] *= np.linspace(0, 1, fade)
        samples[-fade:] *= np.linspace(1, 0, fade)
        index = round(start * sr)
        mix[index:index + len(samples)] = samples
        path = clips / f'{seg["id"]:02d}.wav'
        wav(path, samples, sr)
        row = dict(seg, actual_start=start, actual_end=round(start + length, 4),
                   speech_seconds=round(length, 4), synthesis_speed=speed,
                   audio_file=str(path.relative_to(ROOT)), sha256=sha(path))
        rows.append(row)
        last_end = start + length
        print(json.dumps(row, ensure_ascii=False), flush=True)

    raw = HERE / 'AI女声_对齐原始.wav'
    master = HERE / 'AI女声_完整配音.wav'
    mp3 = HERE / 'AI女声_完整配音.mp3'
    wav(raw, mix, sr)
    run(['ffmpeg', '-v', 'error', '-y', '-i', str(raw), '-af',
         'loudnorm=I=-17:TP=-1.5:LRA=9', '-ar', '48000', '-ac', '1', str(master)])
    run(['ffmpeg', '-v', 'error', '-y', '-i', str(master), '-c:a',
         'libmp3lame', '-b:a', '160k', str(mp3)])
    source, output = ROOT / plan['source_video'], ROOT / plan['output_video']
    run(['ffmpeg', '-v', 'error', '-y', '-i', str(source), '-i', str(master),
         '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac',
         '-b:a', '160k', '-ar', '48000', '-ac', '1', '-map_metadata', '-1',
         '-movflags', '+faststart', '-t', str(plan['video_duration_seconds']),
         str(output)])
    final = probe(output)
    original = probe(source)
    video_same = video_hash(source) == video_hash(output)
    media = final['streams']
    checks = dict(
        video_stream_bit_identical=video_same,
        video_frames=int(next(s for s in media if s['codec_type'] == 'video')['nb_frames']),
        original_video_frames=int(next(s for s in original['streams']
                                       if s['codec_type'] == 'video')['nb_frames']),
        audio_streams=sum(s['codec_type'] == 'audio' for s in media),
        subtitle_streams=sum(s['codec_type'] == 'subtitle' for s in media),
        old_audio_mixed=False,
        audio_source='Only the synthesized master; explicit ffmpeg mapping 1:a:0',
        all_segments_within_picture_windows=all(r['actual_end'] <= r['end'] for r in rows),
        segment_count=len(rows),
    )
    assert video_same and checks['audio_streams'] == 1 and checks['subtitle_streams'] == 0
    assert checks['all_segments_within_picture_windows']
    result = dict(status='complete', engine='sherpa-onnx / Kokoro v1.1 Chinese (offline)',
                  voice=args.voice_name, speaker_id=args.speaker_id,
                  voice_preference='普通话女声', model_sha256=sha(model),
                  sentence_pause_seconds=sentence_pause, base_speech_speed=base_speed,
                  model_source='https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/kokoro.html',
                  audio= str(master.relative_to(ROOT)), audio_sha256=sha(master),
                  video=str(output.relative_to(ROOT)), video_sha256=sha(output),
                  duration_seconds=float(final['format']['duration']),
                  speech_cjk_characters=len(re.findall(r'[\u4e00-\u9fff]', ''.join(r['text'] for r in rows))),
                  subtitles=False, checks=checks, segments=rows)
    (HERE / '音画核对.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    plan['status'] = 'complete'
    plan['engine'] = result['engine']
    plan['voice'] = result['voice']
    (HERE / '配音时间线.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(checks, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
