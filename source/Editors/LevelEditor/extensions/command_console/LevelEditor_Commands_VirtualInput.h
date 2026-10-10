#ifndef LEVELEDITOR_COMMANDS_VIRTUALINPUT_H
#define LEVELEDITOR_COMMANDS_VIRTUALINPUT_H
#pragma once

// The virtual mouse and keyboard of the editor (dependencies/xGPU/source/Details/xgpu_virtual_input.h): commands that make the editor believe somebody is moving a mouse and pressing keys,
// while the real mouse and keyboard of the machine are ignored. A test, or an assistant, drives the window editor with them without fighting the person at the computer for the one real
// mouse. The input is read by the editor's next frame: wait for it with InputFrames before looking at its effect.
//
//      VirtualInput -On true                 the machine's mouse and keys are ignored from now on; -On false gives them back
//      MouseMove -X 640 -Y 360               the virtual mouse, in pixels of the main window
//      MouseButton -Button left -Down true   left, right or middle; -Down false releases it
//      MouseWheel -Delta 1                   a turn of the wheel (positive: away from you)
//      Key -Key F2 -Down true                a key by name (the xgpu key without KEY_: A, RETURN, LCONTROL, F2, LEFT) or -Code N; -Down false releases it
//      Text -Text "Soccer"                   typed, one character per frame
//      InputFrames                           the number of frames the editor has read the virtual input in: it moves when a frame has seen what was sent
//      InputState                            what ImGui sees of the mouse, to check that it arrived
#include "dependencies/xGPU/source/xGPU.h"
#include "imgui.h"
#include "LevelEditor_VirtualInputKeys.h"

#include <algorithm>
#include <charconv>
#include <cstdlib>
#include <format>
#include <string>

namespace level_editor::commands
{
    // The text arguments of these commands, read as text and parsed here (the same way the other commands of the editor do it).
    struct virtual_input_command : xundo::query_command_base
    {
        using xundo::query_command_base::query_command_base;

        bool Arg(xcmdline::parser::handle h, std::string& Out) const noexcept
        {
            auto V = m_Parser.getOptionArgAs<std::string>(h, 0);
            if (std::holds_alternative<xerr>(V)) return false;
            Out = std::get<std::string>(V);
            return true;
        }

        static bool ToFloat(const std::string& Text, float& Out) noexcept { char* pEnd = nullptr; Out = std::strtof(Text.c_str(), &pEnd); return pEnd != Text.c_str() && *pEnd == 0; }
        static bool ToBool (const std::string& Text, bool& Out) noexcept
        {
            std::string L = Text; std::transform(L.begin(), L.end(), L.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
            if (L == "true" || L == "1" || L == "yes" || L == "on")  { Out = true;  return true; }
            if (L == "false" || L == "0" || L == "no" || L == "off") { Out = false; return true; }
            return false;
        }
        static const char* kNotActive() noexcept { return "virtual input is off: send  VirtualInput -On true  first"; }
    };

    struct virtual_input_cmd : virtual_input_command
    {
        virtual_input_cmd(xundo::system& System, void*) noexcept : virtual_input_command(System, "VirtualInput", nullptr) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Gives the editor a virtual mouse and keyboard in place of the machine's (which are ignored while it is on). Usage: VirtualInput -On true|false"; }
        void RegisterArguments() noexcept override { m_hOn = m_Parser.addOption("On", "true: the editor takes its input from the commands; false: from the machine again", false, 1); }
        std::string Query() noexcept override
        {
            std::string Text; bool bOn = false;
            if (Arg(m_hOn, Text))
            {
                if (!ToBool(Text, bOn)) return std::format("VirtualInput: '{}' is not true or false", Text);
                xgpu::virtual_input::SetActive(bOn);
            }
            return std::format("VirtualInput: {}", xgpu::virtual_input::Active() ? "on" : "off");
        }
        xcmdline::parser::handle m_hOn;
    };

