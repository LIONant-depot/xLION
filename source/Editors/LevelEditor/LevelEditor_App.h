#pragma once

#include "source/Editors/LevelEditor/LevelEditor_Kit.h"

#include "dependencies/xundo/source/xundo_history.h"

#include "source/Editors/LevelEditor/extensions/command_console/LevelEditor_CommandConsolePipe.h"

#include "dependencies/xeditor/include/xeditor/host.h"

#include "source/Editors/LevelEditor/extensions/command_console/LevelEditor_Commands_Chat.h"
#include "source/Editors/LevelEditor/extensions/command_console/LevelEditor_Commands_App.h"
#include "source/Editors/LevelEditor/extensions/command_console/LevelEditor_Commands_Actions.h"
#include "dependencies/actions.imgui/ximgui_actions_keymap.h"
#include "dependencies/xeditor/include/xeditor/shortcuts.h"
#include "dependencies/xeditor/include/xeditor/hint.h"
#include "dependencies/actions.imgui/ximgui_actions_ui.h"

#include "plugins/xlevel.plugin/source/Editor/xlevel_commands_level.h"

#include "plugins/xlevel.plugin/source/Editor/xlevel_commands_scene_dependency.h"

#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_commands_library_dependency.h"

#include "plugins/xlevel.plugin/source/Editor/xlevel_commands_workspace.h"

#include "plugins/xlevel.plugin/source/Editor/xlevel_commands_play_session.h"
#include "plugins/xlevel.plugin/source/Editor/xlevel_commands_text.h"
#include "plugins/xlevel.plugin/source/Editor/xlevel_commands_hierarchy.h"
#include "plugins/xlevel.plugin/source/Editor/xlevel_commands_time.h"

#include "plugins/xlevel.plugin/source/Editor/xlevel_commands_viewport_tools.h"

#include "plugins/xscene.plugin/source/Editor/xscene_commands_scene_organization.h"

#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_commands_assets.h"

#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_commands_asset_files.h"

#include "source/Editors/LevelEditor/extensions/game_module/LevelEditor_Commands_Scripting.h"

#include "plugins/xscene.plugin/source/Editor/xscene_commands_make_prefab.h"

#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_commands_compilation.h"

#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_commands_source_control.h"

#include "source/Editors/LevelEditor/extensions/asset_browser/LevelEditor_Commands_ResourceEditors.h"


#include "source/Editors/LevelEditor/LevelEditor_Theme.h"

#include "source/Tools/Editor/xeditor_resource_tab.h"
#include "source/Tools/Editor/xeditor_compile_logs.h"

