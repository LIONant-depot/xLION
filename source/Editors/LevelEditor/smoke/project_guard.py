"""Leaves the example project exactly as the suite found it.

The suite drives a real editor against the developer's real example.lionprj. Tests never save, but Play does: it writes the
open level to disk first (the "V1" Stop restores from), entities the test made in memory included. That leaves ids in
Scene/*/entity_db that no scene lists any more, and rewrites scene files.

This plugin (loaded by pytest.ini) snapshots Descriptors/ and Project.config/ when the session starts and, when it ends:
  - deletes files that did not exist before and were written during the run (never anything older),
  - puts back the Scene/, Level/ and Texture/ files the run rewrote (a test that compiles a texture saves its descriptor; a prefab a test saves), byte for byte, from a backup taken at the start.
Work in progress the developer had before the run is therefore kept: it is restored to what it was, not to git's version.
"""
import os
import shutil
import tempfile
import time
from pathlib import Path

from harness import REPO

PROJECT = REPO / "example.lionprj"
WATCHED = [PROJECT / "Descriptors", PROJECT / "Project.config"]
RESTORABLE = [PROJECT / "Descriptors" / "Scene", PROJECT / "Descriptors" / "Level", PROJECT / "Descriptors" / "Texture", PROJECT / "Descriptors" / "ScriptModule", PROJECT / "Descriptors" / "Game", PROJECT / "Descriptors" / "Prefab"
              , PROJECT / "Project.config" / "Script.config.txt", PROJECT / "Project.config" / "SystemOrder.config.txt"]   # what a saved level rewrites, and a resource editor's Compile; the Game's module list and which Game the project builds; the saved order of the systems

_state = {}


def _files(root: Path):
    for p in root.rglob("*"):
        if p.is_file():
            st = p.stat()
            yield p, (st.st_size, st.st_mtime_ns)


def pytest_sessionstart(session):
    snap, dirs = {}, set()
    for root in WATCHED:
        if root.exists():
            snap.update(dict(_files(root)))
            dirs.update(p for p in root.rglob("*") if p.is_dir())
    backup = Path(tempfile.mkdtemp(prefix="xlion_smoke_backup_"))
    for root in RESTORABLE:
        if root.is_dir():
            shutil.copytree(root, backup / root.relative_to(PROJECT), dirs_exist_ok=True)
        elif root.is_file():
            (backup / root.relative_to(PROJECT)).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root, backup / root.relative_to(PROJECT))
    _state.update(snapshot=snap, dirs=dirs, backup=backup, started=time.time_ns())


def pytest_sessionfinish(session, exitstatus):
    if not _state:
        return
    snap, backup, started = _state["snapshot"], _state["backup"], _state["started"]
    removed, restored = [], []

    now = {}
    for root in WATCHED:
        if root.exists():
            now.update(dict(_files(root)))

    for path, (size, mtime) in now.items():
        if path not in snap:
            if mtime >= started:                     # written by this run: safe to remove
                path.unlink(missing_ok=True)
                removed.append(path)
        elif snap[path] != (size, mtime):
            src = backup / path.relative_to(PROJECT)
            if src.exists():
                shutil.copy2(src, path)
                restored.append(path)
            else:
                print(f"\n[project_guard] WARNING: the run changed {path}, which is outside what the guard can put back")

    # folders this run created and left empty
    for root in WATCHED:
        if root.exists():
            for d in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
                if d not in _state["dirs"] and not any(d.iterdir()):
                    d.rmdir()

    shutil.rmtree(backup, ignore_errors=True)
    if removed or restored:
        print(f"\n[project_guard] put example.lionprj back: {len(restored)} file(s) restored, {len(removed)} file(s) the run created removed")
    _state.clear()
