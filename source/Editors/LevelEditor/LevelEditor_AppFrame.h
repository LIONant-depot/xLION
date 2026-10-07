#pragma once

namespace level_editor
{
    template<typename T_FN>
    void app::ForEachLevelSession(T_FN&& Fn)
    {
        for (auto& E : ResourceEditors.m_List)
            if (E && E->m_bOpen)
                if (auto* pSession = dynamic_cast<xlevel::session*>(E.get())) Fn(*pSession);
    }

    // Opens a Level (or a Prefab: a Prefab Editor is the same editor with a prefab as its document) in its own editor (or brings the one it already has to the front) and builds the OpenLevel / OpenPrefab command's reply.
    inline std::string app::OpenLevelEditor(xresource::full_guid LevelGuid)
    {
        const std::uint64_t Value = LevelGuid.m_Instance.m_Value;
        const bool          bPrefab = LevelGuid.m_Type == xecs::prefab::type_guid_v;
        const char* const   pCommand = bPrefab ? "OpenPrefab" : "OpenLevel";
        if (auto* pOpen = ResourceEditors.Find(LevelGuid); pOpen)
        {
            pOpen->Focus();
            return std::format("{}: {:016X} is already open", pCommand, Value);
        }

#if defined(XECS_BUILD_SHARED)
        // A Level of a Game that has no DLL yet waits for its first build (a command waits right here; the Level tree's open waits in PumpLevels).
        if (const auto Game = xlevel::GameOfDocument(LevelGuid); xlevel::GameNeedsFirstBuild(Game) || xlevel::FirstBuildRunning(Game))
        {
            xlevel::StartFirstBuild(Game);
            xlevel::WaitFirstBuild(Game);
        }
#endif
        auto* pEditor  = ResourceEditors.Open(LevelGuid, xeditor::open_resource_editors::FindLibraryOf(LevelGuid));
        auto* pSession = dynamic_cast<xlevel::session*>(pEditor);
        if (pSession == nullptr || !pSession->m_State.HasDocument())
        {
            if (pEditor) pEditor->m_bOpen = false;          // it never got a Level: drop it
            if (bPrefab) return std::format("OpenPrefab: failed to open {:016X} ({})", Value, pSession && !pSession->m_OpenError.empty() ? pSession->m_OpenError : std::string("unknown Prefab guid or load error"));
            return std::format("OpenLevel: failed to open {:016X} (unknown Level guid or load error)", Value);
        }

        // Listed right away, so the very next command can already be addressed to it (Name\Command).
        ResourceEditors.SyncToHost(EditorHost);

        // Component-registry compatibility plan, Phase 4: informational, not blocking - EnsureLoaded already soft-fails a
        // per-entity missing-component-type case on its own; this surfaces it at the command's reply too.
        std::vector<xecs::scene::component_dependency> Missing;
        for (auto& SceneGuid : pSession->m_State.m_OpenScenes)
            for (auto& Dep : xecs::scene::LoadSceneComponentDependencies(xresource_editor::g_LibMgr.m_ProjectPath, SceneGuid))
                if (!xscene::IsComponentInLiveRegistry(*pSession->m_pGameMgr, Dep.m_Guid) && std::find_if(Missing.begin(), Missing.end(), [&](auto& M) noexcept { return M.m_Guid == Dep.m_Guid; }) == Missing.end())
                    Missing.push_back(Dep);

        std::string Result = bPrefab ? std::format("Opened Prefab {:016X}, {} scene(s) now open", Value, pSession->m_State.m_OpenScenes.size())
                                     : std::format("Opened Level {:016X}, {} scene(s) now open", Value, pSession->m_State.m_OpenScenes.size());
        if (!Missing.empty())
        {
            // Each one with the script module its scene was saved with, when it says (the module the Game has to list for the component to be there)
            const auto ModuleNames = xlevel::commands::BuildAssetNameMap(xscript::module::type_guid_v);
            std::string Names;
            for (auto& Dep : Missing)
            {
                std::string Item = Dep.m_Name;
                if (Dep.m_Module != 0 && Dep.m_Module != xecs::scene::unknown_module_v)
                {
                    const auto Found = ModuleNames.find(Dep.m_Module);
                    Item += std::format(" (module {})", Found == ModuleNames.end() ? std::format("{:X}", Dep.m_Module) : Found->second);
                }
                Names += (Names.empty() ? "" : ", ") + Item;
            }
            Result += std::format(" - WARNING: {} component type(s) used by these scenes are not currently registered: {}", Missing.size(), Names);
        }
        // The same question, answered from the files: does the Game this Level runs under list the modules its scenes need?
        {
            const std::wstring Project = xlevel::ProjectRoot().wstring();
            xlevel::scene_module_needs Needs;
            for (auto& SceneGuid : pSession->m_State.m_OpenScenes) xlevel::AddSceneModuleNeeds(Needs, Project, SceneGuid.m_Instance.m_Value, /*bTransitive*/ false);
            const auto Named = xlevel::GameOfDocument(LevelGuid);                // no Game: no module's scripts, components or systems
            const auto Game  = Named ? xlevel::ReadGame(Named) : xlevel::project_game{};
            if (!Named || Game.HasGame())
                if (const auto Gaps = xlevel::MissingModules(Needs, Game.m_Modules); !Gaps.empty())
                    Result += std::format(" - ERROR: {} {} module(s) these scenes need (CheckGameCompatibility -Level {:016X} says which)", Named ? "the Game does not list" : "the Level names no Game, so nothing provides", Gaps.size(), Value);
        }
        return Result;
    }

