"""The ten task tests of documentation/stack_canvas.md section 11, on the Material Stack canvas of the Material editor (the Debug editor, a real window).

The editor opens example.lionprj read-only: one material is opened in the editor, every test builds its graph in it with the editor's own commands
(and mouse gestures, tests 4 to 7 and 9) and the material is closed without saving at the end. Nothing is ever saved. Windows only.

Every test also checks: no route segment crosses a step, the order invariant (a producer is before its consumers) and one undo step per gesture
(Undo once gives back the state before, Redo the state after; a refused gesture leaves the history alone). The state compared is `ListStack`
(the whole graph with its order); there is no command that prints the file text.

The measures of each run go to Build/material_stack_results.txt (and to the output with `-s`): that is what section 11 of the document records.
"""
import ctypes
import os
import random
import re
import time
from ctypes import wintypes

import pytest

import harness
from harness import REPO, Editor, quote

pytestmark = [pytest.mark.no_editor, pytest.mark.needs_window, pytest.mark.skipif(os.name != "nt", reason="drives the Windows editor window")]

RESULTS = REPO / "Build" / "material_stack_results.txt"
MATERIAL = "39C2185971104003"                       # the example material the tests open (prefix of its guid)
OUTPUT_SECTION_FLAG = "[output]"
PREFAB = {"Vec2": "E2B21A77936C6D1A", "Vec4 Add": "331D5BBD07338A64", "Vec4 Multiply": "ED1599A6BF189C88", "Texture": "C81B1A481148740F",
          "Inputs": "CBC82A6D82A1C031", "ToVec3": "DC249AAC9FE5DC5A", "Float": "7B18F369F0C2CA36"}
LCTRL_VK = 0x11
rnd = random.Random(8)


