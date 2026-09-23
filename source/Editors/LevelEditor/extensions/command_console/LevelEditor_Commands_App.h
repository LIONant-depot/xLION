#ifndef LevelEditor_COMMANDS_APP_H
#define LevelEditor_COMMANDS_APP_H
#pragma once

// Exit - the editor's main loop (graphical Run(), headless RunHeadless()) has no way to stop other
// than a window close or an external kill: the headless build has no window at all, and an
// AI/CLI-driven session (xeditorcli, the smoke tests) needs a clean way to ask the process to end.
// A QUERY command (xundo::query_command_base, not command_base): asking the process to exit isn't
// an undo-able mutation of the scene/entities, same reasoning as Say/GetLog in
// LevelEditor_Commands_Chat.h.
#include "dependencies/xundo/source/xundo_system.h"
#include "dependencies/xeditor/include/xeditor/commands.h"

namespace level_editor::commands
{
    // The app provides one as a host service; Run()/RunHeadless() poll bRequested once per
    // iteration and stop the loop when it's set - same "host owns it, command reaches the same
    // object" pattern chat_log already uses, not a duplicated copy of the app's own state.
    struct exit_state
    {
        bool bRequested = false;
    };

    struct exit_query_cmd : xundo::query_command_base
    {
        exit_query_cmd(xundo::system& System, void*) noexcept : query_command_base(System, "Exit", nullptr) {}
        const char* getCommandHelp() const noexcept override
        {
            return "Asks the editor to close (the graphical build exits its window loop, the headless build exits its command loop). Usage: Exit";
        }
        void RegisterArguments() noexcept override {}
        std::string Query() noexcept override
        {
            xeditor::host::current()->get<exit_state>().bRequested = true;
            return "Exiting";
        }
    };
}

#endif // LevelEditor_COMMANDS_APP_H
