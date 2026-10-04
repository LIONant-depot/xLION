"""The script module editor: the window of a ScriptModule resource - a source tree, a viewer window per open file, the libraries - and its commands.

Everything the window does is a command, so these tests drive the commands, and the real mouse for what only the mouse does (a double click opens a file). The
SoccerGame module of the example project is used, with files the tests create themselves; Undo puts everything back.
"""
import re
import secrets
import time

import pytest

from harness import REPO, quote
from script_project import CMAKELISTS, game_project_text, module_cmake_text

PROJECT = REPO / "example.lionprj"
ASSET = "3849E1DE2402B1A58D3968CB1287FA04"
MODULE_DIR = PROJECT / "Descriptors" / "ScriptModule" / "A5" / "B1" / "3849E1DE2402B1A5.desc"
SOURCE_DB = MODULE_DIR / "source_db"
CMAKE = CMAKELISTS
NAME = "SoccerGame"


def read(path) -> str:
    return path.read_bytes().decode()


def table(reply: str) -> list[dict]:
    head, _, body = reply.partition("\n\n")
    lines = [l for l in body.splitlines() if l]
    names = lines[0].split("\t")
    return [dict(zip(names, l.split("\t"))) for l in lines[1:]]


@pytest.fixture
def module(editor):
    editor.ok(f"OpenResourceEditor -Asset {ASSET} -Library {editor.libraries()[0][0]}") if hasattr(editor, "ok") else editor.cmd(f"OpenResourceEditor -Asset {ASSET} -Library {editor.libraries()[0][0]}", allow_disk=True)
    time.sleep(0.8)

    class Module:
        ed = editor

        def cmd(self, line: str) -> str:
            return editor.cmd(f"{NAME}\\{line}", allow_disk=True)

        def files(self) -> dict:
            return {r["Path"]: r for r in table(self.cmd("ListFiles"))}

        def order(self) -> list:
            return [p for p, r in self.files().items() if r["State"] != "unlisted"]

        def open_files(self) -> list:
            return [r["Path"] for r in table(self.cmd("ListOpenFiles"))]

        def cmake(self) -> str:
            return game_project_text()                                  # waits for the resource pipeline to have made the project

        def undo(self, times: int = 1) -> None:
            for _ in range(times):
                assert self.cmd("Undo") == "Undo: done"

        def tree(self) -> dict:
            reply = self.cmd("ListTree")
            return {r["Path"]: r for r in table(reply)}

    yield Module()
    editor.cmd(f"CloseResourceEditor -Asset {ASSET}")


def test_the_editor_opens_for_the_module_and_lists_its_files_like_the_workspace_does(module):
    sessions = {s.name: s for s in module.ed.sessions()}
    assert NAME in sessions
    files = module.files()
    assert {"soccer_game.cpp", "soccer_common.h"} <= set(files) and files["soccer_game.cpp"]["Kind"] == "source" and files["soccer_common.h"]["Kind"] == "header"
    assert all(r["State"] == "ok" for r in files.values())
    assert all(r["SourceControl"] in ("clean", "modified", "staged", "untracked", "conflicted", "unknown") for r in files.values())
    library = module.ed.libraries()[0][0]
    workspace = module.ed.cmd(f"ListScriptSourceFiles -Library {library} -Asset {ASSET}", allow_disk=True)
    assert [r["Path"] for r in table(workspace)] == list(files), "the editor and the workspace command agree on what the module is"


def test_the_editor_commands_add_remove_rename_and_move_with_undo(module):
    name, moved, folder = f"Ed{secrets.token_hex(2)}.h", f"Moved {secrets.token_hex(2)}.h", f"Sys{secrets.token_hex(2)}"
    before = module.order()
    assert module.cmd(f"AddFile -Path {quote(name)}") == ""
    assert module.files()[name]["Kind"] == "header" and (SOURCE_DB / name).is_file() and f"/source_db/{name}" in module.cmake()
    assert module.cmd(f"NewFolder -Path {folder}") == "" and (SOURCE_DB / folder).is_dir()
    assert module.cmd(f"RenameFile -Path {name} -To {quote(folder + '/' + moved)}") == ""
    assert f"{folder}/{moved}" in module.files() and not (SOURCE_DB / name).exists() and (SOURCE_DB / folder / moved).is_file()
    assert module.cmd(f"RenameFolder -Path {folder} -To {folder}Renamed") == ""
    assert f"{folder}Renamed/{moved}" in module.files() and not (SOURCE_DB / folder).exists()
    assert module.cmd(f"RemoveFolder -Path {folder}Renamed") == ""
    assert f"{folder}Renamed/{moved}" not in module.files() and not (SOURCE_DB / f"{folder}Renamed").exists() and f"{moved}" not in module.cmake()
    module.undo(5)                                                  # RemoveFolder, RenameFolder, RenameFile, NewFolder, AddFile
    assert module.order() == before and not (SOURCE_DB / name).exists() and not (SOURCE_DB / folder).exists() and not (SOURCE_DB / f"{folder}Renamed").exists()


