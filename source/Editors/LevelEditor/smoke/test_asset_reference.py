"""The asset reference of the inspectors: one widget (xresource_editor::RenderAssetReference) for every property that names a source file of the project (the file of a texture, the mesh of a
geometry...) - the name of the file over three actions: open it the way the Assets tab does, find it in the Assets tab, and clear it; a file dragged out of the Assets tab sets it.

"Find" is the LocateAsset command here (the button does the same): the Assets tab of the drawer shows the file - its folder is the current one, what would hide it (the search) is cleared, it is the
selection - and the drawer is open on that tab. GetBrowserState says where the tab is (AssetsFolder, AssetsSelected).
"""
import re

ASSETS_TAB = "1"


def state(editor) -> dict:
    reply = editor.cmd("GetBrowserState")
    assert reply.startswith("GetBrowserState: ok"), reply
    return {key: value for key, value in re.findall(r"^(\w+)=(.*)$", reply, re.M)}


def test_finding_a_file_shows_it_in_the_assets_tab_and_opens_the_drawer_on_it(editor):
    editor.cmd("SetBrowserSearch -Text this_matches_no_file_at_all")
    assert editor.cmd("LocateAsset -Path Assets/SheKnewMe.tga") == "LocateAsset: ok"
    now = state(editor)
    assert now["Drawer"] == "open" and now["DrawerTab"] == ASSETS_TAB, "the drawer is open on the Assets tab"
    assert now["Search"] == "", "the search that hid the file is cleared"
    assert now["AssetsSelected"] == "SheKnewMe.tga", "and it is the selection"
    assert now["AssetsFolder"] == "", "its folder (the root of the Assets) is the current one"


def test_finding_a_file_in_a_folder_makes_that_folder_the_current_one(editor):
    assert editor.cmd("LocateAsset -Path Assets\\PuppyDog\\textures\\White-4096x4096.png") == "LocateAsset: ok"
    now = state(editor)
    assert now["AssetsFolder"] == "PuppyDog\\textures"
    assert now["AssetsSelected"] == "White-4096x4096.png"


def test_finding_a_file_that_is_not_there_is_refused(editor):
    assert "no open library has that file" in editor.cmd("LocateAsset -Path Assets/not_a_file_of_this_project.png")
    assert "required option" in editor.cmd("LocateAsset")
