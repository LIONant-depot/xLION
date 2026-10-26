"""The lighting ledger (documentation/lighting_strategy.md sec. 10): median, p95 and p99 per ledger row, with the GPU's clock state.

    python -I lighting_ledger.py <out_dir> [stress,police] [seconds=60]

stress: the stress city (xLIONRender's xlionrender_stress, Release), every scenario, light modes cells and sampled; per frame from its
        CSV, the first 60 frames of a scenario apart (cold start). The warmed-benchmark condition.
police: the Police level in a Release harness editor (never the user's), twice: maximized with no frame budget (warmed benchmark),
        and the default window with the frame budget (editor-normal). Per-frame GPU samples from GPUTIMES (one frame every 120),
        the CPU from RENDERCPU (120-frame means), and the LEDGER lines when the editor prints them (XLION_LEDGER). Compile idle is
        checked before and after; a run that overlapped a compile is marked invalid.
Clocks: nvidia-smi sampled every 500 ms during each run (pstate, graphics and memory MHz).
"""
import json
import os
import re
import statistics as st
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import harness
from harness import Editor, REPO
import bench_cull

STRESS_DIR = REPO / "example.lionprj" / "Cache" / "dependencies" / "xLIONRender" / "Build" / "test" / "vs2022" / "Release"


def stats(v: list) -> dict:
    v = sorted(x for x in v if x is not None)
    if not v: return {}
    q = lambda p: v[min(len(v) - 1, int(len(v) * p))]
    return {"median": round(st.median(v), 4), "p95": round(q(0.95), 4), "p99": round(q(0.99), 4), "n": len(v)}


class Clocks:
    """nvidia-smi in the background while a run lasts."""
    def __enter__(self):
        self.p = subprocess.Popen(["nvidia-smi", "--query-gpu=pstate,clocks.gr,clocks.mem", "--format=csv,noheader,nounits", "-lms", "500"],
                                  stdout=subprocess.PIPE, text=True)
        return self
    def __exit__(self, *_):
        self.p.terminate()
        out, _ = self.p.communicate(timeout=10)
        rows = [r.split(", ") for r in out.splitlines() if r.count(",") == 2]
        self.result = {"pstates": sorted({r[0] for r in rows}), "graphics_mhz": stats([float(r[1]) for r in rows]),
                       "memory_mhz": stats([float(r[2]) for r in rows])}


def stress(out: Path) -> dict:
    res = {}
    for mode in ("cells", "sampled"):
        csv = out / f"stress_{mode}.csv"
        with Clocks() as c:
            r = subprocess.run([str(STRESS_DIR / "xlionrender_stress.exe"), "--scenario", "all", "--mode", mode, "--csv", str(csv)],
                               cwd=STRESS_DIR, capture_output=True, text=True, timeout=1800)
        (out / f"stress_{mode}.log").write_text(r.stdout + r.stderr)
        lines = csv.read_text().splitlines()
        head = lines[0].split(",")
        rows = [dict(zip(head, l.split(","))) for l in lines[1:]]
        for scen in sorted({x["scenario"] for x in rows}):
            fr = [x for x in rows if x["scenario"] == scen]
            warm, cold = fr[60:], fr[:60]
            col = lambda rs, k: [float(x[k]) for x in rs]
            res[f"{scen}_{mode}"] = {
                "records+grid cpu": stats(col(warm, "cpu_cells_ms")),
                "shadow prep gpu": stats(col(warm, "gpu_shadow_ms")), "shadow prep cpu": stats(col(warm, "cpu_shadows_ms")),
                "direct shading (scene pass) gpu": stats(col(warm, "gpu_scene_ms")),
                "cold start: shadow prep gpu": stats(col(cold, "gpu_shadow_ms")), "cold start: scene pass gpu": stats(col(cold, "gpu_scene_ms")),
                "frame wall": stats(col(warm, "wall_ms")), "lights": warm[0]["lights"] if warm else "-", "clocks": c.result}
    return res


def police(out: Path, seconds: int, benchmark: bool) -> dict:
    tag = "police_" + ("benchmark" if benchmark else "editor_normal")
    (out / tag).mkdir(parents=True, exist_ok=True)
    exe = harness.DEFAULT_EXE.parent.parent / "Release" / harness.DEFAULT_EXE.name
    env = {"XLION_FRAME_TIMES": "1", "XLION_GPU_TIMES": "1", "XLION_LEDGER": "1", **({"XLION_NO_FRAME_BUDGET": "1"} if benchmark else {})}
    ed = Editor(exe, log_dir=out / tag, extra_env=env)
    ed.start()
    res = {"exe_time": time.ctime(exe.stat().st_mtime)}
    try:
        if benchmark: res["window"] = bench_cull.maximize(ed.proc.pid)
        bench_cull.open_view(ed, "police")
        time.sleep(10)
        before = ed.wait_compile_idle(timeout=3600)
        n0 = len(ed.log_text().splitlines())
        with Clocks() as c:
            time.sleep(seconds)
        lines = ed.log_text().splitlines()[n0:]
        after = harness.compile_snapshot(ed)
        num = lambda pat: [float(m[1]) for l in lines if (m := re.search(pat, l))]
        res.update({"valid": before["idle"] and after["idle"], "clocks": c.result,
                    "shadow prep gpu (frame samples)": stats(num(r"GPUTIMES shadows ([\d.]+)")),
                    "scene pass gpu (frame samples)": stats(num(r"GPUTIMES shadows [\d.]+ scene ([\d.]+)")),
                    "shadows+probes cpu (120-frame means)": stats(num(r"RENDERCPU .*shadows\+probes ([\d.]+)")),
                    "scene pass cpu (120-frame means)": stats(num(r"RENDERCPU .*scene pass ([\d.]+)")),
                    "ledger": [l.strip() for l in lines if "LEDGER" in l][-5:]})
    finally:
        ed.stop()
    return res


def main(argv: list[str]) -> int:
    out = Path(argv[0]); out.mkdir(parents=True, exist_ok=True)
    what = (argv[1] if len(argv) > 1 else "stress,police").split(",")
    seconds = int(argv[2]) if len(argv) > 2 else 60
    res = {}
    if "stress" in what: res["stress"] = stress(out)
    if "police" in what:
        res["police_benchmark"] = police(out, seconds, True)
        res["police_editor_normal"] = police(out, seconds, False)
    (out / "ledger.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
