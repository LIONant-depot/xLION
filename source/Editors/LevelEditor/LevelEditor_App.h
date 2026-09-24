#pragma once

#include "source/Editors/LevelEditor/LevelEditor_Kit.h"

#include "dependencies/xundo/source/xundo_history.h"

#include "source/Editors/LevelEditor/extensions/command_console/LevelEditor_CommandConsolePipe.h"

#include "dependencies/xeditor/include/xeditor/host.h"

#include "source/Editors/LevelEditor/extensions/command_console/LevelEditor_Commands_Chat.h"
#include "source/Editors/LevelEditor/extensions/command_console/LevelEditor_Commands_App.h"

#include "plugins/xlevel.plugin/source/Editor/xlevel_commands_level.h"

#include "plugins/xlevel.plugin/source/Editor/xlevel_commands_scene_dependency.h"

#include "dependencies/xresource_pipeline_v2/source/editor/E10_Commands_LibraryDependency.h"

#include "plugins/xlevel.plugin/source/Editor/xlevel_commands_workspace.h"

#include "plugins/xlevel.plugin/source/Editor/xlevel_commands_play_session.h"

#include "plugins/xscene.plugin/source/Editor/xscene_commands_scene_organization.h"

#include "dependencies/xresource_pipeline_v2/source/editor/E10_Commands_Assets.h"

#include "dependencies/xresource_pipeline_v2/source/editor/E10_Commands_AssetFiles.h"

#include "source/Editors/LevelEditor/extensions/game_module/LevelEditor_Commands_Scripting.h"

#include "plugins/xscene.plugin/source/Editor/xscene_commands_make_prefab.h"

#include "dependencies/xresource_pipeline_v2/source/editor/E10_Commands_Compilation.h"

#include "dependencies/xresource_pipeline_v2/source/editor/E10_Commands_SourceControl.h"

#include "source/Editors/LevelEditor/extensions/asset_browser/LevelEditor_Commands_ResourceEditors.h"


#include "source/Editors/LevelEditor/LevelEditor_Theme.h"

#include "source/Tools/Editor/xeditor_resource_tab.h"

#include "dependencies/xeditor/include/xeditor/diagnostics.h"

#include "ximgui_toolbar.h"

//-----------------------------------------------------------------------------------
//
// LevelEditor - the process shell.
//
// STAGE (b) of the Level-ownership move: level_editor::app is no longer the Level editor itself - it is a
// neutral shell (window/device/host/asset browser/command console/theme) that opens Level exactly like it
// opens Texture, through xeditor::open_resource_editors::Open(xecs::level::type_guid_v). Everything that used
// to be hand-rendered here every frame (the ECS world, Game.dll scripting, Play/Pause/Stop, the Level Tree/
// Inspector/System Registry panels and their dockspace, the Editor/Scene toolbars) now lives in
// plugins/xlevel.plugin/source/Editor/xlevel_session.h's xlevel::session, the same shape every other resource
// editor (Texture, Material, GeomStatic, ...) already used.
//
// pLevelSession is a raw, non-owning pointer to the one Level session Open() constructs at startup - it is a
// SINGLETON (see xlevel_session.h's own top comment for why: no per-Guid identity, never destroyed for the
// life of the process), so this pointer stays valid for as long as `app` does. Commands (still built here,
// against the session's own CmdContext/Undo for its "Level" half) and WireAssetBrowser's open-asset routing
// both reach into it directly. command_set's ~32 Level-tagged commands (entity/scene/play mutation) are
// already registered on pLevelSession->m_Undo, not a shell-owned system - true since stage (b) - so
// host::dispatch()'s Name\Command already reaches them; physically relocating those command *objects* into
// xlevel::session itself (so command_set holds only the ~50 Workspace-tagged ones) is left for a follow-up -
// one of them (CmdSerializeRoundtrip) is defined in a shell-only file
// (extensions/game_module/LevelEditor_Commands_Scripting.h) that xlevel_session.h cannot see without a real
// include-order untangling, and that's a bigger, separate piece of work than the AddSystem/
// m_pExternalWorkspace removal this stage is actually about.
//
//-----------------------------------------------------------------------------------

#include "source/Editors/LevelEditor/commands/LevelEditor_CommandSet.h"

namespace level_editor
{
    struct app
    {
        xgpu::instance Instance;
        xgpu::device   Device;
        xgpu::window   MainWindow;

        // Same wiring E10 does: texture (and other) loaders Destroy via UserData.m_Device. Without this,
        // RegisterResource/ReleaseRef (Texture editor preview reload after Compile) crashes in device::Destroy
        // on a default-constructed empty device handle.
        resource_mgr_user_data ResourceMgrUserData{};

        //
        // Asset browser
        //
        e10::assert_browser AsserBrowser;

        //
        // Command/undo system - the shell's own framework-level workspace: asset CRUD, source control, compile,
        // idle-work, Say/GetLog, OpenResourceEditor and friends. EditorHost.m_Workspace IS this workspace
        // (stage (c): no more m_pExternalWorkspace override onto a separate app-owned system, and no more
        // routing the legacy "LevelEditor/..." prefix through LevelEditorHistory - Level is a normal
        // host.m_Sessions entry, so host::dispatch()'s Name\Command already resolves it by display name, the
        // same way it already does for Texture).
        //
        level_editor::commands::chat_log            ChatLog;
        level_editor::commands::exit_state          ExitState;

        xeditor::host                     EditorHost;
        xeditor::open_resource_editors    ResourceEditors;         // the resource editors open in their own windows (Texture, Static Geom, Level, ...)

        xlevel::session*                  pLevelSession = nullptr; // the one Level session Open() constructs at startup - see this file's own top comment

        xundo::history                        LevelEditorHistory;

        // Command Console named pipe - lets an external process (a script, an AI) drive the editor through
        // LevelEditorHistory.Route() with no UI automation - see extensions/command_console/
        // LevelEditor_CommandConsolePipe.h's own top comment for the full threading reasoning. Detached, not
        // joined - a local dev/debug feature, dies with the process.
        level_editor::command_console_pipe_bridge    ConsolePipeBridge;

        std::uint64_t FrameNumber = 0;

        std::optional<command_set> Commands;

        void WireAssetBrowser();
        void DrawDrawerTab(int TabIndex);

        // bHeadless=true skips window/device/ImGui init entirely - the editor still runs its full command
        // system (ECS, undo, asset browser, Command Console pipe), just with no GPU/UI. See
        // LevelEditor_AppInit.h / LevelEditor_AppFrameHeadless.h. Remembered (not just an Init() local) so
        // Shutdown() knows which teardown steps are safe to skip.
        bool bHeadless = false;

        int  Init(bool bHeadlessMode = false);   // 0 on success, otherwise the process exit code
        void Frame();          // one iteration of the graphical main loop
        void Run();            // Frame() until the window closes or the Exit command runs
        void RunHeadless();    // pumps the command console/idle work with no window, until the Exit command runs
        void Shutdown();
    };
}
