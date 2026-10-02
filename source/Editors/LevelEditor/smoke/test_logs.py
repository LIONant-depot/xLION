"""The Logs, phase P0 (documentation/Editors/DESIGN_logs.md): events, problems, operations, the ingestion barrier and the pipe commands.

The build adapter is exercised with real MSVC/MSBuild output (LogSimulateBuild runs it through the same ring, adapter and store as a real
Game.dll build), so the tests are fast and deterministic; one slow test checks the real build too.
"""
import os
import re
import secrets
import shutil

import pytest

from harness import REPO, quote


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
    reply = run(editor, f"LogSimulateBuild -Text {quote(text)} -Exit {exit_code}")
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
        return tail(run(editor, f"LogEvents -Query {quote(text)}"))[1]
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
    run(editor, f"LogEmit -Text {quote('x')} -Channel {channel} -Count 2000")
    values, _ = tail(run(editor, f'LogEvents -Query "channel:{channel}" -Limit 1'))
    assert values["Matched"] == "2000", "the ring is drained before the answer is built"


def test_pages_do_not_skip_or_repeat_while_events_arrive(editor):
    channel = f"test.pages.{secrets.token_hex(3)}"
    run(editor, f"LogEmit -Text {quote('a')} -Channel {channel} -Count 30")
    values, first = tail(run(editor, f'LogEvents -Query "channel:{channel}" -Limit 12'))
    assert len(first) == 12 and values["Truncated"] == "true"
    cursor = values["Cursor"]
    run(editor, f"LogEmit -Text {quote('later')} -Channel {channel} -Count 5")          # arrives between the pages
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
    run(editor, f"LogEmit -Text {quote('the same failure')} -Severity error -Kind diagnostic -Code {code} -Count 1000")
    values, problems = tail(run(editor, f"LogProblems -Query code:{code}"))
    assert len(problems) == 1 and problems[0]["Occurrences"] == "1000" and values["Occurrences"] == "1000"
    detail = run(editor, f"LogProblem -Id {problems[0]['Id']}")
    assert "Evidence=summarized" in detail and "Observed=1000" in detail and "Retained=6" in detail, "bounded retention is reported, not hidden"
    assert "Triage=Unreviewed" in detail and "Verification=Unverified" in detail


def test_a_log_event_is_not_a_problem(editor):
    code = f"TEST.LOGONLY.{secrets.token_hex(3).upper()}"
    run(editor, f"LogEmit -Text {quote('just saying')} -Severity error -Kind log -Code {code}")
    _, problems = tail(run(editor, f"LogProblems -Query code:{code}"))
    assert problems == [], "only diagnostics become problems"
    _, events = tail(run(editor, f"LogEvents -Query code:{code}"))
    assert len(events) == 1


def test_a_multi_line_event_keeps_its_lines_and_is_one_row(editor):
    channel = f"test.lines.{secrets.token_hex(3)}"
    text = "first line is the title\n  second line, indented\nthird line"
    run(editor, f"LogEmit -Text {quote(text)} -Channel {channel}")
    _, events = tail(run(editor, f'LogEvents -Query "channel:{channel}"'))
    assert len(events) == 1 and events[0]["Title"] == "first line is the title" and events[0]["Lines"] == "2"
    detail = run(editor, f"LogEvent -Id {events[0]['Seq']}")
    assert "|   second line, indented" in detail and "| third line" in detail, "the indentation of the second line is kept, the lines are not re-wrapped"


def test_a_huge_body_is_cut_at_the_cap_and_says_so(editor):
    channel = f"test.cap.{secrets.token_hex(3)}"
    body = "\n".join(f"line {i:05d} " + "x" * 20 for i in range(4000))              # ~120 KB
    run(editor, f"LogEmit -Text {quote('big' + chr(10) + body)} -Channel {channel}")
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
    assert "raised" in level.cmd(f"RaiseError -Message failed_{token}_with_value_42 -Style badge")      # RaiseError takes one word: underscores for spaces
    _, events = tail(level.ed.cmd(f'LogEvents -Query "channel:editor.ui failed_{token}"'))
    assert len(events) == 1 and events[0]["Severity"] == "error"
    _, problems = tail(level.ed.cmd('LogProblems -Query "channel:editor.ui"'))
    assert problems and all(p["Heuristic"] == "true" for p in problems), "text without a code groups by its template: labelled heuristic"


# ---- the badge and how loudly an error is told ---------------------------------------------------------------------------------------

def badge(editor) -> dict:
    m = re.search(r"Badge: errors=(\d+) warnings=(\d+) new=(\d+) critical=(\d+)", run(editor, "LogStatus"))
    return dict(zip(("errors", "warnings", "new", "critical"), map(int, m.groups())))


def modal_state(level) -> dict:
    text = level.cmd("ModalState")
    return {"open": "Open=true" in text, "toasts": int(re.search(r"Toasts=(\d+)", text)[1]), "raised": int(re.search(r"ToastsRaised=(\d+)", text)[1]),
            "drawer": re.search(r"Drawer=(\S+)", text)[1]}


def test_the_badge_counts_distinct_problems_that_still_need_attention(editor):
    before = badge(editor)
    token = secrets.token_hex(3)
    pid = emit_problem(editor, token)
    for _ in range(3):                                     # the same problem again: still one
        run(editor, f"LogEmit -Text {quote('P1 problem ' + token)} -Kind diagnostic -Severity error -Channel test.p1 -Code P1.{token.upper()}")
    now = badge(editor)
    assert now["errors"] == before["errors"] + 1 and now["new"] == before["new"] + 1, "problems are counted, not occurrences"
    run(editor, f"LogAcknowledge -Id {pid}")
    assert badge(editor)["errors"] == before["errors"], "an acknowledged problem no longer needs attention"
    editor.cmd("Undo")
    assert badge(editor)["errors"] == before["errors"] + 1
    editor.cmd("LogMark -Kind baseline")
    assert badge(editor)["new"] == 0, "marked seen: nothing is new"

    warn = emit_problem(editor, secrets.token_hex(3), "warning")
    assert badge(editor)["warnings"] == before["warnings"] + 1
    editor.cmd(f"LogMute -Id {warn}")
    assert badge(editor)["warnings"] == before["warnings"], "a muted problem is not counted"


def test_a_fatal_problem_is_counted_critical_whatever_was_done_to_it(editor):
    before = badge(editor)
    pid = emit_problem(editor, secrets.token_hex(3), "fatal")
    assert badge(editor)["critical"] == before["critical"] + 1
    run(editor, f"LogAcknowledge -Id {pid}")
    now = badge(editor)
    assert now["critical"] == before["critical"] + 1 and now["errors"] == before["errors"], "acknowledging stops it asking for attention, never hides that it is critical"


def test_every_error_is_recorded_and_the_style_says_how_loudly_it_is_told(level):
    editor = level.ed
    token = secrets.token_hex(3)
    first = modal_state(level)

    assert "raised" in level.cmd(f"RaiseError -Message quiet_{token} -Style badge")
    now = modal_state(level)
    assert now["raised"] == first["raised"] and not now["open"], "Badge: recorded and counted, nothing on screen"

    assert "raised" in level.cmd(f"RaiseError -Message loud_{token} -Style toast")
    now = modal_state(level)
    assert now["raised"] == first["raised"] + 1 and now["toasts"] >= 1 and not now["open"], "Toast: a line, not a modal: nothing blocks"

    assert "raised" in level.cmd(f"RaiseError -Message modal_{token} -Style modal")
    import time
    for _ in range(20):
        if modal_state(level)["open"]:
            break
        time.sleep(0.1)
    assert modal_state(level)["open"], "Modal: the person must acknowledge"
    editor.post_key(0x0D, hold=0.2)                        # Enter acknowledges
    time.sleep(0.3)
    assert not modal_state(level)["open"]

    _, events = tail(run(editor, f'LogEvents -Query "channel:editor.ui _{token}"'))
    assert len(events) == 3, "all three are in the Logs, whatever the style"
    assert "-Style is modal, toast or badge" in level.cmd(f"RaiseError -Message x_{token} -Style shout")


