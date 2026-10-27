"""Reflections on Police (documentation/reflections_strategy.md milestone B): screenshots with the traced / planar reflections off and on,
the same views each (Lily over the floor, the corridor). The Release editor, maximized; nothing saved unless --save.
    python refl_police.py <out_dir> [--floor-y 1.5] [--rough 0.3] [--save]"""
import argparse, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness, bench_cull
from harness import Editor

LEVEL, SCENE, ENV_ID, L = "EF31687D49834DD9", "EF19AB610AD85421", "00000003", "Police Level"
VIEWS = {"lily": "250,-4,4,0.8/1.9/5.3", "spheres": "250,-14,3.6,0.6/2.0/2.6", "spheres_low": "200,-5,3.2,0.6/1.95/2.6"}

ap = argparse.ArgumentParser()
ap.add_argument("out"); ap.add_argument("--floor-y", type=float, default=1.5); ap.add_argument("--rough", type=float, default=0.3); ap.add_argument("--save", action="store_true")
a = ap.parse_args()
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)


def capture(ed, name):
    p = out / f"{name}.png"
    if p.exists(): p.unlink()
    ed.cmd(f"CaptureWindow -File {p}")
    for _ in range(40):
        if p.exists(): break
        time.sleep(0.25)
    print("captured", p, p.exists(), flush=True)


ed = Editor(harness.DEFAULT_EXE.parent.parent / "Release" / harness.DEFAULT_EXE.name, log_dir=out / "log", extra_env={"XLION_GPU_TIMES": "1"})
ed.start()
try:
    bench_cull.maximize(ed.proc.pid)
    ed.wait_compile_idle(timeout=3600)
    ed._roundtrip(f"OpenLevel -Level {LEVEL}", 300)
    time.sleep(25)
    setp = lambda p, v: ed.cmd(rf"{L}\SetProperty -Scene {SCENE} -Id {ENV_ID} -Component Environment -Path Environment/{p} -After {v}")
    for state in ("off", "on"):
        if state == "on":
            setp("ReflectionFloorY", a.floor_y); setp("ReflectionFloor", "true"); setp("ReflectionMaxRoughness", a.rough)
        for name, cam in VIEWS.items():
            yaw, pitch, dist, tgt = cam.split(",")
            ed.cmd(rf"{L}\SetCamera -Mode orbit -Yaw {yaw} -Pitch {pitch} -Distance {dist} -Target {tgt.replace('/', ',')}")
            time.sleep(4)
            capture(ed, f"{name}_{state}")
            setp("ReflectionDebug", "true"); time.sleep(3); capture(ed, f"{name}_{state}_debug"); setp("ReflectionDebug", "false")
    time.sleep(5)
    print("\n".join([l for l in ed.log_text().splitlines() if "REFLBENCH" in l or "RENDERGPU" in l][-4:]))
    if a.save: ed.cmd(f"{L}\\Save", timeout=120)
finally:
    ed.stop(graceful=False)
