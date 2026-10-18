#ifndef XEDITOR_SCALE_REFERENCE_H
#define XEDITOR_SCALE_REFERENCE_H
#pragma once

// The human scale reference: a figure 1.8 m tall (the engine's unit is the meter) a 3D view draws beside what it shows, so its size reads at a glance.
// A camera-facing outline (it turns about the vertical to face the camera), generated here (no art), drawn with ImGui over the view: editor only, never
// saved, exported or drawn by the game. Always 1.8 m: it never takes the scale of what it stands by.
//  - The Geom Static and Geom Skin previews stand one on the ground beside the -X side of the mesh's box (Button: their toolbar's Human toggle, on by
//    default and remembered in the ImGui settings), with the mesh at the pre-transform the descriptor has now (xeditor_transform_gizmo.h's
//    PendingTransform), so a scale being edited shows against it before it is compiled.
//  - The Level viewport places, picks and moves its own (plugins/xlevel.plugin/source/Editor/xlevel_scale_reference.h).
#include "dependencies/xeditor/include/xeditor/hint.h"
#include "dependencies/xmath/source/xmath.h"
#include "dependencies/imgui/imgui.h"
#include "dependencies/imgui/imgui_internal.h"     // the settings handler of the Human toggle

#include <algorithm>
#include <array>
#include <cfloat>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

namespace xeditor::scale_reference
{
    inline constexpr float height_v = 1.8f;     // meters

    // The outline, right half from the neck down to the crotch, in heights (feet at 0, top of the head at 1); the left half mirrors it
    inline constexpr std::array<std::array<float, 2>, 15> half_v
    {{ { 0.030f, 0.865f }, { 0.060f, 0.845f }, { 0.125f, 0.820f }, { 0.145f, 0.780f }, { 0.160f, 0.620f }, { 0.165f, 0.480f }
     , { 0.140f, 0.455f }, { 0.125f, 0.480f }, { 0.118f, 0.640f }, { 0.100f, 0.700f }, { 0.095f, 0.560f }, { 0.105f, 0.480f }
     , { 0.085f, 0.030f }, { 0.100f, 0.000f }, { 0.018f, 0.000f } }};
    inline constexpr float crotch_v     = 0.470f;
    inline constexpr float head_y_v     = 0.932f, head_r_v = 0.065f;
    inline constexpr float half_width_v = 0.165f * height_v;   // the widest the outline is from its middle (the hands), meters

    // The world points of the outline of a figure standing at Feet facing Eye; Right: the right of the figure, as the camera sees it
    inline void Outline(const xmath::fvec3& Feet, const xmath::fvec3& Eye, std::vector<xmath::fvec3>& Out, xmath::fvec3& Right) noexcept
    {
        xmath::fvec3 ToEye{ Eye.m_X - Feet.m_X, 0, Eye.m_Z - Feet.m_Z };
        if (ToEye.Length() < 1.0e-4f) ToEye = xmath::fvec3{ 0, 0, 1 };
        ToEye = ToEye.NormalizeCopy();
        Right = xmath::fvec3{ ToEye.m_Z, 0, -ToEye.m_X };
        const auto At = [&](float X, float Y) { return Feet + Right * (X * height_v) + xmath::fvec3{ 0, Y * height_v, 0 }; };
        Out.clear();
        for (const auto& P : half_v) Out.push_back(At(P[0], P[1]));
        Out.push_back(At(0.0f, crotch_v));
        for (auto It = half_v.rbegin(); It != half_v.rend(); ++It) Out.push_back(At(-(*It)[0], (*It)[1]));
    }

