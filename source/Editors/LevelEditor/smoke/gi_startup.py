"""The GI's startup in Police, measured (dependencies/xLIONRender/documentation/gi_dynamic_master_plan.md, section 7a). A measurement, not a
test: no timing is asserted.

    python gi_startup.py run <tag> [--captures-first] [--at 1,2,3,5,9,15,60,60.5]
    python gi_startup.py analyse <tag>

run: a fresh editor (the harness's own: never one the user is running) opens Police with the fixed camera, and dumps the GI (DumpGI)
at the given wall times after the camera is set; the last two dumps are the reference and its noise. --captures-first sets
XLION_GI_HOLD_CAPTURES: no solve until the material captures have been done for 10 frames (the control: the solve never sees an
uncaptured material).

analyse: each dump's solver light (the dump's e columns) against the reference, by the GI time of its frame log (TimeMs: since the first
GI frame). The level 0 surfels are grouped by their parent (the dump's parent column); a surfel's weight is its area (radius^2):
- between groups: the rms over groups of the group's area weighted mean error, of the area weighted mean reference light;
- within groups: the rms of each surfel's error less its group's mean, of the same;
- coherent groups only: the same over the groups whose children's normals are within ~37 deg of their mean;
- warm-up: the surfels with fewer than 16 samples; watching: the change detector's watch.
The shown light is not in the dump while the GPU shows it (the CPU has no copy). The reference is the last solver light, not an exact one.
"""
import collections
import csv
import glob
import math
import os
import sys
import time

import harness
from harness import DEFAULT_EXE, Editor, REPO

OUT = REPO / "Build" / "gi_startup"
POLICE = "EF31687D49834DD9"


def run(tag, at, captures_first):
    OUT.mkdir(parents=True, exist_ok=True)
    if captures_first:
        os.environ["XLION_GI_HOLD_CAPTURES"] = "1"
    ed = Editor(DEFAULT_EXE); ed.start()
    r = lambda c, t=300: ed._roundtrip(c, t)
    r(f"OpenLevel -Level {POLICE}")
    r(r"Police Level\SetCamera -Mode orbit -Yaw 30 -Pitch -25 -Distance 6 -Target 0,2.0,10.01")
    t0 = time.time()
    for k, a in enumerate(at):
        time.sleep(max(0, a - (time.time() - t0)))
        r(rf"Police Level\DumpGI -File {OUT / f'{tag}_{k}.csv'}")
    time.sleep(1.5)
    ed.stop()


def analyse(tag):
    K = sorted(int(os.path.basename(f)[len(tag) + 1:-4]) for f in glob.glob(str(OUT / f"{tag}_*.csv")) if os.path.basename(f)[len(tag) + 1:-4].isdigit())

    def load(k):
        p = OUT / f"{tag}_{k}.csv"
        rows = {(x["inst"], x["level"], x["surfel"]): x for x in csv.DictReader(l for l in open(p) if not l.startswith("#"))}
        fr = [x for x in csv.DictReader(l for l in open(str(p) + ".frames.csv") if not l.startswith("#"))]
        return rows, fr

    lum = lambda x: 0.2126 * float(x["er"]) + 0.7152 * float(x["eg"]) + 0.0722 * float(x["eb"])
    # The GI time without the frames the earlier dumps froze (a DumpGI is a frame of about 1 s in Debug: the GI makes no progress in it)
    Effective = lambda fr: (float(fr[-1]["TimeMs"]) - sum(float(x["UpdateGIMs"]) for x in fr if float(x["UpdateGIMs"]) > 100)) / 1000
    Ref, _ = load(K[-2]); Ref2, _ = load(K[-1])
    G = collections.defaultdict(list)
    for k, x in Ref.items():
        if x["level"] == "0": G[(x["inst"], x["parent"])].append(k)

    def coherent(keys):
        n = [tuple(float(Ref[k][c]) for c in ("nx", "ny", "nz")) for k in keys]
        m = [sum(v[i] for v in n) for i in range(3)]; l = math.sqrt(sum(c * c for c in m)) or 1
        return min(sum(a * b / l for a, b in zip(v, m)) for v in n) >= 0.8

    Coh = {g: coherent(ks) for g, ks in G.items()}
    A = {k: float(x["radius"]) ** 2 for k, x in Ref.items()}

    def split(D, only=None):
        ta = tl = bt = wt = 0.0
        for g, ks in G.items():
            if only is not None and Coh[g] != only: continue
            ks = [k for k in ks if k in D]
            if not ks: continue
            a = sum(A[k] for k in ks)
            e = {k: lum(D[k]) - lum(Ref[k]) for k in ks}
            eg = sum(A[k] * e[k] for k in ks) / a
            bt += a * eg * eg; wt += sum(A[k] * (e[k] - eg) ** 2 for k in ks)
            ta += a; tl += sum(A[k] * lum(Ref[k]) for k in ks)
        m = tl / ta
        return math.sqrt(bt / ta) / m, math.sqrt(wt / ta) / m, sum(A[k] * lum(D[k]) for ks in G.values() for k in ks if k in D) / tl

    nG = len(G)
    print(f"{tag}: {sum(len(v) for v in G.values())} level 0 surfels in {nG} parent groups ({100 * (nG - sum(Coh.values())) / nG:.0f}% with normals over ~37 deg apart)")
    b, w, _ = split(Ref2)
    print(f"  the reference's own change (its last two dumps): between groups {b:.1%}, within {w:.1%}")
    print("  t: GI seconds without the frames the dumps froze")
    print("  t (GI s)  between  within  mean/ref  coherent: between, within  warm-up  watching")
    for k in K[:-2]:
        D, fr = load(k)
        if not fr: continue
        t = Effective(fr)
        l0 = [x for x in D.values() if x["level"] == "0"]
        b, w, mr = split(D); bc, wc, _ = split(D, True)
        print(f"  {t:7.2f}  {b:7.1%} {w:7.1%}  {mr:7.3f}   {bc:7.1%} {wc:7.1%}         {sum(int(x['n']) < 16 for x in l0) / len(l0):6.1%}  {sum(x['watch'] == '1' for x in l0) / len(l0):6.1%}")
    _, fr = load(K[-3] if len(K) > 2 else K[-1])
    cum, marks, low, n, frozen = 0, {}, 0, 0, 0.0
    for x in fr:
        if float(x["UpdateGIMs"]) > 100: frozen += float(x["UpdateGIMs"]) / 1000     # (a dump's frame)
        t = float(x["TimeMs"]) / 1000 - frozen; cum += int(x["Rays"])
        for m in (1, 3, 5, 9, 15):
            if t >= m and m not in marks: marks[m] = cum
        if 2 < t < 15: n += 1; low += int(x["Rays"]) < 5000
    caps = [Effective(fr[:k + 1]) for k, x in enumerate(fr) if float(x["CaptureMs"]) > 0.05]
    print("  rays by GI time: " + ", ".join(f"{v / 1e6:.1f}M at {m} s" for m, v in sorted(marks.items()))
          + f"; frames under 5k rays (2-15 s): {low}/{n}; the last capture at {caps[-1] if caps else float('nan'):.2f} s")


if __name__ == "__main__":
    if sys.argv[1] == "run":
        at = [1, 2, 3, 5, 9, 15, 60, 60.5]
        if "--at" in sys.argv: at = [float(v) for v in sys.argv[sys.argv.index("--at") + 1].split(",")]
        run(sys.argv[2], at, "--captures-first" in sys.argv)
    analyse(sys.argv[2])