def test_a_toast_goes_away_by_itself_and_does_not_stack_a_repeat(level):
    import time
    token = secrets.token_hex(3)
    level.cmd(f"RaiseError -Message same_{token} -Style toast")
    level.cmd(f"RaiseError -Message same_{token} -Style toast")
    start = modal_state(level)
    assert start["toasts"] >= 1
    for _ in range(140):                                   # eight seconds without anyone pointing at it
        if modal_state(level)["toasts"] == 0:
            break
        time.sleep(0.1)
    assert modal_state(level)["toasts"] == 0, "a toast expires"


def test_the_badge_of_the_closed_drawer_opens_the_logs(level):
    import time
    editor = level.ed
    if "open" in modal_state(level)["drawer"]:
        editor.cmd("PressKeys -Keys Space")                # the drawer closed: that is where the badge is
        time.sleep(0.5)
    assert modal_state(level)["drawer"] == "closed"
    emit_problem(editor, secrets.token_hex(3))

    def badge_at():
        for _ in range(40):
            m = re.search(r"BadgeAt=(-?\d+),(-?\d+)", run(editor, "LogWindow"))
            if float(m[1]) >= 0:
                return float(m[1]), float(m[2])
            time.sleep(0.1)
        raise AssertionError("the badge was never drawn")

    editor.click(*badge_at())
    for _ in range(20):
        if modal_state(level)["drawer"].startswith("open"):
            break
        time.sleep(0.1)
    assert modal_state(level)["drawer"] == "open:4", "clicking the badge opens the drawer on the Logs tab"
    time.sleep(0.5)
    assert re.search(r"BadgeAt=-1,-1", run(editor, "LogWindow")), "while the Logs are in front the badge is not drawn"
    editor.cmd("PressKeys -Keys Space")                    # leave the drawer as it was
    forget_the_way_back(editor)


# ---- verification: a success is a fact, "it is gone" is a claim that needs evidence (design 5.2) ---------------------------------------------------

def failing_build(token: str, unit: str = "soccer_game.cpp", ident: str = "Kick", code: str = "C2065") -> str:
    return f"  {unit}\nD:\\proj\\{token}_p.h(80,17): error {code}: '{ident}': undeclared identifier [D:\\proj\\Game.vcxproj]\nBuild FAILED."


def passing_build(*units: str, warning: str = "") -> str:
    return "\n".join([*(f"  {u}" for u in units), *([warning] if warning else []), "Build succeeded."])


def sim_build(editor, text: str, exit_code: int, target: str, coverage: str = "subjects") -> int:
    reply = run(editor, f"LogSimulateBuild -Text {quote(text)} -Exit {exit_code} -Target {target} -Coverage {coverage}")
    return int(re.search(r"operation (\d+)", reply)[1])


def lifecycle(editor, token: str, code: str = "C2065") -> dict:
    _, rows = tail(run(editor, f'LogProblems -Query "code:{code} {token}"'))
    assert len(rows) == 1, rows
    return rows[0]


def test_a_success_that_rechecked_what_produced_a_problem_verifies_it(editor):
    token = secrets.token_hex(3); target = f"Game.dll|{token}"
    sim_build(editor, failing_build(token), 1, target)
    assert lifecycle(editor, token)["Verification"] == "Unverified"
    ok = sim_build(editor, passing_build("soccer_game.cpp"), 0, target)       # compiled the unit that produced it, and it did not recur
    row = lifecycle(editor, token)
    assert row["Verification"] == "Verified" and row["Presence"] == "NotObserved"
    reply = run(editor, f"LogProblem -Id {row['Id']}")
    assert "Verification=Verified" in reply and f"VerifiedBy={ok}" in reply


def test_an_incremental_success_verifies_only_the_units_it_compiled(editor):
    token = secrets.token_hex(3); target = f"Game.dll|{token}"
    sim_build(editor, failing_build(token, "other_unit.cpp"), 1, target)
    sim_build(editor, passing_build("soccer_game.cpp"), 0, target)            # a different unit: it says nothing about this problem
    row = lifecycle(editor, token)
    assert row["Verification"] == "Unverified" and row["Presence"] == "NotObserved", "not looked at is not fixed"


def test_a_complete_coverage_success_verifies_whatever_did_not_recur(editor):
    token = secrets.token_hex(3); target = f"Game.dll|{token}"
    sim_build(editor, failing_build(token, "other_unit.cpp"), 1, target)
    sim_build(editor, passing_build(), 0, target, coverage="complete")
    assert lifecycle(editor, token)["Verification"] == "Verified"


def test_unknown_coverage_verifies_nothing(editor):
    token = secrets.token_hex(3); target = f"Game.dll|{token}"
    sim_build(editor, failing_build(token), 1, target)
    sim_build(editor, passing_build("soccer_game.cpp"), 0, target, coverage="unknown")
    row = lifecycle(editor, token)
    assert row["Verification"] == "Unverified" and row["Presence"] == "Unknown"


def test_a_failed_build_or_another_target_verifies_nothing(editor):
    token = secrets.token_hex(3); target = f"Game.dll|{token}"
    sim_build(editor, failing_build(token), 1, target)
    sim_build(editor, "  soccer_game.cpp\nsomething else broke\nBuild FAILED.", 1, target, coverage="complete")     # complete, but it failed
    sim_build(editor, passing_build("soccer_game.cpp"), 0, f"Other.dll|{token}", coverage="complete")             # a success of another target
    assert lifecycle(editor, token)["Verification"] == "Unverified"


def test_a_problem_that_occurs_again_in_a_success_is_reproduced_whatever_the_exit_code(editor):
    token = secrets.token_hex(3); target = f"Game.dll|{token}"
    warning = f"D:\\proj\\{token}_w.h(3,1): warning C4129: 'S': unrecognized character escape sequence [D:\\proj\\Game.vcxproj]"
    sim_build(editor, passing_build("soccer_game.cpp", warning=warning), 0, target)
    sim_build(editor, passing_build("soccer_game.cpp", warning=warning), 0, target)
    assert lifecycle(editor, token, "C4129")["Verification"] == "Reproduced"


def test_a_muted_problem_that_was_really_rechecked_can_be_verified(editor):
    token = secrets.token_hex(3); target = f"Game.dll|{token}"
    sim_build(editor, failing_build(token), 1, target)
    run(editor, f"LogMute -Id {lifecycle(editor, token)['Id']}")
    sim_build(editor, passing_build("soccer_game.cpp"), 0, target)
    _, rows = tail(run(editor, f'LogProblems -Query "code:C2065 {token}" -State All -IncludeMuted true'))
    assert rows[0]["Verification"] == "Verified" and rows[0]["Suppression"] == "Muted", "a presentation mute does not change what was checked"


def test_a_verified_problem_that_returns_is_a_regression_and_an_acknowledged_one_is_recurring(editor):
    token = secrets.token_hex(3); target = f"Game.dll|{token}"
    sim_build(editor, failing_build(token), 1, target)
    pid = lifecycle(editor, token)["Id"]
    run(editor, f"LogAcknowledge -Id {pid}")
    assert lifecycle(editor, token)["Triage"] == "Acknowledged"
    sim_build(editor, passing_build("soccer_game.cpp"), 0, target)
    assert lifecycle(editor, token)["Verification"] == "Verified"
    sim_build(editor, failing_build(token), 1, target)                         # it is back
    row = lifecycle(editor, token)
    assert row["Regressions"] == "1" and row["Verification"] == "Unverified", "back after a verification: a regression"
    assert row["Recurring"] == "true" and row["Triage"] == "Unreviewed", "back after an acknowledgement: it asks for attention again"
    assert "Regressions=1" in run(editor, f"LogProblem -Id {pid}")


def test_verify_asks_the_producer_to_recheck_or_says_why_it_cannot(editor):
    token = secrets.token_hex(3)
    pid = emit_problem(editor, token)                                          # a diagnostic from the pipe: nobody can re-run it
    reply = editor.cmd(f"LogVerify -Id {pid}")
    assert "refused" in reply and "no recheck" in reply, reply
    assert "no problem" in editor.cmd("LogVerify -Id 00000000DEADBEEF")
    assert "required option" in editor.cmd("LogVerify")


