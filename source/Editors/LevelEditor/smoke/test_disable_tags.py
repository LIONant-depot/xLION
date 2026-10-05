"""The tags of the Basics that turn things off - two pairs.

Runtime, authored (saved with the scene, set in the Inspector or by scripts):
  disable    an EXCLUSIVE tag: an entity that has one only matches the queries that name it, so every system skips it.
  no_render  a regular tag the render leaves out in every view; the entity goes on existing and running.
The editor's own state (what the Level Tree's power and eye set; not in the Add Component list). Saved with the scene like any tag - it is the state the person left the scene in - and left out of the game by the scene compiler:
  editor_disable    exclusive, like disable
  editor_no_render  regular: the editor's scene view leaves the entity out (a game view would still draw it)
Seen here through the labels of the Text component: DescribeTextDraw says how many the last draw of the editor's viewport (the scene view) sent.
"""
import re

import pytest

from harness import REPO
from test_text_render import draw, quiet, labels      # noqa: F401  (fixtures)

PROJECT = REPO / "example.lionprj"


def component(level, name: str) -> tuple[str, str]:
    """(guid, kind) of a component type, as ListComponentTypes says (the kind may say ",builder" or ",editor" too)."""
    for line in level.cmd("ListComponentTypes").splitlines():
        m = re.match(rf"(\w{{16}})  (\S.*?)\s+{re.escape(name)}(\s|$)", line)
        if m:
            return m[1], m[2].strip()
    raise AssertionError(f"{name} is not in ListComponentTypes")


def test_the_tags_are_there_and_the_kinds_are_told(level):
    assert component(level, "disable")[1] == "exclusive_tag"
    assert component(level, "no_render")[1] == "tag"
    assert component(level, "editor_disable")[1] == "exclusive_tag,editor"
    assert component(level, "editor_no_render")[1] == "tag,editor"
    assert component(level, "static")[1] == "tag"


@pytest.mark.parametrize("tag, what", [
    ("no_render",        "the render leaves out what the game says is not drawn"),
    ("editor_no_render", "the scene view leaves out what the editor hid"),
    ("disable",          "no system names the tag, so none sees the entity (the render included)"),
    ("editor_disable",   "the same for the editor's own exclusive tag"),
])
def test_the_tag_stops_the_drawing_and_removing_it_brings_it_back(quiet, labels, tag, what):
    level = quiet
    t = labels("Hello")
    assert draw(level, 1)["Labels"] == 1
    guid, _ = component(level, tag)

    level.ok(f"AddComponent -Scene {level.scene} -Id {t.entity} -Component {guid}")
    assert draw(level, 0)["Labels"] == 0, what
    description = level.describe(t.entity)
    assert "Text" in description and tag in description, "the entity is not touched: it still has its components, and the tag shows"

    level.ok(f"RemoveComponent -Scene {level.scene} -Id {t.entity} -Component {guid}")
    assert draw(level, 1)["Labels"] == 1, "without the tag it is drawn again: nothing was lost"


def entity_file(level, entity: str):
    for path in (PROJECT / "Descriptors" / "Scene").rglob(f"{entity}.entity"):
        return path
    return None


def test_all_four_tags_are_saved_with_the_scene(quiet, labels):
    """The editor's state is the state the person left the scene in: it is in the file of the entity like the runtime tags (the scene compiler is what leaves it out of the game).
    (A save writes to the project, and the next test must find it as it was: what the save wrote is put back here, not left to the end of the run.)"""
    descriptors = PROJECT / "Descriptors"
    before = {p: p.read_bytes() for p in descriptors.rglob("*") if p.is_file()}
    level = quiet
    t = labels("Hello")
    try:
        guids = {tag: component(level, tag)[0] for tag in ("no_render", "disable", "editor_no_render", "editor_disable")}
        for guid in guids.values():
            level.ok(f"AddComponent -Scene {level.scene} -Id {t.entity} -Component {guid}")
        level.cmd("Save", allow_disk=True)

        path = entity_file(level, t.entity)
        assert path is not None, "the entity was saved"
        text = path.read_text(errors="replace")
        missing = [tag for tag, guid in guids.items() if guid not in text]
        assert not missing, f"saved with the entity: {missing}: {text[:600]}"
    finally:
        for p in list(descriptors.rglob("*")):
            if p.is_file() and p not in before: p.unlink()
        for p, data in before.items():
            if not p.exists() or p.read_bytes() != data: p.write_bytes(data)


def test_the_editor_state_goes_through_play_and_stop(editor, level):
    """Play saves the scenes and rebuilds the world from that save, and Stop does the same: the editor's state is in the save, so what was disabled in the editor is still disabled while the
    game runs, and after Stop."""
    scene, entity, _ = level.find_with_component("Transform")
    guid, _ = component(level, "editor_disable")
    level.ok(f"AddComponent -Scene {scene} -Id {entity} -Component {guid}")
    try:
        assert "editor_disable" in level.describe(entity, scene)
        level.cmd("Save", allow_disk=True)                        # (the harness does not Play over unsaved edits; Play itself saves first anyway)
        editor.cmd("Play")
        editor.wait_play_state("Playing")
        assert "editor_disable" in level.describe(entity, scene), "still disabled while the game runs"
        editor.cmd("Stop -Keep false")
        editor.wait_play_state("Stopped")
        assert "editor_disable" in level.describe(entity, scene), "and after Stop"
    finally:
        if editor.play_state() != "Stopped":
            editor.cmd("Stop -Keep false")
            editor.wait_play_state("Stopped")
        level.cmd(f"RemoveComponent -Scene {scene} -Id {entity} -Component {guid}")
