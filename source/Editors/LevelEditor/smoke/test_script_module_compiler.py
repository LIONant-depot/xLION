"""The compiler of the ScriptModule resource: Descriptor.txt in, the module's CMake file out, through the resource pipeline like every other resource.

Two kinds of tests: the compiler exe on a throwaway project (what it writes, what it refuses, what it depends on) and the editor's pipeline around it (a descriptor
edit compiles the module, the edit of a source file never does).
"""
import re
import subprocess
import time

import pytest

from harness import REPO, compiler_exe, quote

PROJECT = REPO / "example.lionprj"
MODULE_GUID = "3849E1DE2402B1A5"
MODULE_TYPE = "8D3968CB1287FA04"
COMPILER = compiler_exe("xscript_module")
HEADER = """
[ DescriptorVersion ]
{ Major:d  Minor:d }
//-------  -------
     1        0

// New Types
< s32:d u32:g s16:C u16:H s8:c u8:h f32:f f64:F string:s wstring:S u64:G s64:D bool:c full_guid:GG enum:s >
"""


def info_text(guid: int, name: str) -> str:
    return f"""
[ DescriptorVersion ]
{{ Major:d  Minor:d }}
//-------  -------
     1        0

// New Types
< s32:d u32:g s16:C u16:H s8:c u8:h f32:f f64:F string:s wstring:S u64:G s64:D bool:c full_guid:GG enum:s >

[ xProperties : 3 ]
{{ Name:s                        Value:?                                        }}
//----------------------------  ----------------------------------------------
  "Info/Name"                   ;string    "{name}"
  "Info/Comment"                ;string    ""
  "Info/Details/GUID"           ;full_guid #{guid:016X} #8D3968CB1287FA04
"""


def descriptor_text(files, libraries=0) -> str:
    rows = [f'  "ScriptModule/Files[]" ;s64 {len(files)}']
    for i, (path, exclude) in enumerate(files):
        rows.append(f'  "ScriptModule/Files[G:{i}]/Path" ;string "{path}"')
        rows.append(f'  "ScriptModule/Files[G:{i}]/Exclude" ;bool {int(exclude)}')
    rows.append(f'  "ScriptModule/Libraries[]" ;s64 {libraries}')
    return f"{HEADER}\n[ xProperties : {len(rows)} ]\n{{ Name:s Value:? }}\n//---- -----\n" + "\n".join(rows) + "\n"


class Scratch:
    """A throwaway project with a script module, and a way to run the compiler on it the way the pipeline does. Several modules can share one project."""

    def __init__(self, root, guid: int = 0xAB, name: str = "Scratch Game", project=None):
        self.guid = f"{guid:016X}"
        self.project = project or (root / "scratch.lionprj")
        self.rest = f"ScriptModule/{guid & 0xFF:02X}/{(guid >> 8) & 0xFF:02X}/{guid:X}"           # the names the pipeline gives a resource's folders: low byte, second byte, the guid without leading zeros
        self.desc = self.project / "Descriptors" / f"{self.rest}.desc"
        (self.desc / "source_db").mkdir(parents=True, exist_ok=True)
        (self.desc / "info.txt").write_text(info_text(guid, name))
        self.out = self.project / "Cache" / "Resources" / "Platforms" / "WINDOWS"
        self.fragment = self.out / self.rest
        self.log = self.project / "Cache" / "Resources" / "Logs" / f"{self.rest}.log"

    def write(self, name: str, text: str = "// scratch\n") -> None:
        path = self.desc / "source_db" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def descriptor(self, files, libraries=0) -> None:
        (self.desc / "Descriptor.txt").write_text(descriptor_text(files, libraries))

    def compile(self) -> subprocess.CompletedProcess:
        assert COMPILER.is_file(), f"the ScriptModule compiler is not built: {COMPILER} (Windows: plugins/xscript_module.plugin/build/CreateAndBuildProject.bat, Linux: ninja xlion_compilers)"
        return subprocess.run([str(COMPILER), "-PROJECT", str(self.project), "-OPTIMIZATION", "O1", "-DEBUG", "D0"
                               , "-DESCRIPTOR", str(self.desc.relative_to(self.project)), "-OUTPUT", str(self.out)]
                              , capture_output=True, text=True, timeout=60)

    def cmake(self) -> str:
        return self.fragment.read_text().replace("\\", "/")


@pytest.fixture
def scratch(tmp_path):
    return Scratch(tmp_path)


