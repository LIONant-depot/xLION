"""A log of when every test starts and ends, so that what takes long (and what hung) is always known.

Loaded by pytest.ini. It writes, flushed line by line to smoke/.logs/timing.log (XLION_TEST_TIMING_LOG names another file):

    2026-10-09T13:45:12.345 START  test_entities.py::test_create_entity_into_folder
    2026-10-09T13:45:19.012 END    test_entities.py::test_create_entity_into_folder  PASS  6.67s  (setup 0.91 call 5.42 teardown 0.34)

A START line with no END line below it is the test that is running (or hung): read the tail of the file while a run is going. When the session ends it appends
the slowest tests and the time per file, and writes the same numbers as tab separated rows to timing.tsv next to the log (one row per test: file, test, outcome,
seconds, setup, call, teardown) for scripts and for comparing runs. Each run starts a new log (the previous one is kept as timing.previous.log).
"""
import os
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SMOKE_DIR = Path(__file__).resolve().parent
LOG = Path(os.environ.get("XLION_TEST_TIMING_LOG") or SMOKE_DIR / ".logs" / "timing.log")
TSV = LOG.with_suffix(".tsv")

_f = None
_started = {}            # nodeid -> perf_counter at start
_phases = {}             # nodeid -> {"setup": s, "call": s, "teardown": s}
_outcome = {}            # nodeid -> "PASS" / "FAIL" / "SKIP" / "XFAIL" / "XPASS" / "ERROR"
_rows = []               # (file, test, outcome, seconds, setup, call, teardown)


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def _write(line: str) -> None:
    if _f is not None:
        _f.write(line + "\n")
        _f.flush()


def pytest_sessionstart(session):
    global _f
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        if LOG.exists():
            LOG.replace(LOG.with_name("timing.previous.log"))
        _f = open(LOG, "w", encoding="utf-8")
        _write(f"{_now()} SESSION START  pid {os.getpid()}")
    except OSError:
        _f = None                      # a log that cannot be written never stops the run


def pytest_runtest_logstart(nodeid, location):
    _started[nodeid] = time.perf_counter()
    _phases[nodeid] = {}
    _write(f"{_now()} START  {nodeid}")


def pytest_runtest_logreport(report):
    ph = _phases.setdefault(report.nodeid, {})
    ph[report.when] = ph.get(report.when, 0.0) + report.duration
    prev = _outcome.get(report.nodeid)
    if report.when == "call" or report.failed or (report.skipped and report.when == "setup"):
        if report.failed:
            out = "FAIL" if report.when == "call" else "ERROR"
        elif report.skipped:
            out = "XFAIL" if hasattr(report, "wasxfail") else "SKIP"
        else:
            out = "XPASS" if hasattr(report, "wasxfail") else "PASS"
        # a failure in teardown after a pass is reported as ERROR; never lose an earlier failure
        if prev in ("FAIL", "ERROR") and out == "PASS":
            out = prev
        _outcome[report.nodeid] = out


def pytest_runtest_logfinish(nodeid, location):
    total = time.perf_counter() - _started.pop(nodeid, time.perf_counter())
    ph = _phases.pop(nodeid, {})
    out = _outcome.pop(nodeid, "PASS")
    f, _, name = nodeid.partition("::")
    _rows.append((f, name, out, total, ph.get("setup", 0.0), ph.get("call", 0.0), ph.get("teardown", 0.0)))
    _write(f"{_now()} END    {nodeid}  {out}  {total:.2f}s  (setup {ph.get('setup', 0.0):.2f} call {ph.get('call', 0.0):.2f} teardown {ph.get('teardown', 0.0):.2f})")


def pytest_sessionfinish(session, exitstatus):
    if _f is None:
        return
    total = sum(r[3] for r in _rows)
    bad = sum(r[3] for r in _rows if r[2] in ("FAIL", "ERROR"))
    _write("")
    _write(f"{_now()} SESSION END  {len(_rows)} tests, {total / 60:.1f} min in the tests ({bad / 60:.1f} min of it in tests that failed or errored)")
    _write("")
    _write("slowest tests:")
    for r in sorted(_rows, key=lambda r: -r[3])[:25]:
        _write(f"  {r[3]:7.1f}s  {r[2]:5s}  {r[0]}::{r[1]}")
    per = defaultdict(lambda: [0.0, 0.0, 0])
    for r in _rows:
        p = per[r[0]]
        p[0] += r[3]
        p[1] += r[3] if r[2] in ("FAIL", "ERROR") else 0.0
        p[2] += 1
    _write("")
    _write("time per file (minutes; of which failing; tests):")
    for name, (t, b, n) in sorted(per.items(), key=lambda x: -x[1][0])[:25]:
        _write(f"  {t / 60:6.1f}  ({b / 60:5.1f})  {n:4d}  {name}")
    try:
        with open(TSV, "w", encoding="utf-8") as t:
            t.write("file\ttest\toutcome\tseconds\tsetup\tcall\tteardown\n")
            for r in _rows:
                t.write(f"{r[0]}\t{r[1]}\t{r[2]}\t{r[3]:.3f}\t{r[4]:.3f}\t{r[5]:.3f}\t{r[6]:.3f}\n")
    except OSError:
        pass
    _f.close()
