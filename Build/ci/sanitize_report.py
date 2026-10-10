#!/usr/bin/env python3
"""The report of a sanitizer run (AddressSanitizer + UndefinedBehaviorSanitizer): which findings are NEW, and nothing else a person has to read.

    python sanitize_report.py --logs DIR --out DIR [--baseline FILE] [--update-baseline]

DIR holds the logs the sanitizers wrote (asan.<pid>, ubsan.<pid>: ASAN_OPTIONS / UBSAN_OPTIONS log_path=DIR/asan and DIR/ubsan). Every finding gets a fingerprint: its kind, and the top three
frames that are OURS (function and file name, no line numbers, so an edit above does not make it a new finding). The same fingerprint seen again, in this or any run, is one finding with
a count. The baseline file lists the fingerprints that are known (the ones nobody has fixed yet): a run is only worth a person's time when something is NEW.

Writes, in --out: sanitizer.md (the report: new findings with their three frames, the known ones counted), sanitizer_new.txt (one line per new finding), sanitizer_all.txt (every
fingerprint of this run, in the format of the baseline: copy lines from it to accept a finding), sanitizer_status.txt (SAN-GREEN, SAN-KNOWN or SAN-NEW).
"""
import argparse
import hashlib
import re
import sys
from collections import OrderedDict
from pathlib import Path

# code that is not ours: a frame in one of these is skipped when picking the three frames of a fingerprint
FOREIGN = re.compile(r"(/usr/|/lib/x86_64|compiler-rt|libsanitizer|/dependencies/(imgui|imgui-node-editor|ImGuizmo|stb|tinyexr|tinyddsloader|zstd|box3d|assimp|shaderc|freetype|meshoptimizer|"
                     r"msdf-atlas-gen|basis_universal|crunch|compressonator|MikkTSpace)/|/_deps/|/bits/|/c\+\+/|std_|\?\?)")
FRAME = re.compile(r"^\s*#\d+\s+0x[0-9a-f]+\s+in\s+(.+?)\s+(\S+?)(?::\d+)?(?::\d+)?\s*$")
FRAME_NOIN = re.compile(r"^\s*#\d+\s+0x[0-9a-f]+\s+\(([^)]*)\)")
ASAN_HEAD = re.compile(r"ERROR: AddressSanitizer: (\S+)")
UBSAN_HEAD = re.compile(r"^(\S+?):(\d+):(\d+): runtime error: (.*)$")
ANY_ADDR = re.compile(r"0x[0-9a-fA-F]+")
DIGITS = re.compile(r"\d+")


def short_frame(func: str, path: str) -> str:
    func = re.sub(r"\(.*", "", func)                    # no arguments
    func = re.sub(r"<[^<>]*>", "<>", func)
    func = re.sub(r"<[^<>]*>", "<>", func)
    return f"{func.strip()} {Path(path).name}"


def frames_of(lines, start):
    out = []
    for line in lines[start:start + 60]:
        m = FRAME.match(line)
        if not m:
            if line.strip() and not line.lstrip().startswith("#") and out:
                break
            continue
        func, path = m.group(1), m.group(2)
        if FOREIGN.search(path) or FOREIGN.search(func):
            continue
        out.append(short_frame(func, path))
        if len(out) == 3:
            break
    return out


def parse(path: Path):
    """The findings of one log file: (kind, title, frames)."""
    lines = path.read_text(errors="replace").splitlines()
    found = []
    for i, line in enumerate(lines):
        m = ASAN_HEAD.search(line)
        if m:
            what = lines[i + 1].strip() if i + 1 < len(lines) else ""
            what = re.sub(r"0x[0-9a-fA-F]+", "ADDR", what)
            found.append(("asan:" + m.group(1), what, frames_of(lines, i + 1)))
            continue
        m = UBSAN_HEAD.match(line)
        if m:
            message = DIGITS.sub("N", ANY_ADDR.sub("ADDR", m.group(4)))[:160]
            frames = frames_of(lines, i + 1)
            if not frames:                               # no stack printed: the place of the finding itself is the one frame we have
                frames = [Path(m.group(1)).name + ":" + m.group(2)] if not FOREIGN.search(m.group(1)) else []
            found.append(("ubsan", message, frames))
    return found


def fingerprint(kind, title, frames):
    key = kind + "|" + (title if kind == "ubsan" else "") + "|" + "|".join(frames)
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def read_baseline(path: Path):
    known = {}
    if path and path.exists():
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                known[line.split()[0]] = line
    return known


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--baseline", default="")
    ap.add_argument("--update-baseline", action="store_true")
    a = ap.parse_args()

    logs, out = Path(a.logs), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    findings = OrderedDict()
    for f in sorted(logs.glob("*")) if logs.is_dir() else []:
        if not f.is_file() or not (f.name.startswith("asan") or f.name.startswith("ubsan")):
            continue
        for kind, title, frames in parse(f):
            fp = fingerprint(kind, title, frames)
            entry = findings.setdefault(fp, {"kind": kind, "title": title, "frames": frames, "count": 0, "files": set()})
            entry["count"] += 1
            entry["files"].add(f.name)

    baseline = read_baseline(Path(a.baseline)) if a.baseline else {}
    new = [(fp, e) for fp, e in findings.items() if fp not in baseline]
    known = [(fp, e) for fp, e in findings.items() if fp in baseline]
    gone = [fp for fp in baseline if fp not in findings]

    def line(fp, e):
        top = e["frames"][0] if e["frames"] else "(no frame of ours)"
        return f"{fp}  {e['kind']}  {e['title'][:90]}  at {top}"

    (out / "sanitizer_all.txt").write_text("".join(line(fp, e) + "\n" for fp, e in findings.items()))
    (out / "sanitizer_new.txt").write_text("".join(line(fp, e) + "\n" for fp, e in new))
    status = "SAN-NEW" if new else ("SAN-KNOWN" if known else "SAN-GREEN")
    (out / "sanitizer_status.txt").write_text(status + "\n")

    md = [f"# Sanitizer run: {status}", "",
          f"{len(findings)} findings ({sum(e['count'] for e in findings.values())} reports): **{len(new)} new**, {len(known)} known, {len(gone)} of the known ones not seen this time.", ""]
    if new:
        md += ["## New", ""]
        for fp, e in new[:20]:
            md += [f"- `{fp}` **{e['kind']}** {e['title']}  (x{e['count']})"] + [f"    - {fr}" for fr in e["frames"]]
        if len(new) > 20:
            md += [f"- ... and {len(new) - 20} more (sanitizer_new.txt)"]
        md += [""]
    if known:
        md += ["## Known (in the baseline)", ""] + [f"- `{fp}` {e['kind']} {e['title'][:80]} (x{e['count']})" for fp, e in known[:30]] + [""]
    if gone:
        md += ["## In the baseline but not seen this time (fixed? remove the line)", ""] + [f"- {baseline[fp][:140]}" for fp in gone[:30]] + [""]
    (out / "sanitizer.md").write_text("\n".join(md))

    if a.update_baseline and a.baseline:
        text = Path(a.baseline).read_text() if Path(a.baseline).exists() else ""
        head = "".join(l + "\n" for l in text.splitlines() if l.startswith("#"))
        Path(a.baseline).write_text(head + "".join(line(fp, e) + "\n" for fp, e in findings.items()))
    print(status, f"findings={len(findings)} new={len(new)} known={len(known)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
