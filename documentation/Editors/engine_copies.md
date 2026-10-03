# Every Level on its own engine

A Level editor runs completely independent of the others: its own copy of the core (`LIONCore.dll`: the ECS registry, the systems, physics), its own copy of the render DLL (`LIONRender.dll`) and its own game module (the `Game.dll` of the Game the Level names). Any number of Levels, of any number of Games, can be open and playing at the same time.

## Why copies

xECS is mostly header-only: the component registry lives in `LIONCore.dll`, but the logic that works on it is compiled into every binary that includes the headers. Two Levels that share one `LIONCore.dll` share one registry (one component bit space, one set of systems). So each Level gets its own core, and the editor (which stays in `xLION.exe`) never runs xECS code itself: it asks the copy for an `xlioncore::xECSEditor` (see `ecs_link_gate.md`) and only calls that. The render DLL has the same shape (`xlionrender::xRenderEditor`).

## The set

`plugins/xlevel.plugin/source/Editor/xlevel_engine_copies.h`. The manager (`Services().Engines`) makes a *set* when a Level opens:

| original | copy | how |
|---|---|---|
| `LIONCore.dll` | `LC00000N.dll` | a byte copy (the core imports nothing of ours), loaded first, by full path |
| `LIONRender.dll` | `LR00000N.dll` | its import of `LIONCore.dll` is renamed to `LC00000N.dll` (so it binds to ITS core), PE checksum fixed |
| `Game.dll` | `Game_loaded_LC00000N_G.dll` | the same import rename, made by the Game.dll loader (`CopyGamePluginForLoad`) |

The new names are never longer than the old ones (the import table is patched in place). The loader finds a copy by the name of the module that is already loaded, which is why the core copy goes in first. The copies live in `EngineCopies/` next to the executable; PDBs are not copied (the debug directory of a copy still names the original PDB). A set goes away (modules freed, files deleted, with a few retries: a freshly unloaded file can stay locked for a moment) with the last that holds it; what an earlier run left is swept when the next set is made. A file that cannot be loaded right after it was written (a scanner holds it) is tried again for a moment.

`ProbeEngineSet` makes a set, registers in the copy, shows that the registry of this Level's core is untouched, that the render copy imports its own core and that the checksum validates, and frees the set.

## The game module of a Level

`game_plugin_state` is a member of the session. The Level's Game (`GameOfLevel`) decides everything: no Game means no scripts, no components of any module, no systems of one. A Game that has no `Game.dll` yet is built before a Level of it opens (`GameNeedsFirstBuild` / `StartFirstBuild`: the Level tree waits, a command waits right in `OpenLevel`); builds are per Game (see Builds). The Level's world asks its own module which module defines a component (`m_pModuleOfComponent` with the plugin state as its user pointer), and what the editor shows about its types (categories, where each comes from) is the Level's own `xscene::component_display` (`scene_context::Display()`).

## What is gone

- The Play lock: the host has no Play singleton. `Name\Play`, `Name\Pause`, `Name\Step`, `Name\Stop`, `Name\GetPlayState` are the transport of one Level; the gate (`play_gate`) is asked of the Level that wants to play.
- The project's own Game: `Script.config.txt` is not read, there is no Scripting settings page and no `SetProjectGame`. The module commands (`AddProjectModuleReference`, `RemoveProjectModuleReference`, `ListProjectModuleReferences`) take `-Game`.
- "One Game at a time": a Level that names another Game opens on that Game.

## Builds

Each plugin state has its own build job (every process cmake, MSBuild and the compiler start runs in it), so closing a Level stops only its own build. Builds are serialized per build folder (Levels of one Game share it and the second finds the DLL up to date); builds of different Games run side by side. A first build that failed is tried again by the Level that asks for it (opening it, or Play): the Level opens without the module meanwhile. What is refused after a rebuild (the open scenes need components the new build lacks) is the Level's own prompt (`game_plugin_state::m_PendingMissing`), and `GameModuleStatus`, `SimulateModuleCrash` and `SimulateSnapshotFailure` act on the Level they are addressed to.

## Known limits

- Memory and DLL count grow with the Levels that are open: accepted.
- The Logs' "verify a build problem" re-check starts a build for the Level the user touched last.
