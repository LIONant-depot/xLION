# LevelEditor_LevelSceneEditor - Comprehensive Summary

## 1. Main Purpose

Example 29 (LevelEditor) is a **Level and Scene Editor** built on top of the xECSV2 entity-component system framework. It provides a full-featured editor for designing and managing hierarchical game levels composed of multiple scenes with the following core capabilities:

- **Level/Scene Management**: Create, open, close, and organize scenes within levels with dependency tracking
- **Entity Editing**: Create, delete, and organize entities within scenes using a folder-based hierarchy
- **Component Editing**: Inspect and modify entity components through a property inspector with full undo/redo support
- **Prefab System**: Author prefabs by dragging entities to the asset browser, and instantiate them into scenes
- **Hot-Reload Support**: Edit Game.dll code externally and see changes instantly via automatic compilation and world rebuild
- **Command Protocol**: External tool integration via named-pipe command console for AI/scripts
- **Play/Stop Simulation**: Enter play mode to test gameplay while preserving the ability to keep or discard changes

LevelEditor serves as both a practical editor for xECSV2 scenes and a reference implementation demonstrating advanced ECS editor patterns, including the reusable "kit" architecture.

---

## 2. Key Components and Their Roles

### Core Architecture Files

#### `LevelEditorCLI.cpp`
- **Role**: Standalone command-line client for the Command Console
- **Purpose**: Provides external access to LevelEditor's command system without UI automation
- **Mechanism**: Connects to a named pipe (`\\.\pipe\LevelEditor_LevelSceneEditor_Console`) and sends command strings
- **Key Feature**: Zero dependencies on xGPU (uses only Win32 + iostream) for fast builds as an independent tool

#### `LevelEditor_Kit.h`
- **Role**: Master "kit" header containing reusable editor functionality
- **Purpose**: Splits the original single-file example into modular, reusable components
- **Contents**:
  - Error popup mechanism (`Debugger`, `RenderErrorPopup`)
  - Shared `name` component (promoted from demo content to kit)
  - Resource picker wiring (GUID remapping, asset browser popups)
  - Editor state management (`editor_state` struct)
  - ID minting utilities (`NextFreeEntityId`, `NextFreeFolderId`)
  - Folder organization helpers (reparent, prune empty folders, delete)
  - Scene/Level lifecycle management (open/close, dependency cycle detection)
  - Entity reference tracking and cross-scene dependencies
- **Design Pattern**: Header-only library following the same convention as `E10_AssetBrowser.h`

#### `LevelEditor_GamePlugin.h`
- **Role**: Umbrella header for Game.dll hot-reload mechanics
- **Purpose**: Manages loading/unloading and rebuilding the external "Game.dll" plugin
- **Contents** (split into phase 3):
  - `plugin/LevelEditor_GamePluginLog.h` - Logging for DLL operations
  - `plugin/LevelEditor_GamePluginBuild.h` - Staleness checking and CMake-based rebuild
  - `plugin/LevelEditor_GamePluginLoad.h` - DLL loading/unloading mechanics
  - `plugin/LevelEditor_PlaySession.h` - Play session orchestration and V1/Vn snapshots

### Kit Subdirectories

#### `kit/` - Reusable Editor Panels
Contains modular UI components that can be reused across examples:

- **`LevelEditor_Panel_LevelTree.h`**: Renders the hierarchical level tree view
  - Displays Level → Scene → Folder → Entity hierarchy
  - Supports drag-and-drop operations (prefabs onto scenes/folders, entities onto folders)
  - Multi-select support with Ctrl+click
  - Context menus for creating new entities/folders
  - Search filtering for entities
  - Folder icon state tracking (has children vs empty)

- **`LevelEditor_Panel_EntityProperties.h`**: Entity component property inspector
  - Displays all components on selected entity
  - Add/Remove component dropdown
  - Prefab override apply/revert buttons
  - Integrated xproperty inspector with custom styling
  - Property modification support with undo/redo

