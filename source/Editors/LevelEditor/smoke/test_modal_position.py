"""A modal window (the error popup, a question, anything that needs the user's attention) opens in the middle of the editor it belongs to.

xeditor::BeginModal is the one way the editors open a modal. The error popup remembers, when the error is raised, the editor that had the focus;
ImGui's own default would be the middle of the whole application window, which is not the middle of an editor that only fills part of it.
"""
import re
import time

import pytest

VK_RETURN = 0x0D
TOLERANCE = 3.0         # pixels


def _state(level) -> dict:
    reply = level.cmd("ModalState")
    out = {"Open": re.search(r"Open=(\w+)", reply)[1] == "true"}
    for key in ("PopupCenter", "Anchor", "EditorCenter", "ViewportCenter"):
        x, y = re.search(rf"{key}=(-?\d+),(-?\d+)", reply).groups()
        out[key] = (float(x), float(y))
    return out


def _near(a, b) -> bool:
    return abs(a[0] - b[0]) <= TOLERANCE and abs(a[1] - b[1]) <= TOLERANCE


def _dismiss(level) -> None:
    """The popup closes on Enter; never leave one open, it would block every test after."""
    for _ in range(5):
        if not _state(level)["Open"]:
            return
        level.ed.post_key(VK_RETURN, hold=0.2)
        time.sleep(0.2)


@pytest.fixture
def raise_error(level):
    """Raises the error popup; whatever the test does, the popup is gone at the end."""
    def raise_(text="a modal that needs attention"):
        assert level.cmd(f"RaiseError -Message {text.replace(' ', '_')}") == "RaiseError: raised"
        time.sleep(0.6)                                     # a few frames: the popup opens and sizes itself
    yield raise_
    _dismiss(level)


def test_no_modal_is_open_at_rest(level):
    assert _state(level)["Open"] is False


def test_the_error_popup_opens_in_the_middle_of_the_level_editor(level, raise_error):
    expected = _state(level)["EditorCenter"]
    raise_error()
    state = _state(level)
    assert state["Open"], "the error popup did not open"
    assert _near(state["Anchor"], expected), f"asked to open at {state['Anchor']}, the editor's middle is {expected}"
    assert _near(state["PopupCenter"], state["Anchor"]), f"opened with its middle at {state['PopupCenter']}, asked for {state['Anchor']}"


def test_the_error_popup_goes_away_on_enter(level, raise_error):
    raise_error()
    assert _state(level)["Open"]
    _dismiss(level)
    assert _state(level)["Open"] is False


def test_a_second_error_opens_in_the_same_place(level, raise_error):
    raise_error("first")
    first = _state(level)["PopupCenter"]
    _dismiss(level)
    raise_error("second")
    assert _near(_state(level)["PopupCenter"], first)


@pytest.mark.parametrize("type_name", ["Texture", "GeomStatic", "Material", "Skeleton", "Font", "AnimPackage"])
def test_the_error_popup_follows_the_editor_that_has_the_focus(editor, level, raise_error, type_name):
    """Opening another editor moves the focus to it; an error raised there opens in the middle of THAT editor."""
    found = editor.find_asset(type_name)
    if found is None:
        pytest.skip(f"the example project has no compiled {type_name} asset to open")
    guid, _ = found
    assert editor.cmd(f"OpenResourceEditor -Asset {guid} -Library {editor.libraries()[0][0]}", timeout=30) == ""
    time.sleep(1.0)
    try:
        expected = _state(level)["EditorCenter"]
        raise_error()
        state = _state(level)
        assert state["Open"], "the error popup did not open"
        assert _near(state["Anchor"], expected), f"asked to open at {state['Anchor']}, the focused editor's middle is {expected}"
        assert _near(state["PopupCenter"], state["Anchor"])
    finally:
        _dismiss(level)
        editor.cmd(f"CloseResourceEditor -Asset {guid}")
