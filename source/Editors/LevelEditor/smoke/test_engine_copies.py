"""The copies of the engine DLLs that a Level runs on (plugins/xlevel.plugin/source/Editor/xlevel_engine_copies.h): renamed copies of the core and the render DLL, loaded under their own names, each with a registry of
its own, so that several Levels can run side by side without sharing anything."""
import re
import time

COPIES = "EngineCopies"


def fields(reply):
    return dict(line.split("=", 1) for line in reply.splitlines() if "=" in line)


def copies_on_disk(editor, wait=2.0):
    """The copies in the folder; waits a little for the ones that are being deleted (the file of a module that was just freed can stay locked for a moment)."""
    folder = editor.exe.parent / COPIES
    deadline = time.monotonic() + wait
    while True:
        found = sorted(p.name for p in folder.glob("L[CR]??????.dll")) if folder.is_dir() else []
        if not found or time.monotonic() > deadline:
            return found
        time.sleep(0.1)


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
    assert re.fullmatch(r"LR\d{6}\.dll", got["Render"])
    assert got["RenderImportsCore"] == got["Core"], "the import of LIONCore.dll was renamed to the copy of this set"
    assert got["RenderEditor"] == "ok", "the copy loads and hands out its editor interface"
    assert got["Checksum"] == "ok", "the PE checksum was fixed after the import table was patched"


def test_a_set_is_gone_when_it_is_released(editor):
    assert copies_on_disk(editor) == []
    for _ in range(2):
        editor.cmd("ProbeEngineSet")
        assert copies_on_disk(editor) == [], "the modules are freed and the files deleted with the set"


def test_two_sets_do_not_share_names(editor):
    first = fields(editor.cmd("ProbeEngineSet"))["Core"]
    second = fields(editor.cmd("ProbeEngineSet"))["Core"]
    assert first != second, "every set gets a number of its own"