class Canvas:
    """The open material: command helpers and the mouse (screen coordinates, the window at a fixed place)."""

    def __init__(self, ed: Editor):
        self.ed = ed
        lib = ed.libraries()[0][0]
        mats, queue = [], [None]
        while queue:
            for guid, kind, name in ed.list_assets(lib, queue.pop(0)):
                if kind == "Folder":
                    if name != "Trash":
                        queue.append(guid)
                elif kind == "Material":
                    mats.append((guid, name))
        self.guid, self.name = next(m for m in mats if m[0].startswith(MATERIAL))
        hwnd = ed._windows()[0]
        ctypes.windll.user32.ShowWindow(hwnd, 1)
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 20, 20, 1880, 1040, 0x0004)
        time.sleep(1)
        pt = wintypes.POINT(0, 0)
        ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt))
        self.ox, self.oy = pt.x, pt.y
        ed.ok(f"OpenResourceEditor -Asset {self.guid} -Library {lib}")
        ed._frames(10)
        self.click_img(840, 75)                      # the Material Stack tab
        ed._frames(5)

    def close(self):
        self.ed.cmd(f"CloseResourceEditor -Asset {self.guid}")        # never -Save

    # ------------------------------------------------------------ commands
    def C(self, line: str) -> str:
        return self.ed.cmd(f"{self.name}\\{line}")

    def E(self, line: str) -> None:
        r = self.C(line)
        assert not r.strip(), f"{line} -> {r}"

    def stack(self) -> str:
        return self.C("ListStack")

    def steps(self) -> list[tuple[str, str, str]]:
        """(guid, name, line) of every step in reading order; sections as ('', section name, header)."""
        out = []
        for line in self.stack().splitlines():
            if line.startswith("section"):
                out.append(("", line, line))
            elif line.startswith("  "):
                parts = line.split()
                out.append((parts[0], parts[1], line))
        return out

    def order(self) -> list[str]:
        return [n for g, n, _ in self.steps() if g]

    def clear(self):
        """Every step but the output step, every section but the output one."""
        sections, steps, in_output = [], [], False
        for g, n, line in self.steps():
            if not g:
                in_output = OUTPUT_SECTION_FLAG in line
                if not in_output:
                    sections.append(line.split()[1])
            elif not in_output:
                steps.append(g)
        for g in steps:
            self.C(f"DeleteNode -Node {g}")
        for s in sections:
            self.C(f"DeleteSection -Section {s}")
        self.C("SelectStep")
        # the output step's literal and wires are the example's own: unwire it
        for line in self.C("Sources -Node @Output__Target_Color").splitlines():
            m = re.search(r"connection ([0-9A-F]{16})", line)
            if m:
                self.C(f"Disconnect -Connection {m.group(1)}")

    def section(self, name: str) -> str:
        self.E(f"CreateSection -Section {gid()} -Name {quote(name)}")
        return name

    def node(self, prefab: str, name: str, section: str) -> str:
        self.E(f"CreateNode -Prefab {PREFAB[prefab]} -Node {gid()} -Section {quote('@' + section)} -Last 1 -Name {name}")
        return name

    def link(self, out: str, inp: str):
        self.E(f"Connect -Output @{out} -Input @{inp} -Connection {gid()}")

    # ------------------------------------------------------------ queries
    def layout(self) -> dict:
        """LayoutStats as numbers."""
        text = self.C("LayoutStats")
        d = {k: float(v) for k, v in re.findall(r"(columns|crossings|junctions|segments through steps|false junctions|routes|outputs)\s+(\d+)", text)}
        m = re.search(r"layout ([0-9.]+) ms", text)
        d["ms"] = float(m[1]) if m else -1.0
        d["text"] = text
        return d

    def rect(self, name: str):
        r = self.C(f"SelectStep -Node {name}")
        self.C("SelectStep")
        self.ed._frames(2)
        m = re.search(r"screen (-?\d+) (-?\d+) (-?\d+) (-?\d+)", r)
        return tuple(int(v) for v in m.groups()) if m else None

    def pins(self, name: str):
        r = self.C(f"SelectStep -Node @{name}")
        self.C("SelectStep")
        self.ed._frames(2)
        return {m[1] + ":" + m[2]: (int(m[3]), int(m[4])) for m in re.finditer(r"(in|out):([^=]+)=(-?\d+),(-?\d+)", r)}, r

    def conn(self, step: str, inp: str):
        for line in self.C(f"Sources -Node @{step}").splitlines():
            if line.startswith(inp):
                m = re.search(r"connection ([0-9A-F]{16})", line)
                return m and m[1]

    def route(self, cid: str):
        r = self.C(f"SelectStep -Connection {cid}")
        self.C("SelectStep")
        self.ed._frames(2)
        m = re.search(r"screen (-?\d+) (-?\d+)", r)
        c = re.search(r"chip (-?\d+) (-?\d+)", r)
        return (int(m[1]), int(m[2])), (int(c[1]), int(c[2])) if c else None, r

    # ------------------------------------------------------------ mouse
    def click_img(self, x, y, **kw):
        self.ed.click(self.ox + x, self.oy + y, **kw)

    def mv(self, x, y, frames=3):
        self.ed._move(x, y)
        self.ed._frames(frames)

    def down(self):
        self.ed._virtual("MouseButton -Button left -Down true")
        self.ed._frames(3)

    def up(self):
        self.ed._virtual("MouseButton -Button left -Down false")
        self.ed._frames(3)

    def type(self, text: str):
        self.ed._virtual(f"Text -Text {quote(text)}")
        self.ed._frames(10)

    def key(self, vk: int):
        self.ed.post_key(vk)
        self.ed._frames(4)

    # ------------------------------------------------------------ checks
    def invariants(self, tag: str):
        """No segment through a step; a producer is before its consumers."""
        assert self.layout()["segments through steps"] == 0, f"{tag}: a route goes through a step"
        seen = set()
        for g, n, line in self.steps():
            if not g:
                continue
            for src in re.findall(r"<- ([A-Za-z0-9_]+)", line):
                assert src in seen, f"{tag}: {n} reads {src}, which is not before it"
            seen.add(n)

    def one_undo_step(self, before: str, after: str, tag: str):
        """Undo once gives back `before`, Redo gives `after` again."""
        self.C("Undo")
        self.ed._frames(3)
        assert self.stack() == before, f"{tag}: one undo did not restore the state before the gesture"
        self.C("Redo")
        self.ed._frames(3)
        assert self.stack() == after, f"{tag}: redo did not restore the state after the gesture"


