"""Where a component or a system comes from, shown where the person looks (the module tag of a component header, the hints of the Add Component list and of the System Registry) and opened on demand.

The panels draw it from one source (xscene::type_source, filled from the registrations of the loaded Game.dll); OpenTypeSource is the command behind a click on the tag and on "Open ..." of the System
Registry's menu, so it is what these tests (and the AI) use instead of the mouse.
"""
import re

from harness import quote

SOCCER_BALL = "0DC3BCDAB39C3CCF"                                                # the component
SOCCER_BALL_SYSTEM = "05254FF4D7D9A03A"                                         # the system "Soccer Ball"
TRANSFORM = "663773C47FA1D0BA"                                                  # the engine's own
MODULE_NAME = "SoccerGame"


def test_a_component_can_be_shown_in_the_file_it_is_defined_in(editor):
    reply = editor.cmd(f"OpenTypeSource -Guid {SOCCER_BALL}")
    assert reply.startswith("OpenTypeSource: ok"), reply
    assert f"Module={MODULE_NAME}" in reply and "File=soccer_components.h" in reply and "source_db" in reply, "the module, and the file from its source_db"
    assert MODULE_NAME in {s.name for s in editor.sessions()}, "the module's editor is open"
    files = editor.cmd(f"{MODULE_NAME}\\ListOpenFiles")
    assert "soccer_components.h" in files, "and its viewer shows the file"


def test_a_system_can_be_shown_in_the_file_it_is_defined_in(editor):
    reply = editor.cmd(f"OpenTypeSource -Guid {SOCCER_BALL_SYSTEM} -System true")
    assert reply.startswith("OpenTypeSource: ok") and "File=soccer_ball_system.h" in reply, reply
    assert "soccer_ball_system.h" in editor.cmd(f"{MODULE_NAME}\\ListOpenFiles")


def test_an_engine_component_has_no_module_to_open(editor):
    reply = editor.cmd(f"OpenTypeSource -Guid {TRANSFORM}")
    assert "built in" in reply and "no module defines it" in reply, reply


def test_a_bad_guid_is_refused(editor):
    assert "required option" in editor.cmd("OpenTypeSource")
