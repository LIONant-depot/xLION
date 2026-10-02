"""The Logs, phase P0 (documentation/Editors/DESIGN_logs.md): events, problems, operations, the ingestion barrier and the pipe commands.

The build adapter is exercised with real MSVC/MSBuild output (LogSimulateBuild runs it through the same ring, adapter and store as a real
Game.dll build), so the tests are fast and deterministic; one slow test checks the real build too.
"""
import base64
import os
import re
import secrets

import pytest

from harness import REPO


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def tail(reply: str) -> tuple[dict, list[dict]]:
    """(header values, rows): the 'key=value' lines before the blank line, then a header row and tab-separated rows."""
    head, _, body = reply.partition("\n\n")
    values = dict(re.findall(r"(\w+)=(\S+)", head))
    lines = [l for l in body.splitlines() if l]
    if not lines:
        return values, []
    names = lines[0].split("\t")
    return values, [dict(zip(names, l.split("\t"))) for l in lines[1:]]


def run(editor, command: str) -> str:
    reply = editor.cmd(command)
    assert not reply.startswith(("Unable", "Malformed")), reply
    return reply


# What Game.dll's build prints, taken from the shapes MSBuild/cl/link really produce: diagnostics with the project suffix, the "(compiling source file ...)"
# line and notes belonging to a diagnostic, translation units named as they compile, and linker errors.
def build_output(token: str) -> str:
    h = f"D:\\proj\\{token}_player.h"
    proj = "D:\\proj\\Game.vcxproj"
    return "\n".join([
        "MSBuild version 17.14.51+25f168cee for .NET Framework",
        "",
        "  cmake_pch.cxx",
        "  soccer_game.cpp",
        f"{h}(80,17): error C2065: 'Kick': undeclared identifier [{proj}]",
        "  (compiling source file 'D:\\proj\\soccer_game.cpp')",
        f"{h}(80,17): note: see declaration of 'Soccer::player'",
        f"{h}(91,9): error C2039: 'Fire': is not a member of 'Soccer::ball' [{proj}]",
        "  (compiling source file 'D:\\proj\\soccer_game.cpp')",
        "  xscript_game_entry.cpp",
        f"Game.obj : error LNK2019: unresolved external symbol \"void __cdecl Missing{token}(void)\" (?Missing@@YAXXZ) referenced in function main [{proj}]",
        f"D:\\proj\\Debug\\Game.dll : fatal error LNK1120: 1 unresolved externals [{proj}]",
        f"  {token}.vcxproj -> D:\\proj\\Debug\\{token}.dll",
        "Build FAILED.",
    ])


def simulate(editor, text: str, exit_code: int) -> int:
    reply = run(editor, f"LogSimulateBuild -Text {b64(text)} -Exit {exit_code}")
    m = re.search(r"operation (\d+)", reply)
    assert m, reply
    return int(m[1])


# ---- the shape of the answers ------------------------------------------------------------------------------------------

def test_status_reports_the_collector(editor):
    reply = run(editor, "LogStatus")
    assert reply.startswith("LogStatus: ok")
    values, _ = tail(reply)
    for key in ("Session", "CommittedThrough", "Backlog", "Capacity", "Dropped", "Expired", "PendingWrite", "PersistenceFailed"):
        assert key in values, f"{key} missing from {reply!r}"
    assert re.fullmatch(r"[0-9A-F]{16}", values["Session"]), "a session id is random, 64 bits, in hex"
    assert values["Backlog"] == "0", "a query drains the ring first"


def test_an_invalid_query_explains_itself(editor):
    assert "invalid query" in run(editor, 'LogEvents -Query "sev>=banana"')
    assert "invalid query" in run(editor, 'LogProblems -Query "channel:"')
    assert "invalid query" in run(editor, 'LogEvents -Query "op:abc"')


# ---- a failed build, from real compiler output ---------------------------------------------------------------------------

def test_a_failed_build_is_an_operation_with_its_problems(editor):
    token = secrets.token_hex(3)
    op = simulate(editor, build_output(token), 1)

    values, rows = tail(run(editor, f"LogOperations -Id {op}"))
    assert len(rows) == 1
    row = rows[0]
    assert row["Kind"] == "game.build" and row["Outcome"] == "Failed"
    assert row["EvidenceReady"] == "true", "the readers are done: every record of it is committed"
    assert row["Errors"] == "4" and row["Problems"] == "4"
    assert row["Units"] == "3", "the translation units MSBuild named are what a successful incremental build would have checked"
    assert row["Coverage"] == "Selected"

    _, problems = tail(run(editor, f"LogProblems -Operation {op}"))
    assert sorted(p["Code"] for p in problems) == ["C2039", "C2065", "LNK1120", "LNK2019"]
    c2065 = next(p for p in problems if p["Code"] == "C2065")
    assert c2065["Site"].endswith(f"{token}_player.h:80") and c2065["Unit"] == "soccer_game.cpp"
    assert c2065["Heuristic"] == "false" and c2065["Severity"] == "error" and c2065["Occurrences"] == "1"
    assert "undeclared identifier" in c2065["Title"] and "Game.vcxproj" not in c2065["Title"], "the project suffix is attribute, not title"