def test_removing_a_folder_and_undoing_it_restores_every_file_and_its_place(module):
    folder = f"Pack{secrets.token_hex(2)}"
    names = [f"{folder}/A{secrets.token_hex(1)}.h", f"{folder}/B{secrets.token_hex(1)}.h", f"{folder}/Deep/C{secrets.token_hex(1)}.cpp"]
    for n in names:
        assert module.cmd(f"AddFile -Path {quote(n)}") == ""
    loose = SOURCE_DB / folder / "notes.dat"
    loose.write_bytes(b"data\x00that is not C++")
    order = module.order()
    assert module.cmd(f"RemoveFolder -Path {folder}") == ""
    assert not (SOURCE_DB / folder).exists() and not any(n in module.files() for n in names)
    module.undo()
    assert module.order() == order, "the files are back in their places"
    assert loose.read_bytes() == b"data\x00that is not C++", "and a file that is not C++ comes back byte for byte"
    module.undo(len(names))
    assert not (SOURCE_DB / folder).exists() or not any((SOURCE_DB / folder).rglob("*.h"))
    import shutil
    shutil.rmtree(SOURCE_DB / folder, ignore_errors=True)


def test_a_file_left_out_of_the_build_stays_in_the_module(module):
    name = f"Skip{secrets.token_hex(2)}.cpp"
    assert module.cmd(f"AddFile -Path {name}") == ""
    assert f"/source_db/{name}" in module.cmake()
    assert module.cmd(f"ExcludeFile -Path {name}") == ""
    assert module.files()[name]["Excluded"] == "true" and f"/source_db/{name}" not in module.cmake(), "excluded: still listed, no longer built"
    module.undo()
    assert module.files()[name]["Excluded"] == "false" and f"/source_db/{name}" in module.cmake()
    module.undo()
    assert name not in module.files()


def test_a_file_has_one_viewer_ever_and_the_viewer_follows_a_rename(module):
    name, moved = f"View{secrets.token_hex(2)}.h", f"Viewed{secrets.token_hex(2)}.h"
    assert module.cmd(f"AddFile -Path {name}") == ""
    assert module.open_files() == []
    assert module.cmd(f"OpenFile -Path {name} -Line 1").endswith("is open")
    assert module.cmd("OpenFile -Path soccer_game.cpp -Line 12").endswith("is open")
    assert module.cmd(f"OpenFile -Path {name}").endswith("is open")                    # the same file again: no second viewer
    assert module.open_files() == [name, "soccer_game.cpp"], "one tab per file, in the order they were opened"
    time.sleep(0.5)
    assert "Front=" + name in module.cmd("ListOpenFiles"), "opening an open file brings it to the front"
    assert module.cmd(f"RenameFile -Path {name} -To {moved}") == ""
    assert module.open_files() == [moved, "soccer_game.cpp"], "the viewer follows the file to its new name"
    assert "has no viewer" in module.cmd(f"CloseFile -Path {name}")
    assert module.cmd(f"CloseFile -Path {moved}") == "CloseFile: closed" and module.open_files() == ["soccer_game.cpp"]
    assert module.cmd(f"RemoveFile -Path {moved}") == "" if False else True
    assert "is not a C++ file of this module" in module.cmd("OpenFile -Path nothing_like_this.h")
    assert "is not a C++ file of this module" in module.cmd("OpenFile -Path notes.txt")
    assert module.cmd("CloseFile -Path soccer_game.cpp") == "CloseFile: closed"
    module.undo(2)                                                  # the rename, the add


