"""A Level names the Game it runs under (its descriptor: `Game`); empty is the project's Game.

SetLevelGame writes it at once and can be undone, and refuses a Game that lacks a module the Level's scenes need. Every Level runs on the game module of the Game it names, so Levels of
different Games open (and play) together. The module commands take -Game: the project has no Game of its own.
"""
import re

import pytest

from harness import REPO
from script_project import PROJECT, new_asset, remove_asset

MODULE_TYPE = "8D3968CB1287FA04"
GAME_TYPE = "A3F1D6C0452E9B17"
MODULE = "3849E1DE2402B1A5"
MODULE_ASSET = f"{MODULE}{MODULE_TYPE}"
SOCCER_LEVEL = "0166FAE5EB82F3F3"
PROJECT_GAME = f"6EDF20D2F3028001{GAME_TYPE}"                  # the example project's Game
MY_TEST_LEVEL = "6162BB6775AC3293"                               # needs no script module
MY_TEST_LEVEL_DESCRIPTOR = PROJECT / "Descriptors" / "Level" / "93" / "32" / "6162BB6775AC3293.desc" / "Descriptor.txt"
LEVEL_DESCRIPTOR = PROJECT / "Descriptors" / "Level" / "F3" / "F3" / "166FAE5EB82F3F3.desc" / "Descriptor.txt"      # the guid without its leading zero, the way the pipeline names it


def game_of(editor, level=SOCCER_LEVEL) -> tuple:
    reply = editor.cmd(f"GetLevelGame -Level {level}")
    return re.search(r"^Game=(\S+)", reply, re.M)[1], re.search(r"^Source=(\w+)", reply, re.M)[1]


@pytest.fixture
def scratch_game(editor):
    """A Game of the project that lists the SoccerGame module (so the Soccer level can run under it)."""
    lib = editor.libraries()[0][0]
    game = new_asset(editor, lib, GAME_TYPE, "Gym")
    assert editor.cmd(f"AddProjectModuleReference -Module {MODULE_ASSET} -Game {game}", allow_disk=True) == ""
    original = LEVEL_DESCRIPTOR.read_bytes()
    editor.cmd("Close -Save 0")
    yield game
    editor.cmd("Close -Save 0")
    LEVEL_DESCRIPTOR.write_bytes(original)
    remove_asset("Game", game)


def test_a_level_names_the_game_it_runs_under_and_without_one_it_has_no_modules(editor):
    game, source = game_of(editor)
    assert source == "set" and game.endswith(GAME_TYPE), "the Soccer level names its Game"
    assert game == editor.cmd(f"ListProjectModuleReferences -Game {game}").splitlines()[0].removeprefix("Game: "), "it is a Game of the project"
    assert game_of(editor, MY_TEST_LEVEL) == ("(none)", "none"), "a Level that needs no module names none: no scripts, components or systems of any module"
    assert "is not in the project" in editor.cmd("GetLevelGame -Level 0000000000000001")


def test_a_level_cannot_lose_its_game_while_its_scenes_need_the_modules(editor):
    before = game_of(editor)
    reply = editor.cmd(f"SetLevelGame -Level {SOCCER_LEVEL}", allow_disk=True)
    assert "refused" in reply and "needs module SoccerGame" in reply, reply
    assert game_of(editor) == before, "nothing changed"


def test_a_level_that_needs_no_module_can_name_a_game_and_drop_it_again(editor, scratch_game):
    original = MY_TEST_LEVEL_DESCRIPTOR.read_bytes()
    try:
        assert editor.cmd(f"SetLevelGame -Level {MY_TEST_LEVEL} -Game {scratch_game}", allow_disk=True) == ""
        assert game_of(editor, MY_TEST_LEVEL) == (scratch_game, "set")
        assert editor.cmd(f"SetLevelGame -Level {MY_TEST_LEVEL}", allow_disk=True) == ""
        assert game_of(editor, MY_TEST_LEVEL) == ("(none)", "none")
    finally:
        MY_TEST_LEVEL_DESCRIPTOR.write_bytes(original)


def test_a_level_whose_game_lacks_what_its_scenes_need_cannot_be_played(editor):
    """The Soccer scenes need SoccerGame; with no Game on the Level nothing provides it. That is an error: the open says so, and Play and Step refuse."""
    original = LEVEL_DESCRIPTOR.read_bytes()
    editor.cmd("Close -Save 0")
    try:
        text = original.decode().replace("[ xProperties : 3 ]", "[ xProperties : 2 ]")
        LEVEL_DESCRIPTOR.write_bytes("".join(l for l in text.splitlines(keepends=True) if "Level/Game" not in l).encode())
        reply = editor.cmd(f"OpenLevel -Level {SOCCER_LEVEL} -Save 0")
        assert reply.startswith("Opened Level") and "ERROR" in reply and "names no Game" in reply, reply
        editor.wait_for("GetPlayState", r"Building=false", timeout=240)
        assert "refused" in editor.cmd("Play") and editor.play_state() == "Stopped"
        assert "refused" in editor.cmd("Step") and editor.play_state() == "Stopped"
        assert "names no Game" in editor.cmd("DescribeLevel") and "MISSING" in editor.cmd("DescribeLevel")
    finally:
        editor.cmd("Close -Save 0")
        LEVEL_DESCRIPTOR.write_bytes(original)