def test_a_diagnostic_and_the_lines_that_belong_to_it_are_one_event(editor):
    token = secrets.token_hex(3)
    simulate(editor, build_output(token), 1)

    _, events = tail(run(editor, f'LogEvents -Query "code:C2065 {token}_player"'))
    assert len(events) == 1
    event = events[0]
    assert int(event["Lines"]) >= 2, "the 'compiling source file' line and the note are its body, not separate rows"

    detail = run(editor, f"LogEvent -Id {event['Seq']}")
    body = [l for l in detail.splitlines() if l.startswith("| ")]
    assert any("compiling source file" in l for l in body)
    assert any("see declaration of 'Soccer::player'" in l for l in body)
    assert f"Lines={event['Lines']}" in detail
    assert "Discriminator=Kick" in detail and "Attr.unit=soccer_game.cpp" in detail
    # MSBuild's own "Game.vcxproj -> Game.dll" line is not part of the last diagnostic
    assert not any("->" in l for l in body)


def test_search_matches_the_body_as_well_as_the_title(editor):
    token = secrets.token_hex(3)
    simulate(editor, build_output(token), 1)
    def query(text: str) -> list:
        return tail(run(editor, f"LogEvents -Query64 {b64(text)}"))[1]       # base64: a phrase in quotes cannot go through the command line itself
    assert len(query(f'body:"see declaration" code:C2065 {token}_player')) == 1
    assert len(query(f'"see declaration" code:C2065 {token}_player')) == 1, "a plain search looks in the body too"
    assert query(f'body:undeclared code:C2065 {token}_player') == [], "a word that is only in the title is not in the body"


def test_two_errors_on_one_line_are_two_problems(editor):
    token = secrets.token_hex(3)
    f = f"D:\\proj\\{token}_x.h"
    text = "\n".join([
        f"{f}(5,1): error C2065: 'Alpha': undeclared identifier",
        f"{f}(5,9): error C2065: 'Beta': undeclared identifier",
    ])
    op = simulate(editor, text, 1)
    _, problems = tail(run(editor, f"LogProblems -Operation {op}"))
    assert len(problems) == 2, "the offending identifier is part of the identity"
    assert len({p["Id"] for p in problems}) == 2


def test_the_same_problem_in_a_second_build_is_the_same_problem(editor):
    token = secrets.token_hex(3)
    first = simulate(editor, build_output(token), 1)
    second = simulate(editor, build_output(token), 1)
    _, a = tail(run(editor, f"LogProblems -Operation {first}"))
    _, b = tail(run(editor, f"LogProblems -Operation {second}"))
    assert {p["Id"] for p in a} == {p["Id"] for p in b}, "identity does not include the operation, the session or the time"
    assert all(int(p["Occurrences"]) >= 2 for p in b), "one occurrence per build at least (a linker message without a name is shared by other tests' builds)"
    mine = next(p for p in b if p["Code"] == "C2065")
    assert mine["Occurrences"] == "2", "this token's own problem was seen once in each build"


def test_a_build_that_fails_without_a_diagnostic_is_still_a_problem(editor):
    token = secrets.token_hex(3)
    op = simulate(editor, f"something went wrong {token}\nBuild FAILED.", 1)
    _, problems = tail(run(editor, f"LogProblems -Operation {op}"))
    assert [p["Code"] for p in problems] == ["OPERATION.FAILED_WITHOUT_DIAGNOSTICS"]
    assert "failed without diagnostic details" in problems[0]["Title"]


def test_a_successful_build_reports_success_and_its_warnings(editor):
    token = secrets.token_hex(3)
    op = simulate(editor, f"  soccer_game.cpp\nD:\\proj\\{token}_w.h(3,1): warning C4129: 'S': unrecognized character escape sequence\nBuild succeeded.", 0)
    _, rows = tail(run(editor, f"LogOperations -Id {op}"))
    assert rows[0]["Outcome"] == "Succeeded" and rows[0]["Warnings"] == "1" and rows[0]["Errors"] == "0"
    _, problems = tail(run(editor, f"LogProblems -Operation {op}"))
    assert [p["Severity"] for p in problems] == ["warning"], "a successful build can still have problems: success is a fact, not a verification"


