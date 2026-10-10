"""The way back to Visual Studio: the button at the right of the transport (Play, Step, Pause, Stop) and the OpenInVisualStudio command it shares its code with.

Pressing the button brings forward the Visual Studio that has the game project of the Level open, or starts one on it, so the tests use -DryRun, which says which of the two it would do and for which
solution, and touches nothing.
"""
import os
import pytest
import re

SOLUTION = r"Cache[\\/]Script[\\/]([0-9A-F]+)[\\/]Build[\\/]Script\.sln"


def dry_run(level) -> str:
    return level.ed.cmd("OpenInVisualStudio -DryRun true")


@pytest.mark.skipif(os.name != "nt", reason="the Visual Studio solution of the game project: Windows only")
def test_a_level_with_a_game_would_open_the_solution_of_its_game_project(game_level):
    reply = dry_run(game_level)
    assert re.fullmatch(rf"OpenInVisualStudio: would (open|bring forward the Visual Studio that has) .*{SOLUTION}( open \(process \d+\))?", reply), reply


@pytest.mark.skipif(os.name != "nt", reason="the Visual Studio solution of the game project: Windows only")
def test_the_solution_is_the_one_of_the_game_the_level_names(game_level):
    game = re.search(SOLUTION, dry_run(game_level))[1]
    named = re.search(r"^Game=(\w+)", game_level.ed.cmd(f"GetLevelGame -Level {game_level.guid}"), re.M)[1]
    assert int(named[:16], 16) == int(game, 16), (named, game)          # the Game is its instance guid followed by its type