def gid() -> str:
    return "%016X" % rnd.getrandbits(64)


results: list[str] = []


def measure(test: str, verdict: str, text: str):
    line = f"2026-10-22 | test {test} | {verdict} | {text}"
    results.append(line)
    print(line)


@pytest.fixture(scope="module")
def cv():
    ed = Editor(harness.DEFAULT_EXE)
    ed.start()
    canvas = Canvas(ed)
    try:
        yield canvas
    finally:
        RESULTS.write_text("\n".join(results) + "\n")
        try:
            canvas.close()
        finally:
            ed.stop()


def routes_of(cv: Canvas, node: str, output: str | None = None):
    uses = cv.C(f"FindUses -Node @{node}" + (f" -Output {output}" if output else ""))
    return re.findall(r"connection ([0-9A-F]{16})", uses)


def lanes(cv: Canvas, cids: list[str]):
    """(gutter, lane) of every route's first hop and its points."""
    out = []
    for cid in cids:
        r = cv.C(f"RouteInfo -Connection {cid}")
        out.append((re.search(r"column \d+ -> \d+: gutter (\d+) lane (\d+)", r).groups(), re.search(r"points (.*)", r)[1]))
    return out


def test_1_one_uv_feeding_many_branches(cv):
    cv.clear()
    cv.section("Coordinates")
    cv.node("Vec2", "UV", "Coordinates")
    b, c, d = cv.section("Normal"), cv.section("Surface color"), cv.section("Experiments")
    tex = [cv.node("Texture", f"NormalTex{i}", b) for i in range(3)] + [cv.node("Texture", f"ColorTex{i}", c) for i in range(3)] + [cv.node("Texture", f"Probe{i}", d) for i in range(2)]
    for t in tex:
        cv.link("UV", f"{t}.UV")
    cv.node("Vec4 Add", "NormalMix", b)
    cv.link("NormalTex0", "NormalMix.A")
    cv.link("NormalTex1", "NormalMix.B")
    cv.node("Vec4 Add", "ColorMix", c)
    cv.link("ColorTex0", "ColorMix.A")
    cv.link("ColorTex1", "ColorMix.B")
    cv.node("Vec4 Multiply", "Final", d)
    cv.link("ColorMix", "Final.A")
    cv.link("NormalMix", "Final.B")
    cv.node("ToVec3", "ToRGB", d)
    cv.link("Final", "ToRGB.A")
    cv.link("ToRGB", "Output__Target_Color.Color")
    cv.ed._frames(5)
    cv.invariants("test 1")
    stack = cv.stack()
    assert len(re.findall(r"UV\(2\) <- UV\b", stack)) == 8, "all 8 chips read UV"
    ids = routes_of(cv, "UV")
    assert len(ids) == 8
    info = lanes(cv, ids)
    trunks = {g for g, p in info}                          # (gutter, lane): one trunk = one lane of the highway
    st = cv.layout()
    assert len(trunks) == 1, f"one trunk for UV per highway, found {trunks}"
    assert st["false junctions"] == 0
    cv.ed._frames(3)
    measure("1", "pass", f"UV trunks per highway {len(trunks)}, crossings {st['crossings']:.0f}, junctions {st['junctions']:.0f}, columns {st['columns']:.0f}, lanes per gutter: "
            + ", ".join(f"col {a}: {b}" for a, b in re.findall(r"column (\d+): .*gutter lanes (\d+)", st["text"])))
    cv.C("TraceRoute -Node @Final -Direction up")
    cv.ed._frames(3)
    cv.C("TraceRoute -Node @Final -Direction off")


