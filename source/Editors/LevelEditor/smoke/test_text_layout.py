"""The Text component: how its text is laid out (xlionrender_text_layout.h), asked of the render module of the Level with DescribeText.

The layout is in em units and does not depend on the transform, the camera or the color. The example project has two Font resources of the same Arial: one baked as MTSDF (scalable, with kerning) and
one as BITMAP (baked at 24 and 48 pixels, no kerning). The same component draws from either; only the font changes.
"""
import re
import time

import pytest

MTSDF = "5549D8C8E9220001, 3285CB58BB79E1AD"
BITMAP = "5549D8C8E9220003, 3285CB58BB79E1AD"          # an instance guid is odd: the resource manager tells a guid from a pointer by its lowest bit
SIZE_ASCENDER_DESCENDER = 1.117                         # Arial: the ascender and the descender of the font, in em


class label:
    """A Text entity of the Level, with the properties the tests change."""
    def __init__(self, level, entity="7E7E0001"):
        self.level, self.entity = level, entity
        level.ok(f"CreateEntity -Scene {level.scene} -Id {entity} -Folder 0 -Components Transform,Text")

    def set(self, path: str, value) -> None:
        self.level.ok(f"SetProperty -Scene {self.level.scene} -Id {self.entity} -Component Text -Path Text/{path} -After {value!r}".replace("'", '"'))

    def layout(self, wait_for_font: bool = True) -> dict:
        for _ in range(60 if wait_for_font else 1):
            reply = self.level.cmd(f"DescribeText -Scene {self.level.scene} -Id {self.entity}")
            if not wait_for_font or reply.startswith("DescribeText: ok") or "no font" in reply:
                break
            time.sleep(1.0)                                 # the font is compiled in the background the first time the project is opened
        if not reply.startswith("DescribeText: ok"):
            return {"reply": reply}
        out = {"reply": reply, "Lines": int(re.search(r"Lines=(\d+)", reply)[1]), "Quads": int(re.search(r"Quads=(\d+)", reply)[1]), "Missing": int(re.search(r"Missing=(\d+)", reply)[1])}
        out["Bounds"] = tuple(float(v) for v in re.search(r"Bounds=([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+)", reply).groups())
        return out


@pytest.fixture
def text(level):
    t = label(level)
    yield t
    for _ in range(40):                                     # the entity and every property set on it: the Level is left as it was found (nothing was saved)
        if level.cmd("Undo") != "Undo: done":
            break


def width(l) -> float:
    return l["Bounds"][2] - l["Bounds"][0]


def height(l) -> float:
    return l["Bounds"][3] - l["Bounds"][1]


def test_a_text_without_a_font_says_so(text):
    assert "no font is chosen" in text.layout()["reply"]


def test_a_text_that_is_not_there_says_so(level):
    assert "no Text" in level.cmd(f"DescribeText -Scene {level.scene} -Id 7E7EFFFF") or "entity not found" in level.cmd(f"DescribeText -Scene {level.scene} -Id 7E7EFFFF")


def test_a_line_of_text_has_a_glyph_for_each_letter_and_the_height_of_the_font(text):
    text.set("Font", MTSDF)
    text.set("Text", "Text")
    l = text.layout()
    assert l["Lines"] == 1 and l["Quads"] == 4 and l["Missing"] == 0, l
    assert abs(height(l) - SIZE_ASCENDER_DESCENDER) < 0.02, f"a line is as tall as the ascender and the descender of the font: {l['Bounds']}"
    assert 1.6 < width(l) < 2.1, f"four letters are about two ems wide: {l['Bounds']}"


def test_spaces_advance_but_have_no_glyph(text):
    text.set("Font", MTSDF)
    text.set("Text", "a b")
    l = text.layout()
    assert l["Quads"] == 2, "the space has no ink"
    text.set("Text", "ab")
    assert width(l) > width(text.layout()), "but it takes room"


def test_the_origin_is_where_the_alignment_and_the_anchor_say(text):
    text.set("Font", MTSDF)
    text.set("Text", "Hello")
    for halign, check in (("Left", lambda b: abs(b[0]) < 1e-4), ("Center", lambda b: abs(b[0] + b[2]) < 1e-4), ("Right", lambda b: abs(b[2]) < 1e-4)):
        text.set("HAlign", halign)
        assert check(text.layout()["Bounds"]), (halign, text.layout()["Bounds"])
    for vanchor, check in (("Top", lambda b: abs(b[3]) < 1e-4), ("Middle", lambda b: abs(b[1] + b[3]) < 1e-4), ("Bottom", lambda b: abs(b[1]) < 1e-4)):
        text.set("VAnchor", vanchor)
        assert check(text.layout()["Bounds"]), (vanchor, text.layout()["Bounds"])
    text.set("VAnchor", "Baseline")
    b = text.layout()["Bounds"]
    assert 0.8 < b[3] < 1.0 and -0.3 < b[1] < -0.1, f"the baseline is at the origin: the ascender is above it and the descender below: {b}"


