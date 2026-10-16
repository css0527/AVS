#!/usr/bin/env python3
"""Build the current problem–solution–innovation defense deck.

The previous 23-page builder is preserved in 历史版本/问题方案创新重构前_*.
The current content source is roadshow_content.json.
"""
from pathlib import Path
import runpy

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).with_name('build_roadshow_ppt.py')), run_name='__main__')