def test_2_independent_normal_and_color_branches(cv):
    cv.clear()
    b, c = cv.section("Normal"), cv.section("Surface color")
    cv.node("Texture", "NormalMap", b)
    cv.node("Vec4 Multiply", "NormalScale", b)
    cv.link("NormalMap", "NormalScale.A")
    cv.node("Texture", "Albedo", c)
    cv.node("Vec4 Multiply", "Tint", c)
    cv.node("ToVec3", "ToRGB", c)
    cv.link("Albedo", "Tint.A")
    cv.link("Tint", "ToRGB.A")
    cv.link("ToRGB", "Output__Target_Color.Color")
    cv.ed._frames(5)
    cv.invariants("test 2")
    st = cv.layout()
    # a route between the two sections would be a connection whose source and consumer sit in different user sections
    sec_of, cur = {}, None
    for g, n, line in cv.steps():
        if not g:
            cur = "Output" if line.endswith(OUTPUT_SECTION_FLAG) else line.split(None, 2)[2]
        else:
            sec_of[n] = cur
    cross = 0
    for g, n, line in cv.steps():
        if g and sec_of[n] in ("Normal", "Surface color"):
            for src in re.findall(r"<- ([A-Za-z0-9_]+)", line):
                cross += sec_of[src] != sec_of[n]
    assert cross == 0
    # the depth layout does not depend on the width: the two roots share column 0 (the width of a layout is the content's, `-Width` does nothing)
    col0 = re.search(r"column 0: steps (\d+)", st["text"])
    assert int(col0[1]) == 2, st["text"]
    wide = cv.C("LayoutStats -Width 500")
    assert re.search(r"columns (\d+)", wide)[1] == str(int(st["columns"]))
    measure("2", "pass", f"columns {st['columns']:.0f} (column 0 holds {col0[1]} steps: both roots side by side, same at -Width 500 and 1600), cross-section routes {cross}, crossings {st['crossings']:.0f}")


def test_3_multi_output_step(cv):
    cv.clear()
    a = cv.section("Inputs")
    cv.node("Inputs", "Wetness", a)
    b = cv.section("Surface")
    for i in range(2):
        cv.node("Texture", f"Layer{i}", b)
        cv.link("Wetness.UV(2)", f"Layer{i}.UV")
    cv.node("Vec4 Multiply", "Darken0", b)
    cv.node("Vec4 Multiply", "Darken1", b)
    cv.link("Wetness.Color(4)", "Darken0.A")
    cv.link("Wetness.Color(4)", "Darken1.A")
    cv.link("Layer0", "Darken0.B")
    cv.link("Layer1", "Darken1.B")
    cv.node("Vec4 Add", "Mix", b)
    cv.link("Darken0", "Mix.A")
    cv.link("Darken1", "Mix.B")
    cv.node("ToVec3", "ToRGB", b)
    cv.link("Mix", "ToRGB.A")
    cv.link("ToRGB", "Output__Target_Color.Color")
    cv.ed._frames(5)
    cv.invariants("test 3")
    stack = cv.stack()
    assert stack.count("<- Wetness.UV(2)") + stack.count("<- Wetness.Color(4)") == 4
    assert len(re.findall(r"UV\(2\) <- Wetness\.UV\(2\)", stack)) == 2 and len(re.findall(r"A\(4\) <- Wetness\.Color\(4\)", stack)) == 2
    uv, col = routes_of(cv, "Wetness", "UV(2)"), routes_of(cv, "Wetness", "Color(4)")
    assert len(uv) == 2 and len(col) == 2 and not set(uv) & set(col)
    firsts = {tuple(p.split()[:1]) for _, p in lanes(cv, uv + col)}
    trunk_uv, trunk_col = {tuple(p.split()[:2]) for _, p in lanes(cv, uv)}, {tuple(p.split()[:2]) for _, p in lanes(cv, col)}
    assert len(firsts) == 2, "each used output has its own trunk, never merged"
    st = cv.layout()
    measure("3", "pass", f"trunks = {len(firsts)} (distinct outputs used), FindUses -Output: UV(2) {len(uv)} routes, Color(4) {len(col)} routes, crossings {st['crossings']:.0f} (step Inputs stands in for Wetness; chips read Wetness.UV(2) / Wetness.Color(4))")