- **`LevelEditor_Panel_SystemRegistry.h`**: Update system management
  - Lists all registered update systems
  - Drag-and-drop reordering
  - Enable/disable toggles
  - Persists changes to disk when not in Play mode
  - Visual indication when in Play mode (changes temporary)

- **`LevelEditor_Panel_CommandConsole.h`**: Text-based command interface
  - Phase 6 addition per user request
  - Near-port of E27's command console
  - Supports autocomplete and history
  - Same dispatch as the named-pipe server
  - Color-coded log (green for user, teal for pipe/AI)

- **`LevelEditor_PrefabOverrides.h`**: Prefab instance override tracking
  - Tracks property overrides on prefab instances
  - Handles hierarchy diffs (parent/children changes)
  - Provides apply/revert functionality

- **`LevelEditor_PrefabAuthoring.h`**: Prefab creation and management
  - Multi-entity group selection for prefab creation
  - Synthetic root creation when needed
  - Entity-to-instance conversion when dragging to asset browser
  - Folder-aware instantiation

#### `commands/` - Command System
Implements the undo/redo command infrastructure:

- **`LevelEditor_CommandContext.h`**: Command context and utilities
  - `editor_context`: Stores `editor_state&` reference
  - Selection backup/restore for undo
  - GUID formatting utilities (hex conversion)
  - String serialization for property values
  - Base64 encoding for arbitrary property data
  - `commands::Run()`: Shared command dispatcher with logging

- **Command Files** (each implements undo/redo):
  - `LevelEditor_Commands_Selection.h`: Entity selection commands
  - `LevelEditor_Commands_PropertyEdit.h`: Property modification commands
  - `LevelEditor_Commands_ComponentEdit.h`: Add/remove component commands
  - `LevelEditor_Commands_EntityLifecycle.h`: Create/delete entity commands
  - `LevelEditor_Commands_Level.h`: Level/scene membership commands
  - `LevelEditor_Commands_SceneDependency.h`: Parent scene dependency management
  - `LevelEditor_Commands_SceneOrganization.h`: Folder operations, instantiation
  - `LevelEditor_Commands_ApplyOverrides.h`: Prefab override management
  - `LevelEditor_Commands_PlaySession.h`: Play/pause/stop commands
  - `LevelEditor_Commands_AssetBrowser.h`: Asset browser integration
  - `LevelEditor_Commands_AssetFiles.h`: File-level asset operations
  - `LevelEditor_Commands_MakePrefab.h`: Prefab authoring commands
  - `LevelEditor_Commands_Compilation.h`: Compilation control commands
  - `LevelEditor_Commands_Chat.h`: Chat message commands (Say/GetLog)

- **`LevelEditor_CommandConsolePipe.h`**: Named-pipe server
  - Phase 5 addition for AI/script integration
  - Runs on background thread, hands requests to main thread
  - Uses same `ProcessConsoleCommand` dispatch as UI
  - Supports `help`, `Cmd -h`, and actual command routing

### Main Application Files

#### `LevelEditor_Main.cpp`
- **Role**: Main example application entry point
- **Purpose**: Orchestrates the editor, manages main loop, and wires all components together
- **Key Responsibilities**:
  - xGPU/xGPU/imgui setup and initialization
  - ECS `game_mgr::instance` creation and management
  - Plugin build/load system integration
  - Asset browser integration (E10)
  - Command/undo system initialization
  - Main frame loop with:
    - Automatic recompile detection (window focus regain, Play button)
    - Deferred Play/Stop requests (to avoid ImGui state corruption)
    - Idle work processing
    - Panel rendering (Asset Browser, Level Tree, Inspector, System Registry, Command Console)

#### `LevelEditor_Theme.h`
- **Role**: UI theming system
- **Purpose**: Applies a Unity-inspired color scheme
- **Features**:
  - Flat, dark color palette
  - Custom checkbox implementation
  - Unity-style header colors for component sections
  - Tight spacing to match Unity's Inspector layout

