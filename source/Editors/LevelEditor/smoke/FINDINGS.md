# LevelEditor smoke test findings

## Crashes and wrong behaviour

### SetProperty with unparseable -Before/-After crashes
- **Command**: `SetProperty -Scene <guid> -Id <guid> -Component <guid> -Path <b64> -TypeGuid <guid> -Before <invalid> -After <invalid>`
- **Reply**: Editor crashes (exit code)
- **Debug/Release**: Both
- **Status**: Known crash - marked as `xfail` in `test_robustness.py`

### AddComponent does not refuse adding a component that already exists
- **Command**: `AddComponent -Scene <guid> -Id <guid> -Component <guid>` (called twice with the same component)
- **Reply**: Empty (success) both times
- **Debug/Release**: Both
- **Status**: Bug - the command should refuse adding a component that already exists

### AddSceneDependency writes project data
- **Command**: `AddSceneDependency -Scene <guid> -Parent <guid>`
- **Issue**: The command is in `DISK_WRITERS` but it doesn't actually write to disk
- **Status**: The harness incorrectly flags this as a disk writer

### RemoveSceneDependency writes project data
- **Command**: `RemoveSceneDependency -Scene <guid> -Parent <guid>`
- **Issue**: The command is in `DISK_WRITERS` but it doesn't actually write to disk
- **Status**: The harness incorrectly flags this as a disk writer

## Requests for new query commands

### GetSelection query
- **Current state**: No query command exists for getting the current selection
- **Impact**: `Select`, `ToggleMultiSelect`, and `ClearSelection` cannot be tested yet
- **Request**: Add a `GetSelection` query command that returns the primary selection and multi-select set

## Tests skipped

### Prefab tests
- **Reason**: The example project may not have prefabs to test
- **Status**: Skipped with `pytest.skip` if no prefabs found

### Scene dependency cycle test
- **Reason**: Need to verify the exact error message format from the source
- **Status**: Partial implementation - depends on actual scene dependencies in the project

## Known gaps

### Commands not tested
- Asset creation/renaming/moving/deletion (writes project data)
- Library commands (need `allow_disk=True`)
- Script source edits (need `allow_disk=True`)
- Source control writes (need `allow_disk=True`)

### Session commands not fully tested
- Selection commands (`Select`, `ToggleMultiSelect`, `ClearSelection`) - no `GetSelection` query
- Scene dependency commands - need to verify exact error messages

### Play mode tests
- Limited to basic transport cycle and keep/discard tweaks
- Could add more comprehensive play mode tests

## Notes

- The suite runs against the real `example.lionprj` project
- Project data folders (`Descriptors\Scene`, `Level`, `Prefab`) are not under git
- Always backup these folders before running tests
- The suite leaves empty orphan files (`entity_db\..\*.entity`, 116 bytes) - delete those not in backup