def test_8_change_an_instance_value(cv):
    cv.clear()
    s = cv.section("Surface")
    cv.node("Float", "Gloss", s)
    cv.node("Texture", "Albedo", s)
    cv.node("Vec4 Multiply", "Tint", s)
    cv.node("ToVec3", "ToRGB", s)
    cv.link("Albedo", "Tint.A")
    cv.link("Tint", "ToRGB.A")
    cv.link("ToRGB", "Output__Target_Color.Color")
    cv.ed._frames(5)
    names = ["Gloss", "Albedo", "Tint", "ToRGB", "Output__Target_Color"]
    cids = [cv.conn("Tint", "A"), cv.conn("ToRGB", "A"), cv.conn("Output__Target_Color", "Color")]

    def snapshot():
        return [cv.rect(f"@{n}") for n in names], [cv.C(f"RouteInfo -Connection {c}") for c in cids], cv.layout()["text"].replace("\n", "|")
    props = cv.C("NodeProperties -Node @Gloss")
    m = re.search(r"(node/Params\[[^\]]*\]/Float)\S*\s+(?:;\w+\s+)?(-?[0-9.]+)", props) or re.search(r"(node/Params\[[^\]]*\]/Float)", props)
    assert m, props
    path = m[1]
    before_stack, before = cv.stack(), snapshot()
    cv.E(f"SetNodeProperty -Node @Gloss -Path {path} -Value 0.75")
    cv.ed._frames(4)
    after_stack, after = cv.stack(), snapshot()
    assert after_stack != before_stack and "0.750000" in after_stack, "the value changed"
    assert after[0] == before[0], "step rects moved"
    assert after[1] == before[1], "lanes moved"
    cv.one_undo_step(before_stack, after_stack, "test 8")
    measure("8", "pass", f"step rects diff {sum(a != b for a, b in zip(before[0], after[0]))} of {len(names)}, lane diff {sum(a != b for a, b in zip(before[1], after[1]))} of {len(cids)}, undo steps 1 (via SetNodeProperty, the command the canvas widget issues)")


def scene_p2(cv: Canvas):
    """The scene of tests 4, 6 and 9: Albedo feeds BaseColor and Emission; Mask feeds M0..M2; E2 reads Emission."""
    cv.clear()
    s = cv.section("Surface")
    cv.node("Texture", "Albedo", s)
    cv.node("ToVec3", "BaseColor", s)
    cv.node("Vec4 Add", "Emission", s)
    cv.link("Albedo", "BaseColor.A")
    cv.link("Albedo", "Emission.A")
    cv.link("BaseColor", "Output__Target_Color.Color")
    cv.node("Texture", "Mask", s)
    cv.node("Texture", "Mask2", s)
    for i in range(3):
        cv.node("Vec4 Add", f"M{i}", s)
        cv.link("Mask", f"M{i}.A")
    cv.node("Vec4 Add", "E2", s)
    cv.link("Emission", "E2.A")
    cv.ed._frames(5)


def test_4_insert_tint_into_one_branch(cv):
    scene_p2(cv)
    before = cv.stack()
    c_base, c_emis = cv.conn("BaseColor", "A"), cv.conn("Emission", "A")
    (rx, ry), _, _ = cv.route(c_base)
    gestures = 0
    cv.ed.click(rx, ry)                                    # select the route
    cv.ed._frames(3)
    gestures += 1
    cv.ed.click(rx, ry)                                    # its (+), where the route was clicked
    cv.ed._frames(4)
    gestures += 1
    cv.type("Multiply")
    cv.key(0x0D)                                           # Enter: the first entry -> the port chooser
    gestures += 1
    cv.click_img(1015, 158)                                # the chooser's A(4)
    cv.ed._frames(6)
    gestures += 1
    after = cv.stack()
    assert "Vec4_Multiply" in after and "A(4) <- Albedo" in after
    assert cv.conn("Emission", "A") == c_emis, "the Emission connection keeps its guid"
    # the other steps keep their relative order
    assert [n for n in cv.order() if n != "Vec4_Multiply"] == [n for n in re.findall(r"^  \w+  (\S+)", before, re.M)]
    cv.invariants("test 4")
    cv.one_undo_step(before, after, "test 4")
    st = cv.layout()
    measure("4", "pass", f"gestures {gestures}, undo steps 1, Emission connection guid unchanged ({c_emis[:6]}..), other steps' order unchanged, crossings {st['crossings']:.0f}")


