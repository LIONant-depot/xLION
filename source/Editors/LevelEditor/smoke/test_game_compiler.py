"""The compiler of the Game resource: the Game's list of script modules in, the CMake project of the game out.

The project of a Game (Cache/Script/<Game guid>/CMakeLists.txt) is made from the CMake file the ScriptModule compiler wrote for each module, so these tests make a throwaway project with a few
modules, compile each one, and then the Game. What the Game depends on (the log of each module's compile, never a source file), when it refuses to make the project, and
that the project is only written when it changed (its time says when it has to be configured again) are what they pin down.
"""
import re
import subprocess

import pytest

from harness import REPO
from test_script_module_compiler import HEADER, Scratch

GAME_COMPILER = REPO / "plugins" / "xgame.plugin" / "build" / "xgame_compiler.vs2022" / "Release" / "xgame_compiler.exe"
MODULE_TYPE = "8D3968CB1287FA04"
GAME_TYPE = "A3F1D6C0452E9B17"


class GameScratch:
    """The Game resource of a throwaway project, and a way to compile it the way the pipeline does."""

    def __init__(self, project, guid: int = 0xCD):
        self.project = project
        self.guid = f"{guid:016X}"
        self.rest = f"Game/{guid & 0xFF:02X}/{(guid >> 8) & 0xFF:02X}/{guid:X}"
        self.desc = project / "Descriptors" / f"{self.rest}.desc"
        self.desc.mkdir(parents=True, exist_ok=True)
        (self.desc / "info.txt").write_text(f"""{HEADER}
[ xProperties : 3 ]
{{ Name:s Value:? }}
//---- -----
  "Info/Name" ;string "Scratch Game Project"
  "Info/Comment" ;string ""
  "Info/Details/GUID" ;full_guid #{guid:016X} #{GAME_TYPE}
""")
        self.out = project / "Cache" / "Resources" / "Platforms" / "WINDOWS"
        self.log = project / "Cache" / "Resources" / "Logs" / f"{self.rest}.log"
        self.cmakelists = project / "Cache" / "Script" / f"{guid:X}" / "CMakeLists.txt"       # every Game has its own game project

    def modules(self, guids) -> None:
        rows = [f'  "Game/Modules[]" ;s64 {len(guids)}'] + [f'  "Game/Modules[G:{i}]" ;full_guid #{g:016X} #{MODULE_TYPE}' for i, g in enumerate(guids)]
        (self.desc / "Descriptor.txt").write_text(f"{HEADER}\n[ xProperties : {len(rows)} ]\n{{ Name:s Value:? }}\n//---- -----\n" + "\n".join(rows) + "\n")

    def project_builds(self, guid: int) -> None:
        """Project.config/Script.config.txt names the Game the project builds."""
        config = self.project / "Project.config"
        config.mkdir(parents=True, exist_ok=True)
        rows = [f'  "ScriptConfig/Game" ;full_guid #{guid:X} #{GAME_TYPE}', '  "ScriptConfig/ModuleRefs[]" ;s64 0']
        types = "// New Types\n< s32:d u32:g s16:C u16:H s8:c u8:h f32:f f64:F string:s wstring:S u64:G s64:D bool:c full_guid:GG enum:s >\n"      # a settings file has no DescriptorVersion
        (config / "Script.config.txt").write_text(f"{types}\n[ xProperties : {len(rows)} ]\n{{ Name:s Value:? }}\n//---- -----\n" + "\n".join(rows) + "\n")

    def compile(self) -> subprocess.CompletedProcess:
        assert GAME_COMPILER.is_file(), f"the Game compiler is not built: run {GAME_COMPILER.parents[1].parent / 'CreateAndBuildProject.bat'}"
        return subprocess.run([str(GAME_COMPILER), "-PROJECT", str(self.project), "-OPTIMIZATION", "O1", "-DEBUG", "D0"
                               , "-DESCRIPTOR", str(self.desc.relative_to(self.project)), "-OUTPUT", str(self.out)]
                              , capture_output=True, text=True, timeout=60)

    def text(self) -> str:
        return self.cmakelists.read_text()


@pytest.fixture
def game(tmp_path):
    """A project with two compiled modules (Soccer and Tennis) and a Game that lists them, not compiled yet."""
    project = tmp_path / "scratch.lionprj"
    a = Scratch(tmp_path, 0xA1B3, "Soccer", project)
    b = Scratch(tmp_path, 0xC3D5, "Tennis", project)
    a.write("soccer.cpp"); a.write("Systems/ball.h"); a.descriptor([("soccer.cpp", False), ("Systems/ball.h", False)])
    b.write("tennis.cpp"); b.descriptor([("tennis.cpp", False)])
    assert a.compile().returncode == 0 and b.compile().returncode == 0
    g = GameScratch(project)
    g.modules([0xA1B3, 0xC3D5])
    g.soccer, g.tennis = a, b
    return g


def test_the_project_includes_the_cmake_file_of_each_module_in_order(game):
    done = game.compile()
    assert done.returncode == 0 and "[COMPILATION_SUCCESS]" in done.stdout, done.stdout
    text = game.text()
    soccer, tennis = text.index("ScriptModule/B3/A1/A1B3"), text.index("ScriptModule/D5/C3/C3D5")
    assert 0 < soccer < tennis, "the modules are built in the order the Game lists them"
    assert text.count("include(") == 2 and "foreach(P IN LISTS XSCRIPT_MODULE_PREFIXES)" in text and "cmake_language(CALL ${p}_apply Game)" in text
    assert "add_library(Game SHARED" in text and "LIONCore.lib" in text and "target_precompile_headers(Game" in text


