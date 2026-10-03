"""pytest fixtures for the LevelEditor smoke suite.

    python -m pytest smoke -q                       # launches the Release editor itself
    python -m pytest smoke -q --exe <path>          # a different build
    python -m pytest smoke -q --update-golden       # accept the current command surface

One editor process serves the whole run. It is restarted if a test kills it, so a crash fails exactly the
test that caused it (the exit code is in the failure) instead of every test after it.
"""
from __future__ import annotations

import itertools
import shutil
import time
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from harness import DEFAULT_EXE, GOLDEN_DIR, Editor, vulkan_messages_from_text


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


def _dismiss_modals(lv) -> None:
    """A modal left open by an earlier test (an error popup raised by something a test did on purpose) would sit over every test after it:
    Enter closes it."""
    for _ in range(5):
        if "Open=true" not in lv.cmd("ModalState"):
            return
        lv.ed.post_key(0x0D, hold=0.2)                        # VK_RETURN
        time.sleep(0.2)


SOCCER_LEVEL = "0166FAE5EB82F3F3"          # the Level of the example project that names a Game (the project's: SoccerGame is one of its modules)


def _open_level(editor, guid, name):
    editor.cmd("Close -Save 0")
    editor.cmd(f"OpenLevel -Level {guid} -Save 0")
    editor.wait_for("GetPlayState", r"Building=false", timeout=240)   # the Game.dll check of the Level must settle
    scenes = [(m[1], m[2].strip()) for l in editor.cmd(f"{name}\\ListScenes").splitlines()
              if (m := re.match(r"(\w{16})\s+(.*)", l))]
    lv = Level(editor, guid, name, scenes, itertools.count(1))
    _dismiss_modals(lv)
    yield lv
    if editor.alive():
        _dismiss_modals(lv)
        if editor.play_state() != "Stopped":
            editor.cmd("Stop -Keep false")
            editor.wait_play_state("Stopped")
        editor.cmd("Close -Save 0")


@pytest.fixture
def level(editor):
    guid, name = editor.levels()[0]
    yield from _open_level(editor, guid, name)


@pytest.fixture
def game_level(editor):
    """A Level that names a Game: its scripts, components and systems are the Game's. Only such a Level has a game module to build, load, reload or ask about."""
    guid, name = next((g, n) for g, n in editor.levels() if g.lstrip("0").upper() == SOCCER_LEVEL.lstrip("0"))
    yield from _open_level(editor, guid, name)


# --------------------------------------------------------------------------------------------------------------------
# Problem report. Everything that went wrong inside the editor while the suite ran is collected and printed at the end:
#   * asserts, terminate and crash lines  - the editor appends them to LevelEditor.problems.log next to the exe (never truncated)
#   * Vulkan validation errors/warnings   - they only go to the editor's stdout, which the harness keeps in smoke/.logs/editor_N.log
# An assert or a Vulkan validation error fails the run: it is a bug, whatever the tests said. Warnings are listed.
# --------------------------------------------------------------------------------------------------------------------
def _problems_path(config) -> Path:
    return Path(config.getoption("--exe")).parent / "LevelEditor.problems.log"


def pytest_sessionstart(session):
    shutil.rmtree(Path(__file__).parent / ".logs" / "sessions", ignore_errors=True)       # the launches of the tests start from nothing: retention keeps crashes over clean ones, so history from earlier runs would decide what a test finds
    session.config._logs_vulkan = {}                  # what the editor's Logs held of the validation layers' complaints, collected after each test (the editor may be restarted)
    p = _problems_path(session.config)
    session.config._problems_offset = p.stat().st_size if p.exists() else 0
    for old in [*(Path(__file__).parent / ".logs").glob("editor_*.log"), *(Path(__file__).parent / ".logs").glob("trace_*.log")]:
        try:
            old.unlink()                  # only this run's output is reported
        except OSError:
            pass


@pytest.fixture(autouse=True)
def _vulkan_from_the_logs(request, editor):
    """After every test: the Vulkan validation problems the editor's Logs hold (the harness as a client of the Logs, next to its reading of the text)."""
    yield
    if editor.alive():
        try:
            for row in editor.vulkan_problems():
                request.config._logs_vulkan[(editor.proc.pid, row["Id"])] = row
        except Exception:                             # a pipe that is gone with the editor: the text matching still has it
            pass


def _logs_vulkan(config):
    errors, warnings = {}, {}
    for row in getattr(config, "_logs_vulkan", {}).values():
        target = errors if row["Severity"] in ("error", "fatal") else warnings
        target[row["Title"].strip()] = target.get(row["Title"].strip(), 0) + int(row["Occurrences"])
    return errors, warnings


def _parity(text_side: dict, logs_side: dict) -> list[str]:
    """Messages one source has and the other does not (compared on their first 80 characters)."""
    def known(m, others): return any(m[:80] == o[:80] for o in others)
    return [f"only in the text: {m[:100]}" for m in text_side if not known(m, logs_side)] + [f"only in the Logs: {m[:100]}" for m in logs_side if not known(m, text_side)]


def _collect_problems(config):
    p = _problems_path(config)
    new = []
    if p.exists():
        with open(p, "rb") as f:
            f.seek(getattr(config, "_problems_offset", 0))
            new = [l for l in f.read().decode("utf-8", "replace").splitlines() if l.strip()]
    vk, vk_warnings = {}, {}
    for log in sorted((Path(__file__).parent / ".logs").glob("editor_*.log")):
        errors, warnings = vulkan_messages_from_text(log.read_text(errors="replace"))
        for m, n in errors.items(): vk[m] = vk.get(m, 0) + n
        for m, n in warnings.items(): vk_warnings[m] = vk_warnings.get(m, 0) + n
    asserts = [l for l in new if "CRT report" in l]
    return new, asserts, vk, vk_warnings


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    new, asserts, vk, vk_warnings = _collect_problems(config)
    logs_err, logs_warn = _logs_vulkan(config)
    differences = _parity(vk, logs_err) + _parity(vk_warnings, logs_warn)
    tr = terminalreporter
    tr.section("editor problem report")
    if differences:
        for d in differences:
            tr.write_line("Logs vs text parity: " + d, yellow=True)
    if not new and not vk and not vk_warnings and not logs_err and not logs_warn:
        tr.write_line("no asserts, crashes or Vulkan errors were logged")
        return
    for msg, n in sorted(logs_err.items(), key=lambda kv: -kv[1]):
        if msg not in vk: tr.write_line(f"Vulkan validation error (from the Logs) x{n}: {msg[:160]}", red=True)
    for msg, n in sorted(logs_warn.items(), key=lambda kv: -kv[1]):
        if msg not in vk_warnings: tr.write_line(f"Vulkan validation warning (from the Logs) x{n}: {msg[:160]}", yellow=True)
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
    logs_err, _ = _logs_vulkan(session.config)
    if (asserts or vk or logs_err) and session.exitstatus == 0:      # a Vulkan validation error is a bug too: the draw is wrong, whatever the tests said
        session.exitstatus = 1
