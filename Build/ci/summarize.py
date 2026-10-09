#!/usr/bin/env python3
"""Turns the files of a CI test run into something a person can read in Jenkins without opening a log.

    python Build/ci/summarize.py --junit suite.xml --out DIR --tier fast|full [--known known_failures_linux.txt] [--timing timing.tsv]
                                 [--changed changed.txt] [--stages stages.tsv] [--title TEXT]

Writes into DIR:
    summary.md        the full report: headline, what changed, stage times, new / fixed failures, failures grouped by reason, slowest tests and files
    description.txt   2-4 plain lines for the build description (counts, new failures, what changed)
    status.txt        one word: GREEN (nothing failed), KNOWN (only failures that are in the known list), NEW (a failure that is not), NOTESTS (no result)
    new_failures.txt  failed tests that are not in the known list
    fixed.txt         tests in the known list that passed this time
    failed_now.txt    every failed or errored test (the next known list)
and prints summary.md.

The known list is one test per line, "test_file.py::test_name" ('#' starts a comment): the failures a person already knows about. A run only counts as broken
(NEW) when it fails something that is not in the list, so the list can be fixed down over time without every run being red for old reasons.
"""
import argparse
import collections
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def read_list(path):
    out = set()
    if path and Path(path).is_file():
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                out.add(line)
    return out


def normalize(msg: str) -> str:
    msg = (msg or "").strip().splitlines()[0] if (msg or "").strip() else "(no message)"
    msg = re.sub(r"/home/[^/ ]+/[^ ]*xLION/", "<xLION>/", msg)
    msg = re.sub(r"0x[0-9a-fA-F]+", "0x..", msg)
    msg = re.sub(r"\b[0-9A-F]{16}\b", "GUID", msg)
    msg = re.sub(r"\d+(\.\d+)?", "N", msg)
    return msg[:170]


