# LevelEditor smoke tests

Regression tests for the editor's **command surface** - the same commands the AI/CLI uses. They launch the
real editor (`xLION.exe`), drive it through its Command Console pipe, and assert on replies.

```bat
pip install pytest
cd source\Editors\LevelEditor\smoke
python -m pytest -q                     # all tests, launches the DEBUG build itself (asserts exist only there)
python -m pytest test_play.py -q        # one file
python -m pytest -q --exe <path>        # a different build
python -m pytest -q --update-golden     # accept a deliberate change to the command list
```

Build first (MSBuild `Build\xLION.vs2022\xLION.sln`, target `xLION`, config `Debug`), and close any running
editor - the pipe (`\\.\pipe\xEditor_Console`) admits one server.

**Known project-data gap:** the `level` fixture (`conftest.py`) opens `editor.levels()[0]` - the example
project's first Level asset. This dev project currently has none (`ListLevels` replies empty), so every test
that depends on `level` errors with `IndexError: list index out of range` at fixture setup, not a real
regression - it fails the same way before and after any source change. `test_resource_editors.py` and the
`editor`-only tests are unaffected (they don't need an open Level). Fix: create one real Level asset in
`example.lionprj` via the asset browser or `CreateAsset`, then this whole class of failures goes away.

## How it works

| File | Role |
|---|---|
| `harness.py` | `Editor`: launches/kills the process, pipe client (stdlib `ctypes`, no CLI executable needed), typed helpers (`sessions()`, `entities()`, `describe()`, `wait_play_state()`, ...) |
| `conftest.py` | fixtures. `editor` = one process for the run, restarted if a test kills it. `level` = the example project's first level opened **clean**, closed without saving afterwards. `_editor_alive` = a crash fails exactly the test that caused it, with the command and exit code |
| `test_*.py` | the tests. Plain functions and `assert` |
| `golden/commands.txt` | the expected workspace command names; a removed/added command fails until you `--update-golden` |

Command grammar: `<Command> ...` (workspace) or `<Session name>\<Command> ...` (`Main Level\CreateEntity ...`).
**Edit** commands reply with an empty string on success; **query** commands reply with text; refusals are text.
Property paths and values are **text in quotes** (`quote("5.000000")`; rules in documentation/Editors/command_line.md).

## Rules that keep the suite safe

The suite runs against the developer's real `example.lionprj`.

- Tests never save. The harness raises `PermissionError` for commands that write project data (`Save`, `Create*`,
  `Rename*`, source control, ...) unless the call passes `allow_disk=True`.
- `Play` saves the open level first, so the harness refuses `Play`/`Step` while a session has unsaved edits. Create
  test entities **after** the `Play` if you need both. Use the `level` fixture (clean) for any Play test.
- Everything a test creates lives only in memory (`level.new_entity()` mints ids `7E57xxxx`) and is discarded by
  `Close -Save 0` in the fixture teardown.
- `project_guard.py` (loaded by `pytest.ini`) makes that true even for Play: it snapshots `Descriptors/` and `Project.config/`
  at the start and at the end deletes what the run created and puts the Scene/Level files it rewrote back byte for byte
  (work in progress you had before the run is kept, not reset to git). It prints `[project_guard] put example.lionprj back`
  when it had to. A run that is killed midway skips this, so run `git status` in `example.lionprj` after one.
- A test must not depend on fixed entity ids from the project; discover them (`level.find_with_component("Transform")`).

## Writing a test

```python
def test_create_entity_undo_redo(level):
    before = level.entities()
    entity = level.new_entity()                     # Main Level\CreateEntity ... (must reply "")
    assert entity in level.entities() and level.dirty()
    assert level.cmd("Undo") == "Undone"
    assert level.entities() == before
```

## Known gaps (good next tests)

- **Scene dependency cycle test**: Need to verify the exact error message format from the source
- **Selection**: `GetSelection` query command is missing, so `Select`, `ToggleMultiSelect`, and `ClearSelection` cannot be tested yet
- **Save gating**: `Save` refused during Play (needs `allow_disk=True` and care)

## Test files

| File | Description |
|---|---|
| `test_components.py` | AddComponent/RemoveComponent, undo/redo, component list |
| `test_entities.py` | Entity create/delete, parent/child hierarchy, undo/redo |
| `test_folders.py` | Folder create/delete/move and undo/redo |
| `test_scenes_and_levels.py` | Scenes and levels: open/close, dependencies, list formats |
| `test_undo_redo.py` | Undo/redo: multiple edits, branch discard, dirty flag |
| `test_prefabs.py` | Prefab operations: instantiate, revert, hierarchy overrides, apply; and (phase 0 of the prefab plan) what a prefab does across a save and a reload, with the known-wrong cases as strict `xfail`; (phase 1) a prefab stored as a scene, its names, a group with references between its members, the old format read and converted (`golden/prefab_v1` holds the example's prefabs as they were), `UpgradeProject` |
| `test_prefab_storage.py` | No editor: compiles `dependencies/xECSV2/smoke_test_prefab_storage.cpp` in Debug and runs it - the engine side of prefab storage (scene format, references kept inside, names, the rules `Save` checks, the old format) |
| `test_entity_ids.py` | 64-bit permanent ids (phase 2 of the prefab plan): the engine side (no editor: compiles `dependencies/xECSV2/smoke_test_scene_ids.cpp` in Debug - the text form of an id, entity files and descriptors of ids of every width, references and the external table, names and folders, saving again changing no byte, scenes and prefabs written with u32 id rows) and the editor side (an id past 32 bits in every command, listing and undo step, the reserved top bit, save and reload, a Level saved with u32 id rows).
| `test_prefab_recipe.py` | No editor: compiles `dependencies/xECSV2/smoke_test_prefab_recipe.cpp` in Debug and runs it - prefab instances are recipes (phase 3 of the prefab plan): derived member ids, an instance saved as one file and spawned again with the same ids, values and references, a prefab that gains, reorders and loses members (orphans), nested instances, Apply |
| `test_prefab_recipes.py` | The editor side of phase 3: a level saved before recipes (`golden/scenes_v1`, the example's scenes as they were, and their `DescribeEntity` captured before phase 3) converts on load and reads the same, saved and reopened too; reordering a prefab's children keeps the overrides; `InstantiatePrefab -Parent` and a prefab holding an instance as a member; orphan overrides listed and removed; references kept by MakePrefab and mapped by Apply |
| `prefab_bench.py` | Not a test: compiles and runs `dependencies/xECSV2/smoke_test_prefab_bench.cpp` (the prefab spawn / template load baseline; Release; `--quick`, `--debug`) |
| `test_play_more.py` | More play tests: pause/resume, step refusal, keep/discards tweaks |
| `test_console_and_chat.py` | Console and chat: Say/GetLog round trip |
| `test_read_only_queries.py` | Read-only queries: ListAssets, CompileStatus, etc. |
| `test_resource_editors.py` | Every peer resource editor (Texture, Material, MaterialInstance, GeomStatic, GeomSkin, Skeleton, Font, AnimPackage) opens/closes cleanly, doesn't duplicate on reopen, coexists with others |
| `test_robustness.py` | Robustness: commands with missing/malformed arguments |
| `test_session_command_surface.py` | Session command surface: golden list |
| `test_game_module_reload_more.py` | More game module reload tests |

## The problem report

The run ends with an "editor problem report": every assert / CRT report / terminate / crash line the editor logged
(`LevelEditor.problems.log` next to the exe - appended, never truncated, so an assert can no longer be lost to the next launch),
and every distinct Vulkan validation error with its count. An assert fails the run even when all tests passed.
