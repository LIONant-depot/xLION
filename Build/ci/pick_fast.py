#!/usr/bin/env python3
"""Ranks the smoke test files for the fast tier (Build/ci/fast_files.txt) from the JUnit xml of a full run.

    python Build/ci/pick_fast.py suite.xml [--max-seconds 60]

A file is a candidate when it ran at least 2 tests, none of them failed or errored, and no single test took longer than --max-seconds. Candidates are ranked by
breadth per second: breadth = how many rows of golden/test_impact.json list the file (how many source areas it exercises), seconds = the time the file took.
"""
import collections
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SMOKE = Path(__file__).resolve().parents[2] / "source" / "Editors" / "LevelEditor" / "smoke"


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    max_test = float(argv[argv.index("--max-seconds") + 1]) if "--max-seconds" in argv else 60.0
    impact = json.loads((SMOKE / "golden" / "test_impact.json").read_text())
    breadth = collections.Counter()
    for _pattern, tests in impact["map"]:
        for t in (tests if isinstance(tests, list) else [tests]):
            breadth[t if t.endswith(".py") else t + ".py"] += 1

    per = collections.defaultdict(lambda: {"n": 0, "bad": 0, "skip": 0, "t": 0.0, "tmax": 0.0})
    for c in ET.parse(argv[0]).iter("testcase"):
        f = c.get("classname", "").split(".")[0] + ".py"
        d = per[f]
        dt = float(c.get("time") or 0)
        d["n"] += 1
        d["t"] += dt
        d["tmax"] = max(d["tmax"], dt)
        if c.find("failure") is not None or c.find("error") is not None:
            d["bad"] += 1
        elif c.find("skipped") is not None:
            d["skip"] += 1

    cand = []
    for f, d in per.items():
        if d["n"] - d["skip"] >= 2 and d["bad"] == 0 and d["tmax"] < max_test:
            cand.append((breadth.get(f, 0) / max(d["t"], 1.0), f, d))
    cand.sort(reverse=True)
    print(f"{'file':36s} {'tests':>5s} {'sec':>6s} {'max':>5s} {'breadth':>7s}  per-sec")
    for sc, f, d in cand:
        print(f"{f:36s} {d['n']:5d} {d['t']:6.0f} {d['tmax']:5.0f} {breadth.get(f, 0):7d}  {sc:.3f}")
    print(f"\n{len(cand)} candidate files, {sum(d['t'] for _, _, d in cand) / 60:.1f} minutes of test time")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