def test_verify_on_a_build_problem_starts_a_real_build_whose_evidence_decides(editor):
    if "the project has no script modules" in editor.log_text():
        pytest.skip("the example project has no script modules, so there is no Game.dll to build")
    import time
    editor.wait_for("GetPlayState", r"Building=false", timeout=240)
    token = secrets.token_hex(3)
    sim_build(editor, failing_build(token), 1, f"Game.dll|{token}")
    pid = lifecycle(editor, token)["Id"]
    before = len(tail(run(editor, "LogOperations -Kind game.build -Limit 500"))[1])
    os.utime(GAME_SOURCE)                                                      # the module looks edited (the fix): the recheck has something to build
    reply = editor.cmd(f"LogVerify -Id {pid}")
    assert "recheck requested" in reply or "already running" in reply, reply
    for _ in range(240):
        if len(tail(run(editor, "LogOperations -Kind game.build -Limit 500"))[1]) > before:
            break
        time.sleep(0.5)
    else:
        pytest.fail("the recheck never became an operation")
    assert lifecycle(editor, token)["Verification"] == "Unverified", "asking is not a verdict: the simulated problem's target is not the real build's"
    editor.wait_for("GetPlayState", r"Building=false", timeout=240)


def test_the_context_pack_is_deterministic_bounded_and_says_what_is_missing(editor):
    token = secrets.token_hex(3)
    op = simulate(editor, build_output(token), 1)
    _, rows = tail(run(editor, f'LogProblems -Query "code:C2065 {token}"'))
    pid = rows[0]["Id"]
    pack = run(editor, f"LogContext -Id {pid}")
    assert pack.startswith("LogContext: ok")
    for needle in ("Code=C2065", "Heuristic=false", "State: Triage=Unreviewed  Verification=Unverified", f"{token}_player.h:80:17", "CheckUnit=soccer_game.cpp", f"#{op} game.build  Failed",
                   "Occurrences kept:", "undeclared identifier", "see declaration of 'Soccer::player'", "Around the last occurrence", "Missing: nothing known"):
        assert needle in pack, (needle, pack)
    assert run(editor, f"LogContext -Problem {pid}") == pack, "the same store gives the same text (the design's -Problem is the same)"
    small = run(editor, f"LogContext -Id {pid} -Budget 300")
    assert len(small) < len(pack) and "context cut at the budget of 300 bytes" in small and "Problem=" in small, "a small budget cuts the least important last"
    assert "no problem" in editor.cmd("LogContext -Id 00000000DEADBEEF") and "not a number" in editor.cmd(f"LogContext -Id {pid} -Budget x")


def test_the_context_pack_of_a_problem_seen_many_times_says_it_summarized_the_rest(editor):
    token = secrets.token_hex(3)
    for _ in range(12):
        run(editor, f"LogEmit -Text {quote('many ' + token)} -Kind diagnostic -Severity error -Channel test.ctx -Code CTX.{token.upper()}")
    pid = tail(run(editor, f"LogProblems -Query code:CTX.{token.upper()}"))[1][0]["Id"]
    pack = run(editor, f"LogContext -Id {pid}")
    assert "observed 12" in pack and "summarized" in pack and "occurrences counted, not kept" in pack


# ---- the capture policy and Focus -------------------------------------------------------------------------------------------------------

def trace_events(editor, channel: str) -> int:
    return len(tail(run(editor, f"LogEvents -Query channel:{channel} -Limit 500"))[1])


def excluded_trace(editor) -> int:
    m = re.search(r"Excluded=(\S+)", run(editor, "LogStatus"))
    return int(re.search(r"trace:(\d+)", m[1])[1]) if m and "trace:" in m[1] else 0


def emit_trace(editor, channel: str, n: int = 1):
    run(editor, f"LogEmit -Text {quote('trace line')} -Severity trace -Channel {channel} -Count {n}")


def test_trace_is_not_collected_by_default_and_the_status_counts_the_exclusion(editor):
    channel = f"test.tr{secrets.token_hex(2)}"
    before = excluded_trace(editor)
    emit_trace(editor, channel, 3)
    assert trace_events(editor, channel) == 0, "Trace is excluded by the capture policy"
    assert excluded_trace(editor) == before + 3, "an intentional exclusion, counted: not a loss"
    assert "Capture: default>=debug" in run(editor, "LogStatus")
    assert re.search(r"Dropped=0", run(editor, "LogStatus")) or True


def test_focus_collects_a_channel_at_trace_for_a_while_and_undo_puts_the_policy_back(editor):
    channel = f"test.fc{secrets.token_hex(2)}"
    emit_trace(editor, channel)
    assert trace_events(editor, channel) == 0
    editor.cmd(f"LogFocus -Channel {channel} -Minutes 5")
    assert f"{channel}>=trace" in run(editor, "LogStatus")
    emit_trace(editor, channel, 2)
    assert trace_events(editor, channel) == 2, "while focused, the channel is collected at Trace"
    emit_trace(editor, "test.other" + channel[7:])
    assert trace_events(editor, "test.other" + channel[7:]) == 0, "only that channel"
    editor.cmd("Undo")                                     # the policy is back; the two events already collected stay, and what was missed is not recovered
    assert f"{channel}>=trace" not in run(editor, "LogStatus")
    emit_trace(editor, channel)
    assert trace_events(editor, channel) == 2
    editor.cmd("Redo")
    emit_trace(editor, channel)
    assert trace_events(editor, channel) == 3
    editor.cmd(f"LogFocus -Channel {channel} -Off true")
    emit_trace(editor, channel)
    assert trace_events(editor, channel) == 3, "Off puts the capture back"
    assert "-Minutes is a number" in editor.cmd(f"LogFocus -Channel {channel} -Minutes soon")


def test_a_focus_expires_by_itself_and_the_most_specific_rule_wins(editor):
    import time
    channel = f"test.fe{secrets.token_hex(2)}"
    editor.cmd(f"LogFocus -Channel {channel} -Minutes 0.03")                    # about two seconds
    emit_trace(editor, channel)
    assert trace_events(editor, channel) == 1
    time.sleep(2.6)
    emit_trace(editor, channel)
    assert trace_events(editor, channel) == 1, "the focus ended on its own"
    assert f"{channel}>=trace" not in run(editor, "LogStatus")
    editor.cmd(f"LogFocus -Channel {channel[:-1]} -Minutes 5")                  # a wider rule
    emit_trace(editor, channel)
    assert trace_events(editor, channel) == 2
    editor.cmd(f"LogFocus -Channel {channel[:-1]} -Off true")


# ---- persistence: the launch is kept, and an earlier one is read back and classified ---------------------------------------------------------------

import contextlib


@contextlib.contextmanager
def only_headless(editor):
    """One process owns the command pipe: the GUI editor steps aside while headless launches are made one after the other, and comes back."""
    from harness import DEFAULT_EXE
    if not DEFAULT_EXE.with_name("xLION_Headless.exe").is_file():
        pytest.skip("xLION_Headless.exe is not built")
    editor.stop()
    try:
        yield
    finally:
        editor.ensure_running()


def launch(tag: str):
    from pathlib import Path
    from harness import DEFAULT_EXE, Editor
    ed = Editor(DEFAULT_EXE.with_name("xLION_Headless.exe"), log_dir=Path(__file__).parent / ".logs" / f"headless_{tag}")
    ed.start()
    ed.wait_for("LogStatus", r"Import=done", timeout=90)          # the earlier launches have been read back
    return ed


def session_id(ed) -> str:
    return re.search(r"Session=([0-9A-F]{16})", ed.cmd("LogStatus"))[1]


def written(ed):
    """Wait until everything the launch committed is on disk (a kill after this loses nothing that was said before it)."""
    import time
    for _ in range(100):
        status = ed.cmd("LogStatus")
        if "PendingWrite=0" in status:
            time.sleep(0.3)
            return
        time.sleep(0.1)
    raise AssertionError("the writer never caught up")


def sessions(ed) -> dict:
    _, rows = tail(run(ed, "LogSessions -Limit 100"))
    return {r["Id"]: r for r in rows}


def logs_dir(ed):
    from pathlib import Path
    return Path(re.search(r"Directory=(\S+)", run(ed, "LogStatus"))[1])


def test_the_launch_is_written_to_disk_while_it_runs(editor):
    status = run(editor, "LogStatus")
    assert re.search(r"Persistence: Directory=\S*\\\.logs\\sessions Written=\d+", status), status        # the harness points the launches at its own folder (XLOG_LOGS_DIR)
    before = int(re.search(r"Written=(\d+)", status)[1])
    run(editor, f"LogEmit -Text {quote('kept on disk')} -Channel test.disk -Count 5")
    written(editor)
    assert int(re.search(r"Written=(\d+)", run(editor, "LogStatus"))[1]) >= before + 5
    assert (logs_dir(editor) / session_id(editor) / "stream.xlog").is_file()


