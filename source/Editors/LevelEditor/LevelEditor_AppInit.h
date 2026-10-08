#pragma once
#include <shellapi.h>

namespace level_editor
{
    // The project the person asked for: `xLION.exe <project folder>` (or `--project <folder>`), else the XLION_PROJECT environment variable. Empty when none was asked for: the editor then opens the
    // example project that sits above the executable (the repository's own).
    inline std::filesystem::path RequestedProject() noexcept
    {
        std::filesystem::path Asked;
        int    Argc = 0;
        LPWSTR* pArgv = CommandLineToArgvW(GetCommandLineW(), &Argc);
        for (int i = 1; pArgv && i < Argc; ++i)
        {
            const std::wstring Arg = pArgv[i];
            if (Arg == L"--project" || Arg == L"-project" || Arg == L"/project") { if (i + 1 < Argc) Asked = pArgv[++i]; }
#if defined(_WIN32)
            else if (!Arg.empty() && Arg[0] != L'-' && Arg[0] != L'/' && Asked.empty()) Asked = Arg;
#else
            else if (!Arg.empty() && Arg[0] != L'-' && Asked.empty()) Asked = Arg;     // Linux port: a leading '/' is an absolute path, not a switch
#endif
        }
        if (pArgv) LocalFree(pArgv);
        if (Asked.empty())
        {
            wchar_t* pEnv = nullptr; std::size_t Len = 0;
            if (_wdupenv_s(&pEnv, &Len, L"XLION_PROJECT") == 0 && pEnv && *pEnv) Asked = pEnv;
            std::free(pEnv);
        }
        return Asked;
    }

    // The folder of a project to open, made absolute, or empty with Why saying what is wrong with it. A project is a folder with its Project.config\Library.config.txt (which names the library) and the
    // resource plugins in Cache\Plugins (the project's Install.bat puts them there); the Assets and Descriptors folders are made when they are missing.
    inline std::filesystem::path ResolveProjectFolder(const std::filesystem::path& Asked, std::string& Why) noexcept
    {
        std::error_code Ec;
        auto Folder = std::filesystem::absolute(Asked, Ec);
        if (Ec || !std::filesystem::is_directory(Folder, Ec)) { Why = std::format("'{}' is not a folder", Asked.string()); return {}; }
        Folder = std::filesystem::canonical(Folder, Ec);
        if (Ec) { Why = std::format("'{}' cannot be opened", Asked.string()); return {}; }
        if (!std::filesystem::exists(Folder / L"Project.config" / L"Library.config.txt", Ec))
        {
            Why = std::format("'{}' is not a project: it has no Project.config\\Library.config.txt", Folder.string());
            return {};
        }
        if (!std::filesystem::is_directory(Folder / L"Cache" / L"Plugins", Ec))
        {
            Why = std::format("'{}' has no Cache\\Plugins: the resource plugins of a project are installed by its Install.bat", Folder.string());
            return {};
        }
        std::filesystem::create_directories(Folder / L"Assets", Ec);
        std::filesystem::create_directories(Folder / L"Descriptors", Ec);
        return Folder;
    }

