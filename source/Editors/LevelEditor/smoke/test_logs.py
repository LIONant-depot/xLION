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


# ---- the person's decisions: acknowledge, mute, "mark seen" ----------------------------------------------------------------------

def emit_problem(editor, token: str, severity: str = "error") -> str:
    """One diagnostic of its own (a problem from warning up); returns its id."""
    run(editor, f"LogEmit -Text {b64('P1 problem ' + token)} -Kind diagnostic -Severity {severity} -Channel test.p1 -Code P1.{token.upper()}")
    _, rows = tail(run(editor, f"LogProblems -Query code:P1.{token.upper()}"))
    assert len(rows) == 1, rows
    return rows[0]["Id"]


def listed(editor, token: str, state: str, extra: str = "") -> list[dict]:
    _, rows = tail(run(editor, f"LogProblems -Query code:P1.{token.upper()} -State {state} {extra}"))
    return rows


def test_acknowledging_a_problem_moves_it_out_of_active_and_back_with_undo(editor):
    token = secrets.token_hex(3)
    pid = emit_problem(editor, token)
    assert [r["Id"] for r in listed(editor, token, "Active")] == [pid]
    run(editor, f"LogAcknowledge -Id {pid}")
    row = tail(run(editor, f"LogProblems -Query code:P1.{token.upper()}"))[1][0]
    assert row["Triage"] == "Acknowledged" and row["Suppression"] == "None"
    assert listed(editor, token, "Active") == [], "an acknowledged problem leaves Active"
    assert [r["Id"] for r in listed(editor, token, "All")] == [pid], "...and stays in All: acknowledging does not hide anything"
    assert "Triage=Acknowledged" in run(editor, f"LogProblem -Id {pid}")
    editor.cmd("Undo")
    assert [r["Id"] for r in listed(editor, token, "Active")] == [pid], "Undo gives the problem back"
    assert "Triage=Unreviewed" in run(editor, f"LogProblem -Id {pid}")
    editor.cmd("Redo")
    assert listed(editor, token, "Active") == []


def test_a_muted_problem_is_hidden_but_still_collected_and_countable(editor):
    token = secrets.token_hex(3)
    pid = emit_problem(editor, token, "warning")
    run(editor, f"LogEmit -Text {b64('P1 problem ' + token)} -Kind diagnostic -Severity warning -Channel test.p1 -Code P1.{token.upper()}")
    editor.cmd(f"LogMute -Id {pid}")
    assert listed(editor, token, "All") == [], "muted: not listed"
    assert listed(editor, token, "Active") == []
    shown = listed(editor, token, "All", "-IncludeMuted true")
    assert [r["Id"] for r in shown] == [pid] and shown[0]["Suppression"] == "Muted"
    assert shown[0]["Occurrences"] == "2", "collection continues while it is muted"
    run(editor, f"LogEmit -Text {b64('P1 problem ' + token)} -Kind diagnostic -Severity warning -Channel test.p1 -Code P1.{token.upper()}")
    assert listed(editor, token, "All", "-IncludeMuted true")[0]["Occurrences"] == "3"
    editor.cmd("Undo")                                     # the last thing the person decided was the mute
    assert [r["Id"] for r in listed(editor, token, "All")] == [pid]


def test_a_fatal_problem_cannot_be_hidden(editor):
    token = secrets.token_hex(3)
    pid = emit_problem(editor, token, "fatal")
    reply = editor.cmd(f"LogMute -Id {pid}")
    assert "cannot be hidden" in reply, reply
    assert [r["Id"] for r in listed(editor, token, "All")] == [pid]


def test_marking_seen_moves_the_baseline_the_new_preset_counts_from(editor):
    old, new = secrets.token_hex(3), secrets.token_hex(3)
    emit_problem(editor, old)
    assert len(listed(editor, old, "New")) == 1, "everything is New until the person says otherwise"
    editor.cmd("LogMark -Kind baseline")
    assert listed(editor, old, "New") == [], "marked seen"
    assert len(listed(editor, old, "All")) == 1
    emit_problem(editor, new)
    assert len(listed(editor, new, "New")) == 1, "a problem first seen after the baseline is New"
    editor.cmd("Undo")                                     # the baseline goes back
    assert len(listed(editor, old, "New")) == 1


def test_the_decision_commands_name_what_is_wrong(editor):
    assert "no problem" in editor.cmd("LogAcknowledge -Id 00000000DEADBEEF")
    assert "no problem" in editor.cmd("LogMute -Id 00000000DEADBEEF")
    assert "must be baseline" in editor.cmd("LogMark -Kind nonsense")
    assert "unknown state" in run(editor, "LogProblems -State Nonsense")