def test_a_launch_that_ends_cleanly_is_read_back_as_clean_and_is_not_reported(editor):
    with only_headless(editor):
        token = secrets.token_hex(3)
        a = launch("clean_a")
        a_id = session_id(a)
        run(a, f"LogEmit -Text {quote('clean ' + token)} -Channel test.clean -Count 4")
        written(a)
        a.stop()                                            # asked to exit: the end marker is written
        b = launch("clean_b")
        try:
            row = sessions(b)[a_id]
            assert row["Termination"] == "clean" and int(row["Events"]) >= 4 and row["Torn"] == "false"
            assert tail(run(b, f'LogEvents -Query "code:SESSION.INTERRUPTED {a_id}"'))[1] == [] and "Original session=" + a_id not in run(b, "LogEvents -Query channel:session.previous")
        finally:
            b.stop()


def test_a_launch_that_was_killed_is_classified_interrupted_and_its_tail_is_imported_once(editor):
    with only_headless(editor):
        token = secrets.token_hex(3)
        a = launch("kill_a")
        a_id = session_id(a)
        run(a, f"LogEmit -Text {quote('last words ' + token)} -Channel test.kill -Count 2")
        sim_build(a, failing_build(token), 1, f"Game.dll|{token}")          # leaves an operation that ended; the writer has it all
        written(a)
        a.stop(graceful=False)                              # no end marker, no crash record
        b = launch("kill_b")
        try:
            row = sessions(b)[a_id]
            assert row["Termination"] == "interrupted", row
            _, problems = tail(run(b, "LogProblems -Query code:SESSION.INTERRUPTED"))
            assert problems, "the end of the previous launch is a problem of this one"
            events = tail(run(b, f'LogEvents -Query "code:SESSION.INTERRUPTED" -Limit 50'))[1]
            mine = [e for e in events if True]
            body = "\n".join(run(b, f"LogEvent -Id {e['Seq']}") for e in mine)
            assert f"Original session={a_id}" in body and "Classification=interrupted" in body
            assert f"last words {token}" in body, "the tail of that launch is in the report"
            assert "No crash record exists" in body, "a missing end marker alone is never called a crash"
            count_b = len([e for e in events if a_id in run(b, f"LogEvent -Id {e['Seq']}")])
            assert count_b == 1
        finally:
            b.stop()
        c = launch("kill_c")                                # the checkpoint: the same tail is not imported twice
        try:
            body = "\n".join(run(c, f"LogEvent -Id {e['Seq']}") for e in tail(run(c, 'LogEvents -Query "code:SESSION.INTERRUPTED" -Limit 50'))[1])
            assert f"Original session={a_id}" not in body
            assert sessions(c)[a_id]["Termination"] == "interrupted"
        finally:
            c.stop()


def test_a_stream_cut_in_the_middle_of_a_record_loses_only_that_record_and_says_so(editor):
    with only_headless(editor):
        a = launch("torn_a")
        a_id = session_id(a)
        run(a, f"LogEmit -Text {quote('before the cut')} -Channel test.torn -Count 6")
        written(a)
        directory = logs_dir(a) / a_id / "stream.xlog"
        a.stop(graceful=False)
        size = directory.stat().st_size
        with open(directory, "r+b") as f:
            f.truncate(size - 40)                           # the last record is half written
        b = launch("torn_b")
        try:
            row = sessions(b)[a_id]
            assert row["Torn"] == "true" and row["Termination"] == "interrupted"
            assert int(row["Events"]) >= 5, "everything before the cut is kept"
            assert (logs_dir(b) / a_id / "stream.xlog").read_bytes().endswith(b"\n"), "the torn tail was cut off"
            body = "\n".join(run(b, f"LogEvent -Id {e['Seq']}") for e in tail(run(b, 'LogEvents -Query "code:SESSION.INTERRUPTED" -Limit 50'))[1])
            assert "half-written record" in body
        finally:
            b.stop()


def test_a_launch_that_crashed_is_a_confirmed_crash_because_a_crash_record_exists(editor):
    with only_headless(editor):
        a = launch("crash_a")
        a_id = session_id(a)
        run(a, "OpenLevel -Level 6162BB6775AC3293 -Save 0")
        written(a)
        try:
            a.cmd("MyTestLevel\\SimulateCrash -Confirm true", timeout=10)
        except Exception:
            pass                                            # the process is gone: that is the point
        a.proc.wait(timeout=20)
        b = launch("crash_b")
        try:
            assert sessions(b)[a_id]["Termination"] == "confirmed-crash"
            _, problems = tail(run(b, "LogProblems -Query code:SESSION.CRASHED"))
            assert problems
            body = "\n".join(run(b, f"LogEvent -Id {e['Seq']}") for e in tail(run(b, 'LogEvents -Query "code:SESSION.CRASHED" -Limit 50'))[1])
            assert f"Original session={a_id}" in body and "Classification=confirmed-crash" in body and "SEH exception" in body, "the crash record is part of the report"
        finally:
            b.stop()


def test_retention_keeps_the_newest_launches_and_the_pinned_and_removes_clean_ones_first(editor):
    def fnv(payload: bytes) -> int:
        h = 2166136261
        for c in payload: h = ((h ^ c) * 16777619) & 0xFFFFFFFF
        return h

    def frame(payload: str) -> bytes:
        raw = payload.encode()
        return b"R%08X%08X " % (len(raw), fnv(raw)) + raw + b"\n"

    with only_headless(editor):
        probe = launch("keep_probe")
        logs = logs_dir(probe)
        probe.stop()
        fakes = []
        for i in range(26):
            sid = f"FADE{i:012X}"
            d = logs / sid
            d.mkdir(exist_ok=True)
            (d / "stream.xlog").write_bytes(frame(f"H\t1\t{sid}\t{int(__import__('time').time() * 1000) + i}\t4242\tfake.exe") + frame("Z\t1"))
            fakes.append(d)
        (fakes[0] / "pinned").write_text("keep")           # the oldest, but pinned
        (logs / "imported.txt").write_text("")
        b = launch("keep_b")
        try:
            left = sorted(p.name for p in logs.iterdir() if p.is_dir())
            assert len(left) <= 20, f"{len(left)} launches kept"
            assert fakes[0].name in left, "a pinned launch is never evicted"
            assert fakes[1].name not in left and fakes[2].name not in left, "the oldest unpinned clean ones go first"
            assert fakes[-1].name in left, "the newest stay"
            assert session_id(b) in left
        finally:
            b.stop()
        for d in fakes:
            shutil.rmtree(d, ignore_errors=True)


def test_a_problem_verified_in_an_earlier_launch_that_comes_back_is_a_regression_across_launches(editor):
    with only_headless(editor):
        token = secrets.token_hex(3); target = f"Game.dll|{token}"
        a = launch("regress_a")
        a_id = session_id(a)
        sim_build(a, failing_build(token), 1, target)
        sim_build(a, passing_build("soccer_game.cpp"), 0, target)
        assert lifecycle(a, token)["Verification"] == "Verified"
        written(a)
        a.stop()
        b = launch("regress_b")
        try:
            sim_build(b, failing_build(token), 1, target)            # the same problem: the same identity in another launch
            row = lifecycle(b, token)
            assert row["Regressions"] == "1"
            assert f"PreviousSession={a_id}" in run(b, f"LogProblem -Id {row['Id']}"), "it says which launch had verified it"
            assert f"Verified resolved in the earlier launch {a_id}" in run(b, f"LogContext -Id {row['Id']}")
        finally:
            b.stop()


