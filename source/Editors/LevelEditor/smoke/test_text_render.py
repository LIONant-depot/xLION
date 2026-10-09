"""The Text component: what the renderer does with the labels of a Level (DescribeTextDraw says what the last draw sent).

The layout is tested in test_text_layout.py; here it is the batching: a label is a few glyph instances, and all the labels that share a font (its atlas) and a depth mode are one draw call,
however many they are. The editor draws every frame, so the numbers settle a frame or two after a change.
"""
import re
import time

import pytest

pytestmark = pytest.mark.needs_window          # needs a window: skipped for a headless editor (see conftest.py)

from test_text_layout import BITMAP, MTSDF, label


def draw(level, labels: int, timeout: float = 20.0) -> dict:
    """The numbers of the last draw, once it has sent `labels` labels (the draw follows the change by a frame or two, and a font is made the first time it is asked for)."""
    deadline = time.time() + timeout
    while True:
        reply = level.cmd("DescribeTextDraw")
        got = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", reply)}
        if got.get("Labels") == labels or time.time() > deadline:
            return got
        time.sleep(0.25)


@pytest.fixture
def quiet(level):
    """The Level as the tests need it: the Text components it already has (a person may have saved some in the scene) are made invisible, so the numbers of the draw are the test's own. Undone after."""
    for entity in level.entities():
        if re.search(r"\[\w{16}\] Text", level.describe(entity)):
            level.ok(f"SetProperty -Scene {level.scene} -Id {entity} -Component Text -Path Text/Opacity -After 0")
    yield level
    for _ in range(200):
        if level.cmd("Undo") != "Undo: done":
            break


@pytest.fixture
def labels(quiet):
    level = quiet
    made = []

    def make(text="Hi", font=MTSDF, **props):
        t = label(level, entity=f"7E7E{len(made) + 1:04X}")
        made.append(t)
        t.set("Font", font)
        t.set("Text", text)
        for path, value in props.items():
            t.set(path, value)
        return t

    yield make                                              # (the entities and every property set on them are undone by `quiet`: the Level is left as it was found, nothing was saved)


def test_no_text_no_labels(quiet):
    got = draw(quiet, 0)
    assert (got["Labels"], got["Glyphs"], got["Draws"], got["Dropped"]) == (0, 0, 0, 0) and got["Ready"] == 1, got


def test_labels_that_share_a_font_are_one_draw_call(level, labels):
    labels("Hello", MTSDF); labels("World", MTSDF); labels("!?", MTSDF)
    got = draw(level, 3)
    assert got["Labels"] == 3 and got["Glyphs"] == 5 + 5 + 2 and got["Draws"] == 1 and got["Dropped"] == 0, got


def test_a_second_font_is_a_second_draw_call(level, labels):
    labels("One", MTSDF); labels("Two", BITMAP); labels("Three", MTSDF)
    assert draw(level, 3)["Draws"] == 2


def test_overlay_text_is_drawn_apart_from_the_depth_tested_one(level, labels):
    labels("Tested", MTSDF); labels("Over", MTSDF, DepthMode="Overlay")
    assert draw(level, 2)["Draws"] == 2


def test_a_hidden_label_is_not_sent(level, labels):
    labels("Seen"); labels("Gone", Opacity=0)
    got = draw(level, 1)
    assert got["Labels"] == 1 and got["Glyphs"] == 4, got


def test_a_label_without_a_font_or_without_text_sends_nothing(level, labels):
    t = labels("Seen")
    labels("", MTSDF)
    assert draw(level, 1)["Glyphs"] == 4
    t.set("Text", "")
    assert draw(level, 0)["Glyphs"] == 0


def test_a_label_with_a_degenerate_scale_does_not_take_the_frame_down(level, labels):
    t = labels("Seen"); z = labels("Flat")
    level.ok(f"SetProperty -Scene {level.scene} -Id {z.entity} -Component Transform -Path Transform/Scale/X -After 0")
    assert draw(level, 1)["Glyphs"] == 4


def test_sorted_labels_interleave_their_fonts_unsorted_ones_are_grouped(level, labels):
    ts = [labels("A", MTSDF), labels("B", BITMAP), labels("C", MTSDF)]
    for i, t in enumerate(ts):
        level.ok(f"SetProperty -Scene {level.scene} -Id {t.entity} -Component Transform -Path Transform/Position/Z -After {i * 3}")
    assert draw(level, 3)["Draws"] == 2, "not sorted: the two of one font are together"
    for t in ts:
        t.set("Sort", "true")
    assert draw(level, 3)["Draws"] == 3, "sorted by distance: far to near, whatever the font"


def test_many_labels_stay_a_handful_of_draw_calls(level, labels):
    for i in range(60):
        labels(f"Label {i}", MTSDF if i % 2 else BITMAP)
    got = draw(level, 60, timeout=60)
    assert got["Labels"] == 60 and got["Draws"] == 2 and got["Dropped"] == 0, got


def pick(level, origin, direction) -> str:
    return level.cmd(f"PickRay -Origin {origin} -Dir {direction}")


def test_a_label_is_picked_where_its_text_is(level, labels):
    t = labels("Hello", MTSDF, Size=0.5)
    t.layout()                                              # the font must be loaded for there to be a box
    assert t.entity in pick(level, "0,0,5", "0,0,-1"), "the middle of the text: the entity is at its anchor, the middle"
    assert "nothing" in pick(level, "5,0,5", "0,0,-1"), "beside the text"
    assert "nothing" in pick(level, "0,3,5", "0,0,-1"), "above the text"


def test_a_label_that_faces_the_camera_is_picked_from_wherever_it_is_seen(level, labels):
    t = labels("Hello", MTSDF, Size=0.5, Orientation="Camera")
    t.layout()
    assert t.entity in pick(level, "0,0,5", "0,0,-1")
    assert t.entity in pick(level, "5,0,0", "-1,0,0"), "from the side it still shows its face"
    assert "nothing" in pick(level, "0,3,5", "0,0,-1")


def test_a_screen_size_label_is_not_picked(level, labels):
    t = labels("Hello", MTSDF, Size=24, SizeMode="Screen")
    t.layout()
    assert "nothing" in pick(level, "0,0,5", "0,0,-1"), "its size in the world depends on the camera, which a ray does not carry"
