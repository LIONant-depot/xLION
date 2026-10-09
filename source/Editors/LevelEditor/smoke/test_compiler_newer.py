"""A resource that was compiled by an older build of its compiler is compiled again: the compiler is one of the things a resource is made from.

The asset manager already compiled a resource whose descriptor or source files are newer than its output; this is the same rule for the compiler's own
executable. It must not loop either: a compiler that is not newer than the output (or than the last attempt) leaves the resource alone.
"""
import os
import time
from pathlib import Path

import pytest

from harness import REPO, Editor

pytestmark = pytest.mark.no_editor          # the test starts and stops its own editors: the compiler must be touched while none is running

FONT_COMPILER_NAMES = ("xfont_compiler", "xfont_compiler.exe")


def _project() -> Path:
    return Path(os.environ.get("XLION_PROJECT") or REPO / "example.lionprj")


def _font_compilers(project: Path) -> list[Path]:
    """Every built configuration of the font compiler (Windows: <plugin>/Build/xfont_compiler.vs2022/<Config>/xfont_compiler.exe, Linux: .../xfont_compiler.linux/<Config>/xfont_compiler)."""
    build = project / "Cache" / "Plugins" / "xfont.plugin" / "Build"
    return [p for p in build.glob("xfont_compiler.*/*/*") if p.is_file() and p.name in FONT_COMPILER_NAMES]


def _font_resources(project: Path) -> list[Path]:
    return [p for p in (project / "Cache" / "Resources" / "Platforms").glob("*/Font/*/*/*") if p.is_file()]


def _newest(paths: list[Path]) -> float:
    return max(p.stat().st_mtime_ns for p in paths) / 1e9


def _run_editor(exe: Path, seconds: float, until=None) -> None:
    """An editor on the project for at most `seconds` (less when `until()` says so), then closed."""
    ed = Editor(exe)
    ed.start()
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not (until and until()):
            time.sleep(0.5)
    finally:
        ed.stop()


def test_a_compiler_built_after_its_resources_compiles_them_again(request):
    exe     = Path(request.config.getoption("--exe"))
    project = _project()
    compilers = _font_compilers(project)
    if not compilers:
        pytest.skip("the font compiler is not built in this project")

    # The project's font resources exist and are up to date (an editor compiles whatever is missing at startup)
    if not _font_resources(project):
        _run_editor(exe, 180, until=lambda: bool(_font_resources(project)))
    resources = _font_resources(project)
    assert resources, "the project has no compiled font resource to watch"

    # A compiler that is not newer than the resources leaves them alone
    before = _newest(resources)
    _run_editor(exe, 20)
    assert _newest(_font_resources(project)) == before, "the font resources were compiled again although their compiler did not change"

    # The compiler is built again (its executable's time is now): the next editor compiles every font again
    time.sleep(1.1)                                 # file times can be a second apart
    for c in compilers:
        os.utime(c, None)
    _run_editor(exe, 180, until=lambda: _newest(_font_resources(project)) > before)
    assert _newest(_font_resources(project)) > before, "a compiler built after its resources did not make the editor compile them again"

    # ...and only once: the resources are now newer than the compiler
    after = _newest(_font_resources(project))
    _run_editor(exe, 20)
    assert _newest(_font_resources(project)) == after, "the font resources were compiled again and again after their compiler was built"