# ---- the ingestion barrier, events and problems -------------------------------------------------------------------------

def test_a_query_sees_everything_pushed_before_it(editor):
    channel = f"test.barrier.{secrets.token_hex(3)}"
    run(editor, f"LogEmit -Text {b64('x')} -Channel {channel} -Count 2000")
    values, _ = tail(run(editor, f'LogEvents -Query "channel:{channel}" -Limit 1'))
    assert values["Matched"] == "2000", "the ring is drained before the answer is built"


def test_pages_do_not_skip_or_repeat_while_events_arrive(editor):
    channel = f"test.pages.{secrets.token_hex(3)}"
    run(editor, f"LogEmit -Text {b64('a')} -Channel {channel} -Count 30")
    values, first = tail(run(editor, f'LogEvents -Query "channel:{channel}" -Limit 12'))
    assert len(first) == 12 and values["Truncated"] == "true"
    cursor = values["Cursor"]
    run(editor, f"LogEmit -Text {b64('later')} -Channel {channel} -Count 5")          # arrives between the pages
    seen = [r["Seq"] for r in first]
    while True:
        values, rows = tail(run(editor, f'LogEvents -Query "channel:{channel}" -Limit 12 -After {cursor}'))
        seen += [r["Seq"] for r in rows]
        if values.get("Truncated") != "true":
            break
        cursor = values["Cursor"]
    assert len(seen) == 30 and len(set(seen)) == 30, "the pages belong to the snapshot of the first one: no repeats, no skips, nothing newer"


def test_a_repeated_diagnostic_is_one_problem_with_a_count(editor):
    code = f"TEST.REPEAT.{secrets.token_hex(3).upper()}"
    run(editor, f"LogEmit -Text {b64('the same failure')} -Severity error -Kind diagnostic -Code {code} -Count 1000")
    values, problems = tail(run(editor, f"LogProblems -Query code:{code}"))
    assert len(problems) == 1 and problems[0]["Occurrences"] == "1000" and values["Occurrences"] == "1000"
    detail = run(editor, f"LogProblem -Id {problems[0]['Id']}")
    assert "Evidence=summarized" in detail and "Observed=1000" in detail and "Retained=6" in detail, "bounded retention is reported, not hidden"
    assert "Triage=Unreviewed" in detail and "Verification=Unverified" in detail


def test_a_log_event_is_not_a_problem(editor):
    code = f"TEST.LOGONLY.{secrets.token_hex(3).upper()}"
    run(editor, f"LogEmit -Text {b64('just saying')} -Severity error -Kind log -Code {code}")
    _, problems = tail(run(editor, f"LogProblems -Query code:{code}"))
    assert problems == [], "only diagnostics become problems"
    _, events = tail(run(editor, f"LogEvents -Query code:{code}"))
    assert len(events) == 1


def test_a_multi_line_event_keeps_its_lines_and_is_one_row(editor):
    channel = f"test.lines.{secrets.token_hex(3)}"
    text = "first line is the title\n  second line, indented\nthird line"
    run(editor, f"LogEmit -Text {b64(text)} -Channel {channel}")
    _, events = tail(run(editor, f'LogEvents -Query "channel:{channel}"'))
    assert len(events) == 1 and events[0]["Title"] == "first line is the title" and events[0]["Lines"] == "2"
    detail = run(editor, f"LogEvent -Id {events[0]['Seq']}")
    assert "|   second line, indented" in detail and "| third line" in detail, "the indentation of the second line is kept, the lines are not re-wrapped"


def test_a_huge_body_is_cut_at_the_cap_and_says_so(editor):
    channel = f"test.cap.{secrets.token_hex(3)}"
    body = "\n".join(f"line {i:05d} " + "x" * 20 for i in range(4000))              # ~120 KB
    run(editor, f"LogEmit -Text {b64('big' + chr(10) + body)} -Channel {channel}")
    _, events = tail(run(editor, f'LogEvents -Query "channel:{channel}"'))
    detail = run(editor, f"LogEvent -Id {events[0]['Seq']}")
    assert "Summarized=true" in detail
    assert len(detail) <= 32 * 1024, "a reply stays within its budget"
    # the body is given in pages: follow NextOffset until the reply says it is complete, and every line arrives exactly once
    lines = int(re.search(r"Lines=(\d+)", detail)[1])
    got = [l for l in detail.splitlines() if l.startswith("| ")]
    while "Truncated=true" in detail:
        offset = int(re.search(r"NextOffset=(\d+)", detail)[1])
        detail = run(editor, f"LogEvent -Id {events[0]['Seq']} -Offset {offset}")
        assert len(detail) <= 32 * 1024
        got += [l for l in detail.splitlines() if l.startswith("| ")]
    assert len(got) == lines, f"{len(got)} body lines in the pages, the event has {lines}"
    assert re.fullmatch(r"\| \.\.\. \d+ more lines not kept", got[-1]), "the cut says how much was not kept (it is the last line of the last page)"


