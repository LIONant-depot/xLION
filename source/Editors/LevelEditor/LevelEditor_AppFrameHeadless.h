#pragma once

namespace level_editor
{
    // No window, no device, no ImGui context - just the command system. Runs until the Exit command
    // (LevelEditor_Commands_App.h) sets ExitState.bRequested, or the process is killed. Mirrors app::Frame()'s
    // non-rendering half: PumpBeforeFrame (recompile-check completion + deferred Stop) and
    // PumpCommandConsolePipe run there too, unconditionally, before any ImGui/render call.
    inline void app::RunHeadless()
    {
        xeditor::diagnostics::Log("headless: entering command loop");

        while (!ExitState.bRequested)
        {
            PumpLevels();
            ResourceEditors.SyncToHost(EditorHost);

            const auto ConsoleLogCountBefore = EditorHost.m_ConsoleLog.size();
            if (!xlevel::Services().InitialBuild())
                level_editor::PumpCommandConsolePipe(ConsolePipeBridge, LevelEditorHistory, EditorHost.m_ConsoleLog);
            if (EditorHost.m_ConsoleLog.size() != ConsoleLogCountBefore)
                EditorHost.m_IdleWork.NotifyActivity();

            EditorHost.pump_services();

            ForEachLevelSession([](xlevel::session& S)
            {
                if (S.m_State.m_PlayState == xlevel::level_state::play_state::Playing) S.m_pEcs->RunSystems();
            });

            std::this_thread::sleep_for(std::chrono::milliseconds(16));
        }
    }
}