def test_the_project_names_no_place_so_it_is_the_same_on_every_machine(game):
    assert game.compile().returncode == 0
    text = game.text().replace("\\", "/")
    assert str(game.project).replace("\\", "/") not in text, "the project is found from the file's own folder"
    assert "${GAME_PROJECT_ROOT}/Cache/Resources/Platforms/WINDOWS/ScriptModule/" in text
    assert "XGPU_BIN_DIR is not set" in text and "-DXGPU_ROOT" in text, "the engine's folders come from the configure, not from the text"
    assert "${CMAKE_CURRENT_LIST_DIR}/../../.." in text, "the project is three folders up: <project>/Cache/Script/<Game>/CMakeLists.txt"
    assert "Platforms/WINDOWS/GameDll/CD" in text, "the DLL of the Game goes to the folder of that Game"


def test_the_game_depends_on_the_log_of_each_module_and_on_no_source_file(game):
    assert game.compile().returncode == 0
    deps = re.sub(r"[\\]+", "/", (game.log / "dependencies.txt").read_text().lower())    # the file writes its backslashes doubled
    assert "scriptmodule/b3/a1/a1b3.log/log.txt" in deps and "scriptmodule/d5/c3/c3d5.log/log.txt" in deps
    for name in ("soccer.cpp", "tennis.cpp", "ball.h", "source_db", "descriptor.txt"):
        assert name not in deps, f"{name} must not be a dependency: its edit would compile the Game"


def test_the_project_is_written_only_when_it_changed(game):
    assert game.compile().returncode == 0
    first, stamp = game.text(), game.cmakelists.stat().st_mtime_ns
    assert game.compile().returncode == 0
    assert game.text() == first and game.cmakelists.stat().st_mtime_ns == stamp, "nothing changed: the file is left alone (its time is when the project must be configured again)"
    game.tennis.write("net.cpp"); game.tennis.descriptor([("tennis.cpp", False), ("net.cpp", False)])
    assert game.tennis.compile().returncode == 0
    assert game.compile().returncode == 0
    assert game.text() != first and game.cmakelists.stat().st_mtime_ns > stamp, "a module's CMake file changed: the project says so"


def test_a_module_that_is_not_in_the_project_fails_the_compile(game):
    game.modules([0xA1B3, 0xFFFF])
    done = game.compile()
    assert done.returncode != 0 and "[COMPILATION_SUCCESS]" not in done.stdout
    assert "000000000000FFFF" in done.stdout and "not in the project" in done.stdout


def test_a_module_that_was_not_compiled_fails_the_compile_and_says_so(game):
    game.tennis.fragment.unlink()
    done = game.compile()
    assert done.returncode != 0 and "000000000000C3D5" in done.stdout and "no CMake file" in done.stdout, done.stdout


def test_a_module_whose_last_compile_failed_is_not_used_stale(game):
    # the descriptor was saved after the CMake file was made: the module compile that should have made a new one failed or has not run
    game.tennis.descriptor([("tennis.cpp", False), ("../escape.cpp", False)])
    done = game.compile()
    assert done.returncode != 0 and "older than its Descriptor.txt" in done.stdout, done.stdout


def test_a_module_listed_twice_fails_validation(game):
    game.modules([0xA1B3, 0xA1B3])
    done = game.compile()
    assert done.returncode != 0 and "listed twice" in done.stdout, done.stdout


def test_a_game_without_modules_makes_an_empty_project(game):
    game.modules([])
    assert game.compile().returncode == 0
    assert "include(" not in game.text()


def test_the_compiled_resource_is_not_older_than_its_descriptor(game):
    for _ in range(2):
        assert game.compile().returncode == 0
        stamp = (game.out / game.rest)
        assert stamp.is_file() and stamp.stat().st_mtime_ns >= (game.desc / "Descriptor.txt").stat().st_mtime_ns


def test_the_project_configures_and_the_folders_of_the_modules_reach_visual_studio(game, tmp_path):
    assert game.compile().returncode == 0
    build = tmp_path / "build"
    done = subprocess.run(["cmake", "-S", str(game.cmakelists.parent), "-B", str(build), "-G", "Visual Studio 17 2022", "-A", "x64"
                           , f"-DXGPU_ROOT={REPO}", f"-DXGPU_BIN_DIR={REPO / 'Build' / 'xLION.vs2022'}"], capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stdout + done.stderr
    filters = (build / "Game.vcxproj.filters").read_text()
    assert 'Include="Soccer"' in filters and 'Include="Soccer\\Systems"' in filters and 'Include="Tennis"' in filters, "a folder per module, with the module's own subfolders"
    assert "ball.h" in (build / "Game.vcxproj").read_text() and "tennis.cpp" in (build / "Game.vcxproj").read_text()


def test_every_game_writes_its_own_project_whatever_the_project_names(game):
    """Each Game resource is compiled into Cache/Script/<its guid>/: Script.config.txt (the default Game of the editor) does not decide which Game writes a project."""
    game.project_builds(0xEF)                                              # the default Game is another one
    other = GameScratch(game.project, 0xEF)
    other.modules([0xA1B3])
    assert game.compile().returncode == 0 and other.compile().returncode == 0
    assert game.cmakelists.is_file() and other.cmakelists.is_file() and game.cmakelists != other.cmakelists, "a project each"
    assert (game.out / game.rest).is_file() and (other.out / other.rest).is_file()
    assert "GameDll/CD" in game.text().replace("\\", "/") and "GameDll/EF" in other.text().replace("\\", "/"), "each one builds its DLL into its own folder"
    assert other.text().count("include(") == 1 and game.text().count("include(") == 2, "and has the modules it lists"
    game.modules([0xA1B3, 0xA1B3])
    assert game.compile().returncode != 0, "and it is checked: a module listed twice still fails"
