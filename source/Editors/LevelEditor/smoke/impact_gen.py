"""impact_gen: builds impact.py's map from the code (Tomas 2026-11-19: the file-to-test map is generated, never hand-kept).

    python impact_gen.py            prints what it found (impact.py calls build() at every run, ~2 s)

What it records, all read from the sources:
- includers: for every C++ file of ours (source/, plugins/*, dependencies/x*), the files that #include it
- commands:  every console command and component/system type, and the file that registers it ( ...(System, "Name", ...) / .m_pName = "Name" )
- tests:     the commands each test_*.py drives, directly or through a harness/conftest helper it calls
impact.py walks the includers from a changed file to the command files above it, and runs the tests that drive those commands.
"""
import ast
import os
import re
import sys
from pathlib import Path

SMOKE = Path(__file__).resolve().parent
REPO = SMOKE.parents[3]
EXT = (".h", ".hpp", ".cpp", ".inl", ".cc")
SKIP = {"build", ".git", "cache", "examples", "unit_test", "unit_tests", "tests", "test", "dependencies", "plugins"}      # (inner dependencies/plugins: clones of ones walked at the top)
INCLUDE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', re.M)
REGISTER = re.compile(r'\(\s*\w*System\w*\s*,\s*"([A-Za-z]\w+)"|\.m_pName\s*=\s*"([A-Za-z][\w ]+)"')      # a console command | a component/system type
WORD = re.compile(r"[A-Z][A-Za-z0-9]+")
NAMESPACE = re.compile(r"^\s*namespace\s+(\w+(?:::\w+)+)\s*\{", re.M)      # a nested namespace: xlevel::engine


def our_roots():
    yield REPO / "source"
    for top in ("plugins", "dependencies"):
        for d in sorted((REPO / top).iterdir()):
            if d.is_dir() and d.name.startswith("x"):
                yield d


def sources():
    for root in our_roots():
        for d, ds, fs in os.walk(root, followlinks=True):
            ds[:] = [x for x in ds if x.lower() not in SKIP]
            for f in fs:
                if f.endswith(EXT):
                    p = Path(d) / f
                    yield p.relative_to(REPO).as_posix(), p


def library(rel):
    parts = rel.split("/")
    return "/".join(parts[:2]) if parts[0] in ("plugins", "dependencies") else parts[0]


def build(namespace_edges=True):      # (False: #include edges only - include_cycles.py, KPI Q3)
    files = dict(sources())
    by_name = {}
    for rel in files:
        by_name.setdefault(rel.rsplit("/", 1)[-1], []).append(rel)
    includers, commands, texts, spaces, types = {}, {}, {}, {}, set()
    for rel, p in files.items():
        text = texts[rel] = p.read_text(encoding="utf-8", errors="replace")
        for ns in NAMESPACE.findall(text):
            spaces.setdefault(ns, set()).add(rel)
        for cmd, typ in REGISTER.findall(text):
            commands.setdefault(cmd or typ, []).append(rel)
            if typ and not cmd:
                types.add(typ)
        for inc in INCLUDE.findall(text):
            cands = [c for c in by_name.get(inc.rsplit("/", 1)[-1], []) if c.endswith(inc.lstrip("./"))] or by_name.get(inc.rsplit("/", 1)[-1], [])
            same = [c for c in cands if library(c) == library(rel)]      # (an ambiguous name: the includer's own library first)
            for c in same or cands:
                if c != rel:
                    includers.setdefault(c, []).append(rel)
    # a header's nested namespace used by name (ns::thing) is a dependency even with no #include - the editor's unity headers lean on
    # what the file before them included (LevelEditor_Commands_Scripting.h uses xlevel::engine from xlevel_engine_copies.h); only
    # namespaces declared by at most 3 files: a wide one says nothing
    for ns, decl in spaces.items():
        if namespace_edges and len(decl) <= 3:
            for rel, text in texts.items():
                if rel not in decl and ns + "::" in text:
                    for d in decl:
                        includers.setdefault(d, []).append(rel)
    names = set(commands) - types      # (commands: a word in a test is a call)
    helpers = {}       # harness/conftest function -> the commands its body names
    for helper in ("harness.py", "conftest.py"):
        tree = ast.parse((SMOKE / helper).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                used = set(WORD.findall(ast.get_source_segment((SMOKE / helper).read_text(encoding="utf-8"), node) or "")) & names
                if used:
                    helpers[node.name] = helpers.get(node.name, set()) | used
    tests = {}
    for t in sorted(SMOKE.glob("test_*.py")):
        text = t.read_text(encoding="utf-8", errors="replace")
        used = set(WORD.findall(text)) & names
        # a type only where a test names it as a value (-Component Transform, "Physics Body"): "-Scene" or a word in a sentence is not a use
        used |= {n for n in types if re.search(rf"""(-\w+\s+|["'])""" + re.escape(n) + r"""(?![\w])""", text)}
        for h, cmds in helpers.items():
            if re.search(rf"\b{h}\(", text):
                used |= cmds
        tests[t.name] = sorted(used)
    return {"about": "generated by impact_gen.py - do not edit", "includers": {k: sorted(set(v)) for k, v in sorted(includers.items())},
            "commands": {k: sorted(set(v)) for k, v in sorted(commands.items())}, "tests": tests}


if __name__ == "__main__":
    m = build()
    blind = [t for t, c in m["tests"].items() if not c]
    print(f"{len(m['includers'])} included files, {len(m['commands'])} commands, {len(m['tests'])} tests ({len(blind)} drive no command: run only for their own change and in the full run)")
    sys.exit(0)