# ---- resource compiles: the pipeline adapter and the Feedback view's source ---------------------------------------------------------

def compile_output(token: str, error: str = "Unsupported texture format 'exr'") -> str:
    """What xresource_pipeline's compilers print: [Info]/[Warning]/[Error] lines, progress bars, separators, untagged continuation lines."""
    return "\n".join([
        f"\"D:\\tools\\{token}_compiler.exe\" -PROJECT \"D:\\proj\" -DESCRIPTOR \"Descriptors\\Texture\\{token}.desc\"",
        "==============================",
        "------------------------------------------------------------------",
        " Start Compilation",
        "------------------------------------------------------------------",
        "[Info] OUTPUT: D:\\proj\\Cache",
        "[Info] Processing : [=======>                            ]  20%",
        f"[Warning] Input Texture [{token}.png] is large",
        f"[Error] {error} {token}",
        "  supported: png, dds",
        "  see the compiler's documentation",
        "[Info] Compression: [===================================>] 100%",
    ])


def simulate_compile(editor, text: str, asset: int, exit_code: int, name: str = "Face") -> int:
    reply = run(editor, f"LogSimulateCompile -Text {b64(text)} -Asset {asset} -Exit {exit_code} -Name {name}")
    m = re.search(r"operation (\d+)", reply)
    assert m, reply
    return int(m[1])


def test_a_resource_compile_is_an_operation_about_its_asset(editor):
    token = secrets.token_hex(3)
    asset = int(token, 16) + 1
    op = simulate_compile(editor, compile_output(token), asset, 1)
    _, ops = tail(run(editor, f"LogOperations -Id {op}"))
    row = ops[0]
    assert row["Kind"] == "asset.compile" and row["Outcome"] == "Failed" and row["EvidenceReady"] == "true"
    assert row["Subject"] == "Face" and row["Errors"] == "1" and row["Warnings"] == "1"
    _, problems = tail(run(editor, f"LogProblems -Operation {op}"))
    by_severity = sorted((p["Severity"], p["Heuristic"]) for p in problems)
    assert by_severity == [("error", "true"), ("warning", "true")], "the pipeline gives no codes: both are labelled heuristic"
    error = next(p for p in problems if p["Severity"] == "error")
    assert error["Title"].startswith("Unsupported texture format"), error


def test_the_lines_under_a_pipeline_error_are_its_body_and_progress_is_not_a_problem(editor):
    token = secrets.token_hex(3)
    op = simulate_compile(editor, compile_output(token), int(token, 16) + 2, 1)
    _, events = tail(run(editor, f'LogEvents -Operation {op} -Query "unsupported"'))
    assert len(events) == 1 and events[0]["Lines"] == "2", events
    reply = run(editor, f"LogEvent -Id {events[0]['Seq']}")
    assert "|   supported: png, dds" in reply and "|   see the compiler's documentation" in reply, "the body keeps its lines as the compiler printed them, indentation included"
    assert events[0]["Channel"] == "asset.compile.texture"
    _, progress = tail(run(editor, f'LogEvents -Operation {op} -Query "Compression"'))
    assert len(progress) == 1 and progress[0]["Severity"] == "debug", "a progress bar is one debug event, never a problem"
    _, problems = tail(run(editor, f"LogProblems -Operation {op}"))
    assert not any("Compression" in p["Title"] or "Processing" in p["Title"] for p in problems)


def test_the_same_compile_error_is_one_problem_per_asset(editor):
    token = secrets.token_hex(3)
    a, b = int(token, 16) + 3, int(token, 16) + 4
    # the numbers in the text are not part of the identity; the asset is
    first = simulate_compile(editor, f"[Error] Mip count 13 is out of range {token}", a, 1, "A")
    second = simulate_compile(editor, f"[Error] Mip count 14 is out of range {token}", a, 1, "A")
    other = simulate_compile(editor, f"[Error] Mip count 13 is out of range {token}", b, 1, "B")
    _, p1 = tail(run(editor, f"LogProblems -Operation {first}"))
    _, p2 = tail(run(editor, f"LogProblems -Operation {second}"))
    _, p3 = tail(run(editor, f"LogProblems -Operation {other}"))
    assert p1[0]["Id"] == p2[0]["Id"] and p2[0]["Occurrences"] == "2", "the same asset failing the same way is one problem seen twice"
    assert p3[0]["Id"] != p1[0]["Id"], "another asset failing the same way is another problem"


