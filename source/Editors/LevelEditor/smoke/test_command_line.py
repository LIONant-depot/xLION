"""The command line of the editor: what a person types, what a script sends and what xeditorcli forwards must mean the same thing.

One set of rules, the Windows command line rules: words are separated by spaces and tabs; "quotes" keep spaces, tabs and line breaks; a backslash only matters in front of a
quote (\\" is a quote inside a value, "" is an empty value); everything else is literal, so a path needs no care. These tests use real commands of the Logs (LogViewSave and
LogViews keep a name and a query: a value that comes back as it went in proves the line was not damaged on the way).
"""
import re
import subprocess

import pytest

from harness import DEFAULT_EXE, quote, sibling


def views(editor) -> dict:
    reply = editor.cmd("LogViews")
    rows = [l.split("\t") for l in reply.split("\n\n", 1)[1].splitlines()[1:]]
    return {r[0]: r[5] for r in rows}


@pytest.fixture
def clean_views(editor):
    before = set(views(editor))
    yield
    for name in set(views(editor)) - before:
        editor.cmd(f"LogViewDelete -Name {quote(name)}")


def test_a_quoted_value_keeps_its_spaces_exactly(editor, clean_views):
    editor.cmd('LogViewSave -Name "two  spaces here" -Query "channel:a.b"')
    assert views(editor)["two  spaces here"] == "channel:a.b", "two spaces inside quotes were collapsed or lost"


def test_a_quoted_value_is_never_a_flag(editor, clean_views):
    editor.cmd('LogViewSave -Name "-Query" -Query "sev>=error"')
    assert views(editor)["-Query"] == "sev>=error", "a value that looks like a flag is a value when it is quoted"


def test_quotes_inside_a_value_are_escaped_with_a_backslash(editor, clean_views):
    editor.cmd(r'LogViewSave -Name phrase -Query "body:\"two words\" sev>=warning"')
    assert views(editor)["phrase"] == 'body:"two words" sev>=warning'
    editor.cmd('LogViewSave -Name doubled -Query "body:""x y"""')
    assert views(editor)["doubled"] == 'body:"x y"', 'inside quotes "" is a quote'


def test_a_backslash_in_a_value_is_not_a_session(editor):
    reply = editor.cmd(r'LogAttach -Path "C:\no\such dir\file.bin" -Event 1')
    assert "No open session" not in reply and "does not exist" in reply, reply


def test_a_session_prefix_is_only_the_first_word(editor):
    assert "No open session" in editor.cmd("NoSuchSession\\LogViews")
    assert "LogViews: ok" in editor.cmd("Host\\LogViews")


def test_the_cli_sends_the_raw_command_line_not_the_argv(editor, clean_views):
    cli = sibling("xeditorcli")
    if not cli.is_file():
        pytest.skip("xeditorcli.exe is not built")
    # list2cmdline (what subprocess does on Windows) quotes each argument by the same rules: the editor must see the very value that was given
    name, query = r"my  view \ here", r'body:"a b" channel:c:\x' + "\\"
    out = subprocess.run([str(cli), "LogViewSave", "-Name", name, "-Query", query], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert views(editor)[name] == query
    raw = subprocess.run(f'"{cli}" LogViewSave -Name "raw  line" -Query "channel:raw.line"', capture_output=True, text=True, timeout=30)
    assert raw.returncode == 0 and views(editor)["raw  line"] == "channel:raw.line", "a line typed in a shell arrives untouched"
    help_text = subprocess.run([str(cli)], capture_output=True, text=True, timeout=30)
    assert help_text.returncode == 1 and "Usage" in help_text.stderr
