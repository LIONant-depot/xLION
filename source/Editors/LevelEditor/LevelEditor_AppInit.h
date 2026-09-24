#pragma once

namespace level_editor
{
    inline int app::Init(bool bHeadlessMode)
    {
        bHeadless = bHeadlessMode;

        xeditor::diagnostics::Start("LevelEditor.trace.log");
        xeditor::diagnostics::InstallCrtReportHook();
        xeditor::diagnostics::InstallTerminateHandler();
        xeditor::diagnostics::InstallUnhandledExceptionFilter();
        xeditor::diagnostics::Log("startup: LevelEditor_Example begin");

        if (!bHeadless)
        {
            xeditor::diagnostics::Log("startup: creating xgpu instance");
            if (auto Err = xgpu::CreateInstance(Instance, { .m_bDebugMode = true, .m_pLogErrorFunc = xeditor::NotifyError, .m_pLogWarning = xeditor::NotifyError }); Err)
            {
                xeditor::diagnostics::Log("startup: xgpu instance creation failed");
                xeditor::diagnostics::RemoveCrtReportHook();
                xeditor::diagnostics::RemoveTerminateHandler();
                xeditor::diagnostics::Stop();
                return xgpu::getErrorInt(Err);
            }
            xeditor::diagnostics::Log("startup: creating xgpu device");
            if (auto Err = Instance.Create(Device); Err)
            {
                xeditor::diagnostics::Log("startup: xgpu device creation failed");
                xeditor::diagnostics::RemoveCrtReportHook();
                xeditor::diagnostics::RemoveTerminateHandler();
                xeditor::diagnostics::Stop();
                return xgpu::getErrorInt(Err);
            }
            xeditor::diagnostics::Log("startup: creating main window");
            if (auto Err = Device.Create(MainWindow, {}); Err)
            {
                xeditor::diagnostics::Log("startup: main window creation failed");
                xeditor::diagnostics::RemoveCrtReportHook();
                xeditor::diagnostics::RemoveTerminateHandler();
                xeditor::diagnostics::Stop();
                return xgpu::getErrorInt(Err);
            }
        }

        xeditor::diagnostics::Log("startup: initializing resource manager");
        xresource::g_Mgr.Initiallize(20000);
        ResourceMgrUserData.m_Device = Device;
        xresource::g_Mgr.setUserData(&ResourceMgrUserData, false);

        if (!bHeadless)
        {
            xeditor::diagnostics::Log("startup: xgpu/imgui CreateInstance begin");
            ResourceEditors.m_pDevice = &Device;
            xgpu::tools::imgui::CreateInstance(MainWindow);
            xeditor::diagnostics::Log("startup: xgpu/imgui CreateInstance complete");

            xeditor::diagnostics::Log("startup: applying LevelEditor theme begin");
            level_editor::theme::ApplyUnityInspiredTheme();
            xeditor::diagnostics::Log("startup: applying LevelEditor theme complete");

            // io.FontDefault (not a per-frame PushFont) - xgpu::tools::imgui::BeginRendering() calls
            // ImGui::DockSpace() internally, BEFORE any panel's own render code ever runs, and ImGui's docking
            // tab bar renders using whatever font is current AT THAT POINT.
            xeditor::diagnostics::Log("startup: selecting LevelEditor default font begin");
            ImGui::GetIO().FontDefault = ImGui::GetIO().Fonts->Fonts[4];
            xeditor::diagnostics::Log("startup: selecting LevelEditor default font complete");
        }

        //
        // Open the project - every resource editor (Level included) needs it open before it can be created.
        // Historically this located the repo root by searching the executable's own path for the first literal
        // "xGPU" substring; fixed to walk UP the executable's own ancestor directories and pick the first
        // (closest) one that actually has a bootstrapped example.lionprj\Cache\Plugins - i.e. finding the repo
        // root structurally, never by name (a worktree checkout nested under a folder that ALSO contains "xGPU"
        // earlier in its path broke the substring match).
        //
        {
            xeditor::diagnostics::Log("startup: opening project begin");
            TCHAR szModulePath[MAX_PATH];
            GetModuleFileName(NULL, szModulePath, MAX_PATH);

            std::filesystem::path RepoRoot;
            for (std::filesystem::path Dir = std::filesystem::path(szModulePath).parent_path(); ; )
            {
                std::error_code Ec;
                if (std::filesystem::exists(Dir / L"example.lionprj" / L"Cache" / L"Plugins", Ec) && !Ec) { RepoRoot = Dir; break; }
                const std::filesystem::path Parent = Dir.parent_path();
                if (Parent.empty() || Parent == Dir) break; // reached the filesystem root without finding a bootstrapped project
                Dir = Parent;
            }

            if (!RepoRoot.empty())
            {
                const std::wstring ProjectPathW = (RepoRoot / L"example.lionprj").wstring();
                TCHAR szFileName[MAX_PATH];
                wcscpy_s(szFileName, MAX_PATH, ProjectPathW.c_str());

                if (auto Err = e10::g_LibMgr.OpenProject(szFileName); Err)
                {
                    xeditor::NotifyError(Err.getMessage());
                    xeditor::diagnostics::Log("startup: opening project failed");
                    xeditor::diagnostics::RemoveCrtReportHook();
                    xeditor::diagnostics::RemoveTerminateHandler();
                    xeditor::diagnostics::Stop();
                    return 1;
                }
                xeditor::diagnostics::Log("startup: opening project complete");

                if (!bHeadless)
                {
                    ImGuiIO& io = ImGui::GetIO();
                    static std::string IniSave = std::format("{}/Assets/imgui_level_editor.ini", xstrtool::To(szFileName));
                    io.IniFilename = IniSave.c_str();
                }
            }
            else
            {
                xeditor::diagnostics::Log("startup: could not locate a bootstrapped example.lionprj above the executable");
            }
        }
        xeditor::diagnostics::Log("startup: editor state and asset browser constructed");

        // Visible from the start and never closable - browsing/creating Levels and Scenes is this editor's
        // primary activity, so it's a permanent, dockable part of the layout.
        AsserBrowser.setDisplayMode(e10::assert_browser::display_mode::DOCKABLE);
        AsserBrowser.SetWindowName(xlevel::editor_tabs::kResourceBrowserWindow);
        AsserBrowser.Show(true);

        EditorHost.m_pExternalWorkspace = &LevelEditorUndo;
        EditorHost.m_OnBeforeEdit        = xlevel::TryGateLevelMutation;
        EditorHost.provide(ChatLog);
        EditorHost.provide(ExitState);
        EditorHost.provide(ResourceEditors);
        EditorHost.provide(AsserBrowser);
        if (!bHeadless)
        {
            EditorHost.provide(Device);
            EditorHost.provide(MainWindow);
        }
        EditorHost.m_IdleWork.m_OnRun.Register<&e10::source_control::ScanAllLibrariesWhenIdle>();

        if (auto Err = LevelEditorUndo.Init({}, false); !Err.empty())
            xeditor::NotifyError(std::format("LevelEditor: xundo Init failed: {}", Err));

        // Level opens exactly like Texture does on double-click - the one difference is WHEN: Level is a
        // singleton with no natural per-Guid identity of its own (see xlevel_session.h's own top comment), so
        // it opens once here, at startup, rather than lazily on a browser click. Guid.m_Instance is left at its
        // default (0) - Open()/the factory map key off Guid.m_Type only.
        {
            auto* pEditor = ResourceEditors.Open(xresource::full_guid{ {}, xecs::level::type_guid_v }, {});
            pLevelSession = static_cast<xlevel::session*>(pEditor);
            if (!pLevelSession) xeditor::NotifyError("LevelEditor: failed to construct the Level session");
        }

        if (pLevelSession)
        {
            Commands.emplace(LevelEditorUndo, pLevelSession->m_Undo, static_cast<xscene::scene_context*>(&pLevelSession->m_CmdContext), &pLevelSession->m_CmdContext);
            LevelEditorHistory.AddSystem("LevelEditor", 1, LevelEditorUndo);
        }

        std::thread(level_editor::CommandConsolePipeThreadMain, std::ref(ConsolePipeBridge)).detach();

        WireAssetBrowser();

        xeditor::diagnostics::Log("startup: initialization complete, entering frame loop");

        // Host service hooks: Idle Work + SC idle + Game.dll focus-reload.
        EditorHost.m_OnPumpServices = [&]() noexcept
        {
            e10::source_control::ScanNewlyOpenedLibraries();
        };
        EditorHost.m_OnSourceChanged = [this]() noexcept
        {
            if (pLevelSession) xlevel::StartGameReload(pLevelSession->m_GamePlugin);
        };
        EditorHost.m_OnFocusRegain = [this]() noexcept
        {
#if defined(XECS_BUILD_SHARED)
            if (pLevelSession) xlevel::StartGameReload(pLevelSession->m_GamePlugin);
#endif
        };
        EditorHost.m_OnDrawerTab = [this](int TabIndex, const char* /*TabName*/) { DrawDrawerTab(TabIndex); };

        return 0;
    }