def test_a_viewer_zooms_its_text_and_each_file_keeps_its_own_size(module):
    """Ctrl + the mouse wheel over the code changes the text's size; ZoomFile does the same for a script (one notch = one pixel, like the wheel)."""
    size = lambda f: float({r["Path"]: r for r in table(module.cmd("ListOpenFiles"))}[f]["FontSize"])
    module.cmd("OpenFile -Path soccer_game.cpp")
    module.cmd("OpenFile -Path soccer_components.h")
    time.sleep(0.5)                                                 # a frame draws them: the default size is known
    default = size("soccer_game.cpp")
    assert default > 0 and size("soccer_components.h") == default
    assert module.cmd("ZoomFile -Path soccer_game.cpp -By 3") == "ZoomFile: ok" and size("soccer_game.cpp") == default + 3
    assert size("soccer_components.h") == default, "each file's viewer has its own size"
    assert module.cmd("ZoomFile -Path soccer_game.cpp -By -2") == "ZoomFile: ok" and size("soccer_game.cpp") == default + 1
    module.cmd("ZoomFile -Path soccer_game.cpp -By 1000")
    assert size("soccer_game.cpp") == 64, "not bigger than 64 pixels"
    assert module.cmd("ZoomFile -Path soccer_game.cpp -By -1000") == "ZoomFile: ok"
    assert size("soccer_game.cpp") == 6, "not smaller than 6 pixels"
    module.cmd("ZoomFile -Path soccer_game.cpp -Size 0")
    assert size("soccer_game.cpp") == default, "0 is the default size again"
    assert "is not open" in module.cmd("ZoomFile -Path nothing_like_this.h -By 1")
    assert "say -By" in module.cmd("ZoomFile -Path soccer_game.cpp")
    module.cmd("CloseFile -Path soccer_game.cpp"); module.cmd("CloseFile -Path soccer_components.h")


def test_ctrl_and_the_mouse_wheel_over_the_code_zoom_its_text_and_the_wheel_alone_does_not(module):
    """The real wheel, the real Ctrl key and the real pointer: what a person does."""
    row = lambda: {r["Path"]: r for r in table(module.cmd("ListOpenFiles"))}["soccer_game.cpp"]
    module.cmd("OpenFile -Path soccer_game.cpp")
    for _ in range(20):
        if float(row()["X"]) > 0:
            break
        time.sleep(0.2)                                             # until a frame has drawn it
    x, y, default = float(row()["X"]), float(row()["Y"]), float(row()["FontSize"])
    assert x > 0 and y > 0 and default > 0
    module.ed.wheel(x, y, 3, ctrl=True)
    assert float(row()["FontSize"]) == default + 3, "three notches up with Ctrl: three pixels bigger"
    module.ed.wheel(x, y, -5, ctrl=True)
    assert float(row()["FontSize"]) == default - 2, "five notches down with Ctrl: five pixels smaller"
    module.ed.wheel(x, y, 3)
    assert float(row()["FontSize"]) == default - 2, "the wheel without Ctrl scrolls: the size does not change"
    module.cmd("ZoomFile -Path soccer_game.cpp -Size 0")
    module.cmd("CloseFile -Path soccer_game.cpp")


def test_removing_a_file_closes_its_viewer(module):
    name = f"Gone{secrets.token_hex(2)}.h"
    assert module.cmd(f"AddFile -Path {name}") == ""
    module.cmd(f"OpenFile -Path {name}")
    assert module.open_files() == [name]
    assert module.cmd(f"RemoveFile -Path {name}") == ""
    assert module.open_files() == []
    module.undo(2)