def test_the_compiler_writes_the_cmake_file_of_the_module(scratch):
    scratch.write("game.cpp"); scratch.write("game.h"); scratch.write("Systems/ball.h")
    scratch.descriptor([("game.cpp", False), ("game.h", False), ("Systems/ball.h", False)])
    done = scratch.compile()
    assert done.returncode == 0 and "[COMPILATION_SUCCESS]" in done.stdout, done.stdout + done.stderr
    text = scratch.cmake()
    assert "scratchgame_apply" in text and "Module: Scratch Game" in text, "the module is named by its info.txt"
    assert "${SCRATCHGAME_SOURCE_ROOT}/game.cpp" in text and "${SCRATCHGAME_SOURCE_ROOT}/Systems/ball.h" in text
    assert re.search(r'get_filename_component\(SCRATCHGAME_SOURCE_ROOT ".*/source_db" ABSOLUTE\)', text), "the root of the files is made clean: source_group(TREE) compares paths as text"
    assert 'PREFIX "Scratch Game"' in text and "source_group(TREE" in text, "the folders of the module reach Visual Studio"


def test_only_what_the_descriptor_lists_is_in_the_cmake_file(scratch):
    scratch.write("listed.cpp"); scratch.write("unlisted.cpp"); scratch.write("excluded.cpp")
    scratch.descriptor([("listed.cpp", False), ("excluded.cpp", True)])
    assert scratch.compile().returncode == 0
    text = scratch.cmake()
    assert "listed.cpp" in text and "unlisted.cpp" not in text and "excluded.cpp" not in text


def test_the_compile_depends_on_the_descriptor_and_on_no_source_file(scratch):
    scratch.write("game.cpp"); scratch.write("game.h")
    scratch.descriptor([("game.cpp", False), ("game.h", False)])
    assert scratch.compile().returncode == 0
    assert (scratch.log / "Log.txt").is_file()
    assert not (scratch.log / "dependencies.txt").exists(), "a .h/.cpp in dependencies.txt would queue the compile at every edit of the file"


def test_a_listed_file_that_is_not_there_is_a_warning_and_is_left_out(scratch):
    scratch.write("here.cpp")
    scratch.descriptor([("here.cpp", False), ("gone.cpp", False)])
    done = scratch.compile()
    assert done.returncode == 0, done.stdout
    assert "gone.cpp" in done.stdout and "Warning" in done.stdout, "said once, in the log of the compile"
    assert "gone.cpp" not in scratch.cmake() and "here.cpp" in scratch.cmake()


def test_a_descriptor_that_does_not_validate_fails_the_compile_and_says_why(scratch):
    scratch.write("game.cpp")
    scratch.descriptor([("game.cpp", False), ("../escape.cpp", False)])
    done = scratch.compile()
    assert done.returncode != 0 and "[COMPILATION_SUCCESS]" not in done.stdout
    assert "../escape.cpp" in done.stdout, done.stdout


def test_a_module_without_a_descriptor_fails_the_compile(scratch):
    scratch.write("game.cpp")
    done = scratch.compile()
    assert done.returncode != 0 and "Descriptor" in done.stdout, done.stdout


def test_the_same_descriptor_gives_the_same_text(scratch):
    scratch.write("game.cpp")
    scratch.descriptor([("game.cpp", False)])
    assert scratch.compile().returncode == 0
    first = scratch.cmake()
    assert scratch.compile().returncode == 0
    assert scratch.cmake() == first, "no clock, no random: the text only changes when the descriptor does"


def test_the_output_is_never_older_than_the_descriptor_it_was_made_from(scratch):
    scratch.write("game.cpp")
    scratch.descriptor([("game.cpp", False)])
    descriptor = scratch.desc / "Descriptor.txt"
    for _ in range(2):                                             # the second compile finds the same text: it must still stamp, or the pipeline compiles at every start
        assert scratch.compile().returncode == 0
        assert scratch.fragment.stat().st_mtime_ns >= descriptor.stat().st_mtime_ns


def test_an_edit_made_while_the_compile_runs_is_newer_than_its_output(scratch):
    scratch.write("game.cpp")
    scratch.descriptor([("game.cpp", False)])
    before = time.time_ns()
    assert scratch.compile().returncode == 0
    # the output is stamped with the time the compile began: a descriptor saved after that moment is newer than it and is compiled after it, never lost
    assert scratch.fragment.stat().st_mtime_ns <= time.time_ns()
    assert scratch.fragment.stat().st_mtime_ns >= before - 2_000_000_000


