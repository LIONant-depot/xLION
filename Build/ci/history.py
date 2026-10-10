#!/usr/bin/env python3
"""The history of the CI: which test passed or failed in which run, with the commit of every repo of that run, kept for good so that a regression can always be bisected.

Jenkins keeps the artifacts of only the last builds; this keeps what matters of every run (the outcome of every test and the commits) in one file, records.jsonl.

  history.py ingest <jenkins jobs dir> [--store DIR]      add the runs that are not in the store yet (run it on a timer on the Jenkins machine; safe to repeat)
  history.py timeline <test> [--job J] [--leg L] [--store DIR]    the outcome of the tests that match <test> (a part of the name) over time
  history.py bisect <test> [--job J] [--leg L] [--store DIR]      the last run where it passed and the first one where it failed after it, and the repos whose commit differs between them
  history.py runs [--store DIR]                           one line per recorded run

A record (one line of records.jsonl) is one leg of one run: {job, build, leg, time, status, repos: {name: sha}, tests: {"file::test": "P|F|E|S"}}. The tests come from the suite.xml of the run,
the repos from its manifest.txt (what the CI wrote when it built it).
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET

DEFAULT_STORE = os.environ.get("XLION_CI_HISTORY", "/var/lib/xlion-ci-history")


def outcomes(suite_xml: str) -> dict:
    tests = {}
    for tc in ET.parse(suite_xml).getroot().iter("testcase"):
        name = f"{tc.get('classname', '')}::{tc.get('name', '')}"
        kids = {c.tag for c in tc}
        tests[name] = "F" if "failure" in kids else "E" if "error" in kids else "S" if "skipped" in kids else "P"
    return tests


def manifest(path: str) -> dict:
    repos = {}
    if os.path.exists(path):
        for line in open(path, errors="replace"):
            parts = line.split()
            if len(parts) == 2:
                repos[parts[1]] = parts[0]
    return repos


def field(xml_path: str, tag: str) -> str:
    try:
        node = ET.parse(xml_path).getroot().find(tag)
        return node.text if node is not None and node.text else ""
    except (OSError, ET.ParseError):
        return ""


def load(store: str) -> list:
    path = os.path.join(store, "records.jsonl")
    return [json.loads(l) for l in open(path)] if os.path.exists(path) else []


def ingest(jobs_dir: str, store: str) -> None:
    os.makedirs(store, exist_ok=True)
    have = {(r["job"], r["build"], r["leg"]) for r in load(store)}
    added = 0
    with open(os.path.join(store, "records.jsonl"), "a") as out:
        for job in sorted(os.listdir(jobs_dir)):
            builds = os.path.join(jobs_dir, job, "builds")
            if not os.path.isdir(builds):
                continue
            for b in sorted((d for d in os.listdir(builds) if d.isdigit()), key=int):
                archive = os.path.join(builds, b, "archive")
                if not os.path.isdir(archive):
                    continue
                for results in sorted(os.listdir(archive)):
                    if not results.startswith("results"):
                        continue
                    suite = os.path.join(archive, results, "suite.xml")
                    leg = results[len("results-"):] if results.startswith("results-") else "-"
                    if not os.path.exists(suite) or (job, int(b), leg) in have:
                        continue
                    try:
                        tests = outcomes(suite)
                    except ET.ParseError:
                        continue
                    status_file = os.path.join(archive, results, "status.txt")
                    rec = {"job": job, "build": int(b), "leg": leg,
                           "time": int(field(os.path.join(builds, b, "build.xml"), "startTime") or 0) // 1000,
                           "status": open(status_file).read().strip() if os.path.exists(status_file) else "",
                           "repos": manifest(os.path.join(archive, results, "manifest.txt")), "tests": tests}
                    out.write(json.dumps(rec, separators=(",", ":")) + "\n")
                    added += 1
    print(f"{added} run(s) added, {len(have) + added} in the store")


def select(records: list, test: str, job, leg) -> list:
    rows = []
    for r in sorted(records, key=lambda r: (r["time"], r["build"])):
        if (job and r["job"] != job) or (leg and r["leg"] != leg):
            continue
        hit = {t: o for t, o in r["tests"].items() if test in t}
        if hit:
            rows.append((r, hit))
    return rows


def timeline(records, test, job, leg) -> None:
    import datetime
    for r, hit in select(records, test, job, leg):
        when = datetime.datetime.fromtimestamp(r["time"]).strftime("%Y-%m-%d %H:%M")
        print(f"{when}  {r['job']}#{r['build']} {r['leg']:8} {''.join(sorted(set(hit.values()))):4} " + " ".join(f"{t.split('::')[-1][:40]}={o}" for t, o in list(hit.items())[:3]))


def bisect(records, test, job, leg) -> None:
    rows = select(records, test, job, leg)
    last_good = first_bad = None
    for r, hit in rows:
        bad = any(o in "FE" for o in hit.values())
        good = all(o == "P" for o in hit.values())
        if good:
            last_good, first_bad = r, None
        elif bad and last_good is not None and first_bad is None:
            first_bad = r
    if first_bad is None:
        print("no pass followed by a failure in the recorded runs" if last_good else "it never passed in the recorded runs")
        return
    print(f"last good: {last_good['job']}#{last_good['build']} {last_good['leg']}   first bad: {first_bad['job']}#{first_bad['build']} {first_bad['leg']}")
    changed = [(n, last_good["repos"].get(n, "-"), sha) for n, sha in first_bad["repos"].items() if last_good["repos"].get(n) != sha]
    print(f"{len(changed)} repo(s) differ between them:")
    for n, old, new in changed:
        print(f"  {n:22} {old[:9]} -> {new[:9]}      git -C <{n}> log --oneline {old[:9]}..{new[:9]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["ingest", "timeline", "bisect", "runs"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--store", default=DEFAULT_STORE)
    ap.add_argument("--job")
    ap.add_argument("--leg")
    a = ap.parse_args()
    if a.cmd == "ingest":
        ingest(a.arg or "/var/lib/jenkins/jobs", a.store)
        return 0
    records = load(a.store)
    if a.cmd == "runs":
        for r in sorted(records, key=lambda r: (r["time"], r["job"], r["build"])):
            print(f"{r['job']}#{r['build']} {r['leg']:8} {r['status']:8} {sum(1 for o in r['tests'].values() if o == 'P')}P {sum(1 for o in r['tests'].values() if o in 'FE')}F")
        return 0
    if not a.arg:
        print("give a test name (a part of it)")
        return 2
    (timeline if a.cmd == "timeline" else bisect)(records, a.arg, a.job, a.leg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