def test_a_wrap_width_breaks_lines_at_spaces_and_no_wrap_keeps_one(text):
    text.set("Font", MTSDF)
    text.set("Text", "Hello wide world")
    text.set("Size", 0.25)
    assert text.layout()["Lines"] == 1, "no wrap width: only the line breaks of the text break lines"
    text.set("WrapWidth", 1.0)                              # four ems
    wrapped = text.layout()
    assert wrapped["Lines"] == 3, wrapped
    assert abs(width(wrapped) - 4.0) < 1e-3, "the block is as wide as the wrap width"
    text.set("WrapWidth", 0.5)                              # two ems: "wide" alone does not fit in one line with a neighbour
    assert text.layout()["Lines"] > wrapped["Lines"], "a narrower width makes more lines"
    text.set("WrapWidth", 0)
    assert text.layout()["Lines"] == 1


def test_the_line_spacing_is_a_multiplier_of_the_line_height_of_the_font(text):
    text.set("Font", MTSDF)
    text.set("Text", "Hello wide world")
    text.set("Size", 0.25)
    text.set("WrapWidth", 1.0)
    base = height(text.layout())
    text.set("LineSpacing", 2.0)
    assert height(text.layout()) > base * 1.4, "three lines, each twice as far from the next"


def test_the_size_does_not_change_the_layout_it_scales_it(text):
    text.set("Font", MTSDF)
    text.set("Text", "Hello")
    text.set("Size", 0.25)
    a = text.layout()
    text.set("Size", 4.0)
    b = text.layout()
    assert a["Bounds"] == b["Bounds"] and a["Quads"] == b["Quads"], "the layout is in ems: the renderer applies the size"


def test_a_bitmap_font_is_laid_out_like_any_other_but_without_kerning(text):
    text.set("Text", "Text AVATAR")
    text.set("Font", MTSDF)
    scalable = text.layout()
    text.set("Font", BITMAP)
    bitmap = text.layout()
    assert bitmap["Lines"] == scalable["Lines"] == 1 and bitmap["Quads"] == scalable["Quads"] == 10 and bitmap["Missing"] == 0, (scalable, bitmap)
    assert width(bitmap) > width(scalable), "the scalable font kerns T-e and A-V; the bitmap font has no kerning baked, so its pairs sit further apart"


def test_a_character_the_font_does_not_have_is_drawn_as_the_replacement_glyph(text):
    text.set("Font", MTSDF)
    text.set("Text", "?")
    question = text.layout()
    text.set("Text", "é")                              # the font was baked with ASCII only
    unknown = text.layout()
    assert unknown["Quads"] == question["Quads"] == 1 and unknown["Missing"] == 0, (question, unknown)
    assert abs(width(unknown) - width(question)) < 1e-4, "it is the question mark"


def test_a_character_outside_the_basic_plane_is_one_character_not_two(text):
    text.set("Font", MTSDF)
    text.set("Text", "\U0001F600")                         # UTF-16: two units (a surrogate pair) for one codepoint
    l = text.layout()
    assert l["Quads"] == 1 and l["Missing"] == 0, f"one replacement glyph, not two: {l}"


def test_a_text_survives_a_save_and_a_reload(level):
    """Everything the component says is in the saved scene: the text (Unicode included), the font and the choices. The scene is put back as it was."""
    import pathlib
    import shutil
    import tempfile
    from script_project import PROJECT
    scene_dir = pathlib.Path(PROJECT) / "Descriptors" / "Scene" / level.scene[-2:] / level.scene[-4:-2] / f"{level.scene}.desc"
    backup = pathlib.Path(tempfile.mkdtemp(prefix="xlion_text_scene_")) / "scene"
    shutil.copytree(scene_dir, backup)
    try:
        t = label(level, entity="7E7E0A01")
        t.set("Font", BITMAP)
        t.set("Text", "Café \U0001F600")
        t.set("HAlign", "Right")
        t.set("Orientation", "Camera")
        before = t.layout()
        reply = level.ed.cmd("Save", allow_disk=True)
        assert "rror" not in reply, reply
        assert any(scene_dir.rglob("7E7E0A01.entity")), "the entity is in the saved scene"
        level.ed.cmd("Close -Save 0")
        level.ed.cmd(f"OpenLevel -Level {level.guid} -Save 0")
        level.ed.wait_for("GetPlayState", r"Building=false", timeout=240)
        after = t.layout()
        assert after["Quads"] == before["Quads"] == 5 and after["Bounds"] == before["Bounds"], (before, after)       # C a f e + the emoji's replacement glyph (the space has no ink)
        assert level.ed.property_value(level.name, level.scene, t.entity, "Text/Orientation") != "", "the choices are there"
    finally:
        level.ed.cmd("Close -Save 0")
        shutil.rmtree(scene_dir, ignore_errors=True)
        shutil.copytree(backup, scene_dir)
        shutil.rmtree(backup.parent, ignore_errors=True)