def test_a_level_can_be_given_a_game_that_lists_its_modules_and_the_undo_gives_it_back(editor, scratch_game):
    before = game_of(editor)
    assert editor.cmd(f"SetLevelGame -Level {SOCCER_LEVEL} -Game {scratch_game}", allow_disk=True) == ""
    assert game_of(editor) == (scratch_game, "set")
    assert "Game" in LEVEL_DESCRIPTOR.read_bytes().decode() and scratch_game[:16].lstrip("0") in LEVEL_DESCRIPTOR.read_bytes().decode().upper(), "written at once"
    assert SOCCER_LEVEL in editor.cmd(f"ListLevels -Game {scratch_game}") and SOCCER_LEVEL not in editor.cmd(f"ListLevels -Game {before[0]}")
    editor.cmd("Undo")
    assert game_of(editor) == before, "the undo gave the project's Game back"
    assert SOCCER_LEVEL in editor.cmd(f"ListLevels -Game {before[0]}")


def test_a_game_that_lacks_a_module_the_scenes_need_is_refused_with_the_module(editor):
    lib = editor.libraries()[0][0]
    empty = new_asset(editor, lib, GAME_TYPE, "Empty")
    try:
        before = game_of(editor)
        reply = editor.cmd(f"SetLevelGame -Level {SOCCER_LEVEL} -Game {empty}", allow_disk=True)
        assert "refused" in reply and "needs module SoccerGame" in reply and "SoccerBall" in reply, reply
        assert game_of(editor) == before, "nothing changed"
        assert "not a Game asset guid" in editor.cmd(f"SetLevelGame -Level {SOCCER_LEVEL} -Game {MODULE_ASSET}", allow_disk=True)
    finally:
        remove_asset("Game", empty)


def test_a_level_that_names_another_game_opens_on_that_game(editor, scratch_game):
    """Every Level runs on its own game module, the one of the Game it names: another Game than the project's opens like any other, once its Game.dll is built (the open waits for it)."""
    assert editor.cmd(f"SetLevelGame -Level {SOCCER_LEVEL} -Game {scratch_game}", allow_disk=True) == ""
    reply = editor.cmd(f"OpenLevel -Level {SOCCER_LEVEL} -Save 0")
    assert reply.startswith("Opened Level") and "refused" not in reply and "ERROR" not in reply, reply
    assert "not currently registered" not in reply, "the components of the Game's modules are registered: the Level opened on its own Game.dll"
    assert game_of(editor)[0] == scratch_game
    assert editor.cmd(f"SetLevelGame -Level {SOCCER_LEVEL} -Game {PROJECT_GAME}", allow_disk=True) == "", "back to the project's Game"
    editor.cmd("Close -Save 0")
    assert editor.cmd(f"OpenLevel -Level {SOCCER_LEVEL} -Save 0").startswith("Opened Level")


def test_saving_an_open_level_keeps_the_game_it_names(editor):
    """A Level's Save writes its descriptor from the Level in memory: the Game has to be part of it or every Save would erase it."""
    original = LEVEL_DESCRIPTOR.read_bytes()
    game = game_of(editor)[0]
    editor.cmd("Close -Save 0")
    try:
        assert editor.cmd(f"SetLevelGame -Level {SOCCER_LEVEL} -Game {game}", allow_disk=True) == ""      # names the project's own Game: it can open
        assert editor.cmd(f"OpenLevel -Level {SOCCER_LEVEL} -Save 0").startswith("Opened Level")
        editor.wait_for("GetPlayState", r"Building=false", timeout=240)
        assert "rror" not in editor.cmd("Save", allow_disk=True)
        assert game_of(editor) == (game, "set"), "the Game is still there after the Save"
    finally:
        editor.cmd("Close -Save 0")
        LEVEL_DESCRIPTOR.write_bytes(original)


def test_the_module_commands_work_on_any_game(editor, scratch_game):
    other = editor.cmd(f"ListProjectModuleReferences -Game {PROJECT_GAME}").splitlines()
    assert MODULE_ASSET in editor.cmd(f"ListProjectModuleReferences -Game {scratch_game}")
    assert editor.cmd(f"RemoveProjectModuleReference -Module {MODULE_ASSET} -Game {scratch_game}", allow_disk=True) == ""
    assert MODULE_ASSET not in editor.cmd(f"ListProjectModuleReferences -Game {scratch_game}")
    editor.cmd("Undo")
    assert MODULE_ASSET in editor.cmd(f"ListProjectModuleReferences -Game {scratch_game}"), "the undo put it back in that Game"
    assert editor.cmd(f"ListProjectModuleReferences -Game {PROJECT_GAME}").splitlines() == other, "the other Game was not touched"
    assert "not in the project" in editor.cmd(f"ListProjectModuleReferences -Game 0000000000000001{GAME_TYPE}")