#### `LevelEditor_Diagnostics.h`
- **Role**: Diagnostic infrastructure
- **Purpose**: Provides consistent logging and crash reporting
- **Features**:
  - Start/stop diagnostics tracking
  - CRT report hook installation
  - Terminate handler installation
  - Persistent logging to stdout

---

## 3. Features Demonstrated

### Editor Features

1. **Hierarchical Scene Management**
   - Levels contain multiple scenes
   - Scenes can have parent scene dependencies
   - Folders organize entities within scenes
   - Entities can be parented hierarchically (via `parent`/`children` components)

2. **Entity Editing**
   - Create entities (with optional folder placement or parent attachment)
   - Delete entities (with recursive subtree deletion)
   - Multi-select entities for batch operations
   - Search/filter entities by name
   - Drag-and-drop to re-parent or move between folders

3. **Component Editing**
   - Inspect all components on selected entity
   - Add/remove components dynamically
   - Property modification via xproperty inspector
   - Custom resource picker for entity references
   - Prefab instance override display and management

4. **Undo/Redo System**
   - Full command-based undo/redo for all editable actions
   - Selection state preservation across undo/redo
   - Grouped commands (e.g., multi-file delete as one undo step)
   - Command logging to console for audit trail

5. **Prefab System**
   - Author prefabs by dragging entities to asset browser
   - Support for single-entity and multi-entity prefab groups
   - Instantiate prefabs by dragging onto scenes/folders
   - Track property overrides vs. original prefab
   - Apply overrides to prefab or revert hierarchy diffs

6. **Play/Stop Simulation**
   - Enter/exit play mode without restarting editor
   - Snapshot-based state preservation (V1/Vn architecture)
   - Option to keep or discard property tweaks after stopping
   - System registry enables/disables during play
   - World rebuild on play exit restores original state

7. **Asset Browser Integration**
   - Browse/create Levels, Scenes, Prefabs, and other assets
   - Drag-and-drop operations for scene/folder membership
   - Resource picker for property fields with entity references
   - Fuzzy search for assets

8. **External Integration**
   - Named-pipe server for command protocol
   - Standalone CLI client (`LevelEditorCLI.cpp`)
   - Text-based command protocol for AI/scripts
   - Help system (`help`, `Cmd -h`)

### Hot-Reload System

1. **Asynchronous Compilation**
   - Builds Game.dll on background thread
   - Never blocks editor UI
   - Disabled button while building

2. **State Preservation**
   - Raw snapshot bridge for mid-play edits
   - V1 snapshot (real disk save) for play session
   - Scene tree preservation via move semantics

3. **Rolling Update Strategy**
   - Same DLL stays loaded while recompiling
   - New generation copied to separate path
   - Destroy world, unload old, load new
   - Re-register components, restore state

---

## 4. Code Organization

### Architecture Layers

```
LevelEditor_LevelSceneEditor/
├── LevelEditor_Main.cpp    # Main application (wiring + main loop)
├── LevelEditor_Kit.h    # Reusable kit umbrella
├── LevelEditor_GamePlugin.h             # Hot-reload umbrella
├── LevelEditorCLI.cpp                   # External CLI client
├── LevelEditor_Theme.h                  # UI theming
├── LevelEditor_Diagnostics.h            # Diagnostic logging
├── GameProject/LevelEditor_Game.cpp     # Sample Game.dll plugin
├── kit/                         # Reusable editor components
│   ├── LevelEditor_Panel_*.h            # Three main UI panels
│   ├── LevelEditor_PrefabOverrides.h    # Prefab override tracking
│   ├── LevelEditor_PrefabAuthoring.h    # Prefab creation/instancing
│   └── LevelEditor_IdleWork.h           # Background work queue
├── commands/                    # Command/undo system
│   ├── LevelEditor_CommandContext.h     # Context + utilities
│   ├── LevelEditor_CommandConsolePipe.h # Named-pipe server
│   └── LevelEditor_Commands_*.h         # Individual commands
└── plugin/                      # Game.dll management
    ├── LevelEditor_GamePluginLog.h      # DLL logging
    ├── LevelEditor_GamePluginBuild.h    # Build/staleness check
    ├── LevelEditor_GamePluginLoad.h     # Load/unload mechanics
    └── LevelEditor_PlaySession.h        # Play session orchestration
```

