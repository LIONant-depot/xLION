#ifndef XEDITOR_MESH_BUDGET_H
#define XEDITOR_MESH_BUDGET_H
#pragma once

// Huge meshes in a 3D viewport (xlionrender::view_options::m_bBoxesOnly, m_FrameBudgetMs): the two buttons of the viewport's toolbar, and the boxes of what the render did
// not draw, as lines over the viewport.
//  - Boxes:  the Meshes are not drawn, their bounding boxes are (wire frame).
//  - Budget: while the frames take longer than the budget, only as many clusters of the Meshes are drawn as fit, the biggest on the screen first; the others show as their
//            boxes, and come back as the frames get faster. On by default, 33 ms.
// What the viewport shows only: never saved, undo does not see it. Picking and the gizmo do not depend on it (they use the bounds).
#include "dependencies/xLIONRender/src/xlionrender_view.h"
#include "dependencies/xeditor/include/xeditor/hint.h"
#include "dependencies/xmath/source/xmath.h"
#include "dependencies/imgui/imgui.h"

#include <cstdint>
#include <span>

namespace xeditor::mesh_budget
{
    struct state
    {
        bool    m_bBoxesOnly = false;
        bool    m_bBudget    = true;
        float   m_BudgetMs   = 33.0f;

        float   FrameBudgetMs() const noexcept { return m_bBudget ? m_BudgetMs : 0.0f; }
    };

    // The buttons, after what is on the toolbar already (the Level editor's style: a button in the Header color is on). nBoxes: the boxes drawn now (for the hints)
    inline void Buttons(state& S, bool bHorizontal, float ButtonHeight, int nBoxes) noexcept
    {
        const auto Toggle = [&](const char* pLong, const char* pShort, bool& bValue, float Width)
        {
            if (bHorizontal) ImGui::SameLine();
            const bool bOn = bValue;
            if (bOn) ImGui::PushStyleColor(ImGuiCol_Button, ImGui::GetStyle().Colors[ImGuiCol_Header]);
            if (ImGui::Button(bHorizontal ? pLong : pShort, bHorizontal ? ImVec2(Width, ButtonHeight) : ImVec2(32.0f, ButtonHeight))) bValue = !bValue;
            if (bOn) ImGui::PopStyleColor();
        };
        Toggle("Boxes###MeshBoxes", "B###MeshBoxes", S.m_bBoxesOnly, 48.0f);
        if (ImGui::IsItemHovered()) xeditor::hint::Text("Don't render meshes, show bounding boxes only (%s)\nBoxes drawn: %d", S.m_bBoxesOnly ? "on" : "off", nBoxes);
        Toggle("Budget###MeshBudget", "A###MeshBudget", S.m_bBudget, 52.0f);
        if (ImGui::IsItemHovered())
            xeditor::hint::Text("Adaptive mesh drawing (%s): while a frame takes longer than %.0f ms, only as many mesh clusters are drawn as fit, the biggest on the screen first; the others show as their bounding boxes and come back as the frames get faster.\nBoxes drawn: %d"
                               , S.m_bBudget ? "on" : "off", S.m_BudgetMs, nBoxes);
        if (bHorizontal) ImGui::SameLine();
        ImGui::SetNextItemWidth(bHorizontal ? 52.0f : 32.0f);
        ImGui::BeginDisabled(!S.m_bBudget);
        ImGui::DragFloat("##MeshBudgetMs", &S.m_BudgetMs, 0.5f, 8.0f, 200.0f, "%.0f ms", ImGuiSliderFlags_AlwaysClamp);
        ImGui::EndDisabled();
        if (ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled)) xeditor::hint::Text("The frame budget of the adaptive mesh drawing, in ms (33: 30 frames a second). Drag to change it.");
    }

    // The boxes as lines over the viewport (Min, Size: its rectangle in screen pixels). W2C: the camera's world to clip (the engine's, Y down). Each edge is clipped at the
    // near plane. The boxes of the entity Selected (raw value) are in the selection's color.
    inline void DrawBoxes(ImDrawList& DL, const xmath::fmat4& W2C, const ImVec2& Min, const ImVec2& Size, std::span<const xlionrender::wire_box> Boxes, std::uint64_t Selected = ~0ull) noexcept
    {
        if (Boxes.empty()) return;
        constexpr float      kNearW = 1.0e-3f;
        static constexpr int Edges[12][2] = { {0,1},{2,3},{4,5},{6,7}, {0,2},{1,3},{4,6},{5,7}, {0,4},{1,5},{2,6},{3,7} };
        const auto Screen = [&](const xmath::fvec4& C) { return ImVec2(Min.x + (C.m_X / C.m_W * 0.5f + 0.5f) * Size.x, Min.y + (C.m_Y / C.m_W * 0.5f + 0.5f) * Size.y); };

        DL.PushClipRect(Min, ImVec2(Min.x + Size.x, Min.y + Size.y), true);
        for (const auto& B : Boxes)
        {
            xmath::fvec4 C[8];
            for (int i = 0; i < 8; ++i)
            {
                const float L[3] = { (i & 1) ? 0.5f : -0.5f, (i & 2) ? 0.5f : -0.5f, (i & 4) ? 0.5f : -0.5f };
                float P[3];
                for (int r = 0; r < 3; ++r) P[r] = B.m_Rows[r][0] * L[0] + B.m_Rows[r][1] * L[1] + B.m_Rows[r][2] * L[2] + B.m_Rows[r][3];
                C[i] = W2C * xmath::fvec4{ P[0], P[1], P[2], 1.0f };
            }
            const ImU32 Color = B.m_Entity == Selected ? IM_COL32(255, 170, 40, 235) : IM_COL32(120, 200, 255, 170);
            for (const auto& E : Edges)
            {
                xmath::fvec4 A = C[E[0]], Z = C[E[1]];
                if (A.m_W < kNearW && Z.m_W < kNearW) continue;
                if      (A.m_W < kNearW) A = Z + (A - Z) * ((Z.m_W - kNearW) / (Z.m_W - A.m_W));
                else if (Z.m_W < kNearW) Z = A + (Z - A) * ((A.m_W - kNearW) / (A.m_W - Z.m_W));
                DL.AddLine(Screen(A), Screen(Z), Color, 1.0f);
            }
        }
        DL.PopClipRect();
    }
}

#endif // XEDITOR_MESH_BUDGET_H