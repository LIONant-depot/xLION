"""The GI baseline: a fixed record of the Police Station's GI that every GI change is measured against (not a pass/fail test).

    python gi_baseline.py <label>          -> Build/gi_baseline/<label>/   (baseline.json, the images, the surfel dumps)
    python gi_baseline.py <label> <ref>    -> the same, then compared with Build/gi_baseline/<ref>/

What it records:
  identity   the repos' commits (and whether they have changes), hashes of the shader sources and of the compiled
             Material / MaterialInstance / GeomStatic / Texture resources, the Environment's GI settings
  timings    the Level open, until the GI capture is done, the GI's per-frame ms and rays (DescribeScene)
  images     per view: LIGHT per pixel, LIGHT per vertex only (GIPerPixel off), SURFELS, SURFACE_COLOR, the final image
             (tone-mapped window captures)
  surfels    DumpGI twice, 10 s apart: per surfel the solver's light (unfiltered), the shown light (filtered), validity,
             albedo. The two dumps give the temporal noise: the floor of any tolerance between runs
"""
import hashlib, json, subprocess, sys, time
from pathlib import Path
from PIL import Image, ImageChops, ImageStat
sys.path.insert(0, str(Path(__file__).parent))
from harness import Editor  # noqa: E402

ROOT  = Path(__file__).resolve().parents[4]
EXE   = ROOT / "Build/xLION.vs2022/Release/xLION.exe"
OUT   = ROOT / "Build/gi_baseline"
LEVEL, SCENE, ENV_ID = "EF31687D49834DD9", "EF19AB610AD85421", "00000003"      # the Police Level, its scene, the Environment entity
VIEWS = {   # name: SetCamera arguments
    "blinds": "-Target -42.2936,1.12125,14.0861 -Distance 3.66 -Yaw 176.84 -Pitch -7.45",
    "wide":   "-Target -42.2936,1.12125,14.0861 -Distance 12 -Yaw 176.84 -Pitch -15",
}
MODES = [   # name, GIDebug, GIPerPixel
    ("light_pixel", "LIGHT", "true"), ("light_vertex", "LIGHT", "false"),
    ("surfels", "SURFELS", "true"), ("surface_color", "SURFACE_COLOR", "true"), ("final", "NONE", "true"),
]
CROP  = (468, 57, 935, 420)     # the viewport in the window capture
GI_PROPS = ["GI", "GIRayBudget", "GIRaysPerSurfel", "GIMoments", "GIFilterPasses", "GIEmissiveScale", "GIDebug", "GIPerPixel"]
REPOS = ["", "dependencies/xLIONRender", "dependencies/xLIONCore", "dependencies/xresource_mgr", "dependencies/xresource_pipeline_v2",
         "plugins/xgeom_static.plugin", "plugins/xmaterial.plugin", "plugins/xmaterial_instance.plugin", "plugins/xlevel.plugin"]


def hash_tree(path: Path, pattern: str = "*") -> str:
    h = hashlib.sha256()
    for f in sorted(p for p in path.rglob(pattern) if p.is_file()):
        h.update(f.relative_to(path).as_posix().encode()); h.update(f.read_bytes())
    return h.hexdigest()[:16]


def identity() -> dict:
    repos = {}
    for r in REPOS:
        d = ROOT / r
        head = subprocess.run(["git", "-C", str(d), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(d), "status", "--porcelain", "-uno", "."], capture_output=True, text=True).stdout.strip()
        repos[r or "xLION"] = head + ("+changes" if dirty else "")
    rsc = ROOT / "example.lionprj/Cache/Resources/Platforms/Windows"
    return {"repos": repos,
            "shaders": hash_tree(ROOT / "dependencies/xLIONRender/src/shaders"),
            "resources": {t: hash_tree(rsc / t) for t in ("Material", "MaterialInstance", "GeomStatic", "Texture")}}


def describe(ed, name) -> dict:
    return dict(l.split("=", 1) for l in ed.cmd(f"{name}\\DescribeScene").splitlines() if "=" in l)


def shot(ed, f: Path) -> Image.Image:
    if f.exists(): f.unlink()
    ed.cmd(f"CaptureWindow -File {f}")
    for _ in range(40):
        if f.exists(): break
        time.sleep(0.25)
    time.sleep(0.3)
    im = Image.open(f).convert("RGB").crop(CROP)
    im.save(f)
    return im


def read_dump(f: Path) -> dict:
    rows = {}
    for line in f.read_text().splitlines():
        if line.startswith("#") or line.startswith("inst"): continue
        v = line.split(",")
        rows[(round(float(v[3]), 2), round(float(v[4]), 2), round(float(v[5]), 2), v[2])] = [float(x) for x in v[10:17]]
    return rows


def lum(r, g, b): return 0.2126 * r + 0.7152 * g + 0.0722 * b


