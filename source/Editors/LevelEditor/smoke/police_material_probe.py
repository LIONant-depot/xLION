"""Which Police material is drawn where: every material instance of the Police Station tinted a hue of its own (BaseColorFactor), a
capture, then every tint cleared. Prints the instances and their hues; the screenshot shows which is where.
    python police_material_probe.py tint|clear <out_dir>"""
import colorsys, json, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness, bench_cull
from harness import Editor

PROJECT = Path(r"D:\LIONant\xLION\example.lionprj")
MI_TYPE = "B673C5DA4A4A70AD"
LEVEL, L = "EF31687D49834DD9", "Police Level"
mode, out = sys.argv[1], Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)

desc = (PROJECT / "Descriptors" / "GeomStatic" / "73" / "9D" / "1B2E7050C4FC9D73.desc" / "Descriptor.txt").read_text(encoding="utf-8")
guids = sorted(set(re.findall(r'MaterialDetailsList\[G:\d+\]/Instance"\s*;full_guid\s+#([0-9A-F]+) #' + MI_TYPE, desc)))
names = {}
for g in guids:
    v = int(g, 16)
    info = PROJECT / "Descriptors" / "MaterialInstance" / f"{v & 0xFF:02X}" / f"{(v >> 8) & 0xFF:02X}" / f"{v:X}.desc" / "Info.txt"
    m = re.search(r'Info/Name"\s*;string\s*"([^"]*)"', info.read_text(encoding="utf-8")) if info.exists() else None
    names[g] = m[1] if m else None
named = [g for g in guids if names[g]]
hues = {g: colorsys.hsv_to_rgb(i / len(named), 1.0, 1.0) for i, g in enumerate(named)}

ed = Editor(harness.DEFAULT_EXE.parent.parent / "Release" / harness.DEFAULT_EXE.name, log_dir=out / "log")
ed.start()
try:
    ed.wait_compile_idle(timeout=3600)
    lib = ed.libraries()[0][0]
    for g in named:
        n = names[g]
        ed.cmd(f"OpenResourceEditor -Asset {int(g, 16):016X}{MI_TYPE} -Library {lib}", timeout=120)
        if mode == "tint":
            r, gg, b = hues[g]
            ed.cmd(f'{n}\\SetOverride -Id @BaseColorFactor -Value "{r:.3f}, {gg:.3f}, {b:.3f}"')
        else:
            ed.cmd(f"{n}\\ClearOverride -Id @BaseColorFactor")
        ed.cmd(f"{n}\\Save", timeout=60, allow_disk=True)
        ed.cmd(f"CloseResourceEditor -Asset {int(g, 16):016X}{MI_TYPE}")
    (out / "hues.json").write_text(json.dumps({names[g]: hues[g] for g in named}, indent=1))
    if mode == "tint":
        ed.wait_compile_idle(timeout=3600)
        bench_cull.maximize(ed.proc.pid)
        ed._roundtrip(f"OpenLevel -Level {LEVEL}", 300)
        time.sleep(20)
        ed.cmd(rf"{L}\SetCamera -Mode orbit -Yaw 180 -Pitch -12 -Distance 3.2 -Target 0.6,2.0,3.4")
        time.sleep(5)
        p = out / "tinted.png"
        ed.cmd(f"CaptureWindow -File {p}")
        for _ in range(40):
            if p.exists(): break
            time.sleep(0.25)
finally:
    ed.stop(graceful=False)
print(json.dumps({names[g]: [round(c, 2) for c in hues[g]] for g in named}))