# ---- who produces events ---------------------------------------------------------------------------------------------------

def test_commands_are_events_but_the_logs_own_commands_are_not(editor):
    run(editor, "GetPlayState")
    _, mine = tail(run(editor, 'LogEvents -Query "channel:editor.command GetPlayState"'))
    assert mine, "a command run through the host is an event of kind command"
    _, own = tail(run(editor, 'LogEvents -Query "channel:editor.command LogStatus"'))
    assert own == [], "asking about the log must not fill it"


def test_notify_error_is_an_event_and_a_problem(level):
    token = secrets.token_hex(3)
    assert "raised" in level.cmd(f"RaiseError -Message failed_{token}_with_value_42")      # RaiseError takes one word: underscores for spaces
    _, events = tail(level.ed.cmd(f'LogEvents -Query "channel:editor.ui failed_{token}"'))
    assert len(events) == 1 and events[0]["Severity"] == "error"
    _, problems = tail(level.ed.cmd('LogProblems -Query "channel:editor.ui"'))
    assert problems and all(p["Heuristic"] == "true" for p in problems), "text without a code groups by its template: labelled heuristic"


# ---- the real build ----------------------------------------------------------------------------------------------------------

GAME_SOURCE = REPO / "plugins" / "xscript_module.plugin" / "source" / "Runtime" / "xscript_game_entry.cpp"


def test_a_real_game_build_is_an_operation_with_an_outcome(editor, level):
    if "the project has no script modules" in editor.log_text():
        pytest.skip("the example project has no script modules, so there is no Game.dll to build")
    os.utime(GAME_SOURCE)                                  # looks edited: the module is stale, the next Play builds it
    assert editor.cmd("Play").startswith("Play requested")
    editor.wait_play_state("Playing", timeout=240)         # includes the build

    _, rows = tail(run(editor, "LogOperations -Kind game.build -Limit 1"))
    assert rows, "the build left an operation behind"
    row = rows[0]
    assert row["Outcome"] == "Succeeded" and row["EvidenceReady"] == "true"
    assert int(row["Units"]) >= 1, "an incremental build lists the units it compiled"
    assert row["Coverage"] in ("Selected", "Complete")
    assert "LastBuild:" in run(editor, "LogStatus")
    _, status = tail(run(editor, 'LogEvents -Query "channel:game.module rebuild"'))
    assert any("rebuild succeeded" in e["Title"] for e in status)

    assert editor.cmd("Stop") == "Stop requested"
    editor.wait_play_state("Stopped")


# ---- headless parity -----------------------------------------------------------------------------------------------------------

def test_the_headless_host_answers_the_log_commands_too(editor):
    """The Logs live in the host, not in the UI: with no window the same store, ring and commands work (the host loop drains)."""
    from pathlib import Path
    from harness import DEFAULT_EXE, Editor

    exe = DEFAULT_EXE.with_name("xLION_Headless.exe")
    if not exe.is_file():
        pytest.skip("xLION_Headless.exe is not built")
    editor.stop()                                          # one process owns the pipe; the next test restarts the editor
    headless = Editor(exe, log_dir=Path(__file__).parent / ".logs" / "headless")
    headless.start()
    try:
        token = secrets.token_hex(3)
        op = simulate(headless, build_output(token), 1)
        _, rows = tail(run(headless, f"LogOperations -Id {op}"))
        assert rows[0]["Outcome"] == "Failed" and rows[0]["EvidenceReady"] == "true" and rows[0]["Errors"] == "4"
        _, problems = tail(run(headless, f"LogProblems -Operation {op}"))
        assert sorted(p["Code"] for p in problems) == ["C2039", "C2065", "LNK1120", "LNK2019"]
        values, _ = tail(run(headless, "LogStatus"))
        assert values["Backlog"] == "0"
        run(headless, f"LogEmit -Text {b64('headless note')} -Channel test.headless -Count 3")
        values, events = tail(run(headless, 'LogEvents -Query "channel:test.headless"'))
        assert values["Matched"] == "3"
    finally:
        headless.stop()
        editor.ensure_running()                            # the GUI editor the other tests share, back before this test ends
