"""Regenerate every README diagram: python docs/assets/src/make.py

Needs Python 3.10+ with `pip install -r docs/assets/src/requirements.txt`. Fetches the pinned fonts and icons
first (fetch.py), then writes docs/assets/{hero,sim-loop,loops,toolchain,blender-pipeline}.svg. Text is converted
to glyph outlines, so the SVGs render identically on every OS.

The social card is the one manual step: `python social.py ../_social.svg ../showcase/truebeam-mid-arc.jpg`, open
it at exactly 1280 x 640 in a browser, screenshot it to docs/assets/social-preview.png, and delete _social.svg.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.dirname(HERE)
JOBS = [("hero.py", "hero.svg"), ("simloop.py", "sim-loop.svg"), ("loops.py", "loops.svg"),
        ("toolchain.py", "toolchain.svg"), ("pipeline.py", "blender-pipeline.svg")]


def main():
    if subprocess.call([sys.executable, os.path.join(HERE, "fetch.py")]) != 0:
        return 1
    for script, out in JOBS:
        rc = subprocess.call([sys.executable, os.path.join(HERE, script), os.path.join(ASSETS, out)], cwd=HERE)
        if rc != 0:
            print("FAILED:", script)
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