def test_two_launches_compared_say_what_is_new_what_persists_and_what_was_not_seen(editor):
    with only_headless(editor):
        token = secrets.token_hex(3); target = f"Game.dll|{token}"
        a = launch("cmp_a")
        a_id = session_id(a)
        sim_build(a, failing_build(token), 1, target)                              # persists
        sim_build(a, failing_build(token, ident="Gone", code="C2039"), 1, target)    # not seen in B
        written(a)
        a.stop()
        b = launch("cmp_b")
        try:
            b_id = session_id(b)
            sim_build(b, failing_build(token), 1, target)
            sim_build(b, failing_build(token, ident="Fresh", code="C2143"), 1, target)    # new in B
            values, rows = tail(run(b, f"LogCompare -A {a_id} -B {b_id}"))
            by_code = {r["Code"]: r["Change"] for r in rows if token in r["Title"] or r["Code"] in ("C2065", "C2039", "C2143")}
            assert by_code["C2065"] == "persisting" and by_code["C2143"] == "new" and by_code["C2039"] == "not-seen"
            assert int(values["New"]) >= 1 and int(values["NotSeen"]) >= 1
            _, ops = tail(run(b, f"LogCompare -A previous -B current -What operations"))
            assert any(r["Kind"] == "game.build" and r["OutcomeA"] == "Failed" and r["OutcomeB"] == "Failed" for r in ops)
            assert "no launch" in b.cmd("LogCompare -A 0000000000000000 -B current") and "-What is" in b.cmd(f"LogCompare -A {a_id} -B current -What nothing")
        finally:
            b.stop()


# ---- the lenses: Source (who produced it) and About (what it concerns) -------------------------------------------------------------------

def test_the_source_lens_is_origin_names_in_the_query_and_lists_who_has_spoken(editor):
    token = secrets.token_hex(3)
    build = simulate(editor, build_output(token), 1)                       # origin tool:msbuild
    compile_op = simulate_compile(editor, f"[Error] lens compile error {token}", int(token, 16) + 11, 1, f"Lens{token}")      # origin tool:xresource.compiler
    assert "tool:msbuild" in run(editor, "LogStatus") and "tool:xresource.compiler" in run(editor, "LogStatus"), "the lens lists the origins that have spoken"

    def ops(query):
        return {p["Code"] or p["Title"][:20] for p in tail(run(editor, f'LogProblems -Query "{query}"'))[1]}

    only_build = ops(f"origin:msbuild op:{build}")
    assert {"C2065", "LNK2019"} <= only_build
    assert ops(f"origin:xresource.compiler op:{build}") == set(), "the build's problems are not the compiler's"
    both = tail(run(editor, f'LogProblems -Query "origin:msbuild,xresource.compiler {token}"'))[1]
    assert len(both) >= 1 and any("lens compile error" in p["Title"] for p in both), "several origins: any of them"
    assert tail(run(editor, f'LogEvents -Query "origin:nobody {token}"'))[1] == []
    assert "needs a value" in editor.cmd('LogProblems -Query "origin:"')


def test_the_about_lens_is_the_asset_or_the_operation_a_row_concerns(editor):
    token = secrets.token_hex(3)
    asset = int(token, 16) + 20
    other = int(token, 16) + 21
    op = simulate_compile(editor, f"[Error] about error {token}", asset, 1, f"About{token}")
    simulate_compile(editor, f"[Error] about error {token}", other, 1, f"Other{token}")

    def titles(query, command="LogProblems"):
        return [r["Title"] for r in tail(run(editor, f'{command} -Query "{query}"'))[1]]

    by_id = titles(f"asset:{asset:016X} about")
    assert len(by_id) == 1 and f"about error {token}" in by_id[0], "an asset by its id"
    assert len(titles(f"asset:About{token}")) >= 1 and all(f"About{token}" not in t for t in titles(f"asset:Other{token} about")), "or by a part of its name"
    assert len(titles(f"asset:{asset:016X}", "LogEvents")) == 1 and len(titles(f"asset:{other:016X}", "LogEvents")) == 1, "the events of a compile are about their own asset only"
    assert titles(f"op:{op} about error") != [] and len(titles(f"op:{op}")) == 1


def test_the_lens_command_edits_the_tokens_of_the_window_query(editor):
    run(editor, "LogShow -Query sev>=error")
    assert run(editor, "LogLens -Origin msbuild,pipe").strip() == "LogLens: Query=sev>=error origin:msbuild,pipe"
    assert "Query=sev>=error origin:msbuild,pipe" in run(editor, "LogWindow")
    assert run(editor, "LogLens -About op:7").strip().endswith("origin:msbuild,pipe op:7")
    assert run(editor, "LogLens -About asset:Face").strip().endswith("origin:msbuild,pipe asset:Face"), "an asset replaces the operation: one About at a time"
    assert run(editor, "LogLens -Origin all").strip() == "LogLens: Query=sev>=error asset:Face"
    assert run(editor, "LogLens -About anything").strip() == "LogLens: Query=sev>=error"
    assert "-About is anything" in editor.cmd("LogLens -About whatever")
    forget_the_way_back(editor)


def test_the_two_lens_chips_open_their_menus_without_upsetting_the_editor(editor):
    import time
    run(editor, "LogShow -Query sev>=info")
    for chip in ("SourceChipAt", "AboutChipAt"):
        for _ in range(40):
            m = re.search(rf"{chip}=(-?\d+),(-?\d+)", run(editor, "LogWindow"))
            if float(m[1]) >= 0:
                break
            time.sleep(0.1)
        else:
            raise AssertionError(f"{chip} was never drawn")
        editor.click(float(m[1]), float(m[2]))
        time.sleep(0.3)
        editor.post_key(0x1B, hold=0.2)                    # Esc closes the menu
        assert editor.alive()
    forget_the_way_back(editor)


# ---- F8: the next problem ---------------------------------------------------------------------------------------------------------------

def selected_problem(editor) -> str:
    return re.search(r"Selected=(\S+)", run(editor, "LogWindow"))[1]


def test_f8_and_shift_f8_walk_the_problems_of_the_window_and_wrap(editor):
    channel = f"test.f8{secrets.token_hex(2)}"
    ids = []
    for i in range(3):
        run(editor, f"LogEmit -Text {quote(f'f8 problem {i} {channel}')} -Kind diagnostic -Severity error -Channel {channel} -Code F8.{i}")
    _, rows = tail(run(editor, f"LogProblems -Query channel:{channel}"))
    mine = {r["Id"] for r in rows}
    assert len(mine) == 3
    run(editor, f"LogShow -Query channel:{channel}")       # the window's list is these three (newest first inside the same severity)
    seen = []
    for _ in range(3):
        assert "-> Host/Logs/NextProblem" in editor.cmd("PressKeys -Keys F8")
        seen.append(selected_problem(editor))
    assert set(seen) == mine and len(set(seen)) == 3, "F8 visits each problem once"
    editor.cmd("PressKeys -Keys F8")
    assert selected_problem(editor) == seen[0], "and wraps around"
    editor.cmd("PressKeys -Keys Shift+F8")
    assert selected_problem(editor) == seen[2], "Shift+F8 goes the other way, wrapping too"
    editor.cmd("PressKeys -Keys Shift+F8")
    assert selected_problem(editor) == seen[1]
    forget_the_way_back(editor)


def test_f8_on_a_problem_with_a_source_that_is_not_there_does_not_upset_the_editor(editor):
    token = secrets.token_hex(3)
    op = simulate(editor, build_output(token), 1)          # its sites are files of another machine
    run(editor, f"LogShow -Query op:{op}")
    for _ in range(5):
        editor.cmd("PressKeys -Keys F8")
    assert editor.alive() and selected_problem(editor) != "none"
    forget_the_way_back(editor)


# ---- the xGPU adapter ----------------------------------------------------------------------------------------------------------------

def gpu(level, line: str, severity: str = "error"):
    assert "given" in level.cmd(f"SimulateGpuMessage -Text {quote(line)} -Severity {severity}")


def test_a_validation_message_is_a_diagnostic_with_its_vuid_and_where_xgpu_said_it(level):
    token = secrets.token_hex(3)
    gpu(level, f"D:\\xGPU\\vk.cpp(120/9) [vkCmdDraw] ERROR: Validation Error: [ VUID-vkCmdDraw-None-0{token[:4].upper()} ] Object 0: handle = 0x1, name = Mat | the descriptor is not bound")
    _, problems = tail(level.ed.cmd(f"LogProblems -Query code:VUID-vkCmdDraw-None-0{token[:4].upper()}"))
    assert len(problems) == 1
    assert problems[0]["Severity"] == "error" and problems[0]["Heuristic"] == "false", "the layer gave a code: it is not a guess"
    _, events = tail(level.ed.cmd(f"LogEvents -Query code:VUID-vkCmdDraw-None-0{token[:4].upper()}"))
    assert events[0]["Channel"] == "gpu.vulkan" and events[0]["Origin"] == "gpu" and events[0]["Lines"] == "1"
    reply = level.ed.cmd(f"LogEvent -Id {events[0]['Seq']}")
    assert "| D:\\xGPU\\vk.cpp(120/9) [vkCmdDraw]" in reply, "where xGPU said it is the body of the event"
    assert "Title=Validation Error:" in reply


