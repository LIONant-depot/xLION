"""Where a system can be placed: a system says what it needs of its place (xecs::system::constraint), a connector what it gives, and a system is only placed where everything it needs is
given. A system that is not placed is one of the available systems of the registry: it does not run. (The System Registry panel offers the same through drag and drop; these tests use the
commands it runs: ListSystems, SetSystemParent, UnplaceSystem, MoveSystem, SetSystemEnabled - all undoable, and the ones an AI runs.)

The constraint is abstract: the players and the referee of the Soccer game need "Fixed Delta Time" (every run of the system is one fixed step of the game's time), and both connectors of the
Physics system give it. Whether the system runs before the step or after it is where the person places it, not something the system needs.
"""
import re
import time

from script_project import PROJECT

ORDER = PROJECT / "Project.config" / "SystemOrder.config.txt"
PLAYERS = "Soccer Players"
REFEREE = "Soccer Referee"
NEEDS = "Fixed Delta Time"


def _systems(level) -> str:
    return level.cmd("ListSystems")


def _available(level) -> str:
    """The text of the 'Available' part of ListSystems."""
    text = _systems(level)
    return text[text.index("Available (not placed"):] if "Available (not placed" in text else ""


def _hierarchy(level) -> str:
    text = _systems(level)
    return text[text.index("Hierarchy"):text.index("Available (not placed")] if "Available (not placed" in text else text[text.index("Hierarchy"):]


def test_a_system_says_what_it_needs_and_a_connector_what_it_gives(game_level):
    text = _systems(game_level)
    players = text[text.index(PLAYERS):].splitlines()[:2]
    assert players[1].strip() == f"needs: {NEEDS}", "the players need to run once for each fixed step"
    assert text.count(f"(gives: {NEEDS})") == 2, "and both connectors of the Physics give it: before the step and after it"


def test_a_system_cannot_be_placed_where_what_it_needs_is_not_given(game_level):
    reply = game_level.cmd(f"SetSystemParent -System \"{PLAYERS}\"")
    assert reply.startswith("SetSystemParent: refused") and NEEDS in reply, f"the top level of the frame gives nothing: {reply}"


def test_a_system_is_placed_in_any_place_that_gives_what_it_needs(game_level):
    """Before the step or after it is the person's choice: both give a fixed delta time."""
    for connector in ("After Step", "Before Step"):
        game_level.ok(f"SetSystemParent -System \"{PLAYERS}\" -Parent Physics -Connector \"{connector}\"")
    assert PLAYERS not in _available(game_level)


def test_a_system_that_is_taken_out_of_the_graph_is_available_and_can_be_placed_again(game_level):
    game_level.ok(f"UnplaceSystem -System \"{PLAYERS}\"")
    assert "NOT PLACED" in _systems(game_level).split(PLAYERS, 1)[1].split("\n", 1)[0], "ListSystems says it does not run"
    assert f"{PLAYERS}  (needs: {NEEDS})" in _available(game_level), "it is in the available systems, with what it needs"

    game_level.ok(f"SetSystemParent -System \"{PLAYERS}\" -Parent Physics -Connector \"Before Step\"")
    assert PLAYERS not in _available(game_level), "placed where it is given what it needs, it is no longer available"


def test_taking_a_system_out_takes_what_is_connected_under_it(game_level):
    game_level.ok("UnplaceSystem -System Physics")
    available = _available(game_level)
    assert "Physics" in available and PLAYERS in available and REFEREE in available, "what ran in the connectors of the Physics has nowhere to run any more"

    reply = game_level.cmd(f"SetSystemParent -System \"{PLAYERS}\" -Parent Physics -Connector \"Before Step\"")
    assert reply.startswith("SetSystemParent: refused") and "not placed" in reply, f"a connector of a system that is not placed takes nothing: {reply}"


# ---- the edits are commands: undoable, and the same ones for the person and the AI ----------------------------------------------------------------------------------------------------

def test_placing_a_system_is_undone_and_redone(game_level):
    before = _systems(game_level)
    game_level.ok(f"SetSystemParent -System \"{PLAYERS}\" -Parent Physics -Connector \"After Step\"")
    after = _systems(game_level)
    assert after != before, "the players are in the After Step connector now"

    game_level.cmd("Undo")
    assert _systems(game_level) == before, "undone: back in Before Step"
    game_level.cmd("Redo")
    assert _systems(game_level) == after


