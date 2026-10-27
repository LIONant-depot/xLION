"""Reflections milestone A (documentation/reflections_strategy.md sec. 11, 12): the world trace's cost on the real scenes.
One reflection ray per texel of the screen tail's thin G-buffer (half size) through the GI's BVH (xlionrender_refl_trace_comp.glsl),
in three modes the editor cycles through (XLION_REFL_BENCH=9): 1 mirror rays (coherent), 2 roughness 0.5 everywhere (incoherent),
3 the materials' roughness. The Release editor, maximized, no validation, no frame budget; samples only while nothing compiles.
    python bench_reflections.py <out_dir> [launches=2] [samples=9] [views=police,bistro,bistro_street]
Prints the REFLBENCH lines (GPU ms, rays, Mrays/s, hit rate, BVH visits a ray) and a table of the medians per view and mode."""
import json, os, re, statistics as st, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness, bench_cull
from harness import Editor

BASE = {"XLION_REFL_BENCH": "9", "XLION_NO_VALIDATION": "1", "XLION_NO_FRAME_BUDGET": "1"}
LINE = re.compile(r"REFLBENCH mode (\d), (\d+) x (\d+): ([\d.]+) ms, (\d+) rays \((\d+) Mrays/s\), hits ([\d.]+)%, BVH visits ([\d.]+)")


def launch(out: Path, view: str, k: int, samples: int) -> dict:
    tag = f"{view}_{k}"
    (out / "logs" / tag).mkdir(parents=True, exist_ok=True)
    exe = harness.DEFAULT_EXE.parent.parent / "Release" / harness.DEFAULT_EXE.name
    ed = Editor(exe, log_dir=out / "logs" / tag, extra_env=BASE)
    ed.start()
    res = {"tag": tag, "view": view}
    try:
        res["window"] = bench_cull.maximize(ed.proc.pid)
        bench_cull.open_view(ed, view)
        time.sleep(10)
        before = ed.wait_compile_idle(timeout=3600)
        lines = ed.log_samples("REFLBENCH", samples, timeout=600)
        after = harness.compile_snapshot(ed)
        res["valid"] = before["idle"] and after["idle"] and len(lines) == samples
        res["samples"] = [list(m.groups()) for m in (LINE.search(l) for l in lines) if m]
    finally:
        ed.stop()
    return res


def main(argv: list[str]) -> int:
    out      = Path(argv[0])
    launches = int(argv[1]) if len(argv) > 1 else 2
    samples  = int(argv[2]) if len(argv) > 2 else 9
    views    = (argv[3] if len(argv) > 3 else "police,bistro,bistro_street").split(",")
    out.mkdir(parents=True, exist_ok=True)
    runs = []
    for view in views:
        for k in range(launches):
            r = launch(out, view, k, samples)
            print(json.dumps(r), flush=True)
            runs.append(r)
    (out / "runs.json").write_text(json.dumps(runs, indent=1))
    names = {"1": "mirror", "2": "roughness 0.5", "3": "materials"}
    lines = ["| View | Rays | Size | GPU ms median | Mrays/s | Hits | BVH visits a ray | Samples |", "|---|---|---|---|---|---|---|---|"]
    for view in views:
        for mode in ("1", "2", "3"):
            s = [x for r in runs if r["view"] == view and r["valid"] for x in r["samples"] if x[0] == mode]
            if not s: continue
            med = lambda i: st.median(float(x[i]) for x in s)
            lines.append(f"| {view} | {names[mode]} | {s[0][1]} x {s[0][2]} | {med(3):.3f} | {med(5):.0f} | {med(6):.1f}% | {med(7):.1f} | {len(s)} |")
    table = "\n".join(lines)
    (out / "table.md").write_text(table + "\n")
    print(table)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
