"""Script modules: the descriptor is the source of truth for what a module is made of, and the Scripting system turns it into the game's project.

These tests drive the SoccerGame module of the example project through the commands, only ever with files they create themselves, and put everything back with
Undo (what a test leaves is removed by project_guard at the end of the run).
"""
import secrets

import pytest

from harness import REPO, quote
from script_project import game_project_text

PROJECT = REPO / "example.lionprj"
MODULE_GUID = "3849E1DE2402B1A5"
MODULE_TYPE = "8D3968CB1287FA04"
MODULE_DIR = PROJECT / "Descriptors" / "ScriptModule" / "A5" / "B1" / f"{MODULE_GUID}.desc"
SOURCE_DB = MODULE_DIR / "source_db"
CMAKE = PROJECT / "Cache" / "Script" / "CMakeLists.txt"


def read(path) -> str:
    """A file's text exactly as it is on disk (no newline translation)."""
    return path.read_bytes().decode()


@pytest.fixture
def module(editor):
    library = editor.libraries()[0][0]
    target = f"-Library {library} -Asset {MODULE_GUID}{MODULE_TYPE}"

    class Module:
        ed = editor

        def cmd(self, name: str, *args: str) -> str:
            return editor.cmd(f"{name} {target} {' '.join(args)}".strip(), allow_disk=True)

        def files(self) -> dict:
            """{path: (kind, excluded, state)} from ListScriptSourceFiles."""
            reply = self.cmd("ListScriptSourceFiles")
            body = reply.split("\n\n", 1)[1].splitlines()[1:]
            return {r[0]: tuple(r[1:]) for r in (line.split("\t") for line in body)}

        def order(self) -> list:
            return [p for p, (_, _, state) in self.files().items() if state != "unlisted"]

        def cmake(self) -> str:
            return game_project_text()                                  # waits for the resource pipeline to have made the project

        def undo(self, times: int = 1) -> None:
            for _ in range(times):
                editor.cmd("Undo")

    return Module()


def make_file(module, name: str, text: str) -> None:
    """A file of the module that belongs to the test: the files of the real module are never touched."""
    assert module.cmd("AddScriptSourceFile", f"-FileName {quote(name)}") == ""
    assert module.cmd("SetScriptSourceFileContent", f"-FileName {quote(name)} -Content {quote(text)}") == ""


def test_a_module_lists_its_files_from_its_descriptor(module):
    reply = module.cmd("ListScriptSourceFiles")
    assert "ListScriptSourceFiles: ok" in reply and "Descriptor=Descriptor.txt" in reply, "the module has a descriptor (written from its folder the first time)"
    files = module.files()
    assert {"soccer_game.cpp", "soccer_common.h", "soccer_ball_system.h"} <= set(files)
    assert files["soccer_game.cpp"] == ("source", "false", "ok") and files["soccer_common.h"] == ("header", "false", "ok")
    assert (MODULE_DIR / "Descriptor.txt").is_file()


def test_the_generated_project_builds_what_the_descriptor_lists(module):
    text = module.cmake()
    for name in module.order():
        assert f"/source_db/{name}" in text, f"{name} is in the generated project"
    assert "cmake_minimum_required(VERSION 3.18)" in text


def test_adding_a_file_creates_it_lists_it_and_the_undo_removes_it(module):
    name = f"Extras/Added {secrets.token_hex(2)}.h"
    before = module.order()
    assert module.cmd("AddScriptSourceFile", f"-FileName {quote(name)}") == ""
    assert module.files()[name] == ("header", "false", "ok") and module.order() == before + [name]
    assert read(SOURCE_DB / name) == "#pragma once\r\n\r\n", "a header starts with #pragma once"
    assert f"/source_db/{name}" in module.cmake(), "the game project builds it"
    assert "already part of the module" in module.cmd("AddScriptSourceFile", f"-FileName {quote(name)}")
    module.undo()
    assert name not in module.files() and not (SOURCE_DB / name).exists() and f"/source_db/{name}" not in module.cmake()
    folder = SOURCE_DB / "Extras"
    if folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()


def test_a_new_source_file_includes_its_own_header(module):
    stem = f"Pair{secrets.token_hex(2)}"
    assert module.cmd("AddScriptSourceFile", f"-FileName {stem}.h") == ""
    assert module.cmd("AddScriptSourceFile", f"-FileName {stem}.cpp") == ""
    assert read(SOURCE_DB / f"{stem}.cpp") == f'#include "{stem}.h"\r\n\r\n'
    module.undo(2)
    assert stem + ".h" not in module.files()


def test_paths_that_cannot_be_part_of_a_module_are_refused(module):
    for bad, why in (("..\\outside.h", "cannot be a path"), ("C:\\x\\y.h", "cannot be a path"), ("notes.txt", "not a C++ file"), ("a//b.h", "cannot be a path")):
        reply = module.cmd("AddScriptSourceFile", f"-FileName {quote(bad)}")
        assert why in reply, (bad, reply)


