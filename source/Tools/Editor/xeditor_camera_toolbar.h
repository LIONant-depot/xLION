#ifndef XEDITOR_CAMERA_TOOLBAR_H
#define XEDITOR_CAMERA_TOOLBAR_H
#pragma once

// The toolbar of a 3D viewport, the same one the Level editor has (dependencies/toolbar.imgui: a bar the user drags to any edge of the viewport or leaves floating,
// remembered in the ImGui settings), with the buttons of the camera (xeditor_tools_camera.h). Today one button: the mode, Orbit or Fly (a click is F). More
// buttons go in CameraButtons.
//
// An editor holds one camera_toolbar per viewport, calls Init once (a unique id: the guid of its resource) and draws its viewport through Render:
//      m_CameraToolbar.Render(ImGui::GetContentRegionAvail(), m_Camera /* xeditor_tools::camera_state */, [this] { RenderViewportBody(); });
#include "dependencies/toolbar.imgui/ximgui_toolbar.h"
#include "dependencies/xeditor/include/xeditor/hint.h"
#include "dependencies/xeditor_tools/src/xeditor_tools_camera.h"
#include "dependencies/imgui/imgui.h"

#include <cstdint>
#include <cstdio>

namespace xeditor
{
    struct camera_toolbar
    {
        static constexpr float kHeight = 20.0f;                     // as the Level editor's

        ximgui::toolbar::toolbar_host_state m_Host{ {}, false, [](const char* pText) noexcept { xeditor::hint::Text("%s", pText); } };
        char                                m_HandlerName[64] = {};
        bool                                m_bHandler        = false;

        camera_toolbar() noexcept = default;
        camera_toolbar(const camera_toolbar&) = delete;
        camera_toolbar& operator = (const camera_toolbar&) = delete;
        ~camera_toolbar() noexcept { if (m_bHandler && ImGui::GetCurrentContext()) ImGui::RemoveSettingsHandler(m_HandlerName); }

        // Id: unique among the editors that are open (the guid of the resource); the toolbar keeps its place under that name
        void Init(std::uint64_t Id) noexcept
        {
            m_Host.m_Items.push_back({ "Camera", ximgui::toolbar::toolbar_host_edge::Top, ximgui::toolbar::axis::Horizontal
                                     , ImVec2(190.0f, kHeight), ImVec2(32.0f, 120.0f), ImVec2(24.0f, 40.0f) });
            if (!ImGui::GetCurrentContext()) return;
            std::snprintf(m_HandlerName, sizeof(m_HandlerName), "CameraToolbar%016llX", static_cast<unsigned long long>(Id));
            if (ImGui::FindSettingsHandler(m_HandlerName) == nullptr)
            {
                ximgui::toolbar::RegisterSettingsHandler(m_Host, m_HandlerName);
                m_bHandler = true;
            }
        }

        // The buttons, in the style of the Level editor's (a button of the Header color is the one that is on)
        static void CameraButtons(xeditor_tools::camera_state& Camera, ximgui::toolbar::axis Axis) noexcept
        {
            const bool  bHorizontal  = Axis == ximgui::toolbar::axis::Horizontal;
            const float ButtonHeight = bHorizontal ? kHeight - 4.0f : 28.0f;
            ImGui::PushStyleVar(ImGuiStyleVar_ItemSpacing, ImVec2(2.0f, ImGui::GetStyle().ItemSpacing.y));

            const bool bFly = Camera.m_Mode == xeditor_tools::camera_mode::FLY;
            if (bFly) ImGui::PushStyleColor(ImGuiCol_Button, ImGui::GetStyle().Colors[ImGuiCol_Header]);
            if (ImGui::Button(bHorizontal ? (bFly ? "Fly###CameraMode" : "Orbit###CameraMode") : (bFly ? "F###CameraMode" : "O###CameraMode"), bHorizontal ? ImVec2(52.0f, ButtonHeight) : ImVec2(32.0f, ButtonHeight)))
            {
                Camera.SwitchMode(ImGui::GetTime());
            }
            if (bFly) ImGui::PopStyleColor();
            const bool bHoverMode = ImGui::IsItemHovered();

            // The field of view: the lens the camera looks through (a wide one stretches what is away from the middle)
            if (bHorizontal) ImGui::SameLine();
            ImGui::SetNextItemWidth(bHorizontal ? 100.0f : 32.0f);
            if (!bHorizontal) ImGui::TextDisabled("FOV");
            ImGui::SliderFloat("##CameraFov", &Camera.m_FovDeg, 5.0f, 110.0f, "FOV %.0f");
            if (ImGui::IsItemHovered()) xeditor::hint::Text("Field of view (vertical, in degrees). Wide lenses stretch what is away from the middle of the view; 45 is calm, 60 usual, 90 a game.");

            if (bHoverMode)
                xeditor::hint::Text("Camera: %s (key F)\n%s\nClick: %s", bFly ? "Fly" : "Orbit"
                    , bFly ? "Turns where it stands; W A S D Q E fly (right mouse held); the wheel changes the speed." : "Turns around its target; the wheel changes the distance to it."
                    , bFly ? "Orbit around the subject (it is framed)" : "Fly");

            ImGui::PopStyleVar();
        }

        template<typename BODY>
        void Render(const ImVec2& Avail, xeditor_tools::camera_state& Camera, BODY&& Body) noexcept
        {
            ximgui::toolbar::RenderToolbarHost(m_Host, Avail, [&](const char*, ximgui::toolbar::axis Axis) { CameraButtons(Camera, Axis); }, std::forward<BODY>(Body));
        }
    };
}

#endif // XEDITOR_CAMERA_TOOLBAR_H
