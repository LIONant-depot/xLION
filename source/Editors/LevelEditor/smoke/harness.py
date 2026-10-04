"""LevelEditor smoke-test harness: launches the editor, talks to its Command Console pipe, detects crashes.

The editor exposes one named pipe (byte mode, one request per connection): write "<command>\\n", read the
response until the server disconnects. Commands are dispatched on the editor's main thread, one per frame.

Command grammar (xeditor::host::dispatch):
    <Command> ...                   workspace command      (OpenLevel, Play, Stop, Save, ListLevels, ...)
    <Session name>\\<Command> ...    command on a session   (Main Level\\CreateEntity ...)
    help | list                     command names / open sessions
Edit commands return an EMPTY string on success and an error text on failure; query commands return text.
"""
from __future__ import annotations

import os
import ctypes
import re
import shutil
import subprocess
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

PIPE = r"\\.\pipe\xEditor_Console"
SMOKE_DIR = Path(__file__).resolve().parent
GOLDEN_DIR = SMOKE_DIR / "golden"
REPO = SMOKE_DIR.parents[3]
# Debug on purpose: asserts (CRT assert, IM_ASSERT, xproperty/xecs asserts) only exist there. Pass --exe for another build.
DEFAULT_EXE = REPO / "Build" / "xLION.vs2022" / "Debug" / "xLION.exe"


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = wintypes.HANDLE
_k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
_k32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
_k32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
_k32.CancelIoEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_INVALID_HANDLE = wintypes.HANDLE(-1).value
_GENERIC_RW = 0xC0000000
_OPEN_EXISTING = 3
_EOF_ERRORS = (109, 233)      # ERROR_BROKEN_PIPE / ERROR_PIPE_NOT_CONNECTED: the server hung up after its reply


# Commands that write the developer's own project data. The suite runs against the real example project, so a
# test must opt in (allow_disk=True) instead of touching disk by accident.
DISK_WRITERS = frozenset({
    "Save", "SaveAssets", "SaveAllEditors", "CreateAsset", "CreateLibrary", "RenameAsset", "MoveAsset", "DeleteAsset", "RestoreAsset",
    "RenameAssetFile", "MoveAssetFile", "DeleteAssetFileToTrash", "RestoreAssetFileFromTrash", "CopyAssetFile",
    "AddProjectModuleReference", "RemoveProjectModuleReference", "RegenerateProjectModuleSources", "SetLevelGame",
    "AddScriptSourceFile", "RemoveScriptSourceFile", "SetScriptSourceFileContent", "RenameScriptSourceFile", "RescanScriptModule",
    "SourceControlCommit", "SourceControlPull", "SourceControlPush", "SourceControlRevert", "SourceControlStage",
    "SourceControlLock", "SourceControlUnlock",
    "MakePrefab", "MakePrefabVariant", "ApplyOverrides",
    "AddSceneDependency", "RemoveSceneDependency",
    "BindKey", "ResetKey",                       # write Project.config/Keymaps/<user>.keymap.txt
})
# Play (and Step from Stopped) saves the open level to disk first, so it is only safe on a clean document,
# where that save rewrites identical content.
SAVES_ON_START = frozenset({"Play", "Step"})


# What the Vulkan validation layers' complaints look like in the editor's stdout, and the one function that reads them from text: the way the harness has always found them. The editor
# also records each as a problem of the Logs (Editor.vulkan_problems); the report compares the two until the Logs are trusted alone.
VK_ERROR_RE   = re.compile(r"ERROR VK\d \([A-Z_]+\):\s*\n?([^\n]{0,200})")
VK_WARNING_RE = re.compile(r"WARNING VK\d \([A-Z_]+\):\s*\n?([^\n]{0,200})")


def vulkan_messages_from_text(text: str) -> tuple[dict, dict]:
    """({error message: count}, {warning message: count}) found in an editor's stdout."""
    errors, warnings = {}, {}
    for m in VK_ERROR_RE.finditer(text):
        errors[m[1].strip()] = errors.get(m[1].strip(), 0) + 1
    for m in VK_WARNING_RE.finditer(text):
        warnings[m[1].strip()] = warnings.get(m[1].strip(), 0) + 1
    return errors, warnings


