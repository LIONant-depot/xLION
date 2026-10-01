#pragma once

#include "source/Editors/LevelEditor/LevelEditor_Kit.h"

#include "dependencies/xundo/source/xundo_history.h"

#include "source/Editors/LevelEditor/extensions/command_console/LevelEditor_CommandConsolePipe.h"

#include "dependencies/xeditor/include/xeditor/host.h"

#include "source/Editors/LevelEditor/extensions/command_console/LevelEditor_Commands_Chat.h"
#include "source/Editors/LevelEditor/extensions/command_console/LevelEditor_Commands_App.h"
#include "source/Editors/LevelEditor/extensions/command_console/LevelEditor_Commands_Actions.h"
#include "dependencies/actions.imgui/ximgui_actions_keymap.h"

#include "plugins/xlevel.plugin/source/Editor/xlevel_commands_level.h"

#include "plugins/xlevel.plugin/source/Editor/xlevel_commands_scene_dependency.h"

#include "dependencies/xresource_pipeline_v2/source/editor/E10_Commands_LibraryDependency.h"

#include "plugins/xlevel.plugin/source/Editor/xlevel_commands_workspace.h"

#include "plugins/xlevel.plugin/source/Editor/xlevel_commands_play_session.h"

#include "plugins/xlevel.plugin/source/Editor/xlevel_commands_viewport_tools.h"

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
// A Level is a resource like any other: every open Level has its own xlevel::session in ResourceEditors, created by
// ResourceEditors.Open(LevelGuid) (double-click, drop, the OpenLevel command) and gone when the Level is closed. The
// commands addressed to one Level by name (Name\Command) are built per session (level_command_set, kept in the
// session). The workspace commands that act on "the Level the user is working on" (Play, Save, Close, ...) are aimed
// at the active session, or at IdleLevel - a session with no Level that is never shown - when none is open.
//
//-----------------------------------------------------------------------------------

#include "source/Editors/LevelEditor/commands/LevelEditor_CommandSet.h"

namespace level_editor
{
    // The shell's own actions (keys, menus, hints - see dependencies/actions.imgui): what is live whichever editor has the focus.
    struct host_actions
    {
        xeditor::host* m_pHost = nullptr;       // xproperty creates objects by default construction, so the host is a pointer
        host_actions() noexcept = default;
        explicit host_actions(xeditor::host& Host) noexcept : m_pHost(&Host) {}

        void ToggleDrawer() noexcept { m_pHost->toggle_drawer_focused(); }

        XPROPERTY_DEF
        ( "Host", host_actions
        , obj_scope<"Drawer"
            , obj_action<"Toggle", &host_actions::ToggleDrawer
                , member_help<"Opens or closes the drawer (Resources, Assets, Source Control, Log, Commands...) of the window you are in">
                , ximgui::actions::member_keys<"Space"> >
            >
        )
    };
    XPROPERTY_REG(host_actions)

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
        ximgui::actions::context          Actions;                 // keys / menu items / toolbar buttons / hints for the whole process (a host service)
        host_actions                      HostActions{ EditorHost };
        xeditor::open_resource_editors    ResourceEditors;         // the resource editors open in their own windows (Texture, Static Geom, Level, ...)

        std::unique_ptr<xlevel::session>  IdleLevel;               // a Level editor without a Level, never shown: what the workspace commands act on while no Level is open
        xlevel::level_context*            LastLevelTarget = nullptr;

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

        std::string OpenLevelEditor(xresource::full_guid LevelGuid);   // opens (or focuses) the Level's editor; the OpenLevel command's reply
        void        PumpLevels();                                       // once a frame, before anything draws: open what was asked for, drop what closed, pump each editor
        template<typename T_FN> void ForEachLevelSession(T_FN&& Fn);    // every open Level editor (not IdleLevel)

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