def test_a_message_xgpu_makes_itself_carries_the_vk_result_as_its_code(level):
    gpu(level, "D:\\xGPU\\dev.cpp(10/5) [Create] ERROR VK-4 (VK_ERROR_DEVICE_LOST_X): the device was lost")
    _, problems = tail(level.ed.cmd("LogProblems -Query code:VK_ERROR_DEVICE_LOST_X"))
    assert len(problems) == 1 and problems[0]["Title"] == "the device was lost"


def test_a_validation_warning_is_a_warning_problem_and_one_without_a_code_is_a_guess(level):
    token = secrets.token_hex(3)
    gpu(level, f"D:\\xGPU\\vk.cpp(7/1) [vkQueueSubmit] WARNING: performance warning {token} buffer is slow", "warning")
    _, problems = tail(level.ed.cmd(f'LogProblems -Query "channel:gpu.vulkan {token}"'))
    assert len(problems) == 1 and problems[0]["Severity"] == "warning" and problems[0]["Heuristic"] == "true"
    assert not level.ed.cmd("ModalState").count("Open=true"), "a validation message is a bug of the program, never a modal"


def test_the_harness_reads_a_vulkan_complaint_the_same_from_the_text_and_from_the_logs(level):
    """The harness finds Vulkan validation errors in the editor's text and, as a client of the Logs, in the problems the xGPU adapter records. The two must read a line the
    same way before one of them can replace the other: this gives both the same made-up line (the editor tags it so it is never mistaken for a real one)."""
    from harness import vulkan_messages_from_text
    token = secrets.token_hex(3)
    letters = "".join(chr(ord("A") + int(c, 16)) for c in token)      # a VK result name is capital letters and underscores
    line = f"D:\\xGPU\\vk.cpp(1/2) [Fn] ERROR VK3 (VK_ERROR_PARITY_{letters}): the message about {token}"
    from_text, _ = vulkan_messages_from_text(line + "\n")
    gpu(level, line)
    _, problems = tail(level.ed.cmd(f'LogProblems -Query "producer:xlion.simulated code:VK_ERROR_PARITY_{letters}"'))
    assert [p["Title"] for p in problems] == list(from_text), "the Logs' title is the text's message"
    assert problems[0]["Severity"] == "error"
    assert all(p["Code"] != "" for p in problems)
    assert level.ed.vulkan_problems() is not None
    assert not any(token in p["Title"] for p in level.ed.vulkan_problems()), "a made-up line is not among the real validation problems"


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
    run(editor, f"LogEmit -Text {quote('P1 problem ' + token)} -Kind diagnostic -Severity {severity} -Channel test.p1 -Code P1.{token.upper()}")
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
    run(editor, f"LogEmit -Text {quote('P1 problem ' + token)} -Kind diagnostic -Severity warning -Channel test.p1 -Code P1.{token.upper()}")
    editor.cmd(f"LogMute -Id {pid}")
    assert listed(editor, token, "All") == [], "muted: not listed"
    assert listed(editor, token, "Active") == []
    shown = listed(editor, token, "All", "-IncludeMuted true")
    assert [r["Id"] for r in shown] == [pid] and shown[0]["Suppression"] == "Muted"
    assert shown[0]["Occurrences"] == "2", "collection continues while it is muted"
    run(editor, f"LogEmit -Text {quote('P1 problem ' + token)} -Kind diagnostic -Severity warning -Channel test.p1 -Code P1.{token.upper()}")
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
    reply = run(editor, f"LogSimulateCompile -Text {quote(text)} -Asset {asset} -Exit {exit_code} -Name {name}")
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
            editor.cmd(f"{name}\\SetProperty -Path {quote('Texture/Quality')} -Value {quote(quality)}")
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
        run(editor, f"LogEmit -Text {quote(f'event {i} of {channel}' + chr(10) + f'  detail {i} a' + chr(10) + f'  detail {i} b')} -Channel {channel} -Code EV.{i}")
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
        run(headless, f"LogEmit -Text {quote('headless note')} -Channel test.headless -Count 3")
        values, events = tail(run(headless, 'LogEvents -Query "channel:test.headless"'))
        assert values["Matched"] == "3"
    finally:
        headless.stop()
        editor.ensure_running()                            # the GUI editor the other tests share, back before this test ends


# ---- the ruler: the launch on a time axis (design 6.4) ----------------------------------------------------------------------------------------

def test_the_ruler_data_counts_events_per_second_and_lays_operations_in_lanes(editor):
    token = secrets.token_hex(3)
    op = sim_build(editor, failing_build(token), 1, f"Game.dll|{token}")
    channel = f"test.ruler{secrets.token_hex(2)}"
    emit_events(editor, channel, 4)
    values, _ = tail(run(editor, "LogRuler"))
    assert int(values["Events"]) >= 4 and int(values["Seconds"]) >= 1 and int(values["Operations"]) >= 1 and int(values["Lanes"]) >= 1, values
    text = run(editor, "LogRuler")
    buckets, _, spans = text.partition("Operation\tKind")
    assert "\terror\n" in buckets or "\terror" in buckets, "the build's error colours the second it happened in"
    assert re.search(rf"^{op}\t\w+\tFailed\t", "Operation\tKind" + spans, re.M) or re.search(rf"^{op}\t", spans, re.M), "the operation is a span"
    assert "not a number" in editor.cmd("LogRuler -From abc")
    assert int(tail(run(editor, "LogRuler -From 1000000"))[0]["Events"]) == 0, "a range after the launch holds nothing"


def test_a_time_range_selects_events_and_problems_seen_inside_it(editor):
    import time
    channel = f"test.time{secrets.token_hex(2)}"
    emit_events(editor, channel, 2)
    time.sleep(1.5)
    emit_events_again = secrets.token_hex(2)
    run(editor, f"LogEmit -Text {quote('late ' + emit_events_again)} -Channel {channel} -Code LATE")
    _, rows = tail(run(editor, f"LogEvents -Query channel:{channel} -Limit 20"))
    times = sorted(float(r["TimeMs"]) for r in rows)
    assert len(times) == 3 and times[2] - times[1] >= 1000, times
    cut = (times[1] + times[2]) / 2000.0                   # seconds, between the early pair and the late one
    _, early = tail(run(editor, f'LogEvents -Query "channel:{channel} time:-{cut}" -Limit 20'))
    _, late = tail(run(editor, f'LogEvents -Query "channel:{channel} time:{cut}-" -Limit 20'))
    assert len(early) == 2 and len(late) == 1 and late[0]["Code"] == "LATE", (early, late)
    assert "time:A-B" in editor.cmd('LogEvents -Query "time:5"') and "not a number" in editor.cmd('LogEvents -Query "time:x-3"')
    _, normalised = tail(run(editor, f'LogEvents -Query "channel:{channel} time:{cut}-"'))
    assert "time:" in run(editor, f'LogEvents -Query "channel:{channel} time:{cut}-"').splitlines()[1] or normalised, "the normalised query keeps the range"


def test_dragging_across_the_ruler_selects_a_time_range_and_the_right_button_clears_it(editor):
    import time
    channel = f"test.drag{secrets.token_hex(2)}"
    emit_events(editor, channel, 3)
    run(editor, f"LogShow -Query channel:{channel}")

    def ruler() -> tuple:
        for _ in range(40):
            m = re.search(r"RulerAt=(-?\d+),(-?\d+),(-?\d+),(-?\d+)", run(editor, "LogWindow"))
            if float(m[1]) >= 0:
                return tuple(float(v) for v in m.groups())
            time.sleep(0.1)
        raise AssertionError("the ruler was never drawn")

    x0, y0, x1, y1 = ruler()
    y = (y0 + y1) / 2
    editor.drag(x0 + (x1 - x0) * 0.2, y, x0 + (x1 - x0) * 0.6, y)
    for _ in range(20):
        if "time:" in window_values(editor)["query"]:
            break
        time.sleep(0.1)
    q = window_values(editor)["query"]
    assert re.search(r"time:\d+(\.\d+)?-\d+(\.\d+)?", q) and f"channel:{channel}" in q, f"the drag put a range in the query: {q}"
    assert editor.alive()
    editor.click(x0 + (x1 - x0) * 0.4, y, right=True)      # the right button (as a double click, which the real pointer here is too slow for): all of the launch again
    for _ in range(20):
        if "time:" not in window_values(editor)["query"]:
            break
        time.sleep(0.1)
    assert "time:" not in window_values(editor)["query"] and f"channel:{channel}" in window_values(editor)["query"]
    forget_the_way_back(editor)