    // One figure. Project(world, screen) -> false when the point is behind the camera (the figure is then not drawn). bSelected: white lines, a stronger fill
    template<typename T_PROJECT>
    bool Draw(ImDrawList& DL, const xmath::fvec3& Feet, const xmath::fvec3& Eye, T_PROJECT&& Project, bool bSelected = false) noexcept
    {
        std::vector<xmath::fvec3> World;
        std::vector<ImVec2>       Screen;
        xmath::fvec3              Right;
        Outline(Feet, Eye, World, Right);
        for (const auto& P : World) { ImVec2 S; if (!Project(P, S)) return false; Screen.push_back(S); }

        const ImU32 Line = bSelected ? IM_COL32(255, 255, 255, 255) : IM_COL32(255, 196, 64, 255);
        const ImU32 Fill = bSelected ? IM_COL32(255, 196, 64, 110) : IM_COL32(255, 196, 64, 70);
        DL.AddConcavePolyFilled(Screen.data(), static_cast<int>(Screen.size()), Fill);
        DL.AddPolyline(Screen.data(), static_cast<int>(Screen.size()), Line, ImDrawFlags_Closed, bSelected ? 2.5f : 1.5f);

        // The head: a circle in the plane of the figure
        const xmath::fvec3 Head = Feet + xmath::fvec3{ 0, head_y_v * height_v, 0 };
        ImVec2 C, E;
        if (Project(Head, C) && Project(Head + Right * (head_r_v * height_v), E))
        {
            const float R = std::sqrt((E.x - C.x) * (E.x - C.x) + (E.y - C.y) * (E.y - C.y));
            DL.AddCircleFilled(C, R, Fill);
            DL.AddCircle(C, R, Line, 0, bSelected ? 2.5f : 1.5f);
        }
        ImVec2 Top;
        if (Project(Feet + xmath::fvec3{ 0, height_v * 1.04f, 0 }, Top))
            DL.AddText(ImVec2(Top.x - 14.0f, Top.y - ImGui::GetFontSize()), Line, "1.8 m");
        return true;
    }

    // Its screen rectangle (the outline and the head); false when behind the camera
    template<typename T_PROJECT>
    bool ScreenBounds(const xmath::fvec3& Feet, const xmath::fvec3& Eye, T_PROJECT&& Project, ImVec2& Lo, ImVec2& Hi) noexcept
    {
        std::vector<xmath::fvec3> World;
        xmath::fvec3              Right;
        Outline(Feet, Eye, World, Right);
        World.push_back(Feet + xmath::fvec3{ 0, height_v, 0 });
        Lo = ImVec2(FLT_MAX, FLT_MAX); Hi = ImVec2(-FLT_MAX, -FLT_MAX);
        for (const auto& P : World)
        {
            ImVec2 S;
            if (!Project(P, S)) return false;
            Lo = ImVec2(std::min(Lo.x, S.x), std::min(Lo.y, S.y)); Hi = ImVec2(std::max(Hi.x, S.x), std::max(Hi.y, S.y));
        }
        return true;
    }

    // World to the pixels of a view (Min, Size: its rectangle on the screen) through the camera's world to clip (the engine's, Y down; as mesh_budget::DrawBoxes)
    struct clip_projector
    {
        xmath::fmat4    m_W2C;
        ImVec2          m_Min, m_Size;

        bool operator()(const xmath::fvec3& P, ImVec2& S) const noexcept
        {
            const xmath::fvec4 C = m_W2C * xmath::fvec4{ P.m_X, P.m_Y, P.m_Z, 1.0f };
            if (C.m_W < 1.0e-3f) return false;
            S = ImVec2(m_Min.x + (C.m_X / C.m_W * 0.5f + 0.5f) * m_Size.x, m_Min.y + (C.m_Y / C.m_W * 0.5f + 0.5f) * m_Size.y);
            return true;
        }
    };

    // Where a figure stands by a box: on its ground (its bottom), beside its -X side with a hand's gap, in the middle of its depth
    inline xmath::fvec3 BesideBox(const xmath::fvec3& Min, const xmath::fvec3& Max) noexcept
    {
        return { Min.m_X - half_width_v - 0.25f, Min.m_Y, 0.5f * (Min.m_Z + Max.m_Z) };
    }

    // The box Min..Max moved by M (its 8 corners)
    inline void TransformBox(const xmath::fmat4& M, xmath::fvec3& Min, xmath::fvec3& Max) noexcept
    {
        xmath::fvec3 Lo = M * Min, Hi = Lo;
        for (int i = 1; i < 8; ++i)
        {
            const xmath::fvec3 P = M * xmath::fvec3{ (i & 1) ? Max.m_X : Min.m_X, (i & 2) ? Max.m_Y : Min.m_Y, (i & 4) ? Max.m_Z : Min.m_Z };
            Lo = Lo.Min(P); Hi = Hi.Max(P);
        }
        Min = Lo; Max = Hi;
    }

