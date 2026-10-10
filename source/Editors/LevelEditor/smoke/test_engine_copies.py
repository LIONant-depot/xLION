"""The copies of the engine DLLs that a Level runs on (plugins/xlevel.plugin/source/Editor/xlevel_engine_copies.h): renamed copies of the core and the render DLL, loaded under their own names, each with a registry of
its own, so that several Levels can run side by side without sharing anything."""
import os
import re
import time

# the copy of LIONCore.dll is LC000004.dll; on Linux the copy of libLIONCore.so is libLC000004.so
LIB, EXT = ("", "dll") if os.name == "nt" else ("lib", "so")
COPIES = "EngineCopies"


def file_of(module: str) -> str:
    """The file of a module name: the name itself on Windows, "LC000001.dll" -> "libLC000001.so" on Linux."""
    return module if os.name == "nt" else LIB + module[:-4] + "." + EXT


def fields(reply):
    return dict(line.split("=", 1) for line in reply.splitlines() if "=" in line)


def copies_on_disk(editor, wait=2.0):
    """The copies in the folder; waits a little for the ones that are being deleted (the file of a module that was just freed can stay locked for a moment)."""
    folder = editor.exe.parent / COPIES
    if os.name != "nt":
        folder = folder / str(editor.proc.pid)              # on Linux each process keeps its copies in a folder of its own (xlevel_engine_copies.h, CleanLeftovers)
    deadline = time.monotonic() + wait
    while True:
        found = sorted(p.name for p in folder.glob(f"{LIB}L[CR]??????.{EXT}")) if folder.is_dir() else []
        if not found or time.monotonic() > deadline:
            return found
        time.sleep(0.1)


def settled_copies(editor, quiet=1.0, timeout=15.0):
    """The copies in the folder once they stop changing: the editors that were just closed free theirs a frame later."""
    deadline = time.monotonic() + timeout
    last, since = None, time.monotonic()
    while time.monotonic() < deadline:
        now = copies_on_disk(editor, wait=0)
        if now != last:
            last, since = now, time.monotonic()
        elif time.monotonic() - since >= quiet:
            return now
        time.sleep(0.1)
    return last


def test_a_set_of_copies_has_a_registry_of_its_own(editor):
    reply = editor.cmd("ProbeEngineSet")
    assert reply.startswith("ProbeEngineSet: ok"), reply
    got = fields(reply)
    assert re.fullmatch(r"LC\d{6}\.dll", got["Core"]), "the core copy is named after its set, as long as the original"
    assert got["Independent"] == "yes", "registering in the copy does not touch the registry of this Level's core"
    m = re.search(r"copy (\d+) -> (\d+) types, this Level (\d+) -> (\d+) types", reply)
    before, after, mine_before, mine_after = map(int, m.groups())
    assert before == 0 and after > 0 and mine_before == mine_after > 0


def test_the_render_copy_is_bound_to_its_own_core(editor):
    got = fields(editor.cmd("ProbeEngineSet"))
    if got["Render"] == "none":
        return                                              # a build without the render DLL: nothing to bind
    assert re.fullmatch(r"LR\d{6}\.dll", got["Render"])          # the module names keep their Windows spelling on every system
    assert got["RenderImportsCore"] == file_of(got["Core"]), "the import of LIONCore.dll was renamed to the copy of this set"
    assert got["RenderEditor"] == "ok", "the copy loads and hands out its editor interface"
    assert got["Checksum"] == "ok", "the PE checksum was fixed after the import table was patched"


def test_a_set_is_gone_when_it_is_released(editor):
    held = settled_copies(editor)                           # the sets of the editors that are open (every Level, and the one that stands in for none, runs on its own)
    for _ in range(2):
        editor.cmd("ProbeEngineSet")
        assert copies_on_disk(editor) == held, "the modules are freed and the files deleted with the set"


def test_every_open_level_runs_on_copies_of_its_own(level, editor):
    held = settled_copies(editor)
    assert len([n for n in held if n.startswith(LIB + "LC")]) >= 2, "the editor that stands in and the Level each have a core of their own"
    editor.cmd("Close -Save 0")
    assert len(settled_copies(editor)) < len(held), "closing the Level frees its copies"