class EditorCrashed(RuntimeError):
    pass


class CommandError(AssertionError):
    """An edit command answered with an error text instead of an empty success reply."""


def quote(text: str) -> str:
    """A value as the editor's command line wants it: in quotes, a quote as \\" and the backslashes in front of one doubled (the Windows command line rules)."""
    out, backslashes = ['"'], 0
    for ch in text:
        if ch == "\\":
            backslashes += 1
        elif ch == '"':
            out.append("\\" * (2 * backslashes + 1) + '"'); backslashes = 0
        else:
            out.append("\\" * backslashes + ch); backslashes = 0
    out.append("\\" * (2 * backslashes) + '"')
    return "".join(out)


@dataclass
class Session:
    name: str
    type_guid: str
    guid: str
    dirty: bool

    def __str__(self) -> str:
        return self.name


class Editor:
    def __init__(self, exe: Path = DEFAULT_EXE, *, log_dir: Optional[Path] = None, min_gap: float = 0.05, extra_env: Optional[dict] = None, args: Optional[list] = None) -> None:
        self.extra_env = dict(extra_env or {})
        self.args = [str(x) for x in (args or [])]        # the command line of the editor (a project folder, ...)
        self.exe = Path(exe)
        self.log_dir = Path(log_dir) if log_dir else SMOKE_DIR / ".logs"
        self.min_gap = min_gap
        self.proc: Optional[subprocess.Popen] = None
        self.launches = 0
        self._last_cmd_at = 0.0

    # ------------------------------------------------------------------ process
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def exit_code(self) -> Optional[int]:
        return None if self.proc is None else self.proc.poll()

    def start(self, ready_timeout: float = 120.0) -> None:
        if not self.exe.is_file():
            raise FileNotFoundError(f"editor exe not found: {self.exe} (build xLION or pass --exe)")
        # The pipe admits one server. If something already answers on it, it is somebody's editor (maybe a person's, with unsaved work):
        # the tests must not drive it by accident. Close it, or run the suite when no editor is open.
        try:
            self._roundtrip("help", timeout=1.0)
        except (OSError, TimeoutError):
            pass
        else:
            raise RuntimeError("an editor is already running and owns the command pipe; close it before running the smoke tests (refusing to drive it)")
        self.log_dir.mkdir(exist_ok=True)
        # The editor's own trace (LevelEditor.trace.log, with the crash handler's stack when it ran) is truncated by every launch: keep the one of
        # the launch that is ending, so an editor that died (and is being restarted) leaves its evidence behind.
        trace = self.exe.parent / "LevelEditor.trace.log"
        if self.launches and trace.is_file():
            try:
                shutil.copy2(trace, self.log_dir / f"trace_{self.launches}.log")
            except OSError:
                pass
        self.launches += 1
        log = open(self.log_dir / f"editor_{self.launches}.log", "wb")
        self.proc = subprocess.Popen([str(self.exe), *self.args], cwd=str(self.exe.parent), stdout=log, stderr=subprocess.STDOUT,
                                     env={**os.environ, "XEDITOR_NO_ASSERT_DIALOG": "1", "XLOG_USER_DIR": str(SMOKE_DIR / ".logs" / "user"), "XLOG_LOGS_DIR": str(SMOKE_DIR / ".logs" / "sessions"), **self.extra_env})   # an assert is logged + ends the editor, never a dialog nobody clicks
        try:
            deadline = time.monotonic() + ready_timeout
            while time.monotonic() < deadline:
                if not self.alive():
                    raise EditorCrashed(f"editor exited during startup (exit {self.describe_exit()}){self.crash_summary()}")
                try:
                    self._roundtrip("help", timeout=5.0)
                    return
                except (OSError, TimeoutError):
                    time.sleep(0.5)
            raise TimeoutError(f"editor pipe not ready after {ready_timeout}s")
        except BaseException:
            self.stop()                     # never leave a half-started editor holding the pipe
            raise

    def stop(self, graceful: bool = True) -> None:
        """Ends the editor: it is asked to exit first (so its Logs end the launch cleanly, the way a person closing it does) and is killed if it has not gone in a few seconds."""
        if self.alive() and graceful:
            try:
                self.cmd("Exit", timeout=5.0)
            except Exception:
                pass
            try:
                self.proc.wait(timeout=8)
            except Exception:
                pass
        if self.alive():
            self.proc.kill()
            self.proc.wait(timeout=10)

    def ensure_running(self) -> None:
        if not self.alive():
            self.start()

    def log_text(self) -> str:
        """Everything the editor process has printed so far (its stdout is redirected to this run's log file)."""
        return (self.log_dir / f"editor_{self.launches}.log").read_text(errors="replace")

    def describe_exit(self) -> str:
        code = self.exit_code()
        return "running" if code is None else f"{code & 0xFFFFFFFF:#010x}"

    def crash_summary(self, frames: int = 8) -> str:
        """What the editor itself wrote about how it died (its LevelEditor.trace.log: the assert or exception and the frames of the editor's own code), so a failure says it without a trip to the log."""
        trace = self.exe.parent / "LevelEditor.trace.log"
        try:
            lines = trace.read_text(errors="replace").splitlines()
        except OSError:
            return ""
        starts = [i for i, l in enumerate(lines) if l.startswith(("CRT report", "SEH exception"))]
        if not starts:
            return ""
        block = lines[starts[-1]:]
        head = block[0][:240]
        mine = [l.split(" ", 2)[2][:200] for l in block[1:] if l.startswith(("CRT stack", "SEH stack")) and re.search(r"(xecs::|xlevel::|xscene::|xlioncore::|level_editor::|xeditor::)", l) and "CrtReportHook" not in l]
        if not mine:                                                          # no frame of the editor's own code: the first frames as they are
            mine = [l.split(" ", 2)[2][:200] for l in block[1:] if l.startswith(("CRT stack", "SEH stack")) and "CrtReportHook" not in l]
        return "\n  " + "\n  ".join([head] + mine[:frames])

    # ------------------------------------------------------------------ pipe
    def _roundtrip(self, line: str, timeout: float) -> str:
        """One request/response. Connecting retries while the server re-creates its pipe instance; a reply
        that does not finish within `timeout` is cancelled and raises TimeoutError."""
        deadline = time.monotonic() + timeout
        while True:
            h = _k32.CreateFileW(PIPE, _GENERIC_RW, 0, None, _OPEN_EXISTING, 0, None)
            if h != _INVALID_HANDLE:
                break
            err = ctypes.get_last_error()
            if time.monotonic() >= deadline:
                raise TimeoutError(f"pipe not available for {line!r}: {ctypes.WinError(err)}")
            time.sleep(0.05)

        timer = threading.Timer(max(0.1, deadline - time.monotonic()), lambda: _k32.CancelIoEx(h, None))
        timer.start()
        try:
            data = line.encode() + b"\n"
            written = wintypes.DWORD()
            if not _k32.WriteFile(h, data, len(data), ctypes.byref(written), None):
                raise OSError(f"write to pipe failed: {ctypes.WinError(ctypes.get_last_error())}")
            chunks, buf, got = [], ctypes.create_string_buffer(4096), wintypes.DWORD()
            while True:
                if not _k32.ReadFile(h, buf, len(buf), ctypes.byref(got), None):
                    if ctypes.get_last_error() in _EOF_ERRORS:
                        break
                    raise TimeoutError(f"no complete reply to {line!r} within {timeout}s")
                if got.value == 0:
                    break
                chunks.append(buf.raw[:got.value])
            return b"".join(chunks).decode(errors="replace")
        finally:
            timer.cancel()
            _k32.CloseHandle(h)

    def cmd(self, line: str, *, timeout: float = 30.0, allow_disk: bool = False) -> str:
        """Send one command; returns the reply with trailing whitespace trimmed."""
        name = re.split(r"[\\/]", line.split(" -", 1)[0])[-1].split()[0]   # "<session>\<Cmd> -Opt ..." or "LevelEditor/Edit/<Cmd>"
        if name in DISK_WRITERS and not allow_disk:
            raise PermissionError(f"{name} writes project data; pass allow_disk=True if this test really means to")
        if name in SAVES_ON_START and any(s.dirty for s in self.sessions()):
            raise PermissionError(f"{name} saves the open level first; refusing while a session has unsaved edits")
        gap = self.min_gap - (time.monotonic() - self._last_cmd_at)
        if gap > 0:
            time.sleep(gap)
        try:
            reply = self._roundtrip(line, timeout)
        except (TimeoutError, OSError) as e:
            if not self.alive():
                raise EditorCrashed(f"editor died running {line!r} (exit {self.describe_exit()}){self.crash_summary()}") from e
            raise
        finally:
            self._last_cmd_at = time.monotonic()
        if not reply:                       # success for an edit command - but also all a dying editor leaves behind
            time.sleep(0.05)
            if not self.alive():
                raise EditorCrashed(f"editor died running {line!r} (exit {self.describe_exit()}){self.crash_summary()}")
        return reply.rstrip()

    def ok(self, line: str, **kw) -> None:
        """An edit command: success is an empty reply."""
        reply = self.cmd(line, **kw)
        if reply:
            raise CommandError(f"{line!r} -> {reply!r}")

    def fails(self, line: str, **kw) -> str:
        """A command that must be refused with a message (never crash, never succeed silently)."""
        reply = self.cmd(line, **kw)
        assert reply, f"{line!r} was accepted but should have been refused"
        return reply

    def vulkan_problems(self) -> list[dict]:
        """What the editor's Logs hold of the Vulkan validation layers' complaints: [{Severity, Code, Occurrences, Title}], one per problem. The editor records them
        (xeditor::LogGpuError / LogGpuWarning) as problems of producer vulkan.validation; the tests that make up a line use another producer, so they are not in this."""
        reply = self.cmd('LogProblems -Query "producer:vulkan.validation" -Limit 500')
        head, _, body = reply.partition("\n\n")
        lines = [l for l in body.splitlines() if l]
        if len(lines) < 2:
            return []
        names = lines[0].split("\t")
        return [dict(zip(names, l.split("\t"))) for l in lines[1:]]

    def post_key(self, vk: int, hold: float = 0.15, sys: bool = False, while_down=None):
        """A real key press for the editor's window: WM_KEYDOWN / WM_KEYUP posted to it, so it goes through the Win32 key table, xGPU's
        keyboard and ImGui like a keystroke would (PressKeys skips all of that). Needs no focus. vk is a Win32 virtual-key code (VK_F1 = 0x70).
        sys=True posts the SYS variants, which is how Windows delivers Alt (VK_MENU = 0x12) and every key pressed while Alt is held.
        while_down, if given, is called once the key has been down for the hold time (before it is released); its result is returned."""
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        pid = self.proc.pid
        found: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def each(hwnd, _):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
                found.append(hwnd)
            return True

        user32.EnumWindows(each, 0)
        if not found:
            raise AssertionError("post_key: the editor has no visible window")
        scan = user32.MapVirtualKeyW(vk, 0)
        for hwnd in found:
            user32.PostMessageW(hwnd, 0x0104 if sys else 0x0100, vk, 1 | (scan << 16))      # WM_KEYDOWN / WM_SYSKEYDOWN
        time.sleep(hold)                                                                    # a few frames, so ImGui sees it down
        result = while_down() if while_down else None
        for hwnd in found:
            user32.PostMessageW(hwnd, 0x0105 if sys else 0x0101, vk, 1 | (scan << 16) | (1 << 30) | (1 << 31)) # WM_KEYUP / WM_SYSKEYUP
        time.sleep(0.1)
        return result

    def double_click(self, x: float, y: float) -> None:
        """Two quick left clicks at the SCREEN point (x, y): what ImGui calls a double click (the pointer is placed once, the presses come 60 ms apart)."""
        self.click(x, y, double=True)

    def wheel(self, x: float, y: float, notches: int, ctrl: bool = False) -> None:
        """The real mouse wheel turned by `notches` (positive = away from the person, the way that scrolls up) with the pointer at the SCREEN point (x, y), Ctrl held if asked.
        Like click: the window is brought forward and the real pointer goes there, then back."""
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
        pid = self.proc.pid
        found: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def each(hwnd, _):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
                found.append(hwnd)
            return True

        user32.EnumWindows(each, 0)
        if not found:
            raise AssertionError("wheel: the editor has no visible window")
        if user32.GetForegroundWindow() != found[0]:
            user32.SetForegroundWindow(found[0])
            time.sleep(0.6)
        old = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(old))
        try:
            user32.SetCursorPos(int(x), int(y))
            time.sleep(0.4)
            if ctrl: user32.keybd_event(0x11, 0, 0, 0)                  # VK_CONTROL down
            time.sleep(0.1)
            for _ in range(abs(notches)):
                user32.mouse_event(0x0800, 0, 0, (120 if notches > 0 else -120) & 0xFFFFFFFF, 0)   # MOUSEEVENTF_WHEEL, one notch
                time.sleep(0.15)
            if ctrl: user32.keybd_event(0x11, 0, 2, 0)                  # VK_CONTROL up (KEYEVENTF_KEYUP)
            time.sleep(0.3)
        finally:
            user32.SetCursorPos(old.x, old.y)

    def drag(self, x: float, y: float, to_x: float, to_y: float) -> None:
        """Press at the screen point (x, y), move to (to_x, to_y) in steps, release: a drag with the real pointer (see click)."""
        self.click(x, y, to=(to_x, to_y))

    def click(self, x: float, y: float, hold: float = 0.15, shift: bool = False, right: bool = False, to: tuple[float, float] | None = None, double: bool = False) -> None:
        """A real left click at the SCREEN point (x, y) - the coordinates ImGui and the editor's queries (LogWindow's BackAt...) report. It uses the real pointer: xGPU only
        hands ImGui a pointer position while Windows says the pointer is over the window, which messages posted to it cannot keep true. So the editor's window is brought
        forward (a click focuses a window, and ImGui ignores the pointer of one that is not focused), the pointer goes there, presses and releases, and returns to where the
        person had it."""
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        try:
            user32.SetProcessDPIAware()                           # the coordinates are physical pixels, as ImGui's are
        except Exception:
            pass
        pid = self.proc.pid
        found: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def each(hwnd, _):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
                found.append(hwnd)
            return True

        user32.EnumWindows(each, 0)
        if not found:
            raise AssertionError("click: the editor has no visible window")
        if user32.GetForegroundWindow() != found[0]:
            user32.SetForegroundWindow(found[0])
            time.sleep(0.6)
        old = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(old))
        try:
            user32.SetCursorPos(int(x), int(y))
            time.sleep(0.4)                                       # frames pass with the pointer over the item
            if shift: user32.keybd_event(0x10, 0, 0, 0)           # VK_SHIFT down
            time.sleep(0.1)
            user32.mouse_event(0x0008 if right else 0x0002, 0, 0, 0, 0)    # MOUSEEVENTF_LEFTDOWN / RIGHTDOWN
            time.sleep(hold)
            if double:
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                time.sleep(0.06)
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                time.sleep(hold)
            if to:
                for i in range(1, 11):                            # a drag: the pointer travels, frames pass on the way
                    user32.SetCursorPos(int(x + (to[0] - x) * i / 10), int(y + (to[1] - y) * i / 10))
                    time.sleep(0.08)
                time.sleep(0.2)
            user32.mouse_event(0x0010 if right else 0x0004, 0, 0, 0, 0)    # MOUSEEVENTF_LEFTUP / RIGHTUP
            if shift: user32.keybd_event(0x10, 0, 2, 0)           # VK_SHIFT up (KEYEVENTF_KEYUP)
            time.sleep(0.3)
        finally:
            user32.SetCursorPos(old.x, old.y)

    def wait_for(self, line: str, pattern: str, *, timeout: float = 60.0, poll: float = 0.25) -> str:
        """Poll a query until its reply matches the regex."""
        deadline = time.monotonic() + timeout
        reply = ""
        while time.monotonic() < deadline:
            reply = self.cmd(line)
            if re.search(pattern, reply):
                return reply
            time.sleep(poll)
        raise TimeoutError(f"{line!r} never matched /{pattern}/ within {timeout}s (last: {reply!r})")

    # ------------------------------------------------------------------ typed helpers
    def commands(self) -> list[str]:
        """Workspace command names, in the order `help` prints them."""
        lines = self.cmd("help").splitlines()
        return [l.strip() for l in lines[1:lines.index("Sessions:")]] if "Sessions:" in lines else []

    def sessions(self) -> list[Session]:
        out = []
        for line in self.cmd("list").splitlines():
            m = re.match(r"(.+?)\s{2}type=(\w+) inst=(\w+) dirty=(\d)", line)
            if m:
                out.append(Session(m[1], m[2], m[3], m[4] == "1"))
        return out

    def levels(self) -> list[tuple[str, str]]:
        """[(guid, name)] from ListLevels, sorted by name (the editor's own order is not stable)."""
        return sorted(((m[1], m[2].strip()) for l in self.cmd("ListLevels").splitlines() if (m := re.match(r"(\w{16})\s+(.*)", l))), key=lambda g: g[1])

    def play_state(self) -> str:
        return re.search(r"PlayState=(\w+)", self.cmd("GetPlayState"))[1]

    def wait_play_state(self, state: str, timeout: float = 60.0) -> None:
        self.wait_for("GetPlayState", rf"PlayState={state}\b", timeout=timeout)

    def entities(self, session: str, scene: str) -> dict[str, str]:
        """{entity id: label} for a scene."""
        return {m[1]: m[2] for l in self.cmd(f"{session}\\ListEntities -Scene {scene}").splitlines()
                if (m := re.match(r"(\w{8})\s+(.*)", l))}

    def describe(self, session: str, scene: str, entity: str) -> str:
        return self.cmd(f"{session}\\DescribeEntity -Scene {scene} -Id {entity}")

    def property_value(self, session: str, scene: str, entity: str, path: str) -> str:
        m = re.search(rf"^\s*{re.escape(path)} = (\S+)", self.describe(session, scene, entity), re.M)
        assert m, f"{path} not found in DescribeEntity for {entity}"
        return m[1]

    # ------------------------------------------------------------------ libraries / assets (resource editors)
    def libraries(self) -> list[tuple[str, str]]:
        """[(guid, path)] from ListLibraries."""
        return [(m[1], m[2].strip()) for l in self.cmd("ListLibraries").splitlines() if (m := re.match(r"(\S+)\s+(.*)", l))]

    def list_assets(self, library: str, parent: str | None = None) -> list[tuple[str, str, str]]:
        """[(guid, type, name)] - one folder level of ListAssets (Folder rows included)."""
        cmd = f"ListAssets -Library {library}" + (f" -Parent {parent}" if parent else "")
        out = []
        for l in self.cmd(cmd).splitlines():
            m = re.match(r"(\S+)\s+(\S+)\s+(.*)", l.strip())
            if m:
                out.append((m[1], m[2], m[3].strip()))
        return out

    def find_asset(self, type_name: str, library: str | None = None) -> tuple[str, str] | None:
        """(guid, name) of the first non-Trash, non-"Default*" asset of type_name found by walking the asset
        tree breadth-first. "Default*" placeholders are skipped - several are shipped uncompiled in this dev
        project (empty Cache/Resources folder) and asserting on that is a separate, pre-existing gap, not
        something a resource-editor smoke test should trip over."""
        lib = library or self.libraries()[0][0]
        queue: list[str | None] = [None]
        seen: set[str | None] = set()
        while queue:
            parent = queue.pop(0)
            if parent in seen:
                continue
            seen.add(parent)
            for guid, typ, name in self.list_assets(lib, parent):
                if typ == "Folder":
                    if name != "Trash":
                        queue.append(guid)
                elif typ == type_name and "Default" not in name:
                    return guid, name
        return None