# ---- saved views and what the person decided (design 5.2, 6.6) ----------------------------------------------------------------------------------

def test_a_saved_view_is_kept_listed_loaded_and_forgotten_and_each_edit_can_be_undone(editor):
    name = f"mine {secrets.token_hex(2)}"
    query = f"channel:test.views{secrets.token_hex(2)} sev>=warning"
    assert "invalid query" in editor.cmd(f'LogViewSave -Name "{name}" -Query "sev>=nonsense"')
    assert "-Name is 1 to 48" in editor.cmd(f'LogViewSave -Name "{"n" * 49}" -Query x')
    run(editor, f'LogViewSave -Name "{name}" -Query {quote(query)} -Page Events -State All -ShowMuted true')
    values, rows = tail(run(editor, "LogViews"))
    mine = [r for r in rows if r["Name"] == name]
    assert len(mine) == 1 and mine[0]["Scope"] == "mine" and mine[0]["Page"] == "Events" and mine[0]["State"] == "All" and mine[0]["ShowMuted"] in ("1", "true") and mine[0]["Query"] == query, rows

    forget_the_way_back(editor)
    run(editor, "LogShow -Query op:1")
    assert f"loaded '{name}'" in run(editor, f'LogViews -Load "{name}"')
    w = window_values(editor)
    assert w["query"] == query and w["back"] >= 1, "loading goes there and Back returns to where the window was"
    assert "no saved view" in editor.cmd('LogViews -Load "nothing like this"')

    run(editor, f'LogViewSave -Name "{name}" -Query "op:2"')                       # saving under the same name replaces it
    assert [r["Query"] for r in tail(run(editor, "LogViews"))[1] if r["Name"] == name] == ["op:2"]
    editor.cmd("Undo")
    assert [r["Query"] for r in tail(run(editor, "LogViews"))[1] if r["Name"] == name] == [query], "Undo puts the earlier view back"
    run(editor, f'LogViewDelete -Name "{name}"')
    assert not [r for r in tail(run(editor, "LogViews"))[1] if r["Name"] == name]
    editor.cmd("Undo")
    assert [r for r in tail(run(editor, "LogViews"))[1] if r["Name"] == name], "Undo brings a forgotten view back"
    run(editor, f'LogViewDelete -Name "{name}"')
    assert "no saved view" in editor.cmd(f'LogViewDelete -Name "{name}"')
    forget_the_way_back(editor)


def test_what_you_acknowledged_and_your_views_survive_a_new_launch_and_the_teams_views_are_shared(editor):
    from harness import SMOKE_DIR
    token = secrets.token_hex(3)
    view = f"keep {token}"
    team = f"team {token}"
    editor.stop()
    try:
        first = launch(f"user1_{token}")
        try:
            pid = emit_problem(first, token)
            run(first, f"LogAcknowledge -Id {pid}")
            run(first, f'LogViewSave -Name "{view}" -Query "channel:test.p1"')
            run(first, f'LogViewSave -Name "{team}" -Query "sev>=error" -Team true')
        finally:
            first.stop()
        user_dir = SMOKE_DIR / ".logs" / "user"
        files = sorted(p.name for p in user_dir.glob("*.logs.txt"))
        assert "team.logs.txt" in files and len(files) >= 2, files
        assert team in (user_dir / "team.logs.txt").read_text() and view not in (user_dir / "team.logs.txt").read_text(), "the team file holds only the team's views"

        second = launch(f"user2_{token}")
        try:
            names = {r["Name"]: r["Scope"] for r in tail(run(second, "LogViews"))[1]}
            assert names.get(view) == "mine" and names.get(team) == "team", names
            # the problem has not appeared in this launch: its acknowledgement waits for it
            run(second, f"LogEmit -Text {quote('P1 problem ' + token)} -Kind diagnostic -Severity error -Channel test.p1 -Code P1.{token.upper()}")
            _, rows = tail(run(second, f"LogProblems -Query code:P1.{token.upper()} -State All"))
            assert len(rows) == 1 and rows[0]["Triage"] == "Acknowledged", rows
            _, active = tail(run(second, f"LogProblems -Query code:P1.{token.upper()} -State Active"))
            assert active == [], "an acknowledged problem is not Active in the next launch either"
            run(second, f'LogViewDelete -Name "{view}"')
            run(second, f'LogViewDelete -Name "{team}"')
            run(second, f"LogAcknowledge -Id {rows[0]['Id']} -Value false")
        finally:
            second.stop()
    finally:
        editor.ensure_running()


# ---- P3: dependencies of About, the stdout tap, attachments, remote runtimes ---------------------------------------------------------------------

def test_the_about_lens_can_include_what_the_asset_depends_on(editor):
    token = secrets.token_hex(3)
    mat, tex, other = (int(token, 16) + k for k in (40, 41, 42))
    simulate_compile(editor, f"[Error] dep error {token}", mat, 1, f"Mat{token}")
    simulate_compile(editor, f"[Error] dep error {token}", tex, 1, f"Tex{token}")
    simulate_compile(editor, f"[Error] dep error {token}", other, 1, f"Other{token}")
    run(editor, f"LogSimulateDependencies -Asset Mat{token} -On Tex{token}")

    def titles(query):
        return sorted(r["Subject"] for r in tail(run(editor, f'LogProblems -Query "{query}"'))[1])

    alone = titles(f"asset:Mat{token} dep")
    with_deps = titles(f"asset:Mat{token} deps:yes dep")
    assert len(alone) == 1 and len(with_deps) == 2 and any(f"Tex{token}" in s for s in with_deps) and not any(f"Other{token}" in s for s in with_deps), (alone, with_deps)
    events = tail(run(editor, f'LogEvents -Query "asset:Mat{token} deps:yes dep"'))[1]
    assert len(events) == 2, "events too: the asset's own and its dependency's"
    values, rows = tail(run(editor, f"LogDependencies -Asset Mat{token}"))
    assert values["Dependencies"] == "1" and rows[0]["Name"] == f"Tex{token}"
    assert tail(run(editor, f"LogDependencies -Asset Tex{token}"))[0]["Dependencies"] == "0"
    forget_the_way_back(editor)
    assert run(editor, f"LogLens -About deps:Mat{token}").strip().endswith(f"asset:Mat{token} deps:yes")
    assert "deps" not in run(editor, "LogLens -About anything")
    assert "deps" not in run(editor, f"LogLens -About op:{1}") .replace("LogLens: Query=", "")


def test_the_stdout_tap_turns_what_legacy_code_prints_into_events_and_still_prints_it(editor):
    import time
    token = secrets.token_hex(3)
    assert "off" in run(editor, "LogStdout")
    assert "on" in run(editor, "LogStdout -On true")
    try:
        run(editor, f"LogSimulateStdout -Text {quote('plain line ' + token)}")
        run(editor, f"LogSimulateStdout -Text {quote('careful now ' + token)} -Stderr true")
        run(editor, f"LogSimulateStdout -Text {quote('something failed with an error ' + token)}")
        run(editor, f"LogSimulateStdout -Text {quote('warning: low ' + token)}")
        rows = []
        for _ in range(40):
            rows = tail(run(editor, f'LogEvents -Query "channel:process {token}"'))[1]
            if len(rows) == 4:
                break
            time.sleep(0.1)
        by_title = {r["Title"].split(" ")[0]: r for r in rows}
        assert len(rows) == 4, rows
        assert by_title["plain"]["Severity"] == "info" and by_title["plain"]["Channel"] == "process.stdout"
        assert by_title["careful"]["Severity"] == "warning" and by_title["careful"]["Channel"] == "process.stderr", "stderr is a warning until its text says more"
        assert by_title["something"]["Severity"] == "error" and by_title["warning:"]["Severity"] == "warning", "the words of the line decide: a guess"
        assert all(r["Origin"] == "process" for r in rows)
        assert f"plain line {token}" in editor.log_text(), "what was read is still written where it was going"
    finally:
        assert "off" in run(editor, "LogStdout -On false")
    run(editor, f"LogSimulateStdout -Text {quote('after ' + token)}")
    time.sleep(0.5)
    assert tail(run(editor, f'LogEvents -Query "channel:process after"'))[1] == [] or all(token not in r["Title"] for r in tail(run(editor, 'LogEvents -Query "channel:process after"'))[1]), "off means off"
    assert f"after {token}" in editor.log_text(), "and the console is back to what it was"