# ---- the editor's pipeline around it --------------------------------------------------------------------------------------------------------------------------------------

COMPILED = PROJECT / "Cache" / "Resources" / "Platforms" / "WINDOWS" / "ScriptModule" / "A5" / "B1" / MODULE_GUID
COMPILED_LOG = PROJECT / "Cache" / "Resources" / "Logs" / "ScriptModule" / "A5" / "B1" / f"{MODULE_GUID}.log"


def wait_until(condition, timeout: float = 40.0, poll: float = 0.25):
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        time.sleep(poll)
    return False


def settle(path, quiet: float = 2.5, timeout: float = 90.0) -> None:
    """The compile the editor starts with is over: the file has been there, and unchanged, for a while."""
    end, last, since = time.time() + timeout, None, time.time()
    while time.time() < end:
        stamp = path.stat().st_mtime_ns if path.exists() else None
        if stamp != last:
            last, since = stamp, time.time()
        elif stamp is not None and time.time() - since >= quiet:
            return
        time.sleep(0.25)
    raise AssertionError(f"{path} never settled")


@pytest.fixture
def module(editor):
    settle(COMPILED)
    target = f"-Library {editor.libraries()[0][0]} -Asset {MODULE_GUID}{MODULE_TYPE}"

    class Module:
        def cmd(self, name: str, *args: str) -> str:
            return editor.cmd(f"{name} {target} {' '.join(args)}".strip(), allow_disk=True)

    return Module()


def test_a_descriptor_edit_compiles_the_module_through_the_pipeline(module):
    name = f"zz_compile_{int(time.time())}.cpp"
    assert module.cmd("AddScriptSourceFile", f"-FileName {quote(name)}") == ""
    try:
        assert wait_until(lambda: COMPILED.is_file() and name in COMPILED.read_text(errors="replace")), "the pipeline compiled the module: its CMake file lists the new file"
        assert not (COMPILED_LOG / "dependencies.txt").exists()
    finally:
        module.cmd("RemoveScriptSourceFile", f"-FileName {quote(name)}")
    assert wait_until(lambda: name not in COMPILED.read_text(errors="replace")), "and compiled again when the file went"


def test_the_edit_of_a_source_file_does_not_compile_the_module_again(module):
    name = f"zz_content_{int(time.time())}.cpp"
    assert module.cmd("AddScriptSourceFile", f"-FileName {quote(name)}") == ""
    try:
        assert wait_until(lambda: COMPILED.is_file() and name in COMPILED.read_text(errors="replace"))
        time.sleep(3.0)                                             # the compile the add queued is over
        stamps = (COMPILED.stat().st_mtime_ns, (COMPILED_LOG / "Log.txt").stat().st_mtime_ns)
        for i in range(3):
            assert module.cmd("SetScriptSourceFileContent", f"-FileName {quote(name)} -Content {quote(f'// edit {i}' + chr(10))}") == ""
            time.sleep(1.0)
        time.sleep(3.0)
        assert (COMPILED.stat().st_mtime_ns, (COMPILED_LOG / "Log.txt").stat().st_mtime_ns) == stamps, "a .cpp/.h edit does not touch the compile of the module"
    finally:
        module.cmd("RemoveScriptSourceFile", f"-FileName {quote(name)}")


def test_edits_that_come_back_to_back_are_all_compiled(module):
    """The pipeline lost an edit that came while a compile was ending (the resource stayed 'waiting' and every later edit was ignored): the CMake file of the module
    was then missing files, with nothing saying so. A person never types that fast, an AI does."""
    stamp = int(time.time())
    names = [f"zz_burst_{stamp}_{i}.cpp" for i in range(5)]
    try:
        for name in names:
            assert module.cmd("AddScriptSourceFile", f"-FileName {quote(name)}") == ""
        assert wait_until(lambda: all(n in COMPILED.read_text(errors="replace") for n in names)), "every file added in the burst is in the CMake file"
        for name in names:
            assert module.cmd("RemoveScriptSourceFile", f"-FileName {quote(name)}") == ""
        assert wait_until(lambda: not any(n in COMPILED.read_text(errors="replace") for n in names)), "and every file removed in the burst is gone from it"
    finally:
        for name in names:
            module.cmd("RemoveScriptSourceFile", f"-FileName {quote(name)}")
