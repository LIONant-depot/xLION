#pragma once

// level_editor::app: the Host Drawer tab bodies. The menu-bar/Editor/Scene toolbars used to live here too, but
// they read State/CmdContext/pGameMgr/GamePlugin/SceneTool directly, so they moved to
// plugins/xlevel.plugin/source/Editor/xlevel_session.h's xlevel::session::RenderParentEditorToolbar/
// RenderEditorToolbar alongside the rest of that ownership (see LevelEditor_App.h's own top comment).
namespace level_editor
{
    // Host Drawer (xeditor::host): one call - Space + all OS-window manifestations. Editors do not wire this.
    inline void app::DrawDrawerTab(int TabIndex)
    {
        switch (TabIndex)
        {
        case 0:
            AssetBrowser.SetDevice(Device);
            AssetBrowser.RenderEmbeddedTab(xresource_editor::g_LibMgr, xresource::g_Mgr, "Resources");
            break;
        case 1:
            AssetBrowser.SetDevice(Device);
            AssetBrowser.RenderEmbeddedTab(xresource_editor::g_LibMgr, xresource::g_Mgr, "Assets");
            break;
        case 2:
            xresource_editor::RenderSourceControlPanel(EditorHost.m_Workspace);
            break;
        case 3:
            {
                bool bAnyScenes = false;
                ForEachLevelSession([&](xlevel::session& S) { bAnyScenes |= S.m_pGameMgr && !S.m_State.m_OpenScenes.empty(); });
                xeditor::RenderIdleWorkPanel(EditorHost.m_IdleWork, bAnyScenes);
            }
            break;
        case 4:
            xlevel::RenderGamePluginLogPanel(/*bEmbedded*/ true);
            break;
        case 5:
            level_editor::DrawCommandConsolePanel(LevelEditorHistory, EditorHost.m_ConsoleLog, /*bEmbedded*/ true);
            break;
        case 6:
            AssetBrowser.SetDevice(Device);
            AssetBrowser.RenderEmbeddedTab(xresource_editor::g_LibMgr, xresource::g_Mgr, "Compilation");
            break;
        case 7:
            AssetBrowser.SetDevice(Device);
            AssetBrowser.RenderEmbeddedTab(xresource_editor::g_LibMgr, xresource::g_Mgr, "Project Settings");
            break;
        default:
            break;
        }
    }
}
