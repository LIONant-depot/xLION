"""Every peer resource editor (Texture, Material, MaterialInstance, GeomStatic, GeomSkin, Skeleton,
Font, AnimPackage - one xeditor::auto_register_resource_editor per plugin, source/Tools/Editor/
xeditor_resource_editor.h) opens without crashing and shows up in the host's session list, the same
way Level does. This is the regression class a Level-ownership-split style refactor can silently
break for editors it never touches directly (e.g. dropping a piece of shared Init() wiring every
loader depends on) - these tests exist to catch exactly that before a human has to notice a broken
editor by hand.
"""
import pytest

# xecs::level::type_guid_v isn't in this list: Level opens automatically at startup (one session,
# never via OpenResourceEditor - see xlevel_session.h's own top comment), not one-per-resource like
# these. Its coverage lives in the other test files (test_scenes_and_levels.py, etc.) via the `level`
# fixture.
RESOURCE_EDITOR_TYPES = [
    "Texture",
    "Material",
    "MaterialInstance",
    "GeomStatic",
    "GeomSkin",
    "Skeleton",
    "Font",
    "AnimPackage",
]


def _open_and_check(editor, type_name: str) -> tuple[str, str]:
    """find_asset() + OpenResourceEditor + confirm it landed in sessions(); returns (guid, name)."""
    found = editor.find_asset(type_name)
    if found is None:
        pytest.skip(f"the example project has no compiled {type_name} asset to open")
    guid, name = found

    reply = editor.cmd(f"OpenResourceEditor -Asset {guid} -Library {editor.libraries()[0][0]}", timeout=30)
    assert reply == "", f"OpenResourceEditor({type_name} {name!r}) -> {reply!r}"

    sessions = {s.name: s for s in editor.sessions()}
    assert name in sessions, f"{type_name} {name!r} opened but isn't in `list` (sessions: {list(sessions)})"
    return guid, name


# The Material and MaterialInstance editors draw with xeditor::mesh_preview, which sometimes crashes the editor inside vkCmdDrawIndexed
# (documentation/Editors/TODO_stability_and_actions.md, item 2). Not strict: a run where it does not crash passes.
KNOWN_MESH_PREVIEW_CRASH = pytest.mark.xfail(reason="mesh_preview crash, TODO_stability_and_actions.md #2", strict=False)


def with_known_issues(types):
    return [pytest.param(t, marks=KNOWN_MESH_PREVIEW_CRASH) if t in ("Material", "MaterialInstance") else t for t in types]


@pytest.mark.parametrize("type_name", with_known_issues(RESOURCE_EDITOR_TYPES))
def test_open_resource_editor(editor, type_name):
    """Opening a real asset of every resource type succeeds and shows up as a session; closing drops it."""
    guid, name = _open_and_check(editor, type_name)

    reply = editor.cmd(f"CloseResourceEditor -Asset {guid}")
    assert reply == "", f"CloseResourceEditor({type_name} {name!r}) -> {reply!r}"
    sessions = {s.name for s in editor.sessions()}
    assert name not in sessions, f"{type_name} {name!r} still listed after CloseResourceEditor"


def test_reopen_same_asset_focuses_not_duplicates(editor):
    """Opening the same resource twice focuses the existing editor instead of creating a second session."""
    found = editor.find_asset("Texture")
    if found is None:
        pytest.skip("the example project has no compiled Texture asset")
    guid, name = found
    library = editor.libraries()[0][0]

    editor.ok(f"OpenResourceEditor -Asset {guid} -Library {library}")
    editor.ok(f"OpenResourceEditor -Asset {guid} -Library {library}")
    matches = [s for s in editor.sessions() if s.name == name]
    assert len(matches) == 1, f"expected exactly one session for {name!r}, got {len(matches)}"

    editor.ok(f"CloseResourceEditor -Asset {guid}")


def test_multiple_resource_editors_coexist(editor):
    """Two different resource editors can be open at the same time without interfering with each other."""
    library = editor.libraries()[0][0]
    tex = editor.find_asset("Texture")
    mat = editor.find_asset("Material")
    if tex is None or mat is None:
        pytest.skip("the example project needs both a Texture and a Material asset")
    tex_guid, tex_name = tex
    mat_guid, mat_name = mat

    editor.ok(f"OpenResourceEditor -Asset {tex_guid} -Library {library}")
    editor.ok(f"OpenResourceEditor -Asset {mat_guid} -Library {library}")
    names = {s.name for s in editor.sessions()}
    assert tex_name in names and mat_name in names

    editor.ok(f"CloseResourceEditor -Asset {tex_guid}")
    editor.ok(f"CloseResourceEditor -Asset {mat_guid}")


def test_close_resource_editor_never_opened_is_refused_not_crashed(editor):
    """CloseResourceEditor on a resource with no open editor is a clean refusal, never a crash."""
    found = editor.find_asset("Texture")
    if found is None:
        pytest.skip("the example project has no compiled Texture asset")
    guid, _ = found
    reply = editor.cmd(f"CloseResourceEditor -Asset {guid}")
    assert reply, "expected a refusal message (no editor was open for that asset), got success"