def fmt_min(sec: float) -> str:
    return f"{sec / 60:.1f} min" if sec >= 90 else f"{sec:.0f} s"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--junit", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tier", default="full")
    ap.add_argument("--known")
    ap.add_argument("--timing")
    ap.add_argument("--changed")
    ap.add_argument("--stages")
    ap.add_argument("--title", default="")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    cases = []          # (id, file, name, outcome, seconds, message)
    if Path(a.junit).is_file():
        for c in ET.parse(a.junit).iter("testcase"):
            f = c.get("classname", "").split(".")[0] + ".py"
            name = c.get("name", "")
            fail, err, skip = c.find("failure"), c.find("error"), c.find("skipped")
            node = fail if fail is not None else err
            if node is not None:
                o, msg = ("FAIL" if fail is not None else "ERROR"), (node.get("message") or (node.text or ""))
            elif skip is not None:
                o, msg = ("XFAIL" if "xfail" in (skip.get("type") or "") else "SKIP"), (skip.get("message") or "")
            else:
                o, msg = "PASS", ""
            cases.append((f"{f}::{name}", f, name, o, float(c.get("time") or 0), msg))

    if not cases:
        (out / "status.txt").write_text("NOTESTS\n")
        (out / "description.txt").write_text("No test result was produced: see the console log.\n")
        (out / "summary.md").write_text("# No test result\n\nThe run did not produce a JUnit report. See the console log and the stage times.\n")
        print("No test result")
        return 0

    known = read_list(a.known)
    bad = [c for c in cases if c[3] in ("FAIL", "ERROR")]
    passed = [c for c in cases if c[3] == "PASS"]
    skipped = [c for c in cases if c[3] in ("SKIP", "XFAIL")]
    new = [c for c in bad if c[0] not in known]
    fixed = sorted(k for k in known if any(c[0] == k and c[3] == "PASS" for c in cases))
    total_s = sum(c[4] for c in cases)
    bad_s = sum(c[4] for c in bad)
    status = "GREEN" if not bad else ("NEW" if new else "KNOWN")

    (out / "status.txt").write_text(status + "\n")
    (out / "new_failures.txt").write_text("".join(f"{c[0]}\n" for c in sorted(new)))
    (out / "fixed.txt").write_text("".join(f"{k}\n" for k in fixed))
    (out / "failed_now.txt").write_text("".join(f"{c[0]}\n" for c in sorted(bad)))

    changed = []
    if a.changed and Path(a.changed).is_file():
        changed = [l.rstrip("\n") for l in Path(a.changed).read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]

    # ---- description (plain text, a few lines)
    d = [f"{len(passed)} passed, {len(bad)} failed ({len(new)} new), {len(skipped)} skipped, {fmt_min(total_s)} in tests ({a.tier})"]
    if new:
        d.append("NEW failures: " + ", ".join(sorted({c[1] for c in new}))[:160])
    if fixed:
        d.append(f"{len(fixed)} known failures now pass")
    if changed:
        d.append("changed: " + ", ".join(l.split()[0] for l in changed[:8]) + (" ..." if len(changed) > 8 else ""))
    (out / "description.txt").write_text("\n".join(d) + "\n")

    # ---- the report
    L = []
    title = a.title or f"xLION {a.tier} test run"
    L.append(f"# {title}")
    L.append("")
    verdict = {"GREEN": "all tests passed", "KNOWN": "only known failures", "NEW": "NEW FAILURES", "NOTESTS": "no result"}[status]
    L.append(f"**{verdict}**: {len(passed)} passed, {len(bad)} failed or errored ({len(new)} new, {len(bad) - len(new)} known), "
             f"{len(skipped)} skipped; {len(cases)} tests, {fmt_min(total_s)} in tests, {fmt_min(bad_s)} of it in tests that failed.")
    L.append("")
    if changed:
        L.append("## What changed since the last build")
        L.append("")
        for l in changed:
            L.append(f"- {l}")
        L.append("")
    if a.stages and Path(a.stages).is_file():
        L.append("## Where the time went")
        L.append("")
        L.append("| stage | time | result |")
        L.append("|---|---:|---|")
        for l in Path(a.stages).read_text(encoding="utf-8", errors="replace").splitlines():
            p = l.split("\t")
            if len(p) >= 3:
                L.append(f"| {p[0]} | {fmt_min(float(p[1]))} | {p[2]} |")
        L.append("")
    if new:
        L.append(f"## NEW failures ({len(new)}): not in the known list")
        L.append("")
        for c in sorted(new, key=lambda c: c[0]):
            L.append(f"- `{c[0]}` ({c[3]}, {c[4]:.0f}s): {normalize(c[5])}")
        L.append("")
    if fixed:
        L.append(f"## Fixed ({len(fixed)}): in the known list, passed this time")
        L.append("")
        for k in fixed:
            L.append(f"- `{k}`")
        L.append("")
    if bad:
        groups = collections.defaultdict(list)
        for c in bad:
            groups[normalize(c[5])].append(c)
        L.append("## Failures grouped by reason")
        L.append("")
        L.append("| count | reason | in files |")
        L.append("|---:|---|---|")
        for reason, cs in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:20]:
            files = collections.Counter(c[1] for c in cs).most_common(3)
            L.append(f"| {len(cs)} | `{reason.replace('|', '/')}` | {', '.join(f'{f} ({n})' for f, n in files)} |")
        L.append("")
        L.append("## Failing files")
        L.append("")
        perf = collections.defaultdict(lambda: [0, 0, 0.0])
        for c in cases:
            p = perf[c[1]]
            p[1] += 1
            if c[3] in ("FAIL", "ERROR"):
                p[0] += 1
                p[2] += c[4]
        L.append("| file | failed / tests | time in failures |")
        L.append("|---|---:|---:|")
        for f, (nb, n, t) in sorted(perf.items(), key=lambda kv: -kv[1][0])[:25]:
            if nb:
                L.append(f"| {f} | {nb} / {n} | {fmt_min(t)} |")
        L.append("")
    L.append("## Slowest tests")
    L.append("")
    L.append("| time | outcome | test |")
    L.append("|---:|---|---|")
    for c in sorted(cases, key=lambda c: -c[4])[:15]:
        L.append(f"| {c[4]:.0f} s | {c[3]} | `{c[0]}` |")
    L.append("")
    perf2 = collections.defaultdict(float)
    for c in cases:
        perf2[c[1]] += c[4]
    L.append("## Slowest files")
    L.append("")
    L.append("| time | file |")
    L.append("|---:|---|")
    for f, t in sorted(perf2.items(), key=lambda kv: -kv[1])[:10]:
        L.append(f"| {fmt_min(t)} | {f} |")
    L.append("")
    L.append("Per-test start and end times: `timing.log` (a START with no END is the test that hung), `timing.tsv` for scripts. "
             "Each failed test's page in Jenkins carries the tail of the editor's log.")
    text = "\n".join(L) + "\n"
    (out / "summary.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
