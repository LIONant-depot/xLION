#ifndef LEVELEDITOR_FINGER_H
#define LEVELEDITOR_FINGER_H
#pragma once

// The AI's finger (Tomas 2026-11-09: "a virtual mouse where only the AI can use... to point at things for me... your virtual finger";
// "you can hide or show your finger any time... type a message in your finger... a collaborative tool"). A pointer drawn over everything
// that the assistant moves with the Finger command: it never clicks, takes no input and is not the virtual mouse (that one drives the
// UI). It glides to what it points at - a point of the main window or a panel by name (outlined) - and can carry a message bubble.
//      Finger -X 640 -Y 360 -Message "this button picks the file"      a point of the main window (its pixels)
//      Finger -Window "Material Stack" -Message "..."                   a panel by the start of its name: outlined, the finger at its top
//      Finger -Show false | true          hide / show again          Finger -Seconds 8    hide after 8 s (0: stays)
//      Finger                              where it is and what it says - "closed by the person" once they pressed the bubble's Got it
#include "imgui.h"
#include "imgui_internal.h"
#include <algorithm>
#include <cctype>
#include <cmath>
#include <format>
#include <string>

namespace level_editor::finger
{
    struct state
    {
        bool        m_bVisible  = false;
        ImVec2      m_Pos       = {};         // where it is drawn (main window pixels), gliding to m_Goal
        ImVec2      m_Goal      = {};
        bool        m_bPlaced   = false;      // (the first point: no glide from the corner)
        std::string m_Message;
        std::string m_Window;                 // a panel it points at (outlined while it exists)
        double      m_HideAt    = 0;          // ImGui time it hides at (0: stays)
        bool        m_bSeen     = false;      // the person pressed "Got it" on this message (Tomas: "have the user close it")
    };
    inline state& State() noexcept { static state s_State; return s_State; }

    // A visible window whose name starts with Name (case insensitive): ImGui names carry ids after "##" or "###"
    inline ImGuiWindow* FindWindow(const std::string& Name) noexcept
    {
        auto* pCtx = ImGui::GetCurrentContext();
        if (!pCtx || Name.empty()) return nullptr;
        const auto Low = [](std::string S) { for (auto& c : S) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c))); return S; };
        const std::string Want = Low(Name);
        for (auto* pW : pCtx->Windows)
            if (pW && pW->WasActive && !pW->Hidden && Low(pW->Name).starts_with(Want)) return pW;
        return nullptr;
    }

    // Each frame, over everything (after the editors and the drawer)
    inline void Draw() noexcept
    {
        auto& S = State();
        if (!S.m_bVisible) return;
        if (S.m_HideAt > 0 && ImGui::GetTime() >= S.m_HideAt) { S.m_bVisible = false; return; }
        const ImVec2 Origin = ImGui::GetMainViewport()->Pos;
        auto* D = ImGui::GetForegroundDrawList(ImGui::GetMainViewport());
        const ImU32 Ink  = IM_COL32(255, 140, 40, 255), Glow = IM_COL32(255, 140, 40, 70), Paper = IM_COL32(40, 30, 22, 235), Text = IM_COL32(255, 236, 214, 255);

        // a panel: outlined, the finger at the middle of its top
        if (!S.m_Window.empty())
            if (auto* pW = FindWindow(S.m_Window))
            {
                D->AddRect(pW->Pos, { pW->Pos.x + pW->Size.x, pW->Pos.y + pW->Size.y }, Ink, 6.0f, 0, 3.0f);
                S.m_Goal = { pW->Pos.x + pW->Size.x * 0.5f - Origin.x, pW->Pos.y + 28.0f - Origin.y };
            }

        // glide (about a quarter of a second), a little pulse so the eye finds it
        const float dt = std::min(ImGui::GetIO().DeltaTime, 0.1f), k = 1.0f - std::exp(-dt * 14.0f);
        if (!S.m_bPlaced) { S.m_Pos = S.m_Goal; S.m_bPlaced = true; }
        S.m_Pos = { S.m_Pos.x + (S.m_Goal.x - S.m_Pos.x) * k, S.m_Pos.y + (S.m_Goal.y - S.m_Pos.y) * k };
        const ImVec2 P{ Origin.x + S.m_Pos.x, Origin.y + S.m_Pos.y };
        const float Pulse = 14.0f + 5.0f * std::sin(static_cast<float>(ImGui::GetTime()) * 5.0f);
        D->AddCircleFilled(P, Pulse, Glow);
        D->AddCircle(P, Pulse, Ink, 0, 2.0f);

        // the finger: an arrow whose tip is the point, coming from the lower right
        const ImVec2 A{ P.x, P.y }, B{ P.x + 9.0f, P.y + 26.0f }, C{ P.x + 16.0f, P.y + 16.0f }, Dd{ P.x + 26.0f, P.y + 9.0f };
        D->AddQuadFilled(A, B, C, Dd, Ink);
        D->AddLine(C, { C.x + 14.0f, C.y + 14.0f }, Ink, 5.0f);
        D->AddQuad(A, B, C, Dd, IM_COL32(20, 12, 6, 255), 1.5f);

        // the message: a bubble at the lower right of the finger (kept on screen), a window of its own so its "Got it" can be pressed:
        // the person closes it - then the Finger query says it was seen
        if (!S.m_Message.empty())
        {
            const float Wrap = 320.0f;
            const ImVec2 Size = ImGui::CalcTextSize(S.m_Message.c_str(), nullptr, false, Wrap);
            const ImVec2 Vp = ImGui::GetMainViewport()->Size;
            ImVec2 T0{ P.x + 30.0f, P.y + 26.0f };
            T0.x = std::min(T0.x, Origin.x + Vp.x - Size.x - 40.0f);
            T0.y = std::min(T0.y, Origin.y + Vp.y - Size.y - 70.0f);
            ImGui::SetNextWindowPos(T0);
            ImGui::PushStyleColor(ImGuiCol_WindowBg, Paper);
            ImGui::PushStyleColor(ImGuiCol_Border, Ink);
            ImGui::PushStyleColor(ImGuiCol_Text, Text);
            ImGui::PushStyleColor(ImGuiCol_Button, IM_COL32(255, 140, 40, 90));
            ImGui::PushStyleColor(ImGuiCol_ButtonHovered, IM_COL32(255, 140, 40, 170));
            ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding, 8.0f);
            ImGui::PushStyleVar(ImGuiStyleVar_WindowBorderSize, 2.0f);
            ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, { 10.0f, 7.0f });
            constexpr ImGuiWindowFlags Flags = ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_AlwaysAutoResize | ImGuiWindowFlags_NoSavedSettings
                                             | ImGuiWindowFlags_NoFocusOnAppearing | ImGuiWindowFlags_NoNav | ImGuiWindowFlags_NoDocking | ImGuiWindowFlags_NoMove;
            if (ImGui::Begin("##AI finger", nullptr, Flags))
            {
                ImGui::BringWindowToDisplayFront(ImGui::GetCurrentWindow());
                ImGui::PushTextWrapPos(ImGui::GetCursorPosX() + Wrap);
                ImGui::TextUnformatted(S.m_Message.c_str());
                ImGui::PopTextWrapPos();
                if (ImGui::SmallButton("Got it")) { S.m_bSeen = true; S.m_bVisible = false; }
            }
            ImGui::End();
            ImGui::PopStyleVar(3);
            ImGui::PopStyleColor(5);
        }
    }
}

