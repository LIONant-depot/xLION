#!/usr/bin/env python3
"""The report of a sanitizer run (AddressSanitizer + UndefinedBehaviorSanitizer, ThreadSanitizer, or MSVC AddressSanitizer on Windows): which findings are NEW, and nothing else a
person has to read.

    python sanitize_report.py --logs DIR --out DIR [--baseline FILE] [--update-baseline]

DIR holds the logs the sanitizers wrote (asan.<pid>, ubsan.<pid>, tsan.<pid>: ASAN_OPTIONS / UBSAN_OPTIONS / TSAN_OPTIONS log_path=DIR/asan, DIR/ubsan, DIR/tsan; on Windows the MSVC
AddressSanitizer writes the same "ERROR: AddressSanitizer:" reports, with Windows paths: asan*.log or asan.<pid>). Every finding gets a fingerprint: its kind, and the top three
frames that are OURS (function and file name, no line numbers, so an edit above does not make it a new finding). A ThreadSanitizer "data race" is fingerprinted by the top two frames
of BOTH accesses (sorted, so it does not matter which thread came first) and a "lock-order-inversion" by the first frame of each lock taken. The same fingerprint seen again, in this or any run, is one finding with
a count. The baseline file lists the fingerprints that are known (the ones nobody has fixed yet): a run is only worth a person's time when something is NEW.

Writes, in --out: sanitizer.md (the report: new findings with their three frames, the known ones counted), sanitizer_new.txt (one line per new finding), sanitizer_all.txt (every
fingerprint of this run, in the format of the baseline: copy lines from it to accept a finding), sanitizer_status.txt (SAN-GREEN, SAN-KNOWN or SAN-NEW).
"""
import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path

# code that is not ours: a frame in one of these is skipped when picking the three frames of a fingerprint
FOREIGN = re.compile(r"(/usr/|/sysdeps/|libc_start|/llvm/|<null>|Microsoft Visual Studio|Windows Kits|/vctools/|/minkernel/|/onecore/|\.dll\+|/system32/|/lib/x86_64|compiler-rt|libsanitizer|/dependencies/(imgui|imgui-node-editor|ImGuizmo|stb|tinyexr|tinyddsloader|zstd|box3d|assimp|shaderc|freetype|meshoptimizer|"
                     r"msdf-atlas-gen|basis_universal|crunch|compressonator|MikkTSpace)/|/_deps/|/bits/|/c\+\+/|std_|\?\?)", re.I)
FRAME = re.compile(r"^\s*#\d+\s+0x[0-9a-f]+\s+in\s+(.+?)\s+(\S+?)(?::\d+)?(?::\d+)?\s*$")
TSAN_FRAME = re.compile(r"^\s*#\d+\s+(.+?)\s+(\S+?)(?::\d+)?(?::\d+)?\s+\([^()]*\)\s*$")     # TSan: "#0 func file:line:col (module+0x..)" (no address, no "in")
MSVC_FRAME = re.compile(r"^\s*#\d+\s+0x[0-9a-f]+\s+in\s+(.+?)\s+([A-Za-z]:\\.+?)(?::\d+)?\s*$", re.I)           # MSVC: "#0 0x7ff.. in func D:\path with spaces\file.cpp:12"
FRAME_NOIN = re.compile(r"^\s*#\d+\s+0x[0-9a-f]+\s+\(([^)]*)\)")
TSAN_HEAD = re.compile(r"WARNING: ThreadSanitizer: ([a-z][a-z -]*[a-z])")
TSAN_STACK = re.compile(r"^\s*(Write|Read|Atomic write|Atomic read|Previous write|Previous read|Previous atomic write|Previous atomic read) of size|^\s*Mutex \S+ acquired here while holding")
ASAN_HEAD = re.compile(r"ERROR: AddressSanitizer: (\S+)")
UBSAN_HEAD = re.compile(r"^(\S+?):(\d+):(\d+): runtime error: (.*)$")
ANY_ADDR = re.compile(r"0x[0-9a-fA-F]+")
DIGITS = re.compile(r"\d+")


def short_frame(func: str, path: str) -> str:
    func = re.sub(r"\(.*", "", func)                    # no arguments
    func = re.sub(r"<[^<>]*>", "<>", func)
    func = re.sub(r"<[^<>]*>", "<>", func)
    name = re.split(r'[\\/]', path)[-1]                # Linux or Windows path
    return f"{func.strip()} {name}"


