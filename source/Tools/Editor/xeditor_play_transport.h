#ifndef XEDITOR_PLAY_TRANSPORT_H
#define XEDITOR_PLAY_TRANSPORT_H
#pragma once

// The play controls every editor shows the same way (the Level editor's, moved here so the other editors speak the same language):
// the speed slider (an integer slider over fixed stops, a mark under each stop, right-click for 1x) and the Play/Stop, Step/Pause,
// Resume buttons. Unity-style, worked out to keep the mouse from ever landing on a moved button: two fixed slots centred as a PAIR -
// slot 1 is Play/Stop, slot 2 is Step while Stopped/Paused or Pause while Playing (same place, only the icon/action changes). A third
// slot - Pause again, pressed, to Resume - appears only while Paused, to the right of the pair. Glyphs are Segoe MDL2 (U+E768 play,
// E769 pause, E71A stop, E893 step), merged into font 4.
// What the buttons do is the editor's: it passes the state and the actions. Users: xlevel_panel_play_transport.h, the Ragdoll editor.
#include "dependencies/xeditor/include/xeditor/hint.h"
#include "dependencies/imgui/imgui.h"
#include <algorithm>
#include <format>
#include <functional>
#include <span>
#include <string>

namespace xeditor::play_transport
{
    enum class state { Stopped, Playing, Paused };

    inline constexpr const char* kPlayIcon  = "\xEE\x9D\xA8";
    inline constexpr const char* kPauseIcon = "\xEE\x9D\xA9";
    inline constexpr const char* kStopIcon  = "\xEE\x9C\x9A";
    inline constexpr const char* kStepIcon  = "\xEE\xA2\x93";
    inline constexpr float       kSpeedWidth = 120.0f;

    struct layout
    {
        ImVec2 m_ButtonSize  = ImVec2(30.0f, 0.0f);
        bool   m_bHorizontal = true;    // false: stacked top-to-bottom (toolbar docked left/right), no centring
        bool   m_bTooltips   = true;
    };

    struct actions
    {
        std::function<void()> m_Play, m_Stop, m_Pause, m_Resume, m_Step;
        bool                  m_bBusy     = false;      // building or compiling: Play and Step disabled
        std::string           m_WhyNotPlay;             // not empty: cannot play (shown on hover)
        std::string           m_PlayKeys, m_StopKeys;   // the shortcut text of Play/Stop, if any
        const char*           m_pPlayHint = "Start playback";
        const char*           m_pStopHint = "Stop playback";
        const char*           m_pStepHint = "Run one frame";
    };

    // One button of the transport (the icon font, pressed look)
    inline bool Slot(const char* Icon, const layout& L, bool bDisabled, bool bPressed) noexcept
    {
        ImGui::PushFont(xgpu::tools::imgui::getFont(4));
        if (bPressed) ImGui::PushStyleColor(ImGuiCol_Button, ImGui::GetStyle().Colors[ImGuiCol_Header]);
        ImGui::BeginDisabled(bDisabled);
        const bool b = ImGui::Button(Icon, L.m_ButtonSize);
        ImGui::EndDisabled();
        if (bPressed) ImGui::PopStyleColor();
        ImGui::PopFont();
        return b;
    }

    // Where the pair starts when centred in the window
    inline float PairX(const layout& L) noexcept { return (ImGui::GetWindowWidth() - (L.m_ButtonSize.x * 2.0f + ImGui::GetStyle().ItemSpacing.x)) * 0.5f; }

