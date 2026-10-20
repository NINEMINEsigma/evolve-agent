"""Backward-compatible wrapper. Use validate-video.py for localized projects."""
from pathlib import Path
import runpy
import sys

script = Path(__file__).with_name("validate-video.py")
sys.argv[0] = str(script)
runpy.run_path(str(script), run_name="__main__")
