#pragma once

namespace level_editor
{
    // No window, no device, no ImGui context - just the command system. Runs until the Exit command
    // (LevelEditor_Commands_App.h) sets ExitState.bRequested, or the process is killed (matches the
    // named-pipe server model already used for the graphical build's detached Command Console
    // thread; here it's the whole process instead of a background thread). See
    // LevelEditor_AppFrame.h's app::Frame() for the graphical equivalent this mirrors the
    // non-rendering half of (PollGameReload + PumpCommandConsolePipe run there too, unconditionally,
    // before any ImGui/render call - this reuses the exact same two calls).
    inline void app::RunHeadless()
    {
        xeditor::diagnostics::Log("headless: entering command loop");

        while (!ExitState.bRequested)
        {
            level_editor::PollGameReload(CmdContext, GamePlugin, RegisterHostComponents);

            const auto ConsoleLogCountBefore = EditorHost.m_ConsoleLog.size();
            level_editor::PumpCommandConsolePipe(ConsolePipeBridge, LevelEditorHistory, EditorHost.m_ConsoleLog);
            if (EditorHost.m_ConsoleLog.size() != ConsoleLogCountBefore)
                EditorHost.m_IdleWork.NotifyActivity();

            EditorHost.pump_services();

            if (State.m_PlayState == xlevel::level_state::play_state::Playing)
                pGameMgr->Run();

            std::this_thread::sleep_for(std::chrono::milliseconds(16));
        }
    }
}