    // The speed: an integer slider over the stops, so the grab can only sit on a stop and the number is always that stop; right-click: 1x
    inline void Speed(float& Scale, std::span<const float> Stops, const layout& L, const char* pWhat = "the game") noexcept
    {
        const int N = static_cast<int>(Stops.size());
        if (N < 2) return;
        ImGui::SetNextItemWidth(kSpeedWidth);
        int Stop = 0;
        for (int i = 0; i < N; ++i) if (Stops[i] == Scale) Stop = i;
        if (ImGui::SliderInt("##TimeScale", &Stop, 0, N - 1, std::format("{}x", Stops[Stop]).c_str())) Scale = Stops[Stop];
        if (ImGui::IsItemClicked(ImGuiMouseButton_Right)) Scale = 1.0f;
        if (L.m_bTooltips && ImGui::IsItemHovered())
        {
            std::string List; for (float S : Stops) List += std::format("{} ", S);
            xeditor::hint::Text("Speed of %s: %gx  (%sright-click for 1x)", pWhat, Scale, List.c_str());
        }
        // a small mark for every stop, under the slider
        const ImVec2 Min = ImGui::GetItemRectMin(), Max = ImGui::GetItemRectMax();
        const float  Pad  = ImGui::GetStyle().FramePadding.x;
        const float  Grab = std::max((Max.x - Min.x - Pad * 2.0f) / N, ImGui::GetStyle().GrabMinSize);      // ImGui's own grab size for an integer slider
        for (int i = 0; i < N; ++i)
        {
            const float X = Min.x + Pad + Grab * 0.5f + (Max.x - Min.x - Pad * 2.0f - Grab) * (static_cast<float>(i) / (N - 1));
            ImGui::GetWindowDrawList()->AddLine(ImVec2(X, Max.y - 3.0f), ImVec2(X, Max.y), IM_COL32(200, 200, 200, 160));
        }
    }

    // The speed placed left of a centred pair (horizontal layout)
    inline void SpeedLeftOfPair(float& Scale, std::span<const float> Stops, const layout& L, const char* pWhat = "the game") noexcept
    {
        ImGui::SameLine(std::max(0.0f, PairX(L) - kSpeedWidth - ImGui::GetStyle().ItemSpacing.x * 2.0f));
        Speed(Scale, Stops, L, pWhat);
    }

    // Play/Stop, Step/Pause, Resume. A horizontal layout centres the pair in the window (call it on the row it goes on).
    inline void Buttons(state S, const actions& A, const layout& L) noexcept
    {
        // Captured once, before any button: clicking slot 2's Pause must not make slot 3 appear this same frame.
        const bool bStopped = S == state::Stopped, bPlaying = S == state::Playing, bPaused = S == state::Paused;
        auto Tip = [&](const char* Title, const char* Hint, const std::string& Keys) noexcept
        {
            if (L.m_bTooltips && ImGui::IsItemHovered()) xeditor::hint::Draw({ Title, Hint, Keys });
        };
        auto Next = [&]() noexcept { if (L.m_bHorizontal) ImGui::SameLine(); };
        auto Call = [](const std::function<void()>& F) { if (F) F(); };

        if (L.m_bHorizontal) ImGui::SameLine(PairX(L));
        const bool bBlocked = bStopped && !A.m_WhyNotPlay.empty();
        if (Slot(bStopped ? kPlayIcon : kStopIcon, L, A.m_bBusy || bBlocked, false)) Call(bStopped ? A.m_Play : A.m_Stop);
        if (bBlocked) { if (L.m_bTooltips && ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled)) xeditor::hint::Text("Cannot play: %s", A.m_WhyNotPlay.c_str()); }
        else if (bStopped) Tip("Play", A.m_pPlayHint, A.m_PlayKeys);
        else               Tip("Stop", A.m_pStopHint, A.m_StopKeys);

        Next();
        if (bPlaying) { if (Slot(kPauseIcon, L, false, false)) Call(A.m_Pause); Tip("Pause", "Pause playback", {}); }
        else          { if (Slot(kStepIcon, L, A.m_bBusy || bBlocked, false)) Call(A.m_Step); Tip("Step", A.m_pStepHint, {}); }

        if (bPaused) { Next(); if (Slot(kPauseIcon, L, false, true)) Call(A.m_Resume); Tip("Resume", "Resume playback", {}); }
    }
}

#endif
