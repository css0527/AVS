#!/usr/bin/env python3
"""Compatibility entry point for the maintained report generator."""
from pathlib import Path
import runpy

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parents[1] /
        'src/avs_rescue_sim/tools/build_technical_report.py'), run_name='__main__')
