"""Which project the editor opens: the one asked for on the command line (`xLION.exe <project folder>`, `--project <folder>`, or XLION_PROJECT), else the example project of the repository.

Nothing in the startup names the example project but the fallback. A folder that is not a project is refused before anything is created, and says why.
"""
import os
import re
import subprocess
import tempfile
from pathlib import Path

from harness import DEFAULT_EXE, Editor, SMOKE_DIR, sibling
from script_project import PROJECT


def project_of(editor) -> Path:
    return Path(re.search(r"^Project=(.+)$", editor.cmd("GetProject"), re.M)[1].strip())


def test_the_editor_says_which_project_is_open(editor):
    assert project_of(editor).resolve() == PROJECT.resolve(), "without a project asked for, it is the example project of the repository"


def test_a_project_asked_for_on_the_command_line_is_the_one_opened(editor):
    """The example project asked for by its path, in the three ways: it opens exactly like the default."""
    editor.stop()
    try:
        for how, args, env in (("folder", [PROJECT], {}), ("--project", ["--project", PROJECT], {}), ("XLION_PROJECT", [], {"XLION_PROJECT": str(PROJECT)})):
            other = Editor(DEFAULT_EXE, log_dir=SMOKE_DIR / ".logs" / "open_project", args=args, extra_env=env)
            other.start()
            try:
                assert project_of(other).resolve() == PROJECT.resolve(), how
            finally:
                other.stop()
    finally:
        editor.start()


def test_a_folder_that_is_not_a_project_is_refused_with_the_reason(editor):
    """Run without a window and without the error box (the box is for a person: it waits for a click)."""
    env = {**os.environ, "XEDITOR_NO_ASSERT_DIALOG": "1"}
    exe = sibling("xLION_Headless")
    with tempfile.TemporaryDirectory(prefix="xlion_not_a_project_") as folder:
        done = subprocess.run([str(exe), folder], capture_output=True, text=True, timeout=60, cwd=str(exe.parent), env=env)
        assert done.returncode == 1, "it does not start"
        assert "is not a project" in done.stderr and "Library.config.txt" in done.stderr, done.stderr
        assert "is not a folder" in subprocess.run([str(exe), str(Path(folder) / "nowhere")], capture_output=True, text=True, timeout=60, cwd=str(exe.parent), env=env).stderr
