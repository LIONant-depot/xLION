"""One RenderDoc capture of the Bistro preview (outside) from the Release editor, per path: frustum-only GPU culling and the CPU path."""
import sys, time
from pathlib import Path
sys.path.insert(0, r"D:\LIONant\xLION\source\Editors\LevelEditor\smoke")
import harness
import bench_cull
from harness import Editor

OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
EXE = harness.DEFAULT_EXE.parent.parent / "Release" / harness.DEFAULT_EXE.name
for switch in ("frustum", "cpu"):
    trig = OUT / f"trigger_{switch}"
    env = {**bench_cull.BASE, **bench_cull.SWITCHES[switch], "ENABLE_VULKAN_RENDERDOC_CAPTURE": "1",
           "XGPU_RENDERDOC_TRIGGER": str(trig), "XGPU_RENDERDOC_CAPTURE_PATH": str(OUT / f"bistro_{switch}")}
    (OUT / "logs" / switch).mkdir(parents=True, exist_ok=True)
    ed = Editor(EXE, log_dir=OUT / "logs" / switch, extra_env=env)
    ed.start()
    try:
        print(switch, "window", bench_cull.maximize(ed.proc.pid), flush=True)
        bench_cull.open_view(ed, "bistro")
        time.sleep(15)
        print(switch, "idle", ed.wait_compile_idle(timeout=3600)["idle"], flush=True)
        trig.write_text("capture")
        for _ in range(60):
            if not trig.exists(): break
            time.sleep(0.5)
        time.sleep(8)
        print(switch, "captures", [p.name for p in OUT.glob(f"bistro_{switch}*.rdc")], "after idle", harness.compile_snapshot(ed)["idle"], flush=True)
    finally:
        ed.stop()
