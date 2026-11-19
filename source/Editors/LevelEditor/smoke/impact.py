"""impact: which smoke test files to run for what changed (R97, Tomas 2026-11-19: only the relevant tests, from a generated map).

    python impact.py                  the files changed in the working trees and not pushed yet (every repo of the checkout) -> the test files that cover them
    python impact.py FILE...          the same for the files you name (paths relative to the xLION checkout, or absolute)
    python impact.py --run [FILE...]  and run them (pytest -q, a short traceback)

The map is built from the code by impact_gen.py at every run (never by hand, never stale). A C++ file: every file that includes it,
transitively (a .cpp counts as its own header too), up to the files that register console commands; the tests that drive those commands run.
A smoke .py: the tests that import it (harness/conftest: all). Documents and ignore files: none. Anything else the map cannot place
(CMake, shaders, data): the small core set, said as "unplaced" - the nightly full run is the net for those.
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SMOKE = Path(__file__).resolve().parent
CORE = ["test_command_surface.py", "test_entities.py"]
CPP = (".h", ".hpp", ".cpp", ".inl", ".cc")
REPOS = ["."] + [f"{top}/{d.name}" for top in ("plugins", "dependencies") for d in sorted((REPO / top).glob("x*")) if (d / ".git").exists()] + ["example.lionprj"]
_map = None


def load_map():
    global _map
    if _map is None:
        import impact_gen      # (built from the code at every run, ~2 s: never stale, nothing to keep)
        _map = impact_gen.build()
    return _map


def all_tests():
    return sorted(p.name for p in SMOKE.glob("test_*.py"))


def tests_for(path: str, m=None) -> list:
    """the test files for one changed path (relative to the checkout, '/'); [] = nothing to run; CORE when the map cannot place it"""
    m = m or load_map()
    path = path.replace("\\", "/")
    name = path.rsplit("/", 1)[-1]
    if path.startswith("documentation/") or name.endswith((".md", ".gitignore", ".gitattributes")):
        return []
    if "/smoke/" in "/" + path:
        if re.fullmatch(r"test_\w+\.py", name):
            return [name]
        if name in ("harness.py", "conftest.py"):
            return all_tests()
        if name.startswith("impact") or "/golden/" in path:
            return ["test_impact_map.py"]
        mod = name.removesuffix(".py")
        return [t for t in all_tests() if re.search(rf"^\s*(import|from)\s+{mod}\b", (SMOKE / t).read_text(encoding="utf-8", errors="replace"), re.M)]
    if not path.endswith(CPP):
        return CORE
    stem = path.rsplit(".", 1)[0]
    todo = [path] + [stem + e for e in CPP if stem + e != path]
    seen = set()
    while todo:
        f = todo.pop()
        if f not in seen:
            seen.add(f)
            todo += m["includers"].get(f, [])
    cmds = {c for c, files in m["commands"].items() if seen.intersection(files)}
    if not cmds:      # (no include path to a registration - a plugin entry or a DLL loaded at run time: what its library registers)
        lib = library(path)
        cmds = {c for c, files in m["commands"].items() if any(library(f) == lib for f in files)}
    return [t for t, used in m["tests"].items() if cmds.intersection(used)] or CORE


def library(rel):
    parts = rel.split("/")
    return "/".join(parts[:2]) if parts[0] in ("plugins", "dependencies") else parts[0]


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


def impact(files, unplaced=None) -> list:
    wanted = []
    for f in files:
        p = Path(f)
        rel = p.relative_to(REPO).as_posix() if p.is_absolute() and REPO in p.parents else str(f)
        tests = tests_for(rel)
        if tests is CORE and unplaced is not None:
            unplaced.append(rel)
        for t in tests:
            if t not in wanted and (SMOKE / t).is_file():
                wanted.append(t)
    return wanted


def main(argv) -> int:
    run = "--run" in argv
    files = [a for a in argv if not a.startswith("--")] or changed_files()
    unplaced = []
    tests = impact(files, unplaced)
    print(f"{len(files)} changed file(s) -> {len(tests)} of {len(all_tests())} test file(s)")
    if unplaced:
        print(f"unplaced (core set only; the nightly full run covers them): {' '.join(unplaced)}")
    print(" ".join(tests))
    if run and tests:
        return subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider", *tests], cwd=str(SMOKE)).returncode
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
