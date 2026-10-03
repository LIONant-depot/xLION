# Working with the editor from a script or an AI

The tools live in `source/Editors/LevelEditor/smoke/`.

| tool | what it does |
| --- | --- |
| `python live.py start [--window]` | starts an editor that stays up, from a **copy** of the build (`xLION_Headless_live.exe`, or `xLION_live.exe` with `--window`), so the build can be rebuilt while it runs. `stop` stops only that editor (its process id is in `Build/live.pid`); `restart` picks up the newest build. Its output is `Build/live.log`: grep it. |
| `python xcmd.py "Command -x 1" ...` | sends commands to the running editor and prints the replies (`-t 300` waits longer, `-` reads the commands from stdin). No editor is started or stopped, and none of the test guards apply. |
| `python impact.py [--run] [FILE...]` | the test files that cover the files changed in the working trees (or the files named). The map is `golden/test_impact.json`; `test_impact_map.py` keeps it complete: a new test file has to be named in it. |
| the harness | a failure of the editor ("editor died running ...") carries what the editor wrote about its death: the assert or exception and the frames of its own code. A test marked `pytestmark = pytest.mark.no_editor` does not start an editor. |

The test suite refuses to run while an editor owns the command pipe: stop the live one first.

## Commands that spare the bookkeeping

- A component is given by its **name** (`Transform`, `PhysicsColliderBox`, any case) or by its guid, in `AddComponent`, `RemoveComponent`, `SetProperty` and `GetProperty`.
- `CreateEntity ... -Components Transform,Physics,...` makes the entity with those components in one undoable step; a name that is not a component refuses the command before anything is made.
- `SetProperty -Scene S -Id I -Component Transform -Path Transform/Position/Y -After 4.5`: the type of the property and its old value (what the undo gives back) are read by the editor. `-TypeGuid` and `-Before` still work.
- `GetProperty -Scene S -Id I -Component Transform -Path Transform/Position/Y` says that one value and nothing else (`DescribeEntity` says all of them).
- `Play` saves the open scenes itself (the test harness refuses it with unsaved edits to protect the project; `xcmd.py` does not).