    // Once a frame, at a clean point (before anything draws): open the Levels that were asked for, drop the editors that
    // closed, pump the rest (recompile-check completion, deferred Stop, ...), and aim the workspace commands at the Level the
    // user is working on.
    inline void app::PumpLevels()
    {
        // A Level of a Game whose first Game.dll is still building waits for it.
#if defined(XECS_BUILD_SHARED)
        xlevel::PumpFirstBuilds();
#endif
        {
            auto Pending = std::move(xlevel::g_PendingOpenLevels);
            xlevel::g_PendingOpenLevels.clear();
            for (auto& LevelGuid : Pending)
            {
#if defined(XECS_BUILD_SHARED)
                if (const auto Game = xlevel::GameOfDocument(LevelGuid); xlevel::GameNeedsFirstBuild(Game) || xlevel::FirstBuildRunning(Game))
                {
                    xlevel::StartFirstBuild(Game);
                    xlevel::g_PendingOpenLevels.push_back(LevelGuid);
                    continue;
                }
#endif
                OpenLevelEditor(LevelGuid);
            }
        }

        // What a panel asked an editor to do that opens another editor (Edit in Context), now that nothing is drawing.
        {
            auto Commands = std::move(xlevel::g_PendingLevelCommands);
            xlevel::g_PendingLevelCommands.clear();
            for (auto& Pending : Commands)
                if (std::find(xlevel::g_LevelContexts.begin(), xlevel::g_LevelContexts.end(), Pending.m_pEditor) != xlevel::g_LevelContexts.end())
                {
                    // A query (EditInContext is one): xeditor::Run would look it up among the edit commands and not find it, and RunQuery takes any "X: ..." reply for a failure.
                    xeditor::LogConsole(Pending.m_Command, xeditor::log_source::User);
                    auto Reply = Pending.m_pEditor->m_Undo.Query(Pending.m_Command);
                    if (Reply.find(": ok") == std::string::npos) xeditor::NotifyToast(Reply);
                    xeditor::LogConsole(std::move(Reply), xeditor::log_source::System);
                }
        }

        ResourceEditors.DropClosed();

        if (IdleLevel) IdleLevel->PumpBeforeFrame();
        ForEachLevelSession([](xlevel::session& S) { S.PumpBeforeFrame(); });

        xlevel::level_context* pTarget = xlevel::g_pActiveLevelContext;
        if (pTarget == nullptr && IdleLevel) pTarget = &IdleLevel->m_CmdContext;
        if (pTarget != LastLevelTarget && Commands)
        {
            Commands->SetLevelTarget(pTarget);
            LastLevelTarget = pTarget;
        }
    }

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
        PumpLevels();