#include "dependencies/xeditor/include/xeditor/diagnostics.h"
#include "dependencies/xeditor/include/xeditor/gpu_log.h"
#include "dependencies/xlog/source/xlog_store.h"

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
        xeditor::host*             m_pHost    = nullptr;   // xproperty creates objects by default construction, so these are pointers
        ximgui::actions::context*  m_pActions = nullptr;
        host_actions() noexcept = default;
        host_actions(xeditor::host& Host, ximgui::actions::context& Actions) noexcept : m_pHost(&Host), m_pActions(&Actions) {}

        void ToggleDrawer() noexcept { m_pHost->toggle_drawer_focused(); }
        void OpenPalette()  noexcept { m_pActions->OpenPalette(); }
        void ShowKeyboard() noexcept { m_pActions->OpenOverlay(); }
        void Explain()      noexcept { m_pActions->Explain(); }
        void NextProblem()     noexcept { m_pHost->logs_step_problem(+1); }
        void PreviousProblem() noexcept { m_pHost->logs_step_problem(-1); }

        XPROPERTY_DEF
        ( "Host", host_actions
        , obj_scope<"Drawer"
            , obj_action<"Toggle", &host_actions::ToggleDrawer
                , member_help<"Opens or closes the drawer (Resources, Assets, Source Control, Logs, Commands...) of the window you are in">
                , ximgui::actions::member_keys<"Space"> >
            >
        , obj_scope<"Logs"
            , obj_action<"NextProblem", &host_actions::NextProblem
                , member_help<"Goes to the next problem of the Logs (worst first) and opens its source, with the drawer closed too">
                , ximgui::actions::member_keys<"F8"> >
            , obj_action<"PreviousProblem", &host_actions::PreviousProblem
                , member_help<"Goes to the previous problem of the Logs and opens its source">
                , ximgui::actions::member_keys<"Shift+F8"> >
            >
        , obj_scope<"Explain"
            , obj_action<"Pin", &host_actions::Explain
                , member_help<"Explains what the mouse rests on: keeps its hint card on screen, with what can be done to its key. Over nothing, shows the keyboard">
                , ximgui::actions::member_keys<"F1"> >
            >
        , obj_scope<"Keyboard"
            , obj_action<"Show", &host_actions::ShowKeyboard
                , member_help<"Shows the keyboard and the mouse: every key and button coloured by what it does where you are working">
                , ximgui::actions::member_keys<"Shift+F1"> >
            >
        , obj_scope<"Palette"
            , obj_action<"Open", &host_actions::OpenPalette
                , member_help<"Search every action that is available where you are working, and run it">
                , ximgui::actions::member_keys<"Ctrl+Shift+P", true> >
            >
        )
    };
    XPROPERTY_REG(host_actions)
    XIMGUI_ACTIONS_OWNER(host_actions)

    // The Assets tab's file keys as actions (the tab itself is xresource_editor::files_tab; its methods are called in LevelEditor_FilesActions.h,
    // after that header is included). Live while the Assets tab of the Host Drawer has the focus.
    struct files_actions
    {
        void* m_pTab = nullptr;         // the files_tab, found each frame the Assets tab is drawn; null otherwise

        void        Rename() noexcept;      const char* WhyNoRename() const noexcept;
        void        Cut()    noexcept;      const char* WhyNoCut()    const noexcept;
        void        Copy()   noexcept;      const char* WhyNoCopy()   const noexcept;
        void        Paste()  noexcept;      const char* WhyNoPaste()  const noexcept;
        void        Delete() noexcept;      const char* WhyNoDelete() const noexcept;

        XPROPERTY_DEF
        ( "Assets", files_actions
        , obj_action<"Rename", &files_actions::Rename
            , member_help<"Renames the selected file">
            , ximgui::actions::member_keys<"F2">
            , member_dynamic_reason<+[](const files_actions& A) noexcept -> const char* { return A.WhyNoRename(); }> >
        , obj_action<"Cut", &files_actions::Cut
            , member_help<"Cuts the selected files; Paste moves them to the folder you are in">
            , ximgui::actions::member_keys<"Ctrl+X">
            , member_dynamic_reason<+[](const files_actions& A) noexcept -> const char* { return A.WhyNoCut(); }> >
        , obj_action<"Copy", &files_actions::Copy
            , member_help<"Copies the selected files; Paste puts the copies in the folder you are in">
            , ximgui::actions::member_keys<"Ctrl+C">
            , member_dynamic_reason<+[](const files_actions& A) noexcept -> const char* { return A.WhyNoCopy(); }> >
        , obj_action<"Paste", &files_actions::Paste
            , member_help<"Pastes the cut or copied files into the folder you are in">
            , ximgui::actions::member_keys<"Ctrl+V">
            , member_dynamic_reason<+[](const files_actions& A) noexcept -> const char* { return A.WhyNoPaste(); }> >
        , obj_action<"Delete", &files_actions::Delete
            , member_help<"Moves the selected files to the trash (undoable)">
            , ximgui::actions::member_keys<"Delete">
            , member_dynamic_reason<+[](const files_actions& A) noexcept -> const char* { return A.WhyNoDelete(); }> >
        )
    };
    XPROPERTY_REG(files_actions)
    XIMGUI_ACTIONS_OWNER(files_actions)

    struct app
    {
        xgpu::instance Instance;
        xgpu::device   Device;
        xgpu::window   MainWindow;

        // Same wiring xresource_editor does: texture (and other) loaders Destroy via UserData.m_Device. Without this,
        // RegisterResource/ReleaseRef (Texture editor preview reload after Compile) crashes in device::Destroy
        // on a default-constructed empty device handle.
        resource_mgr_user_data ResourceMgrUserData{};

        //
        // Asset browser
        //
        xresource_editor::asset_browser AssetBrowser;

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
        host_actions                      HostActions{ EditorHost, Actions };
        files_actions                     FilesActions;            // the Assets tab's file keys
        xeditor::shortcut_labels          ShortcutLabels;          // menus ask the host which key an action has (xeditor/shortcuts.h)
        xeditor::open_resource_editors    ResourceEditors;         // the resource editors open in their own windows (Texture, Static Geom, Level, ...)
        xeditor::compile_log_bridge       CompileLogs;             // every asset compile as an operation of the Logs (what the resource editors' Feedback shows)

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
        bool m_bProjectSettingsHints = false;                       // the Project Settings inspector shows the editors' hint window for its properties
        void BindProjectSettingsHints();
        void WireKeymapNavigation();                                // "Show in keymap": the drawer on Project Settings, at the Keymap section
        void BindFilesActions();                                    // while the Assets tab is drawn: find its files_tab and make the Assets/... actions live
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