def test_a_file_that_is_only_in_the_folder_is_not_built_until_it_is_added(module):
    name = f"Loose{secrets.token_hex(2)}.cpp"
    (SOURCE_DB / name).write_bytes(b"// written by hand\n")
    try:
        assert module.files()[name] == ("source", "false", "unlisted")
        module.ed.cmd("RegenerateProjectModuleSources", allow_disk=True)
        assert f"/source_db/{name}" not in module.cmake(), "the descriptor decides: an unlisted file is not built"
        assert module.cmd("AddScriptSourceFile", f"-FileName {name}") == ""             # adopts it: the content stays
        assert module.files()[name][2] == "ok" and read(SOURCE_DB / name) == "// written by hand\n"
        assert f"/source_db/{name}" in module.cmake()
        module.undo()
        assert (SOURCE_DB / name).exists(), "the undo of adding a file that was already there does not delete it"
        assert module.files()[name][2] == "unlisted"
    finally:
        (SOURCE_DB / name).unlink(missing_ok=True)


def test_removing_a_file_deletes_it_and_the_undo_gives_it_back_with_its_place(module):
    first, second = f"Rm{secrets.token_hex(2)}.h", f"Rm{secrets.token_hex(2)}.h"
    text = '#pragma once\n// bytes that must come back exactly, with "quotes" and a tab\there\n'
    make_file(module, first, text)
    make_file(module, second, "#pragma once\n")
    order = module.order()
    assert order[-2:] == [first, second]
    assert module.cmd("RemoveScriptSourceFile", f"-FileName {quote(first)}") == ""
    assert first not in module.files() and not (SOURCE_DB / first).exists() and f"/source_db/{first}" not in module.cmake()
    assert "not part of the module" in module.cmd("RemoveScriptSourceFile", f"-FileName {quote(first)}")
    module.undo()
    assert read(SOURCE_DB / first) == text, "the exact bytes come back"
    assert module.order() == order, "and the file has the place it had in the list"
    assert f"/source_db/{first}" in module.cmake()
    module.undo(4)                                                  # the two contents and the two files
    assert first not in module.files() and second not in module.files()


def test_renaming_and_moving_a_file_keeps_the_descriptor_and_the_project_in_step(module):
    old = f"Mv{secrets.token_hex(2)}.h"
    new = f"Systems/Renamed {secrets.token_hex(2)}.h"
    text = "#pragma once\n// moved\n"
    make_file(module, old, text)
    order = module.order()
    assert module.cmd("RenameScriptSourceFile", f"-OldFileName {old} -NewFileName {quote(new)}") == ""
    files = module.files()
    assert new in files and old not in files and read(SOURCE_DB / new) == text and not (SOURCE_DB / old).exists()
    assert f"/source_db/{new}" in module.cmake() and f"/source_db/{old}" not in module.cmake()
    assert "already exists" in module.cmd("RenameScriptSourceFile", f"-OldFileName {quote(new)} -NewFileName soccer_game.cpp")
    assert module.order() == order[:-1] + [new], "it keeps its place in the list"
    module.undo()
    assert module.order() == order and read(SOURCE_DB / old) == text and not (SOURCE_DB / new).exists()
    module.undo(2)
    assert old not in module.files()
    folder = SOURCE_DB / "Systems"
    if folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()


def test_the_content_of_a_file_is_set_as_plain_text_and_the_undo_restores_it(module):
    name = f"Content{secrets.token_hex(2)}.h"
    assert module.cmd("AddScriptSourceFile", f"-FileName {name}") == ""
    text = '#pragma once\n// a "quoted" word, a path C:\\games\\x\\ and two  spaces\nstruct S { int a = 1; };\n'
    assert module.cmd("SetScriptSourceFileContent", f"-FileName {name} -Content {quote(text)}") == ""
    assert read(SOURCE_DB / name) == text, "multi-line text with quotes and backslashes arrives as it was written"
    module.undo()
    assert read(SOURCE_DB / name) == "#pragma once\r\n\r\n"
    module.undo()
    assert name not in module.files()
    assert "does not exist" in module.cmd("SetScriptSourceFileContent", f"-FileName missing{secrets.token_hex(2)}.h -Content x")


def test_a_rescan_lists_the_files_that_are_in_the_folder_and_the_undo_puts_the_descriptor_back(module):
    name = f"Found{secrets.token_hex(2)}.hpp"
    (SOURCE_DB / name).write_text("#pragma once\n")
    descriptor = (MODULE_DIR / "Descriptor.txt").read_bytes()
    try:
        assert module.cmd("RescanScriptModule") == ""
        assert module.files()[name][2] == "ok"
        module.undo()
        assert module.files()[name][2] == "unlisted" and (MODULE_DIR / "Descriptor.txt").read_bytes() == descriptor
        (SOURCE_DB / name).unlink()
        stale = f"Gone{secrets.token_hex(2)}.h"
        assert module.cmd("AddScriptSourceFile", f"-FileName {stale}") == ""
        (SOURCE_DB / stale).unlink()
        assert module.files()[stale][2] == "missing", "a listed file that is gone is reported, never dropped silently"
        assert module.cmd("RescanScriptModule", "-RemoveMissing true") == ""
        assert stale not in module.files()
        module.undo(2)
    finally:
        (SOURCE_DB / name).unlink(missing_ok=True)
