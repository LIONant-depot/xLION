"""The Level is selectable in the Level Tree: the Inspector then shows the Level's own properties (its Game, the Game's modules, what each scene needs) instead of an entity's.

SelectLevel is what the click on the Level row runs, DescribeLevel says what the Inspector shows, and the Game combo runs the session's SetLevelGame: undone with the Level's own Ctrl+Z.
"""
import re

from script_project import PROJECT, new_asset, remove_asset

GAME_TYPE = "A3F1D6C0452E9B17"
SOCCER_LEVEL = "0166FAE5EB82F3F3"


def field(text: str, name: str) -> str:
    return re.search(rf"^{name}=(.*)$", text, re.M)[1].strip()


def descriptor_of(level) -> "Path":
    value = int(level.guid, 16)
    return PROJECT / "Descriptors" / "Level" / f"{value & 0xFF:02X}" / f"{(value >> 8) & 0xFF:02X}" / f"{value:X}.desc" / "Descriptor.txt"


def test_describe_level_says_the_level_its_game_and_its_scenes(level):
    text = level.ed.cmd("DescribeLevel")
    assert text.startswith("DescribeLevel: ok"), text
    assert field(text, "Level") == level.guid and field(text, "Name") == level.name
    assert field(text, "GameSource") == "none" and field(text, "Issue") == "none", "this Level needs no module, so it can go without a Game"
    assert field(text, "Scenes") == str(len(level.scenes)) and f"scene {level.scenes[0][1]}" in text


def test_selecting_the_level_shows_its_properties_until_an_entity_is_selected(level):
    assert field(level.ed.cmd("DescribeLevel"), "Selected") == "false"
    level.ok("SelectLevel")
    assert field(level.ed.cmd("DescribeLevel"), "Selected") == "true"

    entity = level.new_entity()
    level.ok(f"Select -Scene {level.scene} -Id {entity}")
    assert field(level.ed.cmd("DescribeLevel"), "Selected") == "false", "selecting an entity brings the entity's properties back"

    level.cmd("Undo")
    assert field(level.ed.cmd("DescribeLevel"), "Selected") == "true", "the undo of the Select gave the Level selection back"
    level.ok("ClearSelection")
    assert field(level.ed.cmd("DescribeLevel"), "Selected") == "false"


def test_the_game_of_the_selected_level_is_set_from_the_session_and_the_undo_gives_it_back(level):
    ed = level.ed
    game = new_asset(ed, ed.libraries()[0][0], GAME_TYPE, "Gym")
    file = descriptor_of(level)
    original = file.read_bytes()
    try:
        level.ok("SelectLevel")
        before = field(ed.cmd("DescribeLevel"), "Game")
        assert level.cmd(f"SetLevelGame -Level {level.guid} -Game {game}", allow_disk=True) == ""
        text = ed.cmd("DescribeLevel")
        assert field(text, "Game") == game and field(text, "GameSource") == "set" and field(text, "GameName") == "Gym"
        assert field(text, "Issue") == "none", "a Level can name any Game of the project: it runs on that Game's own module"

        level.cmd("Undo")
        text = ed.cmd("DescribeLevel")
        assert field(text, "Game") == before and field(text, "GameSource") == "none", "the Level's own undo gave back that it names no Game"
    finally:
        ed.cmd("Close -Save 0")
        file.write_bytes(original)
        remove_asset("Game", game)


def test_a_game_without_the_modules_of_the_scenes_is_refused_from_the_session_too(level):
    ed = level.ed
    empty = new_asset(ed, ed.libraries()[0][0], GAME_TYPE, "Empty")
    try:
        reply = level.cmd(f"SetLevelGame -Level {SOCCER_LEVEL} -Game {empty}", allow_disk=True)
        assert "refused" in reply and "SoccerGame" in reply, reply
        assert "Name=Game\n" in ed.cmd(f"GetLevelGame -Level {SOCCER_LEVEL}") + "\n", "nothing changed: Soccer still names the project's Game"
    finally:
        remove_asset("Game", empty)