def test_a_compile_that_fails_without_an_error_line_is_still_a_problem(editor):
    token = secrets.token_hex(3)
    op = simulate_compile(editor, f"[Info] starting {token}\n[Info] the compiler stopped", int(token, 16) + 5, 1, "Silent")
    _, problems = tail(run(editor, f"LogProblems -Operation {op}"))
    assert [p["Code"] for p in problems] == ["OPERATION.FAILED_WITHOUT_DIAGNOSTICS"]


def test_a_successful_compile_with_warnings_succeeds_with_its_warnings(editor):
    token = secrets.token_hex(3)
    op = simulate_compile(editor, f"[Info] ok\n[Warning] Texture {token} is large\n[COMPILATION_SUCCESS]", int(token, 16) + 6, 0, "Fine")
    _, ops = tail(run(editor, f"LogOperations -Id {op}"))
    assert ops[0]["Outcome"] == "Succeeded" and ops[0]["Warnings"] == "1" and ops[0]["Errors"] == "0"
    _, events = tail(run(editor, f"LogEvents -Operation {op}"))
    assert not any("COMPILATION_SUCCESS" in e["Title"] for e in events), "the compiler's own end marker is not an event"


def test_compiling_a_texture_in_its_editor_records_the_compile_and_feedback_opens_the_logs_on_it(editor):
    """The real thing, end to end: the library manager's compile notification becomes an asset.compile operation (no editor hook), and the editor's
    Feedback (F6) takes the person to the Logs with that operation as the filter."""
    import time
    found = editor.find_asset("Texture")
    if found is None:
        pytest.skip("the example project has no Texture asset")
    guid, name = found
    editor.cmd(f"OpenResourceEditor -Asset {guid} -Library {editor.libraries()[0][0]}")
    try:
        before = {r["Id"] for r in tail(run(editor, "LogOperations -Kind asset.compile -Limit 200"))[1]}
        mine = []
        # a different value each time so the descriptor really changes and the compiler really runs (the project guard puts the file back afterwards)
        for quality in ("0.51", "0.52"):
            editor.cmd(f"{name}\\SetProperty -Path {b64('Texture/Quality')} -Value {b64(quality)}")
            editor.cmd(f"{name}\\Compile")
            for _ in range(120):
                time.sleep(0.5)
                mine = [r for r in tail(run(editor, "LogOperations -Kind asset.compile -Limit 200"))[1] if r["Id"] not in before and r["Subject"] == name]
                if mine and mine[0]["Outcome"] != "Running":
                    break
            else:
                pytest.fail("the compile did not finish")
            if mine:
                break
        assert mine, "no asset.compile operation was recorded for the compile"
        assert mine[0]["Outcome"] == "Succeeded" and mine[0]["EvidenceReady"] == "true", mine[0]
        _, events = tail(run(editor, f'LogEvents -Operation {mine[0]["Id"]} -Query "channel:asset.compile.texture" -Limit 100'))
        assert any("Start Compilation" in e["Title"] for e in events), "the compiler's own output is the operation's events"
        # Feedback (F6) opens the drawer on the Logs, filtered to this asset's last compile: the whole build situation, in the one place it lives
        before_window = run(editor, "LogWindow")
        editor.cmd("PressKeys -Keys F6")
        time.sleep(0.5)
        window = run(editor, "LogWindow")
        assert "Page=Events" in window and f"Query=op:{mine[0]['Id']}" in window, window
        back = lambda text: text.split("Back=")[1].splitlines()[0]
        assert back(window) != "none" and back(window) != back(before_window), "Feedback left a way back to what the person was doing"
        assert "back" in editor.cmd("LogBack"), "Back returns the window to where it was"
        after = run(editor, "LogWindow")
        assert f"Query=op:{mine[0]['Id']}" not in after, after
        time.sleep(0.5)
        assert editor.alive() and run(editor, "LogStatus").startswith("LogStatus: ok"), "the window draws the filtered view without upsetting the editor"
    finally:
        editor.cmd(f"CloseResourceEditor -Asset {guid}")


def test_back_with_nowhere_to_go_says_so(editor):
    for _ in range(20):                                    # whatever an earlier test left behind
        if "nothing to go back" in editor.cmd("LogBack"):
            break
    assert "nothing to go back" in editor.cmd("LogBack")
    assert "Back=none" in run(editor, "LogWindow")


