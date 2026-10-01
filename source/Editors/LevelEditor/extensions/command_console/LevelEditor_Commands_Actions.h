#ifndef LevelEditor_COMMANDS_ACTIONS_H
#define LevelEditor_COMMANDS_ACTIONS_H
#pragma once

// ListActions / RunAction / PressKeys / ExplainLastKey - the AI/CLI face of the actions (keys, menus, toolbar buttons;
// see dependencies/actions.imgui and documentation/Editors/actions_and_keybindings.md). QUERY commands, like Say/Exit: pressing
// a key is not itself an undo step - an action that edits a document goes through xeditor::Run, which is what records the step.
//
// PressKeys resolves a chord exactly like a real key press (focus, then hover, then the host's own, innermost first) and says
// what happened - so the smoke tests can check every binding without sending OS keyboard input, which has never been reliable.
//
// All four need the UI's ximgui::actions::context, which the graphical build provides as a host service; the headless build has
// none (no window, no keys) and says so.
#include "dependencies/xundo/source/xundo_system.h"
#include "dependencies/xeditor/include/xeditor/commands.h"

namespace level_editor::commands
{
    inline ximgui::actions::context* ActionContext() noexcept
    {
        auto* pHost = xeditor::host::current();
        return pHost ? pHost->find<ximgui::actions::context>() : nullptr;
    }

    inline constexpr const char* kNoActions = "No actions here: this build has no UI";

    struct list_actions_query_cmd : xundo::query_command_base
    {
        list_actions_query_cmd(xundo::system& System, void*) noexcept : query_command_base(System, "ListActions", nullptr) {}
        const char* getCommandHelp() const noexcept override
        {
            return "Lists the actions that are live in the editor right now: path, keys, and 'ok' or why they cannot run. Usage: ListActions";
        }
        void RegisterArguments() noexcept override {}
        std::string Query() noexcept override
        {
            auto* pCtx = ActionContext();
            return pCtx ? pCtx->List() : kNoActions;
        }
    };

    struct action_problems_query_cmd : xundo::query_command_base
    {
        action_problems_query_cmd(xundo::system& System, void*) noexcept : query_command_base(System, "ActionProblems", nullptr) {}
        const char* getCommandHelp() const noexcept override
        {
            return "Lists what is wrong with the keys setup: keymaps that did not load, keys that do not parse, two actions on one key. Usage: ActionProblems";
        }
        void RegisterArguments() noexcept override {}
        std::string Query() noexcept override
        {
            auto* pCtx = ActionContext();
            if (!pCtx) return kNoActions;
            const auto Text = pCtx->Validate();
            return Text.empty() ? std::string("No problems") : Text;
        }
    };

    struct run_action_query_cmd : xundo::query_command_base
    {
        run_action_query_cmd(xundo::system& System, void*) noexcept : query_command_base(System, "RunAction", nullptr) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override
        {
            return "Runs a live action by its path, as the menu item or key would. Replies 'Ran <path>' or why it did not run. Usage: RunAction -Path Level/Save";
        }
        void RegisterArguments() noexcept override { m_hPath = m_Parser.addOption("Path", "The action's path (see ListActions)", true, 1); }
        std::string Query() noexcept override
        {
            auto* pCtx = ActionContext();
            if (!pCtx) return kNoActions;
            auto Arg = m_Parser.getOptionArgAs<std::string>(m_hPath, 0);
            if (std::holds_alternative<xerr>(Arg)) return "RunAction: bad arguments";
            const auto& Path = std::get<std::string>(Arg);
            const auto Why = pCtx->RunPath(Path);
            return Why.empty() ? std::format("Ran {}", Path) : std::format("{} did not run: {}", Path, Why);
        }
        xcmdline::parser::handle m_hPath;
    };

    struct press_keys_query_cmd : xundo::query_command_base
    {
        press_keys_query_cmd(xundo::system& System, void*) noexcept : query_command_base(System, "PressKeys", nullptr) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override
        {
            return "Presses a key chord the way the keyboard would and says which action it reached, or why none ran. Usage: PressKeys -Keys Ctrl+Shift+D";
        }
        void RegisterArguments() noexcept override { m_hKeys = m_Parser.addOption("Keys", "A chord such as Ctrl+Z, F2 or Space", true, 1); }
        std::string Query() noexcept override
        {
            auto* pCtx = ActionContext();
            if (!pCtx) return kNoActions;
            auto Arg = m_Parser.getOptionArgAs<std::string>(m_hKeys, 0);
            if (std::holds_alternative<xerr>(Arg)) return "PressKeys: bad arguments";
            const auto Chord = ximgui::actions::ParseChord(std::get<std::string>(Arg));
            if (Chord == 0) return std::format("PressKeys: '{}' is not a key chord", std::get<std::string>(Arg));
            return Describe(pCtx->Press(Chord), std::get<std::string>(Arg));
        }

        static std::string Describe(const ximgui::actions::input_result& R, const std::string& Keys)
        {
            if (!R.m_bMatched) return std::format("{}: no live action is bound to it", Keys);
            if (R.m_bRan)      return std::format("{} -> {}", R.m_Keys, R.m_Path);
            return std::format("{} -> {} did not run: {}", R.m_Keys, R.m_Path, R.m_Reason.empty() ? "it reported a failure" : R.m_Reason);
        }
        xcmdline::parser::handle m_hKeys;
    };

    struct explain_last_key_query_cmd : xundo::query_command_base
    {
        explain_last_key_query_cmd(xundo::system& System, void*) noexcept : query_command_base(System, "ExplainLastKey", nullptr) {}
        const char* getCommandHelp() const noexcept override
        {
            return "Says which action the last key that reached one went to, and whether it ran. Usage: ExplainLastKey";
        }
        void RegisterArguments() noexcept override {}
        std::string Query() noexcept override
        {
            auto* pCtx = ActionContext();
            if (!pCtx) return kNoActions;
            if (!pCtx->m_Last.m_bMatched) return "No key has reached an action yet";
            return press_keys_query_cmd::Describe(pCtx->m_Last, pCtx->m_Last.m_Keys);
        }
    };
}

#endif // LevelEditor_COMMANDS_ACTIONS_H