### Dependency Flow

1. **UI Layer** (Panels, Command Console)
   - Renders ImGui widgets
   - Calls `commands::Run()` for user actions
   - Displays undo/redo state and console logs

2. **Command Layer** (`commands/LevelEditor_Commands_*.h`)
   - Implements `xundo::command` interface
   - `Redo()`: Performs action + records for undo
   - `Undo()`: Reverses action
   - Uses `get<editor_context>()` for editor state
   - Logs to shared console log

3. **Context Layer** (`commands/LevelEditor_CommandContext.h`)
   - Provides `editor_state&` reference
   - GUID formatting utilities
   - Selection backup/restore
   - String/base64 encoding

4. **ECS Layer** (`game_mgr`, `scene_mgr`, `level_mgr`, `prefab_mgr`)
   - Core entity-component system
   - Scene/Level/Prefab resource management
   - Component archetype management
   - System execution

5. **Plugin Layer** (`plugin/`)
   - Game.dll hot-reload orchestration
   - V1/Vn snapshot management
   - Build/staleness checking
   - World rebuild coordination

### Command System Architecture

LevelEditor uses a **command-based undo system** with the following pattern:

```
User Action → commands::Run() → xundo::system::Execute()
                             → command::Redo() → modify editor state
                             → record undo entry

Undo key → xundo::system::Undo()
         → undo entry restore → restore previous editor state
```

- **Commands are registered** with `xundo::system` via `xcmdline::parser`
- **Query commands** return results as strings
- **Edit commands** return empty string on success (xundo convention)
- **All commands logged** to shared console log for audit trail

### Play Mode State Machine

```
Stopped → Playing (via Play button)
  - Save V1 snapshot (real disk save)
  - Set m_PlayHistoryBoundary
  - Set m_PlayState = Playing

Playing → Paused (via Pause button)
  - Set m_PlayState = Paused (world stays as-is)

Paused → Playing (via Play button)
  - Resume from current state
  - May trigger recompile if code changed

Playing/Paused → Stopped (via Stop button or -Keep flag)
  - Stop play session
  - If -Keep: replay property changes on disk scene
  - Otherwise: restore from V1 snapshot
  - Reset to edit mode
```

### Kit Split Design

The codebase is organized into **three phases of kit extraction**:

- **Phase 1**: UI panels moved to `kit/` (LevelTree, EntityProperties, SystemRegistry)
- **Phase 2**: Prefab functionality moved to `kit/` (Overrides, Authoring)
- **Phase 3**: Game plugin split into `plugin/` (Build, Load, PlaySession)

Each phase follows the same pattern:
1. Extract functionality into standalone headers
2. Include via umbrella headers in exact same order
3. No external-facing API changes
4. Documented in comments as "mechanical move"

This allows gradual refactoring while maintaining the existing codebase structure.

---

## Summary

LevelEditor_LevelSceneEditor is a comprehensive level and scene editor built on xECSV2 that demonstrates advanced ECS editor patterns. It provides full entity/component editing with undo/redo, a robust prefab system, hot-reload support for Game.dll, and external integration via command protocol. The code is organized into reusable "kits" (UI panels, prefab logic) and a command system with proper undo/redo support. The architecture follows a clear separation between UI, commands, editor state, ECS management, and plugin loading, making it both maintainable and extensible.