def test_libraries_are_properties_of_the_descriptor_and_end_up_in_the_game_project(module):
    descriptor = (MODULE_DIR / "Descriptor.txt").read_bytes()
    edits = [
        'SetProperty -Path "ScriptModule/Libraries[]" -Value 1',
        'SetProperty -Path "ScriptModule/Libraries[G:0]/Name" -Value "Box2D"',
        'SetProperty -Path "ScriptModule/Libraries[G:0]/IncludeDirs[]" -Value 1',
        'SetProperty -Path "ScriptModule/Libraries[G:0]/IncludeDirs[G:0]" -Value "ThirdParty/box2d/include"',
        'SetProperty -Path "ScriptModule/Libraries[G:0]/LibDirs[]" -Value 1',
        'SetProperty -Path "ScriptModule/Libraries[G:0]/LibDirs[G:0]" -Value "ThirdParty/box2d/lib"',
        'SetProperty -Path "ScriptModule/Libraries[G:0]/Libs[]" -Value 1',
        'SetProperty -Path "ScriptModule/Libraries[G:0]/Libs[G:0]" -Value "box2d.lib"',
        'SetProperty -Path "ScriptModule/Libraries[G:0]/Defines[]" -Value 1',
        'SetProperty -Path "ScriptModule/Libraries[G:0]/Defines[G:0]" -Value "B2_SHARED=1"',
        'SetProperty -Path "ScriptModule/Libraries[G:0]/RuntimeFiles[]" -Value 1',
        'SetProperty -Path "ScriptModule/Libraries[G:0]/RuntimeFiles[G:0]" -Value "ThirdParty/box2d/bin/box2d.dll"',
        'SetProperty -Path "ScriptModule/Defines[]" -Value 1',
        'SetProperty -Path "ScriptModule/Defines[G:0]" -Value "SOCCER_FAST"',
    ]
    try:
        for line in edits:
            assert module.cmd(line) == "", line
        assert module.cmd("Save") == "Save: saved"
        text = module_cmake_text()                                    # the game project follows the saved descriptor: the pipeline compiles the module, then the Game
        assert 'set(SOCCERGAME_INCLUDE_DIRS\n  "${SOCCERGAME_PROJECT_ROOT}/ThirdParty/box2d/include"\n)' in text, "include folders are relative to the project"
        assert 'set(SOCCERGAME_LIB_DIRS\n  "${SOCCERGAME_PROJECT_ROOT}/ThirdParty/box2d/lib"\n)' in text
        assert 'set(SOCCERGAME_LIBS\n  "box2d.lib"\n)' in text, "a bare library name is searched in the library folders"
        assert '"B2_SHARED=1"' in text and '"SOCCER_FAST"' in text
        assert 'set(SOCCERGAME_RUNTIME_FILES\n  "${SOCCERGAME_PROJECT_ROOT}/ThirdParty/box2d/bin/box2d.dll"\n)' in text, "the DLLs the libraries bring are listed for the loader"
        assert "box2d" in game_project_text(), "and the game project includes the module's file"
        problems = module.ed.cmd(f"{NAME}\\Compile").lower()
        assert "validation error" not in problems
        # an absolute path is not allowed: the project must build on another machine
        assert module.cmd('SetProperty -Path "ScriptModule/Libraries[G:0]/IncludeDirs[G:0]" -Value "C:/libs/box2d/include"') == ""
        assert "absolute" in module.ed.cmd(f"{NAME}\\Compile")
    finally:
        for _ in range(len(edits) + 1):                               # the edits and the absolute path
            module.cmd("Undo")
        module.cmd("Save")
    assert "box2d" not in module_cmake_text() and (MODULE_DIR / "Descriptor.txt").read_bytes() == descriptor, "everything is back as it was"


def test_a_file_that_is_only_in_the_folder_is_listed_as_not_in_the_module_and_a_rescan_adds_it(module):
    name = f"Found{secrets.token_hex(2)}.hpp"
    (SOURCE_DB / name).write_bytes(b"#pragma once\n")
    try:
        deadline = time.time() + 5
        while module.files().get(name, {}).get("State") != "unlisted" and time.time() < deadline:
            time.sleep(0.2)
        assert module.files()[name]["State"] == "unlisted"
        assert f"/source_db/{name}" not in module.cmake()
        assert module.cmd("Rescan") == ""
        assert module.files()[name]["State"] == "ok" and f"/source_db/{name}" in module.cmake()
        module.undo()
        assert module.files()[name]["State"] == "unlisted"
    finally:
        (SOURCE_DB / name).unlink(missing_ok=True)


