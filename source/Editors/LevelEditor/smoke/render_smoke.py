"""render_smoke: the smoke tests that draw through xLIONRender, and nothing else (renderer, xGPU and material work).

    python render_smoke.py            run them (pytest -q, a short traceback)
    python render_smoke.py -v         and list each test

Covers the resource editors that render with xLIONRender (their previews and thumbnails): Material, MaterialInstance,
GeomStatic, GeomSkin. The editor problem report at the end still fails the run on any assert, crash or Vulkan error.
The renderer's own tests (dependencies/xLIONRender/Build/test) are the first line; this is the editor-side check.
"""
import subprocess
import sys
from pathlib import Path

SMOKE = Path(__file__).resolve().parent

# test ids of the smoke suite whose editors draw with xLIONRender
TESTS = [f"test_resource_editors.py::test_open_resource_editor[{kind}]" for kind in ("Material", "MaterialInstance", "GeomStatic", "GeomSkin")]


def main(argv) -> int:
    verbose = "-v" in argv
    return subprocess.call([sys.executable, "-m", "pytest", *TESTS, "-v" if verbose else "-q", "--tb=short"], cwd=SMOKE)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