def test_taking_a_system_out_with_what_is_under_it_is_one_undo(game_level):
    """Physics, the players and the referee leave the graph in one step, and come back in one."""
    before = _systems(game_level)
    game_level.ok("UnplaceSystem -System Physics")
    assert PLAYERS in _available(game_level)
    game_level.cmd("Undo")
    assert _systems(game_level) == before, "all three are back where they were"


def test_a_refused_edit_is_not_an_undo_step(game_level):
    before = _systems(game_level)
    game_level.ok(f"SetSystemParent -System \"{PLAYERS}\" -Parent Physics -Connector \"After Step\"")
    assert game_level.cmd(f"SetSystemParent -System \"{REFEREE}\"").startswith("SetSystemParent: refused")
    game_level.cmd("Undo")
    assert _systems(game_level) == before, "one undo goes back before the edit that was done, not before the one that was refused"


def test_a_system_takes_the_place_of_another_and_it_is_undone(game_level):
    before = _hierarchy(game_level)
    game_level.ok(f"MoveSystem -System \"{REFEREE}\" -To \"{PLAYERS}\"")
    moved = _hierarchy(game_level)
    assert moved != before and moved.index(REFEREE) < moved.index(PLAYERS), "the referee runs before the players now"
    game_level.cmd("Undo")
    assert _hierarchy(game_level) == before


def test_a_system_can_be_disabled_and_it_is_undone(game_level):
    game_level.ok(f"SetSystemEnabled -System \"{PLAYERS}\" -Enabled 0")
    assert "(DISABLED)" in _hierarchy(game_level).split(PLAYERS, 1)[1].split("\n", 1)[0]
    game_level.cmd("Undo")
    assert "(DISABLED)" not in _hierarchy(game_level).split(PLAYERS, 1)[1].split("\n", 1)[0]


def test_a_system_is_named_by_its_guid_too(game_level):
    """The panel names a system by its guid (names can repeat); the AI by the name ListSystems shows."""
    game_level.ok("SetSystemEnabled -System 11ED5FB0C5668F79 -Enabled 0")        # the Physics
    assert "(DISABLED)" in _hierarchy(game_level).split("Physics", 1)[1].split("\n", 1)[0]
    game_level.cmd("Undo")


def _unplaced_in_the_file() -> int:
    return re.findall(rb'Placed"\s+;bool\s+(\d)', ORDER.read_bytes()).count(b"0")


def test_an_edit_is_an_edit_of_the_level_saved_with_it(game_level):
    """Like any edit of the Level: the level has unsaved changes until it is saved, the file is written by the Save, and an undo is one more unsaved change."""
    original = ORDER.read_bytes()
    try:
        assert not any(x.dirty for x in game_level.ed.sessions() if x.name == game_level.name)
        game_level.ok(f"UnplaceSystem -System \"{PLAYERS}\"")
        assert any(x.dirty for x in game_level.ed.sessions() if x.name == game_level.name), "the Level has unsaved changes"
        assert ORDER.read_bytes() == original, "and the file has not been written"

        game_level.cmd("Save", allow_disk=True)
        assert _unplaced_in_the_file() == 1, "the Save writes the registry: one system is not placed"
        game_level.cmd("Undo")
        game_level.cmd("Save", allow_disk=True)
        assert _unplaced_in_the_file() == 0, "an undone edit is saved the same way: every system is placed"
    finally:
        ORDER.write_bytes(original)


def test_a_system_that_is_not_placed_does_not_run(game_level, editor):
    """The Tick Loggers print a line each time they run. One that is taken out of the graph (the command saves the registry: a world made again reads it) prints nothing while the other goes on."""
    original = ORDER.read_bytes()
    try:
        game_level.ok('UnplaceSystem -System "Tick Logger A"')
        game_level.cmd("Save", allow_disk=True)                    # a world that is made again (Play) reads the registry from its file

        before = {name: editor.log_text().count(f"[System] Tick Logger {name}") for name in "AB"}
        assert editor.cmd("Play", allow_disk=True).startswith("Play requested")
        editor.wait_play_state("Playing", timeout=240)
        time.sleep(1.5)
        after = {name: editor.log_text().count(f"[System] Tick Logger {name}") for name in "AB"}
        assert after["B"] > before["B"], "the one that is placed runs"
        assert after["A"] == before["A"], "the one that is not does not"

        assert editor.cmd("Stop") == "Stop requested"
        editor.wait_play_state("Stopped")
    finally:
        ORDER.write_bytes(original)
