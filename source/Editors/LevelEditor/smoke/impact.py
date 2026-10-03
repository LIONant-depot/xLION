"""impact: which smoke test files to run for what changed.

    python impact.py                  the files changed in the working trees and not pushed yet (every repo of the checkout) -> the test files that cover them
    python impact.py FILE...          the same for the files you name (paths relative to the xLION checkout, or absolute)
    python impact.py --run [FILE...]  and run them (pytest -q, a short traceback)

The map is golden/test_impact.json (first match wins, most specific first). A file the map does not know falls back to its last line, a small core set.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SMOKE = Path(__file__).resolve().parent
MAP = SMOKE / "golden" / "test_impact.json"
REPOS = [".", "plugins/xlevel.plugin", "plugins/xscene.plugin", "plugins/xgame.plugin", "plugins/xscript_module.plugin", "dependencies/xECSV2", "dependencies/xLIONCore", "dependencies/xLIONRender", "dependencies/xeditor", "example.lionprj"]


def load_map():
    data = json.loads(MAP.read_text())
    return [(re.compile(p), tests) for p, tests in data["map"]]


def tests_for(path: str, rules) -> list:
    path = path.replace("\\", "/")
    for pattern, tests in rules:
        m = pattern.search(path)
        if m:
            own = m.groupdict().get("own")
            return [own if t == "$own" else t for t in tests]
    return []


def changed_files() -> list:
    out = []
    for repo in REPOS:
        folder = REPO / repo
        if not (folder / ".git").exists() and not (folder / ".git").is_file():
            continue
        names = subprocess.run(["git", "-C", str(folder), "status", "--porcelain"], capture_output=True, text=True).stdout.splitlines()
        names = [l[3:].strip().strip('"') for l in names if not l.startswith("??") or "smoke" in l]
        unpushed = subprocess.run(["git", "-C", str(folder), "diff", "--name-only", "@{u}.."], capture_output=True, text=True).stdout.split()
        for n in names + unpushed:
            out.append((repo + "/" + n).removeprefix("./") if repo != "." else n)
    return sorted(set(out))


def impact(files) -> list:
    rules = load_map()
    wanted = []
    for f in files:
        p = Path(f)
        rel = p.relative_to(REPO).as_posix() if p.is_absolute() and REPO in p.parents else str(f)
        for t in tests_for(rel, rules):
            if t not in wanted and (SMOKE / t).is_file():
                wanted.append(t)
    return wanted


def main(argv) -> int:
    run = "--run" in argv
    files = [a for a in argv if not a.startswith("--")] or changed_files()
    tests = impact(files)
    print(f"{len(files)} changed file(s) -> {len(tests)} test file(s)")
    print(" ".join(tests))
    if run and tests:
        return subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider", *tests], cwd=str(SMOKE)).returncode
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