def test_6_replace_a_shared_mask(cv):
    scene_p2(cv)
    before = cv.stack()
    _, chip, _ = cv.route(cv.conn("M0", "A"))
    gestures = 0
    cv.ed.click(*chip, right=True)                         # chip menu
    cv.ed._frames(4)
    gestures += 1
    mx, my = chip
    cv.ed.click(mx + 40, my + 47)                          # Find all uses
    cv.ed._frames(4)
    gestures += 1
    ux, uy = mx + 40, my + 47
    cv.ed.click(ux + 30, uy + 86)                          # Replace all...
    cv.ed._frames(6)
    gestures += 1
    cv.type("Mask2")
    cv.key(0x0D)
    gestures += 1
    after = cv.stack()
    assert after.count("A(4) <- Mask2") == 3 and "A(4) <- Mask," not in after + ",", after
    assert re.search(r"^  \w+  Mask  ", after, re.M), "Mask still exists"
    assert not re.search(r"<- Mask\b(?!2)", after), "unused"
    cv.invariants("test 6")
    cv.one_undo_step(before, after, "test 6")
    measure("6", "pass", f"gestures {gestures} (+ typing), undo steps 1, 3 chips read Mask2, Mask still exists unused")


def test_9_invalid_connection(cv):
    scene_p2(cv)
    # something to undo first: a valid drop (Mask2 -> E2.B), so a refusal that wrongly added history would show
    p, _ = cv.pins("Mask2")
    q, _ = cv.pins("E2")
    base = cv.stack()
    cv.ed.click(*p["out:Vec4"], to=q["in:B(4)"])
    cv.ed._frames(4)
    valid = cv.stack()
    assert valid != base and "B(4) <- Mask2" in valid, "valid drop connects"
    # type refusal: Vec3 -> Float
    p, _ = cv.pins("BaseColor")
    q, _ = cv.pins("Output__Target_Color")
    cv.ed.click(*p["out:Vec3"], to=q["in:A(1)"])
    cv.ed._frames(2)
    assert cv.stack() == valid, "type refusal changed the graph"
    # cycle refusal: E2 -> Emission.B
    p, _ = cv.pins("E2")
    q, _ = cv.pins("Emission")
    cv.ed.click(*p["out:Vec4"], to=q["in:B(4)"])
    cv.ed._frames(2)
    assert cv.stack() == valid, "cycle refusal changed the graph"
    cv.C("Undo")
    cv.ed._frames(3)
    assert cv.stack() == base, "a refusal left an entry in the history (one undo did not undo the valid drop)"
    cv.C("Redo")
    cv.ed._frames(3)
    # the order case: a producer below its consumer: accepted, the consumer and its dependents move, one undo step (the §7.3 popup was not built)
    cv.node("Vec4 Add", "Late", "Surface")
    cv.ed._frames(4)
    pre = cv.stack()
    p, _ = cv.pins("Late")
    q, _ = cv.pins("Emission")
    cv.ed.click(*p["out:Vec4"], to=q["in:B(4)"])
    cv.ed._frames(4)
    post = cv.stack()
    order = cv.order()
    assert post != pre and order.index("Late") < order.index("Emission") < order.index("E2"), order
    cv.invariants("test 9")
    cv.one_undo_step(pre, post, "test 9 order case")
    measure("9", "pass (order case differs from the spec row)", "type refusal and cycle refusal: graph unchanged, history size unchanged (one Undo undid the earlier valid drop); producer-below-consumer drop: accepted, Emission and E2 moved after Late, 1 undo step (no popup)")


