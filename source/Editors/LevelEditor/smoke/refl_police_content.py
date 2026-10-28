"""Police's reflection test content (documentation/reflections_strategy.md milestone B; Tomas 2026-10-28):
  1. the floor tiles. material ("Police 15m": 15c.jpeg) more reflective - its RoughnessFactor (the shared ORME's 0.78 times it)
  2. a sphere grid (make_sphere_grid.py: dielectric and metal, roughness 0 .. 1) as a GeomStatic with its materials imported, placed in
     the Police scene on the floor
    python refl_police_content.py step1|step2|step3 [--rough-factor 0.25]
step1: the floor's override and the grid's asset (CreateAsset); step2 (no editor running): the grid's descriptor (import, merge, GI);
step3: the grid's entity in Police, saved"""
import argparse, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness, bench_cull
from harness import Editor, quote

PROJECT   = Path(r"D:\LIONant\xLION\example.lionprj")
FLOOR_MI  = "697AF9FF5ED70AA5" + "B673C5DA4A4A70AD"      # "Police 15m" (15c.jpeg: the checkered tiles; police_material_probe.py found it)
GEOM_TYPE = "E5359948C52D26D1"
GRID      = "7EF1EC75F00D0001"                           # the grid's GeomStatic
POLICE_GEOM = "1B2E7050C4FC9D73"
LEVEL, SCENE, L = "EF31687D49834DD9", "EF19AB610AD85421", "Police Level"
FOLDER_TYPE = "C4D90C5F0CC43021"

ap = argparse.ArgumentParser(); ap.add_argument("step"); ap.add_argument("--rough-factor", default="0.25"); ap.add_argument("--color", default=""); ap.add_argument("--at", default="0.6,1.726,3.4"); ap.add_argument("--max-rough", default="0.5")
a = ap.parse_args()


def editor():
    ed = Editor(harness.DEFAULT_EXE.parent.parent / "Release" / harness.DEFAULT_EXE.name, log_dir=PROJECT.parent / "Build" / "refl_content_log")
    ed.start()
    ed.wait_compile_idle(timeout=3600)
    return ed


def police_folder() -> str:
    info = (PROJECT / "Descriptors" / "GeomStatic" / "73" / "9D" / f"{POLICE_GEOM}.desc" / "info.txt").read_text()
    return re.search(r'RscLinks\[G:0\]"\s*;full_guid #([0-9A-F]+) #' + FOLDER_TYPE, info)[1]


if a.step in ("step1", "floor"):
    ed = editor()
    try:
        lib = ed.libraries()[0][0]
        print(ed.cmd(f"OpenResourceEditor -Asset {FLOOR_MI} -Library {lib}", timeout=120))
        print(ed.cmd(f"Police 15m\\SetOverride -Id @RoughnessFactor -Value {a.rough_factor}"))
        if a.color: print(ed.cmd(f'Police 15m\\SetOverride -Id @BaseColorFactor -Value "{a.color}"'))
        print(ed.cmd(f"Police 15m\\ListOverrides"))
        print(ed.cmd(f"Police 15m\\Save", timeout=60, allow_disk=True))
        print(ed.cmd(f"CloseResourceEditor -Asset {FLOOR_MI}"))
        if a.step == "floor": raise SystemExit(0)
        folder = police_folder()
        print(ed.cmd(f"CreateAsset -Library {lib} -Type {GEOM_TYPE} -Asset {GRID}{GEOM_TYPE} -Parent {folder}{FOLDER_TYPE} -Name {quote('Reflection Test Spheres')}", allow_disk=True))
        time.sleep(3)
    finally:
        ed.stop()

elif a.step == "step2":
    d = PROJECT / "Descriptors" / "GeomStatic" / f"{int(GRID, 16) & 0xFF:02X}" / f"{(int(GRID, 16) >> 8) & 0xFF:02X}" / f"{int(GRID, 16):X}.desc" / "Descriptor.txt"
    s = d.read_text(encoding="utf-8")
    print(s[:3000])

elif a.step == "env":          # Police's Environment: the reflections on (traced up to --max-rough: 0.5 with D's reconstruction; the floor's planar view), saved
    ed = editor()
    try:
        ed._roundtrip(f"OpenLevel -Level {LEVEL}", 300)
        time.sleep(10)
        for p, v in (("ReflectionMaxRoughness", a.max_rough), ("ReflectionFloor", "true"), ("ReflectionFloorAuto", "true")):
            print(ed.cmd(rf"{L}\SetProperty -Scene {SCENE} -Id 00000003 -Component Environment -Path Environment/{p} -After {v}"))
        print(ed.cmd(rf"{L}\Save", timeout=120, allow_disk=True))
    finally:
        ed.stop()

elif a.step == "move":         # the grid along the corridor (its rows across it are too wide for it)
    ed = editor()
    try:
        ed._roundtrip(f"OpenLevel -Level {LEVEL}", 300)
        time.sleep(10)
        x, y, z = a.at.split(",")
        for p, v in (("Transform/RotationDegrees/Y", "90"), ("Transform/Position/X", x), ("Transform/Position/Y", y), ("Transform/Position/Z", z)):
            print(ed.cmd(rf"{L}\SetProperty -Scene {SCENE} -Id 7EF1EC75 -Component Transform -Path {p} -After {v}"))
        print(ed.cmd(rf"{L}\Save", timeout=120, allow_disk=True))
    finally:
        ed.stop()

elif a.step == "step3":
    ed = editor()
    try:
        ed._roundtrip(f"OpenLevel -Level {LEVEL}", 300)
        time.sleep(10)
        x, y, z = a.at.split(",")
        ent = "7EF1EC75"
        print(ed.cmd(rf"{L}\CreateEntity -Scene {SCENE} -Id {ent} -Folder 0 -Components Transform,Mesh"))
        for p, v in (("Transform/Position/X", x), ("Transform/Position/Y", y), ("Transform/Position/Z", z)):
            print(ed.cmd(rf"{L}\SetProperty -Scene {SCENE} -Id {ent} -Component Transform -Path {p} -After {v}"))
        print(ed.cmd(rf'{L}\SetProperty -Scene {SCENE} -Id {ent} -Component Mesh -Path Mesh/Geom -After "{GRID}, {GEOM_TYPE}"'))
        time.sleep(5)
        print(ed.cmd(rf"{L}\Save", timeout=120, allow_disk=True))
    finally:
        ed.stop()
