"""GPU cluster culling benchmark (documentation/gpu_cluster_culling.md): per view and switch, several editor launches, several of the editor's
120-frame means each (XLION_GPU_TIMES RENDERGPU, XLION_FRAME_TIMES RENDERCPU), only while nothing compiles - medians, min and max.

    python -I bench_cull.py <out_dir> [launches=3] [samples=7] [views=police,bistro,bistro_street] [switches=gpu,frustum,cpu]

Views: the Police level from inside; the Bistro's GeomStatic preview as it opens (outside) and at street level. Switches: GPU culling
(occlusion adaptive), frustum only (XLION_NO_GPU_OCCLUSION), the CPU path (XLION_NO_GPU_CULL). The Release editor (BENCH_CONFIG=Debug: the Debug one), maximized, no validation,
no frame budget. A launch whose samples overlapped a compile (harness.compile_snapshot before and after) is dropped.
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import statistics as st
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import harness
from harness import Editor, REPO

BISTRO   = "4854F8D7DA54C001" + "E5359948C52D26D1"      # GeomStatic: instance + type
POLICE   = "EF31687D49834DD9"                           # Level
SWITCHES = {"gpu": {}, "frustum": {"XLION_NO_GPU_OCCLUSION": "1"}, "cpu": {"XLION_NO_GPU_CULL": "1"}}
BASE     = {"XLION_FRAME_TIMES": "1", "XLION_GPU_TIMES": "1", "XLION_NO_FRAME_BUDGET": "1", "XLION_NO_VALIDATION": "1"}     # (Release: validation off already)


def maximize(pid: int) -> list[tuple[int, int]]:
    """The editor's top-level window maximized (timings of a small window are biased); its client size."""
    U = ctypes.windll.user32
    found = []
    def cb(h, _):
        p = wt.DWORD(); U.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and U.IsWindowVisible(h) and not U.GetWindow(h, 4):
            found.append(h)
        return True
    U.EnumWindows(ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)(cb), 0)
    for h in found: U.ShowWindow(h, 3)
    time.sleep(1.5)
    sizes = []
    for h in found:
        r = wt.RECT(); U.GetClientRect(h, ctypes.byref(r)); sizes.append((r.right - r.left, r.bottom - r.top))
    return sizes


def open_view(ed: Editor, view: str) -> None:
    if view == "police":
        ed._roundtrip(f"OpenLevel -Level {POLICE}", 300)
        ed._roundtrip(r"Police Level\SetCamera -Mode orbit -Yaw 210 -Pitch -20 -Distance 9 -Target 0,1.5,0", 60)
        return
    lib = ed.libraries()[0][0]
    ed.cmd(f"OpenResourceEditor -Asset {BISTRO} -Library {lib}", timeout=300)
    if view == "bistro_street":
        time.sleep(5)
        ed.cmd(f'ResourceEditorCommand -Asset {BISTRO} -Cmd "SetCamera -Yaw 0 -Pitch 0 -Distance 6 -Target 15,2,2.7"', timeout=60)


def number(line: str, pattern: str) -> float | None:
    m = re.search(pattern, line)
    return float(m[1]) if m else None


def launch(out: Path, view: str, switch: str, k: int, samples: int) -> dict:
    tag = f"{view}_{switch}_{k}"
    (out / "logs" / tag).mkdir(parents=True, exist_ok=True)
    extra = {k: v for k, v in os.environ.items() if k.startswith(("XLION_", "XGPU_"))}      # (experiments: e.g. XLION_NO_PREPASS=1 for every run)
    exe = harness.DEFAULT_EXE.parent.parent / os.environ.get("BENCH_CONFIG", "Release") / harness.DEFAULT_EXE.name     # (Release: its timings are the real ones)
    ed = Editor(exe, log_dir=out / "logs" / tag, extra_env={**BASE, **extra, **SWITCHES[switch]})
    ed.start()
    res = {"tag": tag, "view": view, "switch": switch}
    try:
        res["window"] = maximize(ed.proc.pid)
        open_view(ed, view)
        time.sleep(10)                                              # (settled: the GI, the culling's history)
        before = ed.wait_compile_idle(timeout=3600)
        gpu = ed.log_samples("RENDERGPU", samples, timeout=300)
        cpu = [l for l in ed.log_text().splitlines() if "RENDERCPU" in l][-samples:]
        after = harness.compile_snapshot(ed)
        res["valid"] = before["idle"] and after["idle"] and len(gpu) == samples
        res["gpu_ms"] = [number(l, r"shadows\+scene\+tonemap ([\d.]+)") for l in gpu]
        res["cpu_ms"] = [number(l, r"scene pass ([\d.]+)") for l in cpu]
        cull = [l for l in ed.log_text().splitlines() if "CULLGPU" in l]
        res["cull"] = cull[-1].strip() if cull else ""
    finally:
        ed.stop()
    return res


def main(argv: list[str]) -> int:
    out      = Path(argv[0])
    launches = int(argv[1]) if len(argv) > 1 else 3
    samples  = int(argv[2]) if len(argv) > 2 else 7
    views    = (argv[3] if len(argv) > 3 else "police,bistro,bistro_street").split(",")
    switches = (argv[4] if len(argv) > 4 else "gpu,frustum,cpu").split(",")
    out.mkdir(parents=True, exist_ok=True)
    runs = []
    for view in views:
        for k in range(launches):                                   # (the switches interleaved: a slow drift hits them alike)
            for switch in switches:
                r = launch(out, view, switch, k, samples)
                print(json.dumps(r), flush=True)
                runs.append(r)
    (out / "runs.json").write_text(json.dumps(runs, indent=1))

    lines = ["| View | Switch | GPU ms median (min-max) | CPU scene pass ms median (min-max) | launches kept |", "|---|---|---|---|---|"]
    for view in views:
        for switch in switches:
            kept = [r for r in runs if r["view"] == view and r["switch"] == switch and r["valid"]]
            g = [v for r in kept for v in r["gpu_ms"] if v is not None]
            c = [v for r in kept for v in r["cpu_ms"] if v is not None]
            f = lambda v: f"{st.median(v):.3f} ({min(v):.3f}-{max(v):.3f})" if v else "-"
            lines.append(f"| {view} | {switch} | {f(g)} | {f(c)} | {len(kept)} of {launches} |")
    table = "\n".join(lines)
    (out / "table.md").write_text(table + "\n")
    print(table)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
