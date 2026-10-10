"""The resource reference of the inspectors: one widget (xresource_editor::RenderResourceReference) for every property that references a resource - the picture of the resource (its thumbnail, or the
picture of its type), the name that opens the picker, a clear button, and two buttons: open the resource in its editor and find it in the resource browser of the drawer.

"Find" is the LocateResource command here (the button does the same): the Resources tab of the drawer shows the resource - its folder is the current one, reached through the browser's history so Back
and Forward keep working as they always did, what would hide it (the search) is cleared, it is selected - and the drawer is open on that tab. GetBrowserState says where the browser is.
"""
import re

import pytest

NOT_A_RESOURCE = "00000000000000010000000000000001"


def state(editor) -> dict:
    reply = editor.cmd("GetBrowserState")
    assert reply.startswith("GetBrowserState: ok"), reply
    out = {"HistoryEntry": []}
    for key, value in re.findall(r"^(\w+)=(.*)$", reply, re.M):
        if key == "HistoryEntry":
            out[key].append(value)
        else:
            out[key] = value
    return out


def assets(editor) -> list[tuple[str, str, str]]:
    """(type name, guid, name) of one asset of each type the example project has."""
    found = []
    for type_name in ("Texture", "Material", "MaterialInstance", "GeomStatic", "ScriptModule", "Game", "Level"):
        hit = editor.find_asset(type_name)
        if hit:
            found.append((type_name, hit[0], hit[1]))
    return found


def locate(editor, guid: str) -> str:
    return editor.cmd(f"LocateResource -Asset {guid}")


@pytest.mark.needs_window
def test_finding_a_resource_shows_it_in_the_browser_and_opens_the_drawer_on_it(editor):
    type_name, guid, name = assets(editor)[0]
    editor.cmd("SetBrowserSearch -Text this_matches_no_resource_at_all")
    assert state(editor)["Search"] == "this_matches_no_resource_at_all"

    assert locate(editor, guid) == "LocateResource: ok"
    now = state(editor)
    assert now["Drawer"] == "open" and now["DrawerTab"] == "0", "the drawer is open on the Resources tab"
    assert now["Search"] == "", "the search that hid the resource is cleared"
    assert now["Selected"] == guid, "and it is the selection"
    assert now["Folder"], "its folder is the current one"


def test_finding_a_resource_that_is_not_there_is_refused(editor):
    assert "not in the browser" in locate(editor, NOT_A_RESOURCE)
    assert "required option" in editor.cmd("LocateResource")


@pytest.mark.needs_window
def test_finding_goes_through_the_history_of_the_browser(editor):
    """Back and Forward of the browser work on the history of the folders: finding adds the folder the way a click on it does, once, and keeps what was before it."""
    first = next(iter(assets(editor)), None)
    if first is None:
        pytest.skip("the example project has no assets")
    assert locate(editor, first[1]) == "LocateResource: ok"
    folder_a, before = state(editor)["Folder"], len(state(editor)["HistoryEntry"])

    other = None
    for _, guid, _name in assets(editor)[1:]:
        assert locate(editor, guid) == "LocateResource: ok"
        if state(editor)["Folder"] != folder_a:
            other = guid
            break
    if other is None:
        pytest.skip("every asset of the example project is in one folder")

    after = state(editor)
    assert len(after["HistoryEntry"]) == before + 1, "one more entry in the history"
    assert after["HistoryEntry"][-1] == after["Folder"], "the last entry is the folder that is shown"
    assert after["HistoryEntry"][-2] == folder_a, "the one before it is where the browser was: Back goes there"

    assert locate(editor, other) == "LocateResource: ok"
    assert len(state(editor)["HistoryEntry"]) == before + 1, "finding what is already shown adds nothing"


def test_the_hint_of_a_reference_is_the_whole_path_of_the_resource(editor):
    """The hint of the name of a resource reference shows where the resource is in the resource browser (ResourcePath says the same text, the one of the Find Resource and Open Resource items of
    the menu of an asset): the library, the folders, the name."""
    type_name, guid, name = assets(editor)[0]
    reply = editor.cmd(f"ResourcePath -Asset {guid}")
    assert reply.startswith("ResourcePath: "), reply
    path = reply[len("ResourcePath: "):]
    parts = path.split(" > ")
    assert len(parts) >= 2, f"the library and the name at least: {path}"
    assert parts[-1] == name, f"the path ends with the name of the resource: {path}"
    assert parts[0] == "example", f"and starts with the library: {path}"


def test_the_path_of_a_resource_that_is_not_there_is_refused(editor):
    assert "no open library has that resource" in editor.cmd(f"ResourcePath -Asset {NOT_A_RESOURCE}")
    assert "required option" in editor.cmd("ResourcePath")
