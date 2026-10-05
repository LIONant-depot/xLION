"""Two verbs: Save saves the local work, SaveAll saves everything in the editor, whoever owns it.

A rename in the resource view is kept in memory until it is saved. The Level's Save does not write it (it is not the Level's work); the resource view's own Save (the SaveAssets command, the Save button)
does, and so does SaveAll, which fires the editor's Save All event - everything that has unsaved work subscribes to it (the open editors, the resource database).
"""
import re

from harness import REPO

LIBRARY = "ADEB2E3BF97B6E03"
FONT = "5549D8C8E9220001" + "3285CB58BB79E1AD"                    # Arial MTSDF of the example project: instance + type
INFO = REPO / "example.lionprj/Descriptors/Font/01/00/5549D8C8E9220001.desc/info.txt"


def name_on_disk() -> str:
    return re.search(r'"Info/Name"\s+;string\s+"([^"]*)"', INFO.read_text(errors="replace"))[1]


def rename(editor, name: str) -> None:
    assert editor.cmd(f'RenameAsset -Library {LIBRARY} -Asset {FONT} -Name "{name}"', allow_disk=True) == ""


def test_a_rename_is_only_in_memory_until_the_resource_view_or_save_all_saves_it(level):
    editor = level.ed
    original, original_bytes = name_on_disk(), INFO.read_bytes()
    try:
        rename(editor, "SaveAllTestName")
        assert name_on_disk() == original, "a rename is kept in memory"

        editor.cmd("Save", allow_disk=True)
        assert name_on_disk() == original, "the Level's Save is local: the rename is not the Level's work"

        reply = editor.cmd("SaveAll", allow_disk=True)
        assert "Resource database" in reply, reply
        assert name_on_disk() == "SaveAllTestName", "Save All saves what the resource view holds"
        assert editor.cmd("SaveAll", allow_disk=True) == "SaveAll: nothing was pending"
    finally:
        rename(editor, original)
        editor.cmd("SaveAssets", allow_disk=True)
        INFO.write_bytes(original_bytes)                  # the editor writes the whole file again (its own spacing): the project is left as it was


def test_the_resource_views_own_save_writes_its_renames(level):
    editor = level.ed
    original, original_bytes = name_on_disk(), INFO.read_bytes()
    try:
        rename(editor, "SaveAssetsTestName")
        assert name_on_disk() == original
        assert editor.cmd("SaveAssets", allow_disk=True) == "Saved"
        assert name_on_disk() == "SaveAssetsTestName"
        assert editor.cmd("SaveAssets", allow_disk=True) == "Nothing to save"
    finally:
        rename(editor, original)
        editor.cmd("SaveAssets", allow_disk=True)
        INFO.write_bytes(original_bytes)                  # the editor writes the whole file again (its own spacing): the project is left as it was


def test_unsaved_says_what_has_unsaved_work_without_saving_it(level):
    """The Save buttons pulse while something is unsaved; `Unsaved` says the same to whoever cannot see them (a command line, an AI): the open editors with changes, and the resource database."""
    editor = level.ed
    assert editor.cmd("Unsaved") == "Unsaved: nothing"

    level.new_entity()                                       # a change of the Level (in memory: nothing is saved)
    reply = editor.cmd("Unsaved")
    assert reply.startswith("Unsaved: 1: ") and level.name in reply, reply
    level.cmd("Undo")
    assert editor.cmd("Unsaved") == "Unsaved: nothing", "undone back to what was saved"

    original, original_bytes = name_on_disk(), INFO.read_bytes()
    try:
        rename(editor, "UnsavedTestName")                    # the resource view's own work
        assert editor.cmd("Unsaved") == "Unsaved: 1: Resource database"
        assert name_on_disk() == original, "asking does not save"
        editor.cmd("SaveAll", allow_disk=True)
        assert editor.cmd("Unsaved") == "Unsaved: nothing"
    finally:
        rename(editor, original)
        editor.cmd("SaveAssets", allow_disk=True)
        INFO.write_bytes(original_bytes)