def frames_of(lines, start):
    out = []
    for line in lines[start:start + 60]:
        m = MSVC_FRAME.match(line) or FRAME.match(line) or TSAN_FRAME.match(line)
        if not m:
            if line.strip() and not line.lstrip().startswith("#") and out:
                break
            continue
        func, path = m.group(1), m.group(2)
        if path.startswith("(") or path.endswith(")"):  # "(module+0x...)" or "(BuildId: ...)": no source file, so not a frame of ours (an interceptor such as operator delete)
            continue
        if FOREIGN.search(path.replace("\\", "/")) or FOREIGN.search(func):
            continue
        out.append(short_frame(func, path))
        if len(out) == 3:
            break
    return out


# Offline symbolization. The CI runs the sanitizers with symbolize=0 (ci_run.sh): symbolizing in the editor starts an llvm-symbolizer of about 1 GB per process and blocks the
# editor while it loads the debug info, and on a 3.8 GB machine with recovering reports (one finding can repeat hundreds of times) that made the tests time out. The logs then hold
# "#3 0x... (/path/module+0xoffset)" frames, and they are symbolized here, once per address, after the run.
UNSYM = re.compile(r"^(\s*#\d+\s+0x[0-9a-f]+\s+)(?:in\s+)?\(([^()+]+)\+(0x[0-9a-f]+)\)")
SYMBOLS = {}


def symbolize_files(files):
    tool = next((t for t in ("llvm-symbolizer-20", "llvm-symbolizer") if shutil.which(t)), None)
    want = {}
    for f in files:
        for line in f.read_text(errors="replace").splitlines():
            m = UNSYM.match(line)
            if m:
                want.setdefault(m.group(2), set()).add(m.group(3))
    if not tool or not want:
        return
    homes = {str(Path(m).parent) for m in want if Path(m).exists()}
    for mod, offs in want.items():
        obj = mod
        if not Path(obj).exists() and re.search(r"/libLC\d+\.so$", mod):     # an engine copy (xlevel_engine_copies.h): a renamed copy of libLIONCore.so, deleted after the run
            obj = next((str(Path(h) / "libLIONCore.so") for h in homes if (Path(h) / "libLIONCore.so").exists()), mod)
        if not Path(obj).exists():
            continue
        offs = sorted(offs)
        try:
            out = subprocess.run([tool, "--demangle", "--no-inlines", f"--obj={obj}"], input="\n".join(offs) + "\n", capture_output=True, text=True, timeout=1800).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        blocks = [b.splitlines() for b in out.strip("\n").split("\n\n")]
        for off, b in zip(offs, blocks):
            if len(b) >= 2 and b[0] != "??":
                SYMBOLS[(mod, off)] = (b[0], b[1])


def symbolized(line):
    m = UNSYM.match(line)
    if m and (m.group(2), m.group(3)) in SYMBOLS:
        func, loc = SYMBOLS[(m.group(2), m.group(3))]
        return f"{m.group(1)}in {func} {loc}"
    return line


def parse(path: Path):
    """The findings of one log file: (kind, title, frames)."""
    lines = [symbolized(l) for l in path.read_text(errors="replace").splitlines()]
    found = []
    for i, line in enumerate(lines):
        m = TSAN_HEAD.search(line)
        if m:
            kind = "tsan:" + m.group(1).replace(" ", "-")
            stacks = []                                 # the stacks of the warning: the two accesses of a race, the lock acquisitions of an inversion
            for j in range(i + 1, min(len(lines), i + 400)):
                if lines[j].startswith("SUMMARY: ThreadSanitizer") or "WARNING: ThreadSanitizer:" in lines[j]:
                    break
                if TSAN_STACK.match(lines[j]):
                    stacks.append(frames_of(lines, j + 1))
            if "lock-order" in kind:
                frames = sorted(s[0] for s in stacks if s)
            else:
                frames = sorted(" < ".join(s[:2]) for s in stacks[:2] if s)
            what = re.sub(r"\(pid=\d+\)", "", line.split("ThreadSanitizer:", 1)[1]).strip()
            found.append((kind, what, frames))
            continue
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
    files = [f for f in (sorted(logs.glob("*")) if logs.is_dir() else []) if f.is_file() and f.name.lower().startswith(("asan", "ubsan", "tsan"))]
    symbolize_files(files)
    for f in files:
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
