#!/usr/bin/env python3
"""Create the local source ZIP and a factual report from acceptance measurements."""
import argparse
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from build_technical_report import build_report

WORKSPACE=Path(__file__).resolve().parents[3]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('acceptance',type=Path)
    parser.add_argument('--output',type=Path,default=WORKSPACE/'submission',
                        help='Output directory for the source ZIP and PDF report.')
    args=parser.parse_args()
    # Fail before publishing artifacts if the selected measurement is missing.
    json.loads((args.acceptance/'evaluation.json').read_text())
    target=args.output;target.mkdir(parents=True,exist_ok=True)
    build_report(WORKSPACE/'TECHNICAL_REPORT.md', target/'technical_report.pdf',
                 acceptance=args.acceptance)
    with ZipFile(target/'avs_rescue_source.zip','w',ZIP_DEFLATED) as archive:
        for directory in ['src','docs']:
            for path in (WORKSPACE/directory).rglob('*'):
                if (path.is_file()
                        and not set(path.parts) & {'__pycache__', '.pytest_cache',
                                                   '.mypy_cache', '.ruff_cache'}
                        and path.suffix not in ['.pyc']):
                    archive.write(path,Path('avs_ws')/path.relative_to(WORKSPACE))
        for path in WORKSPACE.glob('*.sh'):archive.write(path,Path('avs_ws')/path.name)
        archive.write(WORKSPACE/'README.md','avs_ws/README.md')
        archive.write(WORKSPACE/'TECHNICAL_REPORT.md','avs_ws/TECHNICAL_REPORT.md')
        archive.write(args.acceptance/'evaluation.json','avs_ws/docs/acceptance_evaluation.json')
        for name in ['trajectory.png','slam_map.pgm','slam_map.yaml','slam_map.png','source_sha256.json']:
            path=args.acceptance/name
            if path.is_file():
                archive.write(path,Path('avs_ws/docs/acceptance')/name)
    print(target)


if __name__=='__main__':main()