    struct mouse_move_cmd : virtual_input_command
    {
        mouse_move_cmd(xundo::system& System, void*) noexcept : virtual_input_command(System, "MouseMove", nullptr) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Moves the virtual mouse, in pixels of the main window. Usage: MouseMove -X 640 -Y 360"; }
        void RegisterArguments() noexcept override { m_hX = m_Parser.addOption("X", "Pixels from the left of the window", true, 1); m_hY = m_Parser.addOption("Y", "Pixels from the top of the window", true, 1); }
        std::string Query() noexcept override
        {
            if (!xgpu::virtual_input::Active()) return kNotActive();
            std::string X, Y; float Fx = 0, Fy = 0;
            if (!Arg(m_hX, X) || !Arg(m_hY, Y) || !ToFloat(X, Fx) || !ToFloat(Y, Fy)) return "MouseMove: -X and -Y are required (numbers)";
            xgpu::virtual_input::MoveTo(Fx, Fy);
            return std::format("MouseMove: {:.0f},{:.0f}", Fx, Fy);
        }
        xcmdline::parser::handle m_hX, m_hY;
    };

    struct mouse_button_cmd : virtual_input_command
    {
        mouse_button_cmd(xundo::system& System, void*) noexcept : virtual_input_command(System, "MouseButton", nullptr) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Presses or releases a button of the virtual mouse. Usage: MouseButton -Button left|right|middle -Down true|false"; }
        void RegisterArguments() noexcept override { m_hButton = m_Parser.addOption("Button", "left, right or middle", true, 1); m_hDown = m_Parser.addOption("Down", "true: press, false: release", true, 1); }
        std::string Query() noexcept override
        {
            if (!xgpu::virtual_input::Active()) return kNotActive();
            std::string Button, Down; bool bDown = false;
            if (!Arg(m_hButton, Button) || !Arg(m_hDown, Down) || !ToBool(Down, bDown)) return "MouseButton: -Button and -Down are required";
            int Index = -1;
            if (Button == "left") Index = static_cast<int>(xgpu::mouse::digital::BTN_LEFT);
            else if (Button == "right") Index = static_cast<int>(xgpu::mouse::digital::BTN_RIGHT);
            else if (Button == "middle") Index = static_cast<int>(xgpu::mouse::digital::BTN_MIDDLE);
            if (Index < 0) return std::format("MouseButton: '{}' is not left, right or middle", Button);
            xgpu::virtual_input::SetButton(Index, bDown);
            return std::format("MouseButton: {} {}", Button, bDown ? "down" : "up");
        }
        xcmdline::parser::handle m_hButton, m_hDown;
    };

    struct mouse_wheel_cmd : virtual_input_command
    {
        mouse_wheel_cmd(xundo::system& System, void*) noexcept : virtual_input_command(System, "MouseWheel", nullptr) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Turns the wheel of the virtual mouse. Usage: MouseWheel -Delta 1"; }
        void RegisterArguments() noexcept override { m_hDelta = m_Parser.addOption("Delta", "Turns of the wheel (positive: away from you)", true, 1); }
        std::string Query() noexcept override
        {
            if (!xgpu::virtual_input::Active()) return kNotActive();
            std::string Text; float Delta = 0;
            if (!Arg(m_hDelta, Text) || !ToFloat(Text, Delta)) return "MouseWheel: -Delta is required (a number)";
            xgpu::virtual_input::AddWheel(Delta);
            return std::format("MouseWheel: {}", Delta);
        }
        xcmdline::parser::handle m_hDelta;
    };

