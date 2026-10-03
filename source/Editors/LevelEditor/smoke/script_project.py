"""The game project of the example project, as the resource pipeline makes it.

The project's Game resource lists the script modules; the pipeline compiles each module into its CMake file (Cache/Resources/Platforms/WINDOWS/ScriptModule/xx/yy/<guid>), then
the Game into Cache/Script/CMakeLists.txt, which includes them. Both happen in the background after the descriptor of a module changes, so a test that changed one waits here before
it looks at the project: the same rule the build of Game.dll uses (the project is current when it was made after everything it is made from last changed).
"""
import re
import secrets
import time

from harness import REPO, quote

PROJECT = REPO / "example.lionprj"
MODULE_GUID = "3849E1DE2402B1A5"
MODULE_REST = f"ScriptModule/A5/B1/{MODULE_GUID}"
MODULE_DESCRIPTOR = PROJECT / "Descriptors" / f"{MODULE_REST}.desc" / "Descriptor.txt"
MODULE_CMAKE = PROJECT / "Cache" / "Resources" / "Platforms" / "WINDOWS" / MODULE_REST
MODULE_LOG = PROJECT / "Cache" / "Resources" / "Logs" / f"{MODULE_REST}.log" / "Log.txt"
CMAKELISTS = PROJECT / "Cache" / "Script" / "CMakeLists.txt"


def game_folder():
    """The .desc folder of the Game resource the project builds (Script.config.txt names it; tests may make others)."""
    config = (PROJECT / "Project.config" / "Script.config.txt").read_text()
    named = re.search(r'"ScriptConfig/Game"\s*;full_guid\s+#(\w+)', config)
    assert named, "Script.config.txt names the project's Game"
    guid = int(named[1], 16)
    folder = PROJECT / "Descriptors" / "Game" / f"{guid & 0xFF:02X}" / f"{(guid >> 8) & 0xFF:02X}" / f"{guid:X}.desc"
    assert folder.is_dir(), f"the Game {guid:016X} is in the project"
    return folder


def _mtime(path) -> int:
    return path.stat().st_mtime_ns if path.exists() else 0


def pipeline_done() -> bool:
    game = game_folder()
    stamp = PROJECT / "Cache" / "Resources" / "Platforms" / "WINDOWS" / "Game" / game.parent.parent.name / game.parent.name / game.name.removesuffix(".desc")
    return (MODULE_CMAKE.exists() and _mtime(MODULE_CMAKE) >= _mtime(MODULE_DESCRIPTOR)
            and stamp.exists() and _mtime(stamp) >= max(_mtime(MODULE_LOG), _mtime(game / "Descriptor.txt")))


def wait_for_pipeline(timeout: float = 60.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if pipeline_done():
            time.sleep(0.2)                                       # not in the middle of a write
            if pipeline_done():
                return
        time.sleep(0.1)
    raise AssertionError("the resource pipeline did not make the game project")


def game_project_text(timeout: float = 60.0) -> str:
    """CMakeLists.txt and the CMake file of the module it includes, the way a person reads them: forward slashes, and `/source_db/<file>` for a file of the module."""
    wait_for_pipeline(timeout)
    text = CMAKELISTS.read_bytes().decode() + "\n" + MODULE_CMAKE.read_bytes().decode()
    return re.sub(r"\$\{[A-Z0-9_]+_SOURCE_ROOT\}/", "/source_db/", text.replace("\\", "/"))


def module_cmake_text(timeout: float = 60.0) -> str:
    """Only the CMake file of the module (forward slashes)."""
    wait_for_pipeline(timeout)
    return MODULE_CMAKE.read_bytes().decode().replace("\\", "/")


FOLDER_TYPE = "C4D90C5F0CC43021"


def remove_asset(type_name, asset):
    """Deletes what a test made of an asset - its descriptor folder and the files the pipeline made for it - so the next test does not find it (the editor's own database still
    remembers it until it restarts, which is harmless: its descriptor is gone)."""
    import shutil
    value = int(asset[:16], 16)
    rest = f"{type_name}/{value & 0xFF:02X}/{(value >> 8) & 0xFF:02X}/{value:X}"
    shutil.rmtree(PROJECT / "Descriptors" / f"{rest}.desc", ignore_errors=True)
    shutil.rmtree(PROJECT / "Cache" / "Resources" / "Logs" / f"{rest}.log", ignore_errors=True)
    (PROJECT / "Cache" / "Resources" / "Platforms" / "WINDOWS" / rest).unlink(missing_ok=True)


def new_asset(editor, lib, type_guid, name):
    """Creates an asset of a type in the library's root folder; returns its guid."""
    guid = f"{secrets.randbits(63) << 1 | 1:016X}{type_guid}"
    assert editor.cmd(f"CreateAsset -Library {lib} -Type {type_guid} -Asset {guid} -Parent {lib}{FOLDER_TYPE} -Name {quote(name)}", allow_disk=True) == ""
    return guid
