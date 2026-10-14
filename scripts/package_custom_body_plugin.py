"""Compatibility packaging entry point for the complete standalone rig."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("package_integrated_rig.py")), run_name="__main__")