        // The command pipe waits for the first Game.dll build too: a script sees the editor as ready only once its Levels can open.
        const auto ConsoleLogCountBefore = EditorHost.m_ConsoleLog.size();
        if (!xlevel::Services().InitialBuild())
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

        // Keys pressed this frame go to the actions that were live in the last one; this frame's panels register theirs as they draw.
        Actions.NewFrame();
        Actions.Global(HostActions, "Drawer", "Palette", "Keyboard", "Explain", "Logs");

        // Asset open drain (drawer works even with the Level peer tab closed): a newly created or just-selected
        // Level/Scene asset routes into the Level session the same way a double-click does through
        // WireAssetBrowser's m_OnOpenAsset - see that file's own comment.
        {
            AssetBrowser.SetDevice(Device);
            AssetBrowser.EnsureInitialized(xresource_editor::g_LibMgr, xresource::g_Mgr);

            xresource_editor::g_AssetBrowserPopup.SetDevice(Device);
            xresource_editor::g_AssetBrowserPopup.RenderAsPopup(xresource_editor::g_LibMgr, xresource::g_Mgr);

            auto RouteAsset = [this](xresource::full_guid Guid) noexcept
            {
                if (Guid.m_Type == xecs::level::type_guid_v)
                {
                    xlevel::QueueOpenLevel(Guid);       // opened at the start of the next frame (PumpLevels)
                }
                else if (Guid.m_Type == xecs::scene::type_guid_v)
                {
                    // A Scene goes into the Level the user is working on.
                    if (auto* pCtx = xlevel::g_pActiveLevelContext; pCtx && !pCtx->State().m_CurrentLevel.empty())
                        xscene::OpenScene(pCtx->World(), pCtx->State(), Guid);
                }
            };

            if (auto NewAsset = AssetBrowser.getNewAsset(); NewAsset.empty() == false)
                RouteAsset(NewAsset);
            else if (auto SelAsset = AssetBrowser.getSelectedAsset(); SelAsset.empty() == false)
                RouteAsset(SelAsset);
        }

        // Every open resource editor (Level's own singleton session included) renders itself - see
        // xlevel_session.h's own Render() for what used to be hand-rendered here directly.
        ResourceEditors.RenderAll();

        // The error popup belongs to the application, not to one editor: it is drawn here, once a frame, whichever editor is in front (drawn from
        // the Level editor it never showed while another editor had the screen), and it opens in the middle of the editor that had the focus.
        EditorHost.render_notifications();

        // With no Level open there is still a (empty) Level tab, like at startup: its File menu reaches the Asset Browser to open one.
        {
            bool bAnyLevel = false;
            ForEachLevelSession([&](xlevel::session&) { bAnyLevel = true; });
            if (!bAnyLevel && IdleLevel) IdleLevel->Render();
        }
        // Host Drawer last so it stacks above Level and resource editor peer windows (same OS window).
        EditorHost.draw_host_drawers();
        ximgui::actions::DrawPalette(Actions);         // over everything
        ximgui::actions::DrawKeyboardOverlay(Actions);
        ximgui::actions::DrawPinnedCard(Actions);
        ximgui::actions::DrawStatusLine(Actions);
        Actions.EndFrame();

        xgpu::tools::imgui::Render();

        g_WindowCapture.BeforeFlip(MainWindow);
        MainWindow.PageFlip();
        g_WindowCapture.AfterFlip();

        xresource::g_Mgr.OnEndFrameDelegate();

        xeditor::diagnostics::Log("frame %llu end", static_cast<unsigned long long>(FrameNumber));
    }
}