def window_values(editor) -> dict:
    text = run(editor, "LogWindow")
    return {
        "query": re.search(r"^Query=(.*)$", text, re.M)[1],
        "back": int(re.search(r"BackDepth=(\d+)", text)[1]),
        "forward": int(re.search(r"ForwardDepth=(\d+)", text)[1]),
        "back_at": tuple(float(v) for v in re.search(r"BackAt=(-?\d+),(-?\d+)", text).groups()),
        "forward_at": tuple(float(v) for v in re.search(r"ForwardAt=(-?\d+),(-?\d+)", text).groups()),
        "mouse_at": tuple(float(v) for v in re.search(r"MouseAt=(-?\d+),(-?\d+)", text).groups()),
        "events_open": int(re.search(r"EventsOpen=(\d+)", text)[1]),
        "range": tuple(int(v) for v in re.search(r"SelectedRange=(\d+)\.\.(\d+)", text).groups()),
        "arrow_at": tuple(float(v) for v in re.search(r"EventArrowAt=(-?\d+),(-?\d+)", text).groups()),
        "row_at": tuple(float(v) for v in re.search(r"EventRowAt=(-?\d+),(-?\d+)", text).groups()),
        "stride": float(re.search(r"EventStride=(\d+)", text)[1]),
    }


def forget_the_way_back(editor):
    for _ in range(40):
        if "nothing to go back" in editor.cmd("LogBack"):
            break


def test_back_and_forward_walk_the_views_and_a_new_view_ends_the_way_forward(editor):
    forget_the_way_back(editor)
    start = window_values(editor)                          # earlier tests may have left ways forward behind: depths are relative
    assert run(editor, "LogShow -Query op:1").strip() == "LogShow: shown"
    run(editor, "LogShow -Query op:2")
    assert window_values(editor)["query"] == "op:2" and window_values(editor)["back"] == start["back"] + 2 and window_values(editor)["forward"] == 0

    assert "back" in editor.cmd("LogBack")
    assert window_values(editor)["query"] == "op:1" and window_values(editor)["forward"] == 1
    assert "back" in editor.cmd("LogBack")
    now = window_values(editor)
    assert now["query"] == start["query"] and now["back"] == start["back"] and now["forward"] == 2, "Back twice is where it began, with two ways forward"

    assert "forward" in editor.cmd("LogForward")
    assert window_values(editor)["query"] == "op:1" and window_values(editor)["back"] == start["back"] + 1
    assert "forward" in editor.cmd("LogForward")
    assert window_values(editor)["query"] == "op:2" and window_values(editor)["forward"] == 0
    assert "nothing to go forward" in editor.cmd("LogForward")

    editor.cmd("LogBack")
    run(editor, "LogShow -Query op:3")                     # a new way somewhere: what was ahead of the old one is gone
    assert window_values(editor)["forward"] == 0 and window_values(editor)["query"] == "op:3"
    forget_the_way_back(editor)


def test_clicking_back_and_forward_in_the_window_walks_the_views_and_never_crashes(editor):
    """The Back button was drawn with a tooltip that read the entry its own click had just removed: the third Back crashed the editor. This clicks the real
    buttons with the real pointer (see Editor.click), back and forward and all the way back, through the view that sent the person here."""
    import time
    forget_the_way_back(editor)
    for q in ("op:1", "op:2", "op:3"):
        run(editor, f"LogShow -Query {q}")

    def wait_drawn(which: str) -> tuple:
        for _ in range(40):
            at = window_values(editor)[which]
            if at[0] >= 0:
                return at
            time.sleep(0.1)
        raise AssertionError(f"the {which} button was never drawn")

    def click_until(which: str, key: str, expected: int):
        editor.click(*wait_drawn(which))
        for _ in range(20):
            if window_values(editor)[key] == expected:
                break
            time.sleep(0.1)
        assert editor.alive(), f"the editor must survive a click on {which}"
        assert window_values(editor)[key] == expected, f"clicking {which} did not go (wanted {key} = {expected}, window says {window_values(editor)})"

    base = window_values(editor)["back"]
    click_until("back_at", "back", base - 1)               # three views in, two clicks back: still looking at the Logs
    click_until("back_at", "back", base - 2)
    assert window_values(editor)["forward"] == 2 and window_values(editor)["query"] == "op:1"
    click_until("forward_at", "forward", 1)                # and forward again
    click_until("forward_at", "forward", 0)
    assert window_values(editor)["query"] == "op:3"

    # all the way back, through the view that sent the person here (the drawer returns to what it was): the third Back used to crash the editor
    for depth in range(window_values(editor)["back"] - 1, -1, -1):
        click_until("back_at", "back", depth)
    forget_the_way_back(editor)


# ---- events: copy as text, open one in place, select a range ------------------------------------------------------------------------