namespace level_editor::commands
{
    struct finger_cmd : xundo::query_command_base
    {
        finger_cmd(xundo::system& System, void*) noexcept : query_command_base(System, "Finger", nullptr) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override
        {
            return "The AI's finger: a pointer drawn over everything that only these commands move - it never clicks and is not the virtual mouse. "
                   "Usage: Finger [-X px -Y px | -Window \"panel name\"] [-Message text] [-Show true|false] [-Seconds n (0: stays)]. Without arguments: where it is.";
        }
        void RegisterArguments() noexcept override
        {
            m_hX       = m_Parser.addOption("X",       "Pixels from the left of the main window", false, 1);
            m_hY       = m_Parser.addOption("Y",       "Pixels from the top of the main window", false, 1);
            m_hWindow  = m_Parser.addOption("Window",  "A panel by the start of its name: outlined, the finger at its top", false, 1);
            m_hMessage = m_Parser.addOption("Message", "What the bubble says (\"\": none)", false, 1);
            m_hShow    = m_Parser.addOption("Show",    "false: hide it; true: show it again", false, 1);
            m_hSeconds = m_Parser.addOption("Seconds", "Hide it after that many seconds (0: it stays)", false, 1);
        }
        bool Arg(xcmdline::parser::handle h, std::string& Out) const noexcept
        {
            auto V = m_Parser.getOptionArgAs<std::string>(h, 0);
            if (std::holds_alternative<xerr>(V)) return false;
            Out = std::get<std::string>(V);
            return true;
        }
        std::string Query() noexcept override
        {
            auto& S = finger::State();
            std::string X, Y, Window, Message, Show, Seconds;
            const bool bX = Arg(m_hX, X), bY = Arg(m_hY, Y), bWindow = Arg(m_hWindow, Window), bMessage = Arg(m_hMessage, Message), bShow = Arg(m_hShow, Show), bSeconds = Arg(m_hSeconds, Seconds);
            if (bX != bY) return "Finger: -X and -Y go together";
            if (bX)
            {
                char* pEnd = nullptr;
                const float Fx = std::strtof(X.c_str(), &pEnd); if (*pEnd) return std::format("Finger: -X '{}' is not a number", X);
                const float Fy = std::strtof(Y.c_str(), &pEnd); if (*pEnd) return std::format("Finger: -Y '{}' is not a number", Y);
                S.m_Goal = { Fx, Fy }; S.m_Window.clear(); S.m_bVisible = true;
            }
            if (bWindow)
            {
                if (!finger::FindWindow(Window)) return std::format("Finger: no open panel named '{}'", Window);
                S.m_Window = Window; S.m_bVisible = true;
            }
            if (bMessage) { S.m_Message = Message; S.m_bVisible = true; S.m_bSeen = false; }
            if (bShow) S.m_bVisible = Show == "true" || Show == "1" || Show == "on";
            if (bSeconds) { const double Sec = std::atof(Seconds.c_str()); S.m_HideAt = Sec > 0 ? ImGui::GetTime() + Sec : 0.0; }
            else if (bX || bWindow || bMessage) S.m_HideAt = 0;
            return std::format("Finger: {} at {:.0f},{:.0f}{}{}", S.m_bSeen ? "closed by the person (Got it)" : S.m_bVisible ? "shown" : "hidden", S.m_Goal.x, S.m_Goal.y,
                               S.m_Window.empty() ? "" : " (panel '" + S.m_Window + "')", S.m_Message.empty() ? "" : " saying \"" + S.m_Message + "\"");
        }
        xcmdline::parser::handle m_hX, m_hY, m_hWindow, m_hMessage, m_hShow, m_hSeconds;
    };
}

#endif