def test_two_sets_do_not_share_names(editor):
    first = fields(editor.cmd("ProbeEngineSet"))["Core"]
    second = fields(editor.cmd("ProbeEngineSet"))["Core"]
    assert first != second, "every set gets a number of its own"


# ---- Levels that are open together share nothing of the engine ---------------------------------------------------------------------------------------------------------------------

MY_TEST_LEVEL = "6162BB6775AC3293"            # names no Game
SOCCER_LEVEL = "0166FAE5EB82F3F3"             # names the project's Game (module SoccerGame)


def test_two_levels_open_together_have_registries_of_their_own(editor):
    """Each Level has its own core, its own render DLL and its own Game.dll: the components of the Game of one are not in the registry of the other."""
    editor.cmd("Close -Save 0")
    names = dict(editor.levels())
    try:
        assert editor.cmd(f"OpenLevel -Level {SOCCER_LEVEL} -Save 0").startswith("Opened Level")
        editor.wait_for("GetPlayState", r"Building=false", timeout=240)
        assert editor.cmd(f"OpenLevel -Level {MY_TEST_LEVEL} -Save 0").startswith("Opened Level")
        assert {names[SOCCER_LEVEL], names[MY_TEST_LEVEL]} <= {s.name for s in editor.sessions()}, "both are open at the same time"

        soccer = editor.cmd(f"{names[SOCCER_LEVEL]}\\ListComponentTypes")
        plain = editor.cmd(f"{names[MY_TEST_LEVEL]}\\ListComponentTypes")
        assert "SoccerBall" in soccer, "the Level of the Game has its components"
        assert "SoccerBall" not in plain, "the Level with no Game has none of the Game's: its registry is its own"
        assert len(soccer.splitlines()) > len(plain.splitlines())
        assert "Transform" in soccer and "Transform" in plain, "both have the engine's"

    finally:
        editor.cmd("Close -Save 0")
        editor.cmd("Close -Save 0")


def test_two_levels_can_play_at_the_same_time_and_stop_on_their_own(editor):
    """There is no Play lock any more: every Level runs on its own core, so a Level of one Game plays next to a Level of none, and stopping one leaves the other playing."""
    editor.cmd("Close -Save 0")
    names = dict(editor.levels())
    soccer, plain = names[SOCCER_LEVEL], names[MY_TEST_LEVEL]

    def state(name):
        return re.search(r"PlayState=(\w+)", editor.cmd(f"{name}\\GetPlayState"))[1]

    def wait(name, wanted, timeout=120):
        deadline = time.monotonic() + timeout
        while state(name) != wanted:
            assert time.monotonic() < deadline, f"{name} did not reach {wanted}"
            time.sleep(0.2)

    try:
        assert editor.cmd(f"OpenLevel -Level {SOCCER_LEVEL} -Save 0").startswith("Opened Level")
        editor.wait_for("GetPlayState", r"Building=false", timeout=240)
        assert editor.cmd(f"OpenLevel -Level {MY_TEST_LEVEL} -Save 0").startswith("Opened Level")

        assert editor.cmd(f"{soccer}\\Play").startswith("Play requested")
        assert editor.cmd(f"{plain}\\Play").startswith("Play requested"), "the second Level is not refused: nothing is shared"
        wait(soccer, "Playing")
        wait(plain, "Playing")

        assert editor.cmd(f"{soccer}\\Stop") == "Stop requested"
        wait(soccer, "Stopped")
        assert state(plain) == "Playing", "the other Level keeps playing"
        assert editor.cmd(f"{plain}\\Stop") == "Stop requested"
        wait(plain, "Stopped")
    finally:
        for name in (soccer, plain):
            if editor.alive() and state(name) != "Stopped":
                editor.cmd(f"{name}\\Stop -Keep false")
        editor.cmd("Close -Save 0")
        editor.cmd("Close -Save 0")
