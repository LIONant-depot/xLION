# The ECS gates

**Why.** xECS is mostly header-only. `LIONCore.dll` holds the component registry (`xecs::component::mgr::s_Registry`) and a handful of exported functions, but the logic that works on it is compiled into every binary
that includes the headers. The Level editor is compiled into `xLION.exe`, so every registry access it makes goes through the exe's own import of `LIONCore.dll`. That is why only one core (and so one Game.dll) can
live in the process today. The plan (see memory `phase3-engine-copies-decision`) is that each open Level gets its own renamed copy of the core, and that the editor talks to its copy only through a pure virtual
interface, `xECSEditor`, that the copy hands out. Until the editor is moved behind it, two gates keep the amount of direct use from growing, and their baselines are the measured to-do list.

## 1. The source scan (fast, in the suite)

`ecs_gate.py scan` counts, in the code of the editor (comments and strings ignored), the tokens that only make sense against the registry of one core: `m_BitID`, `getComponentBits`, `getEntityDetails`,
`m_pPool`, `info_v`, `findComponentTypeInfo`, `s_Registry`, `SyncLocalBitIDs`, `SyncAllLocalBitIDs`, `m_ComponentInfoMap`. It scans `plugins/xlevel.plugin/source`, `plugins/xscene.plugin/source` and
`source/Editors/LevelEditor`. The per-file counts are the baseline `golden/ecs_scan_baseline.json`: a count may go down, never up, and a file that does not use a token may not start to. The per-binary `info_v<T>.m_BitID`
is the case the link gate cannot see (an exe-side copy of it is an unset sentinel as soon as nothing syncs it), which is why this one exists.

## 2. The link gate (builds a target)

CMake option `XLION_ECS_LINK_GATE` adds the target `xLION_ecs_gate` (never part of a normal build): the headless editor, with the same sources and defines, **not linked** with `LIONCore.dll` and `LIONRender.dll`. The
headers still say `dllimport`, so each thing the editor takes from them through its own import is an unresolved external. `ecs_gate.py link` builds it and compares the symbols with `golden/ecs_link_baseline.txt`.

    cmake -S . -B Build/xLION.vs2022 -DXLION_ECS_LINK_GATE=ON      (once)
    python source/Editors/LevelEditor/smoke/ecs_gate.py link

Today it is empty, and so is the scan baseline: the editor reads no pool, bit id or registry of its own, it asks the `xECSEditor` of the Level's copy of the core (`xlioncore_editor.h`, which the core exports as
`XLionCore_CreateEditor` and the editor finds with `GetProcAddress`). It was ten symbols once: the world's life (`Run`, `Stop`, `SerializeGameState`, `TeleportDynamicBody`), the registration (`SyncAllLocalBitIDs`), the
registry loops (`s_Registry`) and the render calls (now `xRenderEditor`, `xlionrender_api.h`). Two things keep it empty that the symbols do not show:

- `LevelEditor_Main.cpp` defines `XSCRIPT_IMPORT_ONLY` first, so a header that says `XSCRIPT_REGISTER_COMPONENT` (the physics ones) gives the editor the type and its reflection but does not make the exe register the
  component: the copy of the core does.
- The editor does not sync its own `info_v<T>.m_BitID` (they are per binary, and with several copies of the core none of them would be the right one). Whatever it needs of a component it asks the interface
  (`HasComponent`, `ComponentOf`, `ChangeComponents`, `ComponentTypesOf`, `SystemMatches`...). A use of a bit id that slips past both gates fails loudly in the tests, not silently.

## Rule

Both baselines may only shrink. After moving a use behind the interface, run `ecs_gate.py scan --update` / `link --update` and commit the smaller baseline with the change. `test_ecs_gate.py` runs both in the suite
(and checks that the scanner sees what it is there for).

## Note: reconfiguring

A CMake reconfigure needs `dependencies/xlog_editor` to exist: the `xlog` depot declares a component of that name whose files are under `dependencies/xlog/editor`. Until that is fixed in the depot, make the folder a
junction to `dependencies/xlog` (`New-Item -ItemType Junction`).
