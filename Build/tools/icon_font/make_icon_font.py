"""Builds source/Assets/Fonts/segmdl2_compat.ttf: a free stand-in for Segoe MDL2 Assets.

The editor draws its icons as Segoe MDL2 code points (U+E700 ChevronDown...). That font ships only
with Windows and can't be redistributed, so off Windows those icons were "?" boxes. This font puts
Fluent UI System Icons (MIT, https://github.com/microsoft/fluentui-system-icons) at the same code
points, so the same strings draw a matching icon. icon_map.txt lists them: "<code point> <fluent
name>[:filled]". A new MDL2 glyph in the code needs a line there and a re-run.

Usage: python make_icon_font.py <path to the @fluentui/svg-icons package> [out.ttf]
       (npm pack @fluentui/svg-icons, then untar; needs fonttools)
       python make_icon_font.py --check      lists the code points the code uses that icon_map.txt lacks
"""
import glob, os, re, sys

here = os.path.dirname(os.path.abspath(__file__))

if len(sys.argv) > 1 and sys.argv[1] == "--check":
    root  = os.path.join(here, "..", "..", "..")
    known = {int(l.split()[0], 16) for l in open(os.path.join(here, "icon_map.txt")) if l.strip() and not l.startswith("#")}
    used  = {}
    def sources():
        tops = [os.path.join(root, d) for d in ("source", "plugins")]
        tops += [os.path.join(dep, d) for dep in glob.glob(os.path.join(root, "dependencies", "*")) for d in ("source", "src", "include")]
        for top in tops:
            for d, _, files in os.walk(top):     # (links inside are not followed: plugins and dependencies link to each other)
                yield from (os.path.join(d, f) for f in files if f.endswith((".h", ".hpp", ".inl", ".cpp")))
    for path in sources():
        for m in re.finditer(rb"(?:\\x[0-9A-Fa-f]{2}){3}", open(path, "rb").read()):
            try:    cp = ord(bytes(int(x, 16) for x in re.findall(rb"x([0-9A-Fa-f]{2})", m.group())).decode())
            except: continue
            if 0xE000 <= cp <= 0xF8FF and cp not in known: used.setdefault(cp, os.path.relpath(path, root))
    for cp, path in sorted(used.items()): print(f"{cp:04X}  {path}")
    sys.exit(1 if used else 0)
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.svgLib.path import parse_path

EM = 2048       # Segoe MDL2's own em and metrics: ascent 2048, descent 0, every glyph 1 em wide
VIEW = 20.0     # Fluent's 20px icons

pkg  = sys.argv[1]
out  = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "..", "..", "..", "source", "Assets", "Fonts", "segmdl2_compat.ttf")

order, cmap, glyphs, metrics = [".notdef"], {}, {}, {".notdef": (EM, 0)}
glyphs[".notdef"] = TTGlyphPen(None).glyph()
for line in open(os.path.join(here, "icon_map.txt")):
    if not line.strip() or line.startswith("#"): continue
    code, name = line.split()
    base, _, style = name.partition(":")
    svg  = open(os.path.join(pkg, "icons", f"{base}_20_{style or 'regular'}.svg")).read()
    gname = f"uni{code.upper()}"
    pen = TTGlyphPen(None)
    # SVG is y down in a 20x20 box; the font is y up in a 2048 em
    tpen = TransformPen(Cu2QuPen(pen, 1.0), (EM / VIEW, 0, 0, -EM / VIEW, 0, EM))
    for d in re.findall(r'<path[^>]*\sd="([^"]+)"', svg):
        parse_path(d, tpen)
    glyphs[gname] = pen.glyph()
    order.append(gname)
    cmap[int(code, 16)] = gname
    metrics[gname] = (EM, 0)

fb = FontBuilder(EM, isTTF=True)
fb.setupGlyphOrder(order)
fb.setupCharacterMap(cmap)
fb.setupGlyf(glyphs)
glyf = fb.font["glyf"]
for g in order: glyf[g].recalcBounds(glyf)
fb.setupHorizontalMetrics({g: (metrics[g][0], getattr(glyf[g], "xMin", 0)) for g in order})
fb.setupHorizontalHeader(ascent=EM, descent=0)
fb.setupNameTable({"familyName": "Segoe MDL2 Compat (Fluent)", "styleName": "Regular",
                   "copyright": "Glyphs from Fluent UI System Icons, Copyright (c) Microsoft Corporation, MIT License"})
fb.setupOS2(sTypoAscender=EM, sTypoDescender=0, usWinAscent=EM, usWinDescent=0)
fb.setupPost()
os.makedirs(os.path.dirname(out), exist_ok=True)
fb.save(out)
print(f"{out}: {len(cmap)} icons")
