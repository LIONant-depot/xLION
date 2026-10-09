"""Ctrl, Shift and Alt must get from the window's messages, through xGPU's keyboard, to ImGui (the keyboard window and every shortcut read them).

Alt is the odd one: Windows delivers it, and every key pressed while it is held, as WM_SYSKEYDOWN / WM_SYSKEYUP. xGPU used to look at WM_KEYDOWN / WM_KEYUP
only, so Alt did nothing in the editor.
"""
import pytest

pytestmark = pytest.mark.needs_window          # needs a window: skipped for a headless editor (see conftest.py)

VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12


def _state(level) -> dict:
    return dict(line.split("=") for line in level.cmd("InputState").splitlines())


def test_no_modifier_is_held_when_nothing_is_pressed(level):
    assert _state(level) == {"Ctrl": "false", "Shift": "false", "Alt": "false"}


@pytest.mark.parametrize("name, vk, sys", [("Ctrl", VK_CONTROL, False), ("Shift", VK_SHIFT, False), ("Alt", VK_MENU, True)])
def test_a_modifier_is_seen_while_held_and_gone_after(level, name, vk, sys):
    held = level.ed.post_key(vk, hold=0.3, sys=sys, while_down=lambda: _state(level))
    assert held[name] == "true", f"{name} was held and the UI did not see it"
    assert [v for k, v in held.items() if k != name] == ["false", "false"], "only the key that was pressed may read as held"
    assert _state(level)[name] == "false", f"{name} was released and the UI still sees it down"


def test_alt_pressed_as_a_plain_key_message_is_seen_too(level):
    """Some input paths (remote desktop, injected input) post Alt as a plain key message: it must work as well."""
    held = level.ed.post_key(VK_MENU, hold=0.3, sys=False, while_down=lambda: _state(level))
    assert held["Alt"] == "true"
    assert _state(level)["Alt"] == "false"
