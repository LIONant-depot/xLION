"""The prefab spawn baseline (documentation/Editors/prefabs_plan.md, phase 0): compiles dependencies/xECSV2/smoke_test_prefab_bench.cpp in Release and runs it.

    python prefab_bench.py              full run (about two seconds)
    python prefab_bench.py --quick      fewer repetitions (a sanity check, not a measurement)
    python prefab_bench.py --debug      a Debug build with asserts
    python prefab_bench.py --check      the phase 4 targets as a gate (test_prefab_spawn.py runs it): fails when spawning slows down or allocates more

The executable and its objects go to Build/prefab_bench/<config>/<source name>. Nothing in it waits for a dialog (SetErrorMode, no abort message box), and the run has a time limit.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SRC = REPO / "dependencies" / "xECSV2" / "smoke_test_prefab_bench.cpp"
VCVARS = Path(os.environ.get("XLION_VCVARS", r"D:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"))
INCLUDES = ["", "dependencies/xECSV2/src", "dependencies/xerr", "dependencies/xresource_guid", "dependencies/xtextfile", "dependencies/xproperty", "dependencies/xresource_pipeline_v2",
            "dependencies/xstrtool", "dependencies/xcontainer", "dependencies/xdelegate", "dependencies/xscheduler", "dependencies/xmath", "dependencies/xbits"]
SOURCES = [SRC, REPO / "dependencies/xECSV2/src/xecs.cpp", REPO / "dependencies/xtextfile/source/xtextfile.cpp", REPO / "dependencies/xproperty/source/xcore/my_properties.cpp"]


def build(debug: bool, src: Path = SRC) -> Path:
    """Compiles src (a standalone xECSV2 test with its own main) with the engine sources; returns the executable. test_prefab_storage.py builds its test with it too."""
    out = REPO / "Build" / "prefab_bench" / ("debug" if debug else "release") / src.stem
    out.mkdir(parents=True, exist_ok=True)
    flags = "/MDd /Od /Zi /D_DEBUG" if debug else "/MD /O2 /DNDEBUG"
    incs = " ".join(f'/I"{REPO / i}"' for i in INCLUDES)
    srcs = " ".join(f'"{s}"' for s in [src, *SOURCES[1:]])
    exe = out / f"{src.stem}.exe"
    cmd = f'call "{VCVARS}" >nul 2>&1 && cl /nologo /std:c++20 /EHsc {flags} /DWIN32 /D_WINDOWS /DUNICODE /D_UNICODE {incs} {srcs} /Fe:"{exe}" /Fo:{out}/ /link advapi32.lib'
    bat = out / "build.bat"                       # a batch file: cmd /c would mangle the nested quotes
    bat.write_text("@echo off\r\n" + cmd + "\r\n")
    r = subprocess.run(["cmd", "/c", str(bat)], capture_output=True, text=True, cwd=out)
    if r.returncode != 0 or not exe.is_file():
        print(r.stdout[-4000:], r.stderr[-2000:])
        raise SystemExit("the benchmark did not compile")
    return exe


def main(argv) -> int:
    exe = build("--debug" in argv)
    args = [a for a in ("--quick", "--check") if a in argv]
    r = subprocess.run([str(exe), *args], capture_output=True, text=True, cwd=exe.parent, timeout=600)
    print("\n".join(l for l in r.stdout.splitlines() if not l.startswith("[Prefab")))
    if r.stderr.strip():
        print(r.stderr)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
