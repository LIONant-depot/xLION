# LevelEditor smoke tests

Regression tests for the editor's **command surface** - the same commands the AI/CLI uses. They launch the
real editor (`xGPU_unit_test.exe`), drive it through its Command Console pipe, and assert on replies.

```bat
pip install pytest
cd source\Examples\LevelEditor_LevelSceneEditor\smoke
python -m pytest -q                     # all tests (~20 s), launches the Release build itself
python -m pytest test_play.py -q        # one file
python -m pytest -q --exe <path>        # a different build
python -m pytest -q --update-golden     # accept a deliberate change to the command list
```

Build first (`cmake --build Build\xGPUExamples.vs2022 --config Release --target xGPU_unit_test`), and close any
running editor - the pipe (`\\.\pipe\xEditor_Console`) admits one server.

## How it works

| File | Role |
|---|---|
| `harness.py` | `Editor`: launches/kills the process, pipe client (stdlib `ctypes`, no CLI executable needed), typed helpers (`sessions()`, `entities()`, `describe()`, `wait_play_state()`, ...) |
| `conftest.py` | fixtures. `editor` = one process for the run, restarted if a test kills it. `level` = the example project's first level opened **clean**, closed without saving afterwards. `_editor_alive` = a crash fails exactly the test that caused it, with the command and exit code |
| `test_*.py` | the tests. Plain functions and `assert` |
| `golden/commands.txt` | the expected workspace command names; a removed/added command fails until you `--update-golden` |

Command grammar: `<Command> ...` (workspace) or `<Session name>\<Command> ...` (`Main Level\CreateEntity ...`).
**Edit** commands reply with an empty string on success; **query** commands reply with text; refusals are text.
Property paths and values are **base64 of their text** (`b64("5.000000")`), not raw bytes.

## Rules that keep the suite safe

The suite runs against the developer's real `example.lionprj`.

- Tests never save. The harness raises `PermissionError` for commands that write project data (`Save`, `Create*`,
  `Rename*`, source control, ...) unless the call passes `allow_disk=True`.
- `Play` saves the open level first, so the harness refuses `Play`/`Step` while a session has unsaved edits. Create
  test entities **after** the `Play` if you need both. Use the `level` fixture (clean) for any Play test.
- Everything a test creates lives only in memory (`level.new_entity()` mints ids `7E57xxxx`) and is discarded by
  `Close -Save 0` in the fixture teardown.
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
| `test_prefabs.py` | Prefab operations: instantiate, revert, hierarchy overrides |
| `test_play_more.py` | More play tests: pause/resume, step refusal, keep/discards tweaks |
| `test_console_and_chat.py` | Console and chat: Say/GetLog round trip |
| `test_read_only_queries.py` | Read-only queries: ListAssets, CompileStatus, etc. |
| `test_robustness.py` | Robustness: commands with missing/malformed arguments |
| `test_session_command_surface.py` | Session command surface: golden list |
| `test_game_module_reload_more.py` | More game module reload tests |