    inline void app::Run()
    {
        while (Instance.ProcessInputEvents() && !ExitState.bRequested) Frame();
    }

    inline void app::Shutdown()
    {
        xeditor::diagnostics::Log("shutdown: frame loop ended");

        // Plugin systems live in the Level session's world but their DestroyFunction code is in the DLL -
        // dropping every open resource editor (Level's own session included) BEFORE FreeLibrary is what used to
        // matter here; now it is just the generic open_resource_editors teardown, no separate ordering needed.
        ResourceEditors.m_List.clear();
        pLevelSession = nullptr;
        EditorHost.withdraw<xeditor::open_resource_editors>();
        EditorHost.withdraw<e10::assert_browser>();
        if (!bHeadless)
        {
            EditorHost.withdraw<xgpu::device>();
            EditorHost.withdraw<xgpu::window>();
        }
        EditorHost.release_current();

        xeditor::diagnostics::Log("shutdown: game plugin unloaded");

        if (!bHeadless)
        {
            xeditor::diagnostics::Log("shutdown: xgpu/imgui Shutdown begin");
            xgpu::tools::imgui::Shutdown();
            xeditor::diagnostics::Log("shutdown: xgpu/imgui Shutdown complete");
        }

        xeditor::diagnostics::RemoveCrtReportHook();
        xeditor::diagnostics::RemoveTerminateHandler();
        xeditor::diagnostics::Log("shutdown: LevelEditor_Example return");
        xeditor::diagnostics::Stop();
    }
}