    //---------------------------------------------------------------------------------------------------------------------------------------------
    // The previews' Human toggle: one for all of them, remembered in the ImGui settings ("[ScaleReference][Preview]"). An editor opens after ImGui
    // read its settings file, so the handler (registered on first use) reads its own line from that file then.
    //---------------------------------------------------------------------------------------------------------------------------------------------
    inline bool& Shown() noexcept { static bool bShown = true; return bShown; }

    inline void ReadLine(const char* pLine) noexcept
    {
        if (std::strncmp(pLine, "Human=", 6) == 0) Shown() = std::atoi(pLine + 6) != 0;
    }

    inline void RegisterSettings() noexcept
    {
        static constexpr const char* type_v = "ScaleReference";
        if (!ImGui::GetCurrentContext() || ImGui::FindSettingsHandler(type_v)) return;
        ImGuiSettingsHandler H;
        H.TypeName   = type_v;
        H.TypeHash   = ImHashStr(type_v);
        H.ReadOpenFn = [](ImGuiContext*, ImGuiSettingsHandler*, const char*) -> void* { return &Shown(); };
        H.ReadLineFn = [](ImGuiContext*, ImGuiSettingsHandler*, void*, const char* pLine) { ReadLine(pLine); };
        H.WriteAllFn = [](ImGuiContext*, ImGuiSettingsHandler* pH, ImGuiTextBuffer* pBuf) { pBuf->appendf("[%s][Preview]\nHuman=%d\n\n", pH->TypeName, Shown() ? 1 : 0); };
        ImGui::AddSettingsHandler(&H);

        // The settings file was read already (before any editor opened): this section's line from it
        if (const char* pFile = ImGui::GetIO().IniFilename; pFile)
        {
            std::ifstream File(pFile);
            bool          bIn = false;
            for (std::string Line; std::getline(File, Line); )
            {
                if (!Line.empty() && Line.back() == '\r') Line.pop_back();
                if (!Line.empty() && Line[0] == '[') bIn = Line == "[ScaleReference][Preview]";
                else if (bIn) ReadLine(Line.c_str());
            }
        }
    }

    // The toggle, on a viewport toolbar (xeditor::camera_toolbar's Extra: its SameLine first when horizontal; a button in the Header color is on)
    inline void Button(bool bHorizontal, float ButtonHeight) noexcept
    {
        RegisterSettings();
        if (bHorizontal) ImGui::SameLine();
        bool&      bShown = Shown();
        const bool bOn    = bShown;
        if (bOn) ImGui::PushStyleColor(ImGuiCol_Button, ImGui::GetStyle().Colors[ImGuiCol_Header]);
        if (ImGui::Button(bHorizontal ? "Human###ScaleReference" : "H###ScaleReference", bHorizontal ? ImVec2(52.0f, ButtonHeight) : ImVec2(32.0f, ButtonHeight)))
        {
            bShown = !bShown;
            ImGui::MarkIniSettingsDirty();
        }
        if (bOn) ImGui::PopStyleColor();
        if (ImGui::IsItemHovered()) xeditor::hint::Text("Human scale reference (%s): a 1.8 m figure beside the mesh, to judge its size. It keeps its size when the mesh's Scale changes (the preview shows the Scale being edited before it is compiled). Every preview, remembered.", bOn ? "on" : "off");
    }

    // A preview's figure, when the toggle is on: beside the box BoxMin..BoxMax (the mesh as the preview draws it), over the view's rectangle Min, Size.
    // ViewScale: a view that draws everything scaled (the Skeleton's "Resize to 1m") draws the figure scaled with it, so it keeps its size against the box
    inline void DrawBesideBox(ImDrawList& DL, const xmath::fmat4& W2C, const xmath::fvec3& Eye, const ImVec2& Min, const ImVec2& Size, const xmath::fvec3& BoxMin, const xmath::fvec3& BoxMax, float ViewScale = 1.0f) noexcept
    {
        RegisterSettings();
        if (!Shown() || ViewScale <= 1.0e-9f) return;
        DL.PushClipRect(Min, ImVec2(Min.x + Size.x, Min.y + Size.y), true);
        const float          Inv = 1.0f / ViewScale;
        const clip_projector Project{ W2C, Min, Size };
        Draw(DL, BesideBox(BoxMin * Inv, BoxMax * Inv), Eye * Inv, [&](const xmath::fvec3& P, ImVec2& S) { return Project(P * ViewScale, S); });
        DL.PopClipRect();
    }
}

#endif // XEDITOR_SCALE_REFERENCE_H
