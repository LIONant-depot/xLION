"""pytest fixtures for the LevelEditor smoke suite.

    python -m pytest smoke -q                       # launches the Release editor itself
    python -m pytest smoke -q --exe <path>          # a different build
    python -m pytest smoke -q --update-golden       # accept the current command surface

One editor process serves the whole run. It is restarted if a test kills it, so a crash fails exactly the
test that caused it (the exit code is in the failure) instead of every test after it.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from harness import DEFAULT_EXE, GOLDEN_DIR, Editor


def pytest_addoption(parser):
    parser.addoption("--exe", default=str(DEFAULT_EXE), help="xGPU_unit_test.exe to launch")
    parser.addoption("--update-golden", action="store_true", help="rewrite golden files from the running editor")


@pytest.fixture(scope="session")
def editor(request):
    ed = Editor(Path(request.config.getoption("--exe")))
    ed.start()
    yield ed
    ed.stop()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    if call.when == "call":
        item.call_failed = outcome.get_result().failed


@pytest.fixture(autouse=True)
def _editor_alive(request, editor):
    """Restart a dead editor before each test; fail the test that killed it (once)."""
    editor.ensure_running()
    yield
    if not editor.alive() and not getattr(request.node, "call_failed", False):
        pytest.fail(f"editor crashed during this test (exit {editor.describe_exit()}); log: {editor.log_dir}", pytrace=False)


@dataclass
class Level:
    """The example project's first level, opened clean. Everything a test creates lives only in memory."""
    ed: Editor
    guid: str
    name: str
    scenes: list                      # [(guid, name)]
    _ids: itertools.count

    @property
    def scene(self) -> str:
        return self.scenes[0][0]

    def cmd(self, line: str, **kw) -> str:
        return self.ed.cmd(f"{self.name}\\{line}", **kw)

    def ok(self, line: str, **kw) -> None:
        self.ed.ok(f"{self.name}\\{line}", **kw)

    def new_entity(self, scene: str | None = None) -> str:
        """Creates an empty entity with a fresh id and returns the id."""
        entity = f"7E57{next(self._ids):04X}"
        self.ok(f"CreateEntity -Scene {scene or self.scene} -Id {entity} -Folder 0")
        return entity

    def entities(self, scene: str | None = None) -> dict:
        return self.ed.entities(self.name, scene or self.scene)

    def describe(self, entity: str, scene: str | None = None) -> str:
        return self.ed.describe(self.name, scene or self.scene, entity)

    def dirty(self) -> bool:
        return next(s.dirty for s in self.ed.sessions() if s.name == self.name)

    def find_with_component(self, component: str):
        """(scene, entity, component guid) of the first existing entity that has the named component."""
        for scene, _ in self.scenes:
            for entity in self.entities(scene):
                m = re.search(rf"\[(\w{{16}})\] {re.escape(component)}", self.describe(entity, scene))
                if m:
                    return scene, entity, m[1]
        pytest.skip(f"the example project has no entity with a {component} component")

    def property_type(self, entity: str, path: str, scene: str | None = None) -> str:
        """The TypeGuid DescribeEntity prints next to a property."""
        m = re.search(rf"{re.escape(path)} = \S+\s+\(TypeGuid (\w+)\)", self.describe(entity, scene))
        assert m, f"{path} not on {entity}"
        return m[1]


@pytest.fixture
def level(editor):
    guid, name = editor.levels()[0]
    editor.cmd("Close -Save 0")
    editor.cmd(f"OpenLevel -Level {guid} -Save 0")
    editor.wait_for("GetPlayState", r"Building=false", timeout=120)   # the startup Game.dll check must settle
    scenes = [(m[1], m[2].strip()) for l in editor.cmd(f"{name}\\ListScenes").splitlines()
              if (m := re.match(r"(\w{16})\s+(.*)", l))]
    lv = Level(editor, guid, name, scenes, itertools.count(1))
    yield lv
    if editor.alive():
        if editor.play_state() != "Stopped":
            editor.cmd("Stop -Keep false")
            editor.wait_play_state("Stopped")
        editor.cmd("Close -Save 0")


# --------------------------------------------------------------------------------------------------------------------
# Problem report. Everything that went wrong inside the editor while the suite ran is collected and printed at the end:
#   * asserts, terminate and crash lines  - the editor appends them to LevelEditor.problems.log next to the exe (never truncated)
#   * Vulkan validation errors/warnings   - they only go to the editor's stdout, which the harness keeps in smoke/.logs/editor_N.log
# An assert or a Vulkan validation error fails the run: it is a bug, whatever the tests said. Warnings are listed.
# --------------------------------------------------------------------------------------------------------------------
def _problems_path(config) -> Path:
    return Path(config.getoption("--exe")).parent / "LevelEditor.problems.log"


def pytest_sessionstart(session):
    p = _problems_path(session.config)
    session.config._problems_offset = p.stat().st_size if p.exists() else 0
    for old in (Path(__file__).parent / ".logs").glob("editor_*.log"):
        try:
            old.unlink()                  # only this run's output is reported
        except OSError:
            pass


def _collect_problems(config):
    p = _problems_path(config)
    new = []
    if p.exists():
        with open(p, "rb") as f:
            f.seek(getattr(config, "_problems_offset", 0))
            new = [l for l in f.read().decode("utf-8", "replace").splitlines() if l.strip()]
    vk, vk_warnings = {}, {}
    for log in sorted((Path(__file__).parent / ".logs").glob("editor_*.log")):
        text = log.read_text(errors="replace")
        for m in re.finditer(r"ERROR VK\d \([A-Z_]+\):\s*\n?([^\n]{0,200})", text):
            vk[m[1].strip()] = vk.get(m[1].strip(), 0) + 1
        for m in re.finditer(r"WARNING VK\d \([A-Z_]+\):\s*\n?([^\n]{0,200})", text):
            vk_warnings[m[1].strip()] = vk_warnings.get(m[1].strip(), 0) + 1
    asserts = [l for l in new if "CRT report" in l]
    return new, asserts, vk, vk_warnings


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    new, asserts, vk, vk_warnings = _collect_problems(config)
    tr = terminalreporter
    tr.section("editor problem report")
    if not new and not vk and not vk_warnings:
        tr.write_line("no asserts, crashes or Vulkan errors were logged")
        return
    if asserts:
        tr.write_line(f"{len(asserts)} ASSERT/CRT report(s) - see {_problems_path(config)}", red=True)
    for l in new[:40]:
        tr.write_line("  " + l[:300])
    if len(new) > 40:
        tr.write_line(f"  ... {len(new) - 40} more lines in the file")
    for msg, n in sorted(vk.items(), key=lambda kv: -kv[1]):
        tr.write_line(f"Vulkan validation error x{n}: {msg[:160]}", red=True)
    for msg, n in sorted(vk_warnings.items(), key=lambda kv: -kv[1]):
        tr.write_line(f"Vulkan validation warning x{n}: {msg[:160]}", yellow=True)


def pytest_sessionfinish(session, exitstatus):
    _, asserts, vk, _ = _collect_problems(session.config)
    if (asserts or vk) and session.exitstatus == 0:      # a Vulkan validation error is a bug too: the draw is wrong, whatever the tests said
        session.exitstatus = 1