def test_5_reorder_in_a_column(cv):
    cv.clear()
    s = cv.section("Surface")
    cv.node("Texture", "Albedo", s)
    cv.node("Texture", "Mask", s)
    cv.node("Vec4 Multiply", "Tint", s)
    cv.node("ToVec3", "BaseColor", s)
    cv.link("Albedo", "Tint.A")
    cv.link("Mask", "Tint.B")
    cv.link("Tint", "BaseColor.A")
    cv.link("BaseColor", "Output__Target_Color.Color")
    cv.node("Texture", "Detail", s)
    cv.node("Texture", "Detail2", s)
    cv.node("Vec4 Add", "D0", s)
    cv.node("Vec4 Add", "D1", s)
    cv.link("Detail", "D0.A")
    cv.link("Detail2", "D1.A")
    cv.ed._frames(6)
    before = cv.stack()
    st0 = cv.layout()
    a, b = cv.rect("@Detail2"), cv.rect("@Detail")
    cv.mv(a[0] + 30, a[1] + 8)
    cv.down()
    for i in range(1, 9):
        cv.mv(a[0] + 30, a[1] + 8 + (b[1] - 12 - a[1] - 8) * i / 8)
    cv.ed._frames(4)
    during = cv.stack()
    assert during == before, "the preview must not touch the graph"
    cv.up()
    cv.ed._frames(6)
    after = cv.stack()
    o = cv.order()
    assert o.index("Detail2") < o.index("Detail"), o
    assert re.findall(r"<- \w+", before.replace("\n", " ")).__len__() == re.findall(r"<- \w+", after.replace("\n", " ")).__len__(), "bindings unchanged"
    st1 = cv.layout()
    assert st1["crossings"] <= st0["crossings"], "crossings raised"
    cv.invariants("test 5")
    cv.one_undo_step(before, after, "test 5")
    # a drop that changes nothing, and Esc: no history
    for what in ("nochange", "esc"):
        marker = cv.stack()
        a, b = cv.rect("@D0"), cv.rect("@D1")
        cv.mv(a[0] + 30, a[1] + 8)
        cv.down()
        for i in range(1, 9):
            cv.mv(a[0] + 30, a[1] + 8 + (b[1] + b[3] + 12 - a[1] - 8) * i / 8)
        if what == "esc":
            cv.ed.post_key(0x1B)
        cv.up()
        cv.ed._frames(4)
        assert cv.stack() == marker, f"{what}: the graph changed"
    cv.C("Undo")
    cv.ed._frames(3)
    cv.C("Redo")
    cv.ed._frames(3)
    assert cv.stack() == after, "the no-change drop and Esc left history entries (one undo would not have been the reorder)"
    measure("5", "pass", f"undo steps 1 (0 for the no-change drop and Esc), bindings unchanged, crossings {st0['crossings']:.0f} -> {st1['crossings']:.0f}, order {' '.join(o[4:6])} after the drop")


