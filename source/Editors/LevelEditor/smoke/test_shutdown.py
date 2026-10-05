"""Closing the editor: what the Inspector holds (the property values of the selected entity) carries type functions that live in the copies of the core and the render module and in the Game.dll
of the Level; they have to be let go of before those are unloaded, or closing the editor with an entity selected crashed (a std::wstring property - the Text of a label - is one).
"""
import time

SCENE = "5B388EFC2203EC6F"
SCORE_BLUE_LABEL = "00007100"            # an entity of the Soccer pitch with a Text component (a std::wstring property)


def test_closing_the_editor_with_a_text_entity_selected_exits_cleanly(game_level):
    editor = game_level.ed
    assert game_level.cmd(f"Select -Scene {SCENE} -Id {SCORE_BLUE_LABEL}") == ""
    time.sleep(2.0)                       # frames: the Inspector is built for it
    try:
        editor.stop(graceful=True)        # the editor is asked to exit, the way a person closing it does
        assert editor.exit_code() == 0, f"the editor exited by itself, cleanly (exit {editor.describe_exit()}){editor.crash_summary()}"
    finally:
        editor.start()                    # the other tests go on with an editor