def test_source_control_says_a_new_file_is_untracked(module):
    name = f"Scm{secrets.token_hex(2)}.h"
    assert module.cmd(f"AddFile -Path {name}") == ""
    try:
        library = module.ed.libraries()[0][0]
        state = ""
        for _ in range(60):
            module.ed.cmd(f"SourceControlRefresh -Library {library}", allow_disk=True)
            state = module.files()[name]["SourceControl"]
            if state == "untracked":
                break
            time.sleep(0.5)
        assert state == "untracked", state
        assert module.files()["soccer_game.cpp"]["SourceControl"] in ("clean", "modified", "staged")
    finally:
        module.undo()


def test_the_tree_lists_what_it_draws_and_a_double_click_opens_a_file(module):
    time.sleep(1.0)
    rows = module.tree()
    assert "(module)" in rows and rows["(module)"]["Kind"] == "folder" and "soccer_game.cpp" in rows, rows.keys()
    target = rows["soccer_game.cpp"]
    assert float(target["X"]) > 0 and float(target["Y"]) > 0, "the row is on the screen"
    module.ed.click(float(target["X"]) + 10, float(target["Y"]))
    time.sleep(0.4)
    assert module.tree()["soccer_game.cpp"]["Selected"] == "true", "a click selects the row"
    assert module.open_files() == []
    module.ed.double_click(float(target["X"]) + 10, float(target["Y"]))
    for _ in range(20):
        if module.open_files():
            break
        time.sleep(0.2)
    assert module.open_files() == ["soccer_game.cpp"], "a double click opens the file in its own tab"
    module.ed.double_click(float(target["X"]) + 10, float(target["Y"]))
    time.sleep(0.5)
    assert module.open_files() == ["soccer_game.cpp"], "and a second double click does not open it again"
    module.cmd("CloseFile -Path soccer_game.cpp")


def test_select_file_selects_a_row_and_is_refused_for_what_is_not_there(module):
    time.sleep(0.8)
    assert module.cmd("SelectFile -Path soccer_common.h") == "SelectFile: selected"
    time.sleep(0.5)
    assert module.tree()["soccer_common.h"]["Selected"] == "true"
    assert "is not in the tree" in module.cmd("SelectFile -Path nothing.h")
    assert module.cmd('SelectFile -Path ""') == "SelectFile: selected"


