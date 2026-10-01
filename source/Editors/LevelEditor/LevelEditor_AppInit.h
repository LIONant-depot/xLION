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

                if (auto Err = xresource_editor::g_LibMgr.OpenProject(szFileName); Err)
                {
                    xeditor::NotifyError(Err.getMessage());
                    xeditor::diagnostics::Log("startup: opening project failed");
                    xeditor::diagnostics::RemoveCrtReportHook();
                    xeditor::diagnostics::RemoveTerminateHandler();
                    xeditor::diagnostics::Stop();
                    return 1;
                }
                xeditor::diagnostics::Log("startup: opening project complete");

                // Every xresource::loader<T>::Load() builds its path from this root - dropped during the
                // Level-ownership split (it sat next to the Level-specific pGameMgr->*Mgr.m_ProjectPath lines
                // that correctly moved into xlevel_session.h, but this one is resource-manager-global, not
                // Level-specific, so it belongs here in the shell, not the plugin).
                xresource::g_Mgr.setRootPath(std::format(L"{}//Cache//Resources//Platforms//Windows", xresource_editor::g_LibMgr.m_ProjectPath));

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
        AssetBrowser.setDisplayMode(xresource_editor::asset_browser::display_mode::DOCKABLE);
        AssetBrowser.SetWindowName(xlevel::editor_tabs::kResourceBrowserWindow);
        AssetBrowser.Show(true);

        // EditorHost.m_Workspace IS the shell's framework-level workspace now - no more overriding it with a
        // separate app-owned system (stage (c): removed the m_pExternalWorkspace indirection entirely).
        EditorHost.m_OnBeforeEdit        = xlevel::TryGateLevelMutation;
        EditorHost.provide(ChatLog);
        EditorHost.provide(ExitState);
        EditorHost.provide(ResourceEditors);
        EditorHost.provide(AssetBrowser);
        if (!bHeadless)
        {
            EditorHost.provide(Device);
            EditorHost.provide(MainWindow);

            // Keys: the actions' defaults (member_keys), then the base preset and this person's own file from
            // Project.config\Keymaps\<user>.keymap.txt (see ximgui_actions_keymap.h). The Drawer key is the first of them.
            EditorHost.provide(Actions);
            AssetBrowser.m_bFileKeysByHost = true;                         // the Assets tab's file keys are the Assets/... actions (FilesActions)
            ShortcutLabels.m_KeysOf = [this](std::string_view Path) { return Actions.KeysOfPath(Path); };
            EditorHost.provide(ShortcutLabels);
            Actions.m_pShowHint = [](const ximgui::actions::hint_text& H) noexcept       // every action hint is the editors' one hint window
                { xeditor::hint::Draw({ H.m_Topic, H.m_Body, H.m_Shortcut, H.m_Disabled, H.m_Detail }); };
            Actions.m_pSearchBox = &xeditor::RenderTreeSearchBar;           // the palette's search box is the editors' one
            EditorHost.m_bDrawerToggleByAction = true;

            // Everything that goes wrong with the keys lands in the console log (the Commands tab, GetLog-style reports): setup
            // problems as they are found, and every key that reached an action but could not run it.
            Actions.m_OnProblem.Register<+[](ximgui::actions::context&, const std::string& Text) { xeditor::LogConsole("actions: " + Text, xeditor::log_source::System); }>();
            Actions.m_OnInput.Register<+[](ximgui::actions::context&, const ximgui::actions::input_result& R)
            {
                if (!R.m_bRan) xeditor::LogConsole(std::format("actions: {} -> {} did not run: {}", R.m_Keys, R.m_Path, R.m_Reason.empty() ? "it reported a failure" : R.m_Reason), xeditor::log_source::System);
            }>();
            {
                char User[256] = {};
                size_t UserLen = 0;
                getenv_s(&UserLen, User, sizeof(User), "USERNAME");
                ximgui::actions::ApplyKeymapLayers(Actions, std::format(L"{}\\Project.config\\Keymaps", xresource_editor::g_LibMgr.m_ProjectPath), User);
            }
        }
        EditorHost.m_IdleWork.m_OnRun.Register<&xresource_editor::source_control::ScanAllLibrariesWhenIdle>();

        if (auto Err = EditorHost.m_Workspace.Init({}, false); !Err.empty())
            xeditor::NotifyError(std::format("LevelEditor: xundo Init failed: {}", Err));

        // A Level opens exactly like Texture does: ResourceEditors.Open(LevelGuid) creates its editor when it is asked for
        // (see OpenLevelEditor). Each new editor gets the commands addressed to it by name (Name\Command is resolved by
        // host::dispatch() through open_resource_editors::SyncToHost, like for Texture).
        xlevel::g_OnSessionCreated = [](xlevel::session& Session) noexcept
        {
            Session.m_ShellCommands = std::make_shared<level_command_set>
                (Session.m_Undo, static_cast<xscene::scene_context*>(&Session.m_CmdContext), &Session.m_CmdContext);
        };
        xlevel::g_OpenLevelSession = [this](xresource::full_guid LevelGuid) { return OpenLevelEditor(LevelGuid); };

        // The editor without a Level: it brings the game module up and is what the workspace commands act on until a
        // Level is open. It is not in ResourceEditors, so it is never drawn or listed.
        IdleLevel = std::make_unique<xlevel::session>(xresource::full_guid{}, xresource_editor::library::guid{}, ResourceEditors.m_pDevice);
        LastLevelTarget = &IdleLevel->m_CmdContext;
        Commands.emplace(EditorHost.m_Workspace, LastLevelTarget);

        std::thread(level_editor::CommandConsolePipeThreadMain, std::ref(ConsolePipeBridge)).detach();

        WireAssetBrowser();

        xeditor::diagnostics::Log("startup: initialization complete, entering frame loop");

        // Host service hooks: Idle Work + SC idle + Game.dll focus-reload.
        EditorHost.m_OnPumpServices = [&]() noexcept
        {
            xresource_editor::source_control::ScanNewlyOpenedLibraries();
        };
        EditorHost.m_OnSourceChanged = [this]() noexcept
        {
            xlevel::StartGameReload(xlevel::Services().Plugin);
        };
        EditorHost.m_OnFocusRegain = [this]() noexcept
        {
#if defined(XECS_BUILD_SHARED)
            xlevel::StartGameReload(xlevel::Services().Plugin);
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
        IdleLevel.reset();
        xlevel::ShutdownLevelServices();
        xlevel::g_OnSessionCreated = {};
        xlevel::g_OpenLevelSession = {};
        EditorHost.withdraw<xeditor::open_resource_editors>();
        EditorHost.withdraw<xresource_editor::asset_browser>();
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