    inline int app::Init(bool bHeadlessMode)
    {
        bHeadless = bHeadlessMode;

        xeditor::diagnostics::Start("LevelEditor.trace.log");
        xeditor::diagnostics::InstallCrtReportHook();
        xeditor::diagnostics::InstallTerminateHandler();
        xeditor::diagnostics::InstallUnhandledExceptionFilter();
        xeditor::diagnostics::Log("startup: LevelEditor_Example begin");

        // A project that was asked for is checked before anything is created (no window for a path that is wrong).
        std::filesystem::path RequestedFolder;
        if (const auto Asked = RequestedProject(); !Asked.empty())
        {
            std::string Why;
            RequestedFolder = ResolveProjectFolder(Asked, Why);
            if (RequestedFolder.empty())
            {
                xeditor::diagnostics::Log("startup: the project asked for cannot be opened: %s", Why.c_str());
                std::fprintf(stderr, "xLION: %s\n", Why.c_str());
                // A person gets a box (there is no console); a script (XEDITOR_NO_ASSERT_DIALOG, what the tests set) or the headless build only gets the line on stderr and the exit code.
                const bool bNoDialog = []() noexcept
                {
#if defined(_MSC_VER)
                    char* p = nullptr; std::size_t n = 0;                          // _dupenv_s: MSVC's checked getenv (C4996)
                    const bool b = _dupenv_s(&p, &n, "XEDITOR_NO_ASSERT_DIALOG") == 0 && p != nullptr;
                    std::free(p);
                    return b;
#else
                    return std::getenv("XEDITOR_NO_ASSERT_DIALOG") != nullptr;
#endif
                }();
                if (!bHeadless && !bNoDialog) MessageBoxW(nullptr, xstrtool::To(Why).c_str(), L"xLION - cannot open the project", MB_OK | MB_ICONERROR);
                xeditor::diagnostics::RemoveCrtReportHook();
                xeditor::diagnostics::RemoveTerminateHandler();
                xeditor::diagnostics::Stop();
                return 1;
            }
        }

        if (!bHeadless)
        {
            xeditor::diagnostics::Log("startup: creating xgpu instance");
            if (auto Err = xgpu::CreateInstance(Instance, { .m_bDebugMode = true, .m_pLogErrorFunc = xeditor::LogGpuError, .m_pLogWarning = xeditor::LogGpuWarning }); Err)
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
#if defined(XLION_LINUX_GUI)
            xlion::linux_gui::Install(static_cast<unsigned long>(MainWindow.getSystemWindowHandle()), "xLION");   // X11 clipboard for ImGui, the window title
#endif

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

            // The project that was asked for (command line, XLION_PROJECT), else the example project of the repository the executable is in.
            std::filesystem::path ProjectDir = RequestedFolder;
            if (ProjectDir.empty())
            {
                for (std::filesystem::path Dir = std::filesystem::path(szModulePath).parent_path(); ; )
                {
                    std::error_code Ec;
                    if (std::filesystem::exists(Dir / L"example.lionprj" / L"Cache" / L"Plugins", Ec) && !Ec) { ProjectDir = Dir / L"example.lionprj"; break; }
                    const std::filesystem::path Parent = Dir.parent_path();
                    if (Parent.empty() || Parent == Dir) break; // reached the filesystem root without finding a bootstrapped project
                    Dir = Parent;
                }
            }

            if (!ProjectDir.empty())
            {
                const std::wstring ProjectPathW = ProjectDir.wstring();
                TCHAR szFileName[MAX_PATH];
                wcscpy_s(szFileName, MAX_PATH, ProjectPathW.c_str());

                if (auto Err = xresource_editor::g_LibMgr.OpenProject(szFileName); Err)
                {
                    xeditor::NotifyToast(Err.getMessage());
                    xeditor::diagnostics::Log("startup: opening project failed");
                    xeditor::diagnostics::RemoveCrtReportHook();
                    xeditor::diagnostics::RemoveTerminateHandler();
                    xeditor::diagnostics::Stop();
                    return 1;
                }
                xeditor::diagnostics::Log("startup: opening project complete");

                // The Logs are kept from here on: <project>/Cache/Logs/<this launch>/, and the earlier launches are read back in the background (how each ended is classified
                // from its stream and from the crash records xeditor::diagnostics keeps next to the working folder).
                {
                    xlog::store::import_options Options;
                    Options.m_Logs = ProjectDir / L"Cache" / L"Logs";
                    {
                        char* pLogs = nullptr; std::size_t LogsLen = 0;
                        if (_dupenv_s(&pLogs, &LogsLen, "XLOG_LOGS_DIR") == 0 && pLogs && *pLogs) Options.m_Logs = pLogs;       // the smoke tests keep their launches apart from the project's own history
                        std::free(pLogs);
                    }
                    const std::filesystem::path LogsDir = Options.m_Logs;                // (Options is moved into the persistence below)
                    std::error_code Ec;
                    const std::filesystem::path ProblemsLog = std::filesystem::current_path(Ec) / "LevelEditor.problems.log";
                    Options.m_CrashRecord = [ProblemsLog](std::uint32_t Pid, std::uint64_t StartWallMs) { return xlog::store::FindCrashRecord(ProblemsLog, Pid, StartWallMs); };
                    xlog::store::StartPersistence(EditorHost.m_Logs, std::move(Options), xstrtool::To(std::wstring(szModulePath)));

                    // What the person decided (acknowledged, muted, saved views) comes back from the last launch; the team's views are a file of the project (source control).
                    xlog::store::user_files Files;
                    std::filesystem::path Config = ProjectDir / L"Project.config" / L"Logs";
                    char* pDir = nullptr; std::size_t DirLen = 0;
                    if (_dupenv_s(&pDir, &DirLen, "XLOG_USER_DIR") == 0 && pDir && *pDir) Config = pDir;       // the smoke tests keep what they decide out of the project
                    std::free(pDir);
                    char* pUser = nullptr; std::size_t UserLen = 0;
                    std::string User = (_dupenv_s(&pUser, &UserLen, "USERNAME") == 0 && pUser) ? pUser : "user";
                    std::free(pUser);
                    Files.m_Personal = Config / (User + ".logs.txt"); Files.m_Team = Config / "team.logs.txt";
                    xlog::store::StartUserState(EditorHost.m_Logs, std::move(Files));

                    // Runtimes of other processes (a game, a server) speak into these Logs over a named pipe; its name is published next to the launches for them to find. And this
                    // process may itself be such a runtime (XLOG_REMOTE_PIPE = the pipe of the editor that started it): then everything it says is also sent there.
                    {
                        std::string Why;
                        const std::string Pipe = std::format("xlion.logs.{}", static_cast<unsigned>(GetCurrentProcessId()));
                        if (EditorHost.m_RemoteLogs.Start(EditorHost.m_Logs, Pipe, Why))
                        {
                            std::error_code RemoteEc;
                            std::filesystem::create_directories(LogsDir, RemoteEc);
                            std::ofstream(LogsDir / L"remote.txt", std::ios::trunc) << "\\\\.\\pipe\\" << Pipe << "\n";
                            EditorHost.m_Logs.SetRemoteStatus([pRemote = &EditorHost.m_RemoteLogs] { return std::format("Listening=true Pipe={} Connected={} Connections={} Records={} Rejected={}", pRemote->Pipe(), pRemote->Connected(), pRemote->Connections(), pRemote->Records(), pRemote->Rejected()); });
                        }
                        else xeditor::diagnostics::Log("startup: the Logs' remote pipe is not available: %s", Why.c_str());
                        char* pRemote = nullptr; std::size_t RemoteLen = 0;
                        if (_dupenv_s(&pRemote, &RemoteLen, "XLOG_REMOTE_PIPE") == 0 && pRemote && *pRemote)
                            xlog::remote::Connect(EditorHost.m_Logs, pRemote, xstrtool::To(std::wstring(szModulePath)));
                        std::free(pRemote);
                    }
                }

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
                xeditor::diagnostics::Log("startup: no project: none was asked for (xLION.exe <project folder>) and no bootstrapped example.lionprj is above the executable");
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
            WireKeymapNavigation();                                          // "Show in keymap" on a pinned card
            Actions.m_pSearchBox = [](std::string& Text, float Width, bool bFocus) noexcept { return xeditor::RenderTreeSearchBar(Text, Width, bFocus); };           // the palette's search box is the editors' one
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

        // Save All: the open editors (the Levels among them) save theirs, then the resource database (renames and moves). Anything else that keeps unsaved work subscribes here too.
        EditorHost.m_SaveAll.m_OnSave.Register<&xeditor::open_resource_editors::SaveAll>(ResourceEditors);
        EditorHost.m_SaveAll.m_OnSave.Register<&xresource_editor::SaveAssetsOnSaveAll>();

        if (auto Err = EditorHost.m_Workspace.Init({}, false); !Err.empty())
            xeditor::NotifyModal(std::format("LevelEditor: xundo Init failed: {}", Err));

        // A Level opens exactly like Texture does: ResourceEditors.Open(LevelGuid) creates its editor when it is asked for
        // (see OpenLevelEditor). Each new editor gets the commands addressed to it by name (Name\Command is resolved by
        // host::dispatch() through open_resource_editors::SyncToHost, like for Texture).
        xlevel::g_OnSessionCreated = [](xlevel::session& Session) noexcept
        {
            // The viewport camera, to place it from the pipe (SetCamera / GetCamera) the way the mouse does.
            xeditor::camera_access Camera;
            Camera.m_pAngles   = &Session.m_Camera.m_Angles;
            Camera.m_pDistance = &Session.m_Camera.m_Distance;
            Camera.m_pTarget   = &Session.m_Camera.m_Target;
            Session.m_ShellCommands = std::make_shared<level_command_set>
                (Session.m_Undo, static_cast<xscene::scene_context*>(&Session.m_CmdContext), &Session.m_CmdContext, Camera);
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
        // The sources a Game.dll is built from changed, or the window got the focus back: every open Level looks at its own game module.
        EditorHost.m_OnSourceChanged = [this]() noexcept
        {
            for (auto* pContext : xlevel::g_LevelContexts) if (pContext->m_pGamePlugin) xlevel::StartGameReload(*pContext->m_pGamePlugin);
        };
        EditorHost.m_OnFocusRegain = [this]() noexcept
        {
#if defined(XECS_BUILD_SHARED)
            for (auto* pContext : xlevel::g_LevelContexts) if (pContext->m_pGamePlugin) xlevel::StartGameReload(*pContext->m_pGamePlugin);
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

        xresource_editor::source_control::StopSourceControlScans();       // a scan worker must not outlive the statics it reads

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
#if defined(XLION_LINUX_GUI)
            xlion::linux_gui::Shutdown();
#endif
            xgpu::tools::imgui::Shutdown();
            xeditor::diagnostics::Log("shutdown: xgpu/imgui Shutdown complete");
        }

        xeditor::diagnostics::RemoveCrtReportHook();
        xeditor::diagnostics::RemoveTerminateHandler();
        xeditor::diagnostics::Log("shutdown: LevelEditor_Example return");
        xeditor::diagnostics::Stop();
    }
}
