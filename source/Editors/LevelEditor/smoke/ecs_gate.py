"""The two ECS gates (documentation/Editors/ecs_link_gate.md).

The editor is moving to talk to the ECS only through a pure virtual interface (xECSEditor) that each copy of the core DLL hands out, so that several copies of LIONCore.dll, each with its
own registry, can be used at once. Until then the editor still reaches the engine directly in two ways, and each has a gate that may only shrink:

  scan   source scan: tokens that only make sense against the registry of ONE core (bit ids, pools, the registry itself, per-binary info_v ...) in the editor's own sources, counted per file.
         The baseline is golden/ecs_scan_baseline.json: a count may go down, never up, and a file that never used a token may not start to.
  link   link gate: the headless editor built WITHOUT LIONCore.dll/LIONRender.dll (the CMake target xLION_ecs_gate, option XLION_ECS_LINK_GATE). Everything it still takes from them through
         its own import is an unresolved external. The baseline is golden/ecs_link_baseline.txt: the symbols may go away, a new one may not come.

    python ecs_gate.py scan [--update]
    python ecs_gate.py link [--update]          (--update writes the baseline: only after the list shrank)
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
GOLDEN = Path(__file__).resolve().parent / "golden"
SCAN_BASELINE = GOLDEN / "ecs_scan_baseline.json"
LINK_BASELINE = GOLDEN / "ecs_link_baseline.txt"

# The sources that are compiled into xLION.exe and touch the ECS: the Level and Scene editors and the shell. The smoke tests are not part of it.
SCAN_DIRS = [REPO / "plugins" / "xlevel.plugin" / "source", REPO / "plugins" / "xscene.plugin" / "source", REPO / "source" / "Editors" / "LevelEditor"]
SKIP_PARTS = {"smoke", ".logs", "__pycache__"}
SCAN_SUFFIXES = {".h", ".hpp", ".inl", ".cpp"}

# What only means something against the registry (and the bit ids) of the ONE core the binary imports.
TOKENS = ["m_BitID", "getComponentBits", "getEntityDetails", "m_pPool", "info_v", "findComponentTypeInfo", "s_Registry", "SyncLocalBitIDs", "SyncAllLocalBitIDs", "m_ComponentInfoMap"]
TOKEN_RE = re.compile(r"\b(" + "|".join(TOKENS) + r")\b")


def strip_comments_and_strings(text: str) -> str:
    """The code only: comments and string/char literals do not use anything (the comments are full of the names)."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        two = text[i:i + 2]
        if two == "//":
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif two == "/*":
            j = text.find("*/", i + 2)
            out.append("\n" * text.count("\n", i, n if j < 0 else j + 2))
            i = n if j < 0 else j + 2
        elif c == '"' or c == "'":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            i = j + 1
            out.append('""' if c == '"' else "''")
        else:
            out.append(c)
            i += 1
    return "".join(out)


def scan() -> dict:
    """{relative file: {token: count}} of the code of the editor's sources."""
    found: dict = {}
    for root in SCAN_DIRS:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_PARTS]
            for name in filenames:
                path = Path(dirpath) / name
                if path.suffix.lower() not in SCAN_SUFFIXES:
                    continue
                code = strip_comments_and_strings(path.read_text(encoding="utf-8", errors="replace"))
                counts: dict = {}
                for m in TOKEN_RE.finditer(code):
                    counts[m[1]] = counts.get(m[1], 0) + 1
                if counts:
                    found[path.relative_to(REPO).as_posix()] = dict(sorted(counts.items()))
    return dict(sorted(found.items()))


def compare_scan(now: dict, baseline: dict) -> tuple[list[str], list[str]]:
    """(what grew or is new: the failures, what shrank or went: the good news)."""
    grown, shrunk = [], []
    for file, counts in now.items():
        for token, count in counts.items():
            was = baseline.get(file, {}).get(token, 0)
            if count > was:
                grown.append(f"{file}: {token} {was} -> {count}")
    for file, counts in baseline.items():
        for token, was in counts.items():
            count = now.get(file, {}).get(token, 0)
            if count < was:
                shrunk.append(f"{file}: {token} {was} -> {count}")
    return grown, shrunk


def totals(scanned: dict) -> dict:
    t = {k: 0 for k in TOKENS}
    for counts in scanned.values():
        for k, v in counts.items():
            t[k] += v
    return t


# ---- the link gate ----------------------------------------------------------------------------------------------------------------------------------------------------------

def msbuild() -> str:
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    found = subprocess.run([str(vswhere), "-latest", "-requires", "Microsoft.Component.MSBuild", "-find", r"MSBuild\**\Bin\MSBuild.exe"], capture_output=True, text=True).stdout.split("\n")[0].strip()
    assert found, "MSBuild was not found (vswhere)"
    return found


UNRESOLVED = re.compile(r'LNK2019: unresolved external symbol ".+?" \((\S+?)\) referenced in function')


def link_gate(config: str = "Debug") -> list[str]:
    """Builds xLION_ecs_gate and returns the sorted unresolved (decorated) symbols. [] when it linked."""
    sln = REPO / "Build" / "xLION.vs2022" / "xLION.sln"
    done = subprocess.run([msbuild(), str(sln), "/t:xLION_ecs_gate", f"/p:Configuration={config}", "/m", "/nologo", "/v:m"], capture_output=True, text=True, errors="replace")
    text = done.stdout + done.stderr
    assert "error MSB4057" not in text, "the target xLION_ecs_gate does not exist: configure with  cmake -S . -B Build/xLION.vs2022 -DXLION_ECS_LINK_GATE=ON"
    assert not re.search(r"error C\d+", text), "the gate target does not compile:\n" + "\n".join(l for l in text.splitlines() if "error C" in l)[:3000]
    symbols = sorted({m[1] for m in UNRESOLVED.finditer(text)})
    assert done.returncode == 0 or symbols, "the gate target failed and not at the link:\n" + text[-3000:]
    return symbols


def read_link_baseline() -> list[str]:
    return [l.strip() for l in LINK_BASELINE.read_text().splitlines() if l.strip() and not l.startswith("#")] if LINK_BASELINE.exists() else []


LINK_HEADER = "# Symbols the editor still takes from LIONCore.dll / LIONRender.dll through xLION.exe's own import (decorated names). May only shrink: python ecs_gate.py link --update\n"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("scan", "link"):
        print(__doc__)
        return 2
    update = "--update" in argv
    if argv[1] == "scan":
        now = scan()
        baseline = json.loads(SCAN_BASELINE.read_text()) if SCAN_BASELINE.exists() else {}
        grown, shrunk = compare_scan(now, baseline)
        print("totals:", totals(now), "in", len(now), "files")
        for line in shrunk:
            print("  less:", line)
        for line in grown:
            print("  MORE:", line)
        if update:
            GOLDEN.mkdir(exist_ok=True)
            SCAN_BASELINE.write_text(json.dumps(now, indent=1) + "\n")
            print("baseline written")
            return 0
        return 1 if grown else 0
    symbols = link_gate()
    baseline = read_link_baseline()
    new, gone = [s for s in symbols if s not in baseline], [s for s in baseline if s not in symbols]
    print(f"unresolved: {len(symbols)} (baseline {len(baseline)})")
    for s in gone:
        print("  gone:", s)
    for s in new:
        print("  NEW:", s)
    if update:
        LINK_BASELINE.write_text(LINK_HEADER + "\n".join(symbols) + "\n")
        print("baseline written")
        return 0
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