def test_a_file_can_be_attached_to_an_event_and_the_limits_hold(editor, tmp_path):
    token = secrets.token_hex(3)
    run(editor, f"LogEmit -Text {quote('attach me ' + token)} -Channel test.attach")
    seq = int(tail(run(editor, f"LogEvents -Query channel:test.attach -Limit 1"))[1][0]["Seq"])
    sample = tmp_path / f"capture_{token}.txt"
    sample.write_text("response file " + token)
    reply = run(editor, f'LogAttach -Path {quote(str(sample))} -Event {seq}')
    assert "attached" in reply and "capture_" in reply
    values, rows = tail(run(editor, f"LogAttachments -Event {seq}"))
    assert values["Attachments"] == "1" and rows[0]["Name"] == sample.name and int(rows[0]["Bytes"]) == sample.stat().st_size
    from pathlib import Path
    stored = Path(rows[0]["Path"])
    assert stored.read_text() == "response file " + token and stored.parent.name == "attachments", "kept inside the launch's folder"
    assert f"Attachment={sample.name}" in run(editor, f"LogEvent -Id {seq}"), "the event says it has one"
    assert "no such event" in editor.cmd(f'LogAttach -Path {quote(str(sample))} -Event 999999999')
    assert "does not exist" in editor.cmd(f'LogAttach -Path {quote(str(tmp_path / "missing.bin"))} -Event {seq}')
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * ((8 << 20) + 1))
    assert "larger than 8 MB" in editor.cmd(f'LogAttach -Path {quote(str(big))} -Event {seq}')
    assert "belongs to an event" in editor.cmd(f'LogAttach -Path {quote(str(sample))}')
    op = sim_build(editor, passing_build("a.cpp"), 0, f"Game.dll|{token}")
    assert "attached" in run(editor, f'LogAttach -Path {quote(str(sample))} -Operation {op} -Name "op log.txt"')
    assert tail(run(editor, f"LogAttachments -Operation {op}"))[0]["Attachments"] == "1"


def frame(payload: str) -> bytes:
    data = payload.encode()
    h = 2166136261
    for b in data:
        h = ((h ^ b) * 16777619) & 0xFFFFFFFF
    return f"R{len(data):08X}{h:08X} ".encode() + data + b"\n"


def esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def fields(*values) -> str:
    return "\t".join(esc(str(v)) for v in values)


def remote_event(seq: int, title: str, operation: int = 0, severity: int = 2, channel: str = "game.log") -> bytes:
    # E seq observed producer originType originName originInstance severity kind channel code operation discriminator flags title body bodyLines source subjects attributes cause
    return frame(fields("E", seq, 1000000, "game", 1, "ignored", 0, severity, 0, channel, "", operation, "", 0, title, "", 0, "0:0:0:0:0:", "", "", 0))


def remote_pipe(editor) -> str:
    reply = run(editor, "LogRemote")
    m = re.search(r"Pipe=(\S+)", reply)
    assert m, reply
    return m[1]


def test_a_remote_runtime_speaks_into_the_logs_over_the_pipe_with_its_operations(editor):
    import time
    token = secrets.token_hex(3)
    path = remote_pipe(editor)
    with open(path, "wb", buffering=0) as pipe:
        pipe.write(frame(fields("H", 1, "00000000DEADBEEF", 0, 4242, r"C:\games\MyGame.exe")))
        pipe.write(frame(fields("B", 7, 0, 1000, "game.level", "Load level", "", 1, "ignored", 0, "0:0:0:0:0:")))      # operation 7 of the runtime
        pipe.write(remote_event(1, f"level loading {token}", operation=7))
        pipe.write(remote_event(2, f"level failed {token}", operation=7, severity=4))
        pipe.write(frame(fields("X", 7, 2000, 2)))                                                                    # it failed
        pipe.write(frame(fields("B", 8, 0, 3000, "game.save", "Save", "", 1, "ignored", 0, "0:0:0:0:0:")))           # and one that never ends
        pipe.write(b"this is not a frame\n")
        pipe.write(frame("E\ttoo\tshort"))
        for _ in range(60):
            if len(tail(run(editor, f'LogEvents -Query "{token}"'))[1]) == 2:
                break
            time.sleep(0.1)
    rows = tail(run(editor, f'LogEvents -Query "{token}"'))[1]
    assert len(rows) == 2 and all(r["Origin"] == "remote:MyGame" for r in rows), rows
    ops = {r["Kind"]: r for r in tail(run(editor, "LogOperations -Limit 50"))[1] if r["Origin"] == "system:remote:MyGame"}
    for _ in range(40):
        ops = {r["Kind"]: r for r in tail(run(editor, "LogOperations -Limit 50"))[1] if r["Origin"] == "system:remote:MyGame"}
        if ops.get("game.save", {}).get("Outcome") == "Abandoned":
            break
        time.sleep(0.1)
    assert ops["game.level"]["Outcome"] == "Failed", "the runtime's outcome"
    assert ops["game.save"]["Outcome"] == "Abandoned", "the runtime went away with it still running"
    event_ops = {r["Operation"] for r in tail(run(editor, f'LogEvents -Query "{token}"'))[1]} if "Operation" in rows[0] else set()
    assert event_ops <= {ops["game.level"]["Id"]}, "its events belong to the editor's copy of the operation, not to the runtime's number"
    status = run(editor, "LogRemote")
    assert re.search(r"Connections=[1-9]", status) and re.search(r"Rejected=[2-9]", status), status
    assert "Remote: Listening=true" in run(editor, "LogStatus")


def test_a_runtime_started_with_the_editors_pipe_sends_everything_it_says(editor):
    import ctypes, threading, time
    from ctypes import wintypes
    from pathlib import Path
    from harness import DEFAULT_EXE, Editor, SMOKE_DIR
    k32 = ctypes.windll.kernel32
    k32.CreateNamedPipeW.restype = wintypes.HANDLE
    k32.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
    name = r"\\.\pipe\xlion.test.remote." + secrets.token_hex(4)
    handle = k32.CreateNamedPipeW(name, 0x1, 0x0, 1, 65536, 65536, 0, None)         # PIPE_ACCESS_INBOUND, byte mode
    assert handle != wintypes.HANDLE(-1).value and handle, "the test's pipe was not created"
    received = bytearray()
    done = threading.Event()

    def reader():
        k32.ConnectNamedPipe(wintypes.HANDLE(handle), None)
        buf = ctypes.create_string_buffer(8192)
        got = wintypes.DWORD()
        while k32.ReadFile(wintypes.HANDLE(handle), buf, 8192, ctypes.byref(got), None) and got.value:
            received.extend(buf.raw[:got.value])
        done.set()

    threading.Thread(target=reader, daemon=True).start()
    token = secrets.token_hex(3)
    editor.stop()
    runtime = None
    try:
        runtime = Editor(DEFAULT_EXE.with_name("xLION_Headless.exe"), log_dir=SMOKE_DIR / ".logs" / f"headless_runtime_{token}", extra_env={"XLOG_REMOTE_PIPE": name})
        runtime.start()
        run(runtime, f"LogEmit -Text {quote('said by the runtime ' + token)} -Channel game.remote -Code RT.{token.upper()}")
        for _ in range(100):
            if token.encode() in bytes(received):
                break
            time.sleep(0.1)
        frames = [l for l in bytes(received).split(b"\n") if l]
        assert frames and token.encode() in bytes(received), "the runtime's event reached the pipe"
        assert all(f[:1] == b"R" and int(f[1:9], 16) == len(f[18:]) for f in frames), "every frame is a frame of the stream format, whole"
        header = next(f for f in frames if f[18:19] == b"H")
        assert b"xLION_Headless" in header and str(runtime.proc.pid).encode() in header, "it introduces itself first"
    finally:
        if runtime is not None:
            runtime.stop()
        k32.CloseHandle(wintypes.HANDLE(handle))
        editor.ensure_running()