    struct virtual_key_cmd : virtual_input_command
    {
        virtual_key_cmd(xundo::system& System, void*) noexcept : virtual_input_command(System, "Key", nullptr) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Presses or releases a key of the virtual keyboard. Usage: Key -Key F2 -Down true|false   (the key by name, as xgpu names it without KEY_, or -Code N)"; }
        void RegisterArguments() noexcept override
        {
            m_hKey  = m_Parser.addOption("Key",  "The name of the key: A, RETURN, LCONTROL, F2, LEFT...", false, 1);
            m_hCode = m_Parser.addOption("Code", "The key as a number (the xgpu key code)", false, 1);
            m_hDown = m_Parser.addOption("Down", "true: press, false: release", true, 1);
        }
        std::string Query() noexcept override
        {
            if (!xgpu::virtual_input::Active()) return kNotActive();
            std::string Name, Code, Down; bool bDown = false;
            if (!Arg(m_hDown, Down) || !ToBool(Down, bDown)) return "Key: -Down is required (true or false)";
            int Key = 0;
            if (Arg(m_hCode, Code)) { Key = std::atoi(Code.c_str()); }
            else if (Arg(m_hKey, Name))
            {
                std::string U = Name; std::transform(U.begin(), U.end(), U.begin(), [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
                for (const auto& K : g_VirtualKeyNames) if (U == K.m_pName) { Key = static_cast<int>(K.m_Key); break; }
                if (Key == 0) return std::format("Key: '{}' is not a key name", Name);
            }
            else return "Key: -Key (a name) or -Code (a number) is required";
            xgpu::virtual_input::SetKey(Key, bDown);
            return std::format("Key: {} {}", Key, bDown ? "down" : "up");
        }
        xcmdline::parser::handle m_hKey, m_hCode, m_hDown;
    };

    struct virtual_text_cmd : virtual_input_command
    {
        virtual_text_cmd(xundo::system& System, void*) noexcept : virtual_input_command(System, "Text", nullptr) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Types text on the virtual keyboard, one character per frame. Usage: Text -Text \"Soccer\""; }
        void RegisterArguments() noexcept override { m_hText = m_Parser.addOption("Text", "What to type", true, 1); }
        std::string Query() noexcept override
        {
            if (!xgpu::virtual_input::Active()) return kNotActive();
            std::string Text;
            if (!Arg(m_hText, Text)) return "Text: -Text is required";
            xgpu::virtual_input::Type(Text);
            return std::format("Text: {} characters queued", Text.size());
        }
        xcmdline::parser::handle m_hText;
    };

    struct input_frames_cmd : virtual_input_command
    {
        input_frames_cmd(xundo::system& System, void*) noexcept : virtual_input_command(System, "InputFrames", nullptr) {}
        const char* getCommandHelp() const noexcept override { return "The number of frames the editor has read the virtual input in (it moves when a frame has seen what was sent). Usage: InputFrames"; }
        void RegisterArguments() noexcept override {}
        std::string Query() noexcept override
        {
            return std::format("InputFrames: {}", xgpu::virtual_input::State().m_Frames);
        }
    };

    struct input_state_cmd : virtual_input_command
    {
        input_state_cmd(xundo::system& System, void*) noexcept : virtual_input_command(System, "InputState", nullptr) {}
        const char* getCommandHelp() const noexcept override { return "What ImGui sees of the mouse, to check that the virtual input arrived. Usage: InputState"; }
        void RegisterArguments() noexcept override {}
        std::string Query() noexcept override
        {
            const auto& S = xgpu::virtual_input::State();
            std::string Out = std::format("InputState: virtual={} frames={} sent={:.0f},{:.0f} buttons={}{}{}", S.m_bActive ? "on" : "off", S.m_Frames, S.m_Position[0], S.m_Position[1]
                , S.m_ButtonDown[static_cast<int>(xgpu::mouse::digital::BTN_LEFT)] ? "L" : "-", S.m_ButtonDown[static_cast<int>(xgpu::mouse::digital::BTN_MIDDLE)] ? "M" : "-"
                , S.m_ButtonDown[static_cast<int>(xgpu::mouse::digital::BTN_RIGHT)] ? "R" : "-");
            if (ImGui::GetCurrentContext() == nullptr) return Out + " imgui=none (a headless editor has no UI)";
            const ImGuiIO& io = ImGui::GetIO();
            Out += std::format(" imgui={:.0f},{:.0f} down={}{}{} wantCaptureMouse={} wantTextInput={} ctrl={} shift={} alt={}", io.MousePos.x, io.MousePos.y, io.MouseDown[0] ? "L" : "-", io.MouseDown[2] ? "M" : "-", io.MouseDown[1] ? "R" : "-"
                , io.WantCaptureMouse ? 1 : 0, io.WantTextInput ? 1 : 0, io.KeyCtrl ? 1 : 0, io.KeyShift ? 1 : 0, io.KeyAlt ? 1 : 0);
            return Out;
        }
    };
}

#endif // LEVELEDITOR_COMMANDS_VIRTUALINPUT_H
