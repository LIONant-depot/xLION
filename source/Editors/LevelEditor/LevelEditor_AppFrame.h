#pragma once

namespace level_editor
{
    inline void app::Frame()
    {
        ++FrameNumber;
        xeditor::diagnostics::Log("frame %llu begin", static_cast<unsigned long long>(FrameNumber));

        // No manual "Reload Game" button - recompiling is something the editor just does for you. Two automatic
        // triggers only: the window regaining OS focus, and the Play button itself (see xlevel::RequestPlay).
#if defined(XECS_BUILD_SHARED)
        if (xgpu::tools::imgui::ConsumeWindowFocusGained())
            EditorHost.on_focus_regain();
#else
        xgpu::tools::imgui::ConsumeWindowFocusGained(); // still consume the edge - just nothing to react to without a Game.dll
#endif

        // Checked unconditionally, every frame, BEFORE BeginRendering starts this frame - see
        // xlevel::session::PumpBeforeFrame's own comment for why this can never move into Render().
        if (pLevelSession) pLevelSession->PumpBeforeFrame();

        const auto ConsoleLogCountBefore = EditorHost.m_ConsoleLog.size();
        level_editor::PumpCommandConsolePipe(ConsolePipeBridge, LevelEditorHistory, EditorHost.m_ConsoleLog);
        if (EditorHost.m_ConsoleLog.size() != ConsoleLogCountBefore)
            EditorHost.m_IdleWork.NotifyActivity();

        if (xgpu::tools::imgui::BeginRendering(true))
        {
            xeditor::diagnostics::Log("frame %llu BeginRendering skipped", static_cast<unsigned long long>(FrameNumber));
            return;
        }
        xeditor::diagnostics::Log("frame %llu BeginRendering complete", static_cast<unsigned long long>(FrameNumber));

        // Real mouse/keyboard activity this frame resets Idle Work's clock AND cancels any in-flight idle task.
        if (xeditor::DetectUserInputActivity())
        {
            EditorHost.m_IdleWork.NotifyActivity();
            xeditor::RequestIdleWorkCancel();
        }
        EditorHost.pump_services();

        // Asset open drain (drawer works even with the Level peer tab closed): a newly created or just-selected
        // Level/Scene asset routes into the Level session the same way a double-click does through
        // WireAssetBrowser's m_OnOpenAsset - see that file's own comment.
        {
            AsserBrowser.SetDevice(Device);
            AsserBrowser.EnsureInitialized(e10::g_LibMgr, xresource::g_Mgr);

            e10::g_AssetBrowserPopup.SetDevice(Device);
            e10::g_AssetBrowserPopup.RenderAsPopup(e10::g_LibMgr, xresource::g_Mgr);

            auto RouteAsset = [this](xresource::full_guid Guid) noexcept
            {
                if (!pLevelSession) return;
                if (Guid.m_Type == xecs::level::type_guid_v)
                {
#if defined(XECS_BUILD_SHARED)
                    if (xlevel::RequestOpenLevel(*pLevelSession->m_pGameMgr, pLevelSession->m_State, pLevelSession->m_Undo, Guid, /*bStartGameReload*/ true))
                        xlevel::StartGameReload(pLevelSession->m_GamePlugin);
#else
                    xlevel::RequestOpenLevel(*pLevelSession->m_pGameMgr, pLevelSession->m_State, pLevelSession->m_Undo, Guid, /*bStartGameReload*/ false);
#endif
                }
                else if (Guid.m_Type == xecs::scene::type_guid_v)
                {
                    xscene::OpenScene(*pLevelSession->m_pGameMgr, pLevelSession->m_State, Guid);
                }
            };

            if (auto NewAsset = AsserBrowser.getNewAsset(); NewAsset.empty() == false)
                RouteAsset(NewAsset);
            else if (auto SelAsset = AsserBrowser.getSelectedAsset(); SelAsset.empty() == false)
                RouteAsset(SelAsset);
        }

        // Every open resource editor (Level's own singleton session included) renders itself - see
        // xlevel_session.h's own Render() for what used to be hand-rendered here directly.
        ResourceEditors.RenderAll();
        // Host Drawer last so it stacks above Level and resource editor peer windows (same OS window).
        EditorHost.draw_host_drawers();

        xgpu::tools::imgui::Render();

        g_WindowCapture.BeforeFlip(MainWindow);
        MainWindow.PageFlip();
        g_WindowCapture.AfterFlip();

        xresource::g_Mgr.OnEndFrameDelegate();

        xeditor::diagnostics::Log("frame %llu end", static_cast<unsigned long long>(FrameNumber));
    }
}