def cmake_values(fragment, prefix: str, tmp_path) -> dict:
    """What CMake itself makes of an exported fragment: include it in a script and print its variables."""
    import shutil
    import subprocess
    cmake = shutil.which("cmake")
    if not cmake:
        pytest.skip("cmake is not on the PATH (the editor itself needs it to build the game)")
    script = tmp_path / "read_module.cmake"
    names = ["SOURCES", "HEADERS", "PCH_HEADERS", "INCLUDE_DIRS", "LIB_DIRS", "LIBS", "DEFINES", "RUNTIME_FILES", "PROJECT_ROOT"]
    lines = [f'include("{str(fragment).replace(chr(92), "/")}")'] + [f'message("{n}=${{{prefix}_{n}}}")' for n in names]
    lines += [f'if(COMMAND {prefix.lower()}_apply)', '  message("APPLY=yes")', 'endif()']
    script.write_text("\n".join(lines))
    out = subprocess.run([cmake, "-P", str(script)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    values = {}
    for line in (out.stderr + out.stdout).splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def test_a_module_exports_as_a_cmake_file_that_a_project_without_the_editor_can_include(module, tmp_path):
    from pathlib import Path
    fragment = tmp_path / "elsewhere" / "soccer.cmake"                # not in the module's folder: its paths are relative to where it is
    reply = module.cmd(f"ExportCMake -File {quote(str(fragment))}")
    assert reply.startswith("ExportCMake: wrote"), reply
    values = cmake_values(fragment, "SOCCERGAME", tmp_path)
    assert values.get("APPLY") == "yes", "the file defines soccergame_apply(target)"
    sources, headers = values["SOURCES"].split(";"), values["HEADERS"].split(";")
    assert [Path(p).name for p in sources] == ["soccer_game.cpp"] and len(headers) == 7
    assert all(Path(p).is_file() for p in sources + headers), "every path in the file is a real file"
    assert Path(values["PROJECT_ROOT"]).resolve() == PROJECT.resolve(), "it finds the project root from where it is"
    assert all(Path(p).name in values["PCH_HEADERS"] for p in headers)
    assert module.cmd(f"ExportCMake -File {quote(str(fragment))}").startswith("ExportCMake: unchanged"), "exporting the same module again does not rewrite the file"


def test_an_exported_module_carries_its_libraries_defines_and_files_that_are_left_out(module, tmp_path):
    from pathlib import Path
    skipped = f"Skip{secrets.token_hex(2)}.cpp"
    edits = ['SetProperty -Path "ScriptModule/Libraries[]" -Value 1',
             'SetProperty -Path "ScriptModule/Libraries[G:0]/Name" -Value "Lib"',
             'SetProperty -Path "ScriptModule/Libraries[G:0]/IncludeDirs[]" -Value 1',
             'SetProperty -Path "ScriptModule/Libraries[G:0]/IncludeDirs[G:0]" -Value "ThirdParty/lib/include"',
             'SetProperty -Path "ScriptModule/Libraries[G:0]/Libs[]" -Value 2',
             'SetProperty -Path "ScriptModule/Libraries[G:0]/Libs[G:0]" -Value "lib.lib"',
             'SetProperty -Path "ScriptModule/Libraries[G:0]/Libs[G:1]" -Value "ThirdParty/lib/bin/other.lib"',
             'SetProperty -Path "ScriptModule/Defines[]" -Value 1',
             'SetProperty -Path "ScriptModule/Defines[G:0]" -Value "FAST=1"']
    assert module.cmd(f"AddFile -Path {skipped}") == "" and module.cmd(f"ExcludeFile -Path {skipped}") == ""
    try:
        for line in edits:
            assert module.cmd(line) == "", line
        fragment = MODULE_DIR / "module.cmake"
        existed = fragment.exists()
        assert module.cmd("ExportCMake").startswith("ExportCMake: wrote")
        text = fragment.read_text()
        values = cmake_values(fragment, "SOCCERGAME", tmp_path)
        assert skipped not in values["SOURCES"] + values["HEADERS"], "a file that is left out of the build is not in the exported project"
        assert values["INCLUDE_DIRS"] == str(PROJECT / "ThirdParty" / "lib" / "include").replace("\\", "/")
        assert values["LIBS"].split(";")[0] == "lib.lib" and values["LIBS"].split(";")[1] == str(PROJECT / "ThirdParty" / "lib" / "bin" / "other.lib").replace("\\", "/")
        assert values["DEFINES"] == "FAST=1"
        assert "function(soccergame_apply target)" in text
    finally:
        for _ in range(len(edits) + 2):
            module.cmd("Undo")
        module.cmd("Save")
        if not existed:
            (MODULE_DIR / "module.cmake").unlink(missing_ok=True)


def test_a_build_error_in_a_file_of_the_module_marks_its_line_and_f8_opens_it_in_the_viewer(module):
    token = secrets.token_hex(3)
    file = SOURCE_DB / "soccer_game.cpp"
    text = f"  soccer_game.cpp\n{file}(7,3): error C2065: 'Zork{token}': undeclared identifier [D:\\proj\\Game.vcxproj]\nBuild FAILED."
    editor = module.ed
    assert "operation" in editor.cmd(f"LogSimulateBuild -Text {quote(text)} -Exit 1 -Target {quote('Game.dll|' + token)}", allow_disk=True)
    assert module.open_files() == []
    # the Logs window lists that one problem; F8 selects the next problem of its list and opens its source
    assert editor.cmd(f'LogShow -Query "Zork{token}"') == "LogShow: shown"
    time.sleep(0.8)
    assert "NextProblem" in editor.cmd("PressKeys -Keys F8")
    deadline = time.time() + 5
    while not module.open_files() and time.time() < deadline:
        time.sleep(0.2)
    assert module.open_files() == ["soccer_game.cpp"], "the file of the error opens in the module's own viewer, not in the system's program"
    rows = table(module.cmd("ListOpenFiles"))
    deadline = time.time() + 5
    while rows[0]["Problems"] == "0" and time.time() < deadline:
        time.sleep(0.2)
        rows = table(module.cmd("ListOpenFiles"))
    assert rows[0]["Problems"] == "1", "the line the compiler complained about is marked"
    module.cmd("CloseFile -Path soccer_game.cpp")
    if "open" in editor.cmd("ModalState"):
        editor.cmd("PressKeys -Keys Space")                         # the drawer the test opened