def emit_events(editor, channel: str, count: int) -> list[int]:
    """Count events of their own, each with a body of two lines; returns their sequences."""
    for i in range(count):
        run(editor, f"LogEmit -Text {b64(f'event {i} of {channel}' + chr(10) + f'  detail {i} a' + chr(10) + f'  detail {i} b')} -Channel {channel} -Code EV.{i}")
    _, rows = tail(run(editor, f"LogEvents -Query channel:{channel} -Limit {count + 5}"))
    assert len(rows) == count, rows
    return [int(r["Seq"]) for r in rows]


def test_copying_events_gives_plain_text_one_header_line_each_and_the_body_under_it(editor):
    channel = f"test.copy{secrets.token_hex(2)}"
    seqs = emit_events(editor, channel, 2)
    text = run(editor, f"LogCopy -From {seqs[0]} -To {seqs[1]}")
    lines = text.splitlines()[1:]
    assert len(lines) == 6, lines
    assert re.fullmatch(rf"\d\d:\d\d\.\d{{3}}  info     {re.escape(channel)}  event 0 of {re.escape(channel)}  \[EV\.0\]", lines[0]), lines[0]
    assert lines[1] == "      detail 0 a" and lines[2] == "      detail 0 b", "the body is indented under its header, as it was written"
    assert lines[3].endswith("event 1 of " + channel + "  [EV.1]")
    assert "not a sequence" in editor.cmd("LogCopy -From abc")


def test_each_event_opens_by_its_own_arrow_and_shift_click_selects_a_range(editor):
    import time
    channel = f"test.rows{secrets.token_hex(2)}"
    seqs = emit_events(editor, channel, 5)
    run(editor, f"LogShow -Query channel:{channel}")

    def drawn() -> dict:
        for _ in range(40):
            w = window_values(editor)
            if w["arrow_at"][0] >= 0 and w["stride"] > 0:
                return w
            time.sleep(0.1)
        raise AssertionError("the events were never drawn")

    def row_arrow(k): w = drawn(); return (w["arrow_at"][0], w["arrow_at"][1] + k * w["stride"])
    def row_body(k):  w = drawn(); return (w["row_at"][0], w["row_at"][1] + k * w["stride"])

    # a click selects one event; Shift+click extends it to a range (the rows are in order of sequence)
    editor.click(*row_body(1))
    assert window_values(editor)["range"] == (seqs[1], seqs[1]), window_values(editor)
    editor.click(*row_body(3), shift=True)
    assert window_values(editor)["range"] == (seqs[1], seqs[3]), "Shift+click selects everything between"
    editor.click(*row_body(4))
    assert window_values(editor)["range"] == (seqs[4], seqs[4]), "a plain click starts again"

    # the menu of the selection (right click) does Copy / Open / Close on every selected event; the pipe command is the same function
    editor.click(*row_body(1))
    editor.click(*row_body(3), shift=True)
    copied = run(editor, "LogEventsAction -Action copy")
    assert "copied 3 event(s)" in copied and f"event 1 of {channel}" in copied and f"event 3 of {channel}" in copied and f"event 4 of {channel}" not in copied
    assert "open 3 event(s)" in run(editor, "LogEventsAction -Action open")
    assert window_values(editor)["events_open"] == 3
    assert "close 3 event(s)" in run(editor, "LogEventsAction -Action close")
    assert window_values(editor)["events_open"] == 0
    editor.click(*row_body(2), right=True)                 # the real menu opens inside the selection: the selection stays
    assert window_values(editor)["range"] == (seqs[1], seqs[3])
    editor.post_key(0x1B, hold=0.2)                        # Esc closes the menu
    editor.click(*row_body(0))
    assert editor.alive() and window_values(editor)["range"] == (seqs[0], seqs[0])
    editor.click(*row_body(4))

    # the arrow of one event opens that one alone, and closes it again; the click on it does not select
    assert window_values(editor)["events_open"] == 0
    first_row = drawn()["arrow_at"]
    editor.click(*row_arrow(2))
    assert window_values(editor)["events_open"] == 1 and window_values(editor)["range"] == (seqs[4], seqs[4])
    editor.click(*row_arrow(0))
    assert window_values(editor)["events_open"] == 2, "each event has its own arrow"
    assert drawn()["arrow_at"] == first_row, "opening an event pushes what is below it down: the rows above it do not move"
    editor.click(*row_arrow(0))
    assert window_values(editor)["events_open"] == 1
    assert drawn()["arrow_at"] == first_row, "and closing it does not move them either"
    assert editor.alive()
    forget_the_way_back(editor)


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
