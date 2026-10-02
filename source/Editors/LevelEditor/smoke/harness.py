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
import base64
import ctypes
import re
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
    "Save", "SaveAssets", "CreateAsset", "CreateLibrary", "RenameAsset", "MoveAsset", "DeleteAsset", "RestoreAsset",
    "RenameAssetFile", "MoveAssetFile", "DeleteAssetFileToTrash", "RestoreAssetFileFromTrash", "CopyAssetFile",
    "AddProjectModuleReference", "RemoveProjectModuleReference", "RegenerateProjectModuleSources",
    "AddScriptSourceFile", "RemoveScriptSourceFile", "SetScriptSourceFileContent", "RenameScriptSourceFile",
    "SourceControlCommit", "SourceControlPull", "SourceControlPush", "SourceControlRevert", "SourceControlStage",
    "SourceControlLock", "SourceControlUnlock",
    "MakePrefab", "MakePrefabVariant", "ApplyOverrides",
    "AddSceneDependency", "RemoveSceneDependency",
    "BindKey", "ResetKey",                       # write Project.config/Keymaps/<user>.keymap.txt
})
# Play (and Step from Stopped) saves the open level to disk first, so it is only safe on a clean document,
# where that save rewrites identical content.
SAVES_ON_START = frozenset({"Play", "Step"})


class EditorCrashed(RuntimeError):
    pass


class CommandError(AssertionError):
    """An edit command answered with an error text instead of an empty success reply."""


def b64(text: str) -> str:
    """Property paths and values travel as base64 of their TEXT form (not raw bytes)."""
    return base64.b64encode(text.encode()).decode()


@dataclass
class Session:
    name: str
    type_guid: str
    guid: str
    dirty: bool

    def __str__(self) -> str:
        return self.name


class Editor:
    def __init__(self, exe: Path = DEFAULT_EXE, *, log_dir: Optional[Path] = None, min_gap: float = 0.05) -> None:
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
        self.launches += 1
        log = open(self.log_dir / f"editor_{self.launches}.log", "wb")
        self.proc = subprocess.Popen([str(self.exe)], cwd=str(self.exe.parent), stdout=log, stderr=subprocess.STDOUT,
                                     env={**os.environ, "XEDITOR_NO_ASSERT_DIALOG": "1"})   # an assert is logged + ends the editor, never a dialog nobody clicks
        try:
            deadline = time.monotonic() + ready_timeout
            while time.monotonic() < deadline:
                if not self.alive():
                    raise EditorCrashed(f"editor exited during startup (exit {self.describe_exit()})")
                try:
                    self._roundtrip("help", timeout=5.0)
                    return
                except (OSError, TimeoutError):
                    time.sleep(0.5)
            raise TimeoutError(f"editor pipe not ready after {ready_timeout}s")
        except BaseException:
            self.stop()                     # never leave a half-started editor holding the pipe
            raise

    def stop(self) -> None:
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
                raise EditorCrashed(f"editor died running {line!r} (exit {self.describe_exit()})") from e
            raise
        finally:
            self._last_cmd_at = time.monotonic()
        if not reply:                       # success for an edit command - but also all a dying editor leaves behind
            time.sleep(0.05)
            if not self.alive():
                raise EditorCrashed(f"editor died running {line!r} (exit {self.describe_exit()})")
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