def dump_stats(a: dict, b: dict) -> dict:
    """Over the surfels: the mean light, how far the shown light is from the solver's (what the filter changes), the
    temporal noise between the two dumps (unfiltered and filtered), invalid surfels."""
    keys = [k for k in a if k in b]
    E  = [lum(*a[k][0:3]) for k in keys]; F = [lum(*a[k][3:6]) for k in keys]
    dE = [abs(lum(*a[k][0:3]) - lum(*b[k][0:3])) for k in keys]; dF = [abs(lum(*a[k][3:6]) - lum(*b[k][3:6])) for k in keys]
    n = max(len(keys), 1); mE = sum(E) / n; mF = sum(F) / n
    rel = sorted(abs(e - f) / max(f, 1e-4) for e, f in zip(E, F))
    return {"surfels": len(a), "matched": len(keys), "mean_unfiltered": mE, "mean_filtered": mF,
            "filter_change_median": rel[len(rel) // 2] if rel else 0, "filter_change_p95": rel[int(len(rel) * 0.95)] if rel else 0,
            "temporal_noise_unfiltered": sum(dE) / n / max(mE, 1e-6), "temporal_noise_filtered": sum(dF) / n / max(mF, 1e-6),
            "invalid": sum(1 for k in keys if a[k][6] < 0.5)}


def image_stats(im: Image.Image) -> dict:
    """The mean, and the local contrast: the mean difference to a 1-pixel shift (the blotches and the edges)."""
    g = im.convert("L")
    shifted = ImageChops.offset(g, 1, 1)
    return {"mean": round(ImageStat.Stat(g).mean[0], 2), "local_contrast": round(ImageStat.Stat(ImageChops.difference(g, shifted)).mean[0], 3)}


def run(label: str) -> dict:
    out = OUT / label
    out.mkdir(parents=True, exist_ok=True)
    rec = {"label": label, "date": time.strftime("%Y-%m-%d %H:%M:%S"), "identity": identity(), "views": VIEWS}
    ed = Editor(EXE)
    ed.start()
    try:
        name = dict(ed.levels())[LEVEL]
        ed.cmd("Close -Save 0")
        t0 = time.time()
        ed.cmd(f"OpenLevel -Level {LEVEL} -Save 0")
        ed.wait_for("GetPlayState", r"Building=false", timeout=400)
        t_open = time.time() - t0
        ed.cmd(f"{name}\\SetCamera {VIEWS['blinds']}")
        while time.time() - t0 < 600 and describe(ed, name).get("GICapturing", "1") != "0":
            time.sleep(0.5)
        t_captured = time.time() - t0
        env = lambda p: ed.cmd(f"{name}\\GetProperty -Scene {SCENE} -Id {ENV_ID} -Component Environment -Path Environment/{p}").strip()
        rec["settings"] = {p: env(p) for p in GI_PROPS}
        time.sleep(60)                                      # the solve settles
        rec["timings"] = {"open_s": round(t_open, 1), "captured_s": round(t_captured, 1), "describe": describe(ed, name)}
        for d in ("dump_a", "dump_b"):
            rec[d] = ed.cmd(f"{name}\\DumpGI -File {out / (d + '.csv')}").replace("\n", " ")
            if d == "dump_a": time.sleep(10)
        rec["surfels"] = dump_stats(read_dump(out / "dump_a.csv"), read_dump(out / "dump_b.csv"))
        rec["images"] = {}
        setp = lambda p, v: ed.cmd(f"{name}\\SetProperty -Scene {SCENE} -Id {ENV_ID} -Component Environment -Path Environment/{p} -After {v}")
        for view, cam in VIEWS.items():
            ed.cmd(f"{name}\\SetCamera {cam}")
            for mode, debug, perpixel in MODES:
                setp("GIDebug", debug); setp("GIPerPixel", perpixel)
                time.sleep(3)
                rec["images"][f"{view}/{mode}"] = image_stats(shot(ed, out / f"{view}_{mode}.png"))
    finally:
        ed.cmd("Close -Save 0")
        ed.stop()
    (out / "baseline.json").write_text(json.dumps(rec, indent=2))
    return rec


def compare(cur: dict, ref: dict) -> None:
    print(f"\n{cur['label']} vs {ref['label']}")
    for k in ("mean_unfiltered", "mean_filtered", "filter_change_median", "temporal_noise_unfiltered", "invalid"):
        print(f"  {k:28s} {ref['surfels'][k]:.4g} -> {cur['surfels'][k]:.4g}")
    for k, v in cur["images"].items():
        r = ref["images"].get(k)
        if r: print(f"  {k:28s} mean {r['mean']} -> {v['mean']}, local contrast {r['local_contrast']} -> {v['local_contrast']}")


if __name__ == "__main__":
    rec = run(sys.argv[1] if len(sys.argv) > 1 else time.strftime("%Y%m%d_%H%M"))
    print(json.dumps({k: rec[k] for k in ("timings", "settings", "surfels")}, indent=2))
    for k, v in rec["images"].items(): print(f"  {k:28s} {v}")
    if len(sys.argv) > 2: compare(rec, json.loads((OUT / sys.argv[2] / "baseline.json").read_text()))