def test_7_collapse_steps(cv):
    cv.clear()
    s = cv.section("Surface")
    cv.node("Texture", "Albedo", s)
    cv.node("Texture", "Mask", s)
    cv.node("Vec4 Multiply", "Tint", s)
    cv.node("ToVec3", "BaseColor", s)
    cv.link("Albedo", "Tint.A")
    cv.link("Mask", "Tint.B")
    cv.link("Tint", "BaseColor.A")
    cv.link("BaseColor", "Output__Target_Color.Color")
    cv.node("Vec4 Add", "D0", s)
    cv.link("Tint", "D0.A")
    cv.ed._frames(6)
    before = cv.stack()
    st_before = cv.layout()
    t, bc = cv.rect("@Tint"), cv.rect("@BaseColor")
    cv.ed.click(t[0] + 30, t[1] + 8)
    cv.ed._key("LCONTROL", True)
    cv.ed._frames(2)
    cv.ed.click(bc[0] + 30, bc[1] + 8)
    cv.ed._key("LCONTROL", False)
    cv.ed._frames(2)
    cv.ed.click(bc[0] + 30, bc[1] + 8, right=True)
    cv.ed._frames(4)
    mx, my = bc[0] + 30, bc[1] + 8
    cv.mv(mx + 40, my + 85)
    cv.ed._frames(4)
    cv.ed.click(mx + 40, my + 85)                          # Collapse
    cv.ed._frames(6)
    collapsed = cv.stack()
    m = re.search(r"section ([0-9A-F]+)  Group\s+\[collapsed\]", collapsed)
    assert m, collapsed
    st_c = cv.layout()
    assert st_c["segments through steps"] == 0
    box = cv.rect(m[1])
    assert box, "the collapsed box is on screen"
    cv.C("Undo")
    cv.ed._frames(3)
    assert cv.stack() == before, "one undo did not restore"
    cv.C("Redo")
    cv.ed._frames(3)
    assert cv.stack() == collapsed
    box = cv.rect(m[1])
    cv.ed.double_click(box[0] + 30, box[1] + 8)            # expand
    cv.ed._frames(6)
    expanded = cv.stack()
    assert "[collapsed]" not in expanded
    st_after = cv.layout()
    assert st_after["text"].split("layout")[0] == st_before["text"].split("layout")[0], "LayoutStats after expand differ from before collapse"
    cv.invariants("test 7")
    measure("7", "pass", f"undo steps 1 (collapse), LayoutStats before collapse = after expand (columns {st_before['columns']:.0f}, crossings {st_before['crossings']:.0f}, routes {st_before['routes']:.0f}); collapsed: columns {st_c['columns']:.0f}, routes {st_c['routes']:.0f}; segments through steps 0")


def test_10_add_one_node_to_a_large_material(cv):
    cv.clear()
    s = cv.section("Big")
    n = 100
    for i in range(n):
        cv.node("Texture", f"T{i}", s)
        cv.node("Vec4 Add", f"A{i}", s)
        cv.link(f"T{i}", f"A{i}.A")
        if i:
            cv.link(f"A{i - 1}", f"A{i}.B")
    cv.ed._frames(10)
    names = [f"T{i}" for i in range(0, n, 10)] + [f"A{i}" for i in range(0, n, 10)] + ["A99"]
    before = {k: cv.rect(f"@{k}") for k in names}
    st0 = cv.layout()
    cv.node("Vec2", "NewStep", "Big")                       # the console twin of the background menu's Add step: unwired, at the end of the section
    cv.ed._frames(6)
    after = {k: cv.rect(f"@{k}") for k in names}
    st1 = cv.layout()
    # the view origin may shift (the canvas follows the content's bounds): the layout moved nothing if every step kept its place relative to the first one
    dx, dy = after["T0"][0] - before["T0"][0], after["T0"][1] - before["T0"][1]
    moved = sum((after[k][0] - dx, after[k][1] - dy, *after[k][2:]) != before[k] for k in names)
    assert moved == 0, f"{moved} sampled steps moved by the add"
    steps_now = len([g for g, nm, _ in cv.steps() if g])
    assert cv.order().index("NewStep") == len(cv.order()) - 2, "the new step waits at the end of the section"
    cv.invariants("test 10")
    # a reorder (the console twin of the drag): the new step to the front of the section, one more layout
    cv.E(f"PlaceSteps -Nodes @NewStep -Section @Big -First 1")
    cv.ed._frames(6)
    st2 = cv.layout()
    after_place = cv.stack()
    cv.C("Undo")
    cv.ed._frames(3)
    assert cv.order().index("NewStep") == len(cv.order()) - 2, "one undo did not undo the reorder"
    cv.C("Redo")
    cv.ed._frames(3)
    assert cv.stack() == after_place
    measure("10", "pass (Debug build)", f"steps {steps_now}, sampled steps moved by the add {moved} of {len(names)} (view origin shift {dx},{dy} px), layout ms: before add {st0['ms']:.2f}, after add {st1['ms']:.2f}, after a reorder {st2['ms']:.2f}, columns {st1['columns']:.0f}, crossings {st1['crossings']:.0f}; the drag preview itself was not driven (the new step is off screen at 200 steps)")
