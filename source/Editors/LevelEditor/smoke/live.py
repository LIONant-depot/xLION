"""live: an editor that stays up while it is rebuilt.

    python live.py start [--window]     starts an editor (headless unless --window) from a COPY of the build (xLION_live.exe / xLION_Headless_live.exe next to it)
    python live.py stop                 stops that editor (only that one: its process id is kept in Build/live.pid)
    python live.py restart [--window]   stop, then start again from the newest build
    python live.py status

Why a copy: a running exe cannot be overwritten, so the editor would have to be closed for every build. The copy is what runs; the build writes the original.
The editor engine DLLs are copied by the editor itself per Level, so they are not locked either. A change of the editor's own code needs a `restart` to be seen.
Talk to it with xcmd.py. The test suite refuses to run while this editor owns the command pipe (stop it first).
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from harness import DEFAULT_EXE, Editor, REPO

PID_FILE = REPO / "Build" / "live.pid"
LOG_FILE = REPO / "Build" / "live.log"


def read_pid():
    try:
        return int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None


def running(pid) -> bool:
    if not pid:
        return False
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


def answers() -> bool:
    try:
        Editor(DEFAULT_EXE)._roundtrip("GetProject", 2.0)
        return True
    except (OSError, TimeoutError):
        return False


def stop() -> None:
    pid = read_pid()
    if running(pid):
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
        print(f"stopped the live editor (process {pid})")
    else:
        print("no live editor of mine is running")
    PID_FILE.unlink(missing_ok=True)


def start(window: bool) -> int:
    if running(read_pid()):
        print(f"already running (process {read_pid()})")
        return 0
    if answers():
        print("an editor that is not mine owns the command pipe: not starting another")
        return 1
    original = DEFAULT_EXE if window else DEFAULT_EXE.with_name("xLION_Headless.exe")
    live = original.with_name(original.stem + "_live.exe")
    shutil.copy2(original, live)
    LOG_FILE.parent.mkdir(exist_ok=True)
    proc = subprocess.Popen([str(live)], cwd=str(live.parent), stdout=open(LOG_FILE, "wb"), stderr=subprocess.STDOUT
                            , env={**os.environ, "XEDITOR_NO_ASSERT_DIALOG": "1"}
                            , creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    PID_FILE.write_text(str(proc.pid))
    for _ in range(120):
        if proc.poll() is not None:
            print(f"the editor exited during startup (exit {proc.returncode}); see {LOG_FILE}")
            PID_FILE.unlink(missing_ok=True)
            return 1
        if answers():
            print(f"live editor up (process {proc.pid}, {live.name}); talk to it with xcmd.py")
            return 0
        time.sleep(0.5)
    print("the editor did not answer in time")
    return 1


def main(argv) -> int:
    action = argv[0] if argv else "status"
    window = "--window" in argv
    if action == "start":
        return start(window)
    if action == "stop":
        stop()
        return 0
    if action == "restart":
        stop()
        time.sleep(1.0)
        return start(window)
    if action == "status":
        pid = read_pid()
        print(f"live editor: {'running, process ' + str(pid) if running(pid) else 'not running'}; the pipe {'answers' if answers() else 'does not answer'}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
