#ifndef XEDITOR_TRANSFORM_GIZMO_H
#define XEDITOR_TRANSFORM_GIZMO_H
#pragma once

// The Move / Rotate / Scale gizmo of a resource editor's 3D preview (ImGuizmo, as the Level editor's): it edits the import transform of the
// descriptor (its pre-transform: Scale, Rotation in degrees, Translation), live, and a drag is one undo entry (SnapshotEdit, the command an
// inspector edit of several properties is). The Geom Static, Geom Skin and Skeleton previews use it; the Level editor has its own (entities).
//  - state: the tool (Q none, W move, E rotate, R scale) and Local. Buttons(): the tools on the preview's toolbar. actions: their keys.
//  - Run(): the gizmo, before the preview's InvisibleButton. While it is hovered or dragged the preview submits a Dummy in its place (the
//    Level editor's keyboard fix: the keys and the camera still work while it is hovered; only a drag keeps them out, Dragging()).
//  - The gizmo draws on top of what the preview draws after it (its own draw list channel: layer).
//  - PendingTransform(): the compiled mesh moved to the pre-transform the descriptor has now, so an edit shows before it is compiled.
#include "source/Tools/Editor/xeditor_descriptor_editor.h"
#include "dependencies/xeditor/include/xeditor/hint.h"
#include "dependencies/ImGuizmo/src/ImGuizmo.h"
#include "dependencies/imgui/imgui.h"
#include "dependencies/imgui/imgui_internal.h"

#include <cmath>
#include <format>
#include <string>

namespace xeditor::transform_gizmo
{
    // The pre-transform the compilers apply: vertices * Scale, rotated (degrees: X pitch, Y yaw, Z roll), + Translation
    struct pre
    {
        xmath::fvec3 m_Scale       = xmath::fvec3::fromOne();
        xmath::fvec3 m_RotationDeg = xmath::fvec3::fromZero();
        xmath::fvec3 m_Translation = xmath::fvec3::fromZero();

        bool operator==(const pre& B) const noexcept { return m_Scale == B.m_Scale && m_RotationDeg == B.m_RotationDeg && m_Translation == B.m_Translation; }
    };

    // Where a descriptor keeps it, and its Scale lock (editing one axis scales all three)
    struct target
    {
        xmath::fvec3*   m_pScale        = nullptr;
        xmath::fvec3*   m_pRotationDeg  = nullptr;
        xmath::fvec3*   m_pTranslation  = nullptr;
        const bool*     m_pLockScale    = nullptr;

        bool isValid() const noexcept { return m_pScale && m_pRotationDeg && m_pTranslation; }
        pre  Read()    const noexcept { return isValid() ? pre{ *m_pScale, *m_pRotationDeg, *m_pTranslation } : pre{}; }
    };

    template<typename T>
    pre PreOf(const T& PreTransform) noexcept { return { PreTransform.m_Scale, PreTransform.m_Rotation, PreTransform.m_Translation }; }

    template<typename T>
    target TargetOf(T& PreTransform) noexcept { return { &PreTransform.m_Scale, &PreTransform.m_Rotation, &PreTransform.m_Translation, &PreTransform.m_EditorLockScale }; }

    inline xmath::fmat4 Matrix(const pre& P) noexcept
    {
        xmath::radian3 Rot;
        Rot.m_Roll  = xmath::radian{ xmath::DegToRad(P.m_RotationDeg.m_Z) };
        Rot.m_Pitch = xmath::radian{ xmath::DegToRad(P.m_RotationDeg.m_X) };
        Rot.m_Yaw   = xmath::radian{ xmath::DegToRad(P.m_RotationDeg.m_Y) };
        return xmath::fmat4(P.m_Scale, xmath::fquat(Rot), P.m_Translation);
    }

    // A compiled mesh (compiled at Compiled) moved to the pre-transform Now: Now * Compiled^-1. Exact (the AutoUnits factor, uniform, cancels).
    // Identity when nothing changed, or when the compiled one cannot be undone (a zero scale).
    inline xmath::fmat4 PendingTransform(const pre& Compiled, const pre& Now) noexcept
    {
        if (Compiled == Now) return xmath::fmat4::fromIdentity();
        const auto& S = Compiled.m_Scale;
        if (std::abs(S.m_X) < 1.0e-12f || std::abs(S.m_Y) < 1.0e-12f || std::abs(S.m_Z) < 1.0e-12f) return xmath::fmat4::fromIdentity();
        return Matrix(Now) * Matrix(Compiled).Inverse();
    }

    //---------------------------------------------------------------------------------------------------------------------------------------------
    // The state of one preview's gizmo
    //---------------------------------------------------------------------------------------------------------------------------------------------
    enum tool : int { TOOL_NONE = 0, TOOL_MOVE = 1, TOOL_ROTATE = 2, TOOL_SCALE = 3 };

    struct state
    {
        int                 m_Tool          = TOOL_NONE;    // as the Level editor: Q (no gizmo) until W, E or R
        bool                m_bLocal        = true;         // Rotate along the pre-transform's own axes, or the world's (Scale is always local)
        bool                m_bWasUsing     = false;
        std::string         m_Before;                       // the descriptor when the drag started
        ImDrawListSplitter  m_Splitter;                     // layer
    };

    // Its keys, live while a window of the editor has the focus (an editor's RegisterActions: Ctx.Scope(Actions, "Preview")). Not while the
    // right mouse is held: W A S D Q E fly the camera then.
    struct actions
    {
        state* m_pS = nullptr;
        actions() noexcept = default;
        explicit actions(state& S) noexcept : m_pS(&S) {}

        void Set(int Tool) noexcept { if (m_pS && !ImGui::IsMouseDown(ImGuiMouseButton_Right)) m_pS->m_Tool = Tool; }
        void ToolSelect() noexcept { Set(TOOL_NONE); }
        void ToolMove()   noexcept { Set(TOOL_MOVE); }
        void ToolRotate() noexcept { Set(TOOL_ROTATE); }
        void ToolScale()  noexcept { Set(TOOL_SCALE); }

        XPROPERTY_DEF
        ( "TransformGizmo", actions
        , obj_scope<"Preview"
            , obj_action<"ToolSelect", &actions::ToolSelect, member_help<"No gizmo (the preview's camera only)">,             ximgui::actions::member_keys<"Q"> >
            , obj_action<"ToolMove",   &actions::ToolMove,   member_help<"Move gizmo: the import Translation">,              ximgui::actions::member_keys<"W"> >
            , obj_action<"ToolRotate", &actions::ToolRotate, member_help<"Rotate gizmo: the import Rotation">,               ximgui::actions::member_keys<"E"> >
            , obj_action<"ToolScale",  &actions::ToolScale,  member_help<"Scale gizmo: the import Scale (all three with the Scale lock)">, ximgui::actions::member_keys<"R"> >
            >
        )
    };

    // The tools on a viewport toolbar (xeditor::camera_toolbar's Extra: its SameLine first when horizontal; a button in the Header color is on)
    inline void Buttons(state& S, bool bHorizontal, float ButtonHeight) noexcept
    {
        if (bHorizontal) { ImGui::SameLine(); ImGui::TextDisabled("|"); }
        else ImGui::Separator();
        auto Tool = [&](const char* pLabel, int Tool, const char* pHint)
        {
            if (bHorizontal) ImGui::SameLine();
            const bool bOn = S.m_Tool == Tool;
            if (bOn) ImGui::PushStyleColor(ImGuiCol_Button, ImGui::GetStyle().Colors[ImGuiCol_Header]);
            if (ImGui::Button(pLabel, ImVec2(32.0f, ButtonHeight))) S.m_Tool = Tool;
            if (bOn) ImGui::PopStyleColor();
            if (ImGui::IsItemHovered()) xeditor::hint::Text("%s", pHint);
        };
        Tool("Q###GizmoNone",   TOOL_NONE,   "No gizmo (key Q)");
        Tool("W###GizmoMove",   TOOL_MOVE,   "Move (key W): drags the import Translation of the descriptor. Ctrl: steps of 0.1 m");
        Tool("E###GizmoRotate", TOOL_ROTATE, "Rotate (key E): drags the import Rotation of the descriptor. Ctrl: steps of 15 degrees");
        Tool("R###GizmoScale",  TOOL_SCALE,  "Scale (key R): drags the import Scale of the descriptor (all three axes when its Scale is locked). Ctrl: steps of 0.1");

        if (bHorizontal) ImGui::SameLine();
        const bool bOn = S.m_bLocal;
        if (bOn) ImGui::PushStyleColor(ImGuiCol_Button, ImGui::GetStyle().Colors[ImGuiCol_Header]);
        if (ImGui::Button(bHorizontal ? "Local###GizmoLocal" : "L###GizmoLocal", bHorizontal ? ImVec2(52.0f, ButtonHeight) : ImVec2(32.0f, ButtonHeight))) S.m_bLocal = !S.m_bLocal;
        if (bOn) ImGui::PopStyleColor();
        if (ImGui::IsItemHovered()) xeditor::hint::Text("Gizmo axes (%s): the pre-transform's own, or the world's. Scale is always along its own.", bOn ? "local" : "world");
    }

    // A drag of a gizmo is in progress (the camera and the keys stay out of it)
    inline bool Dragging() noexcept { return ImGuizmo::IsUsingAny(); }

    // What a preview draws after the gizmo goes under it: the gizmo is drawn in channel 1 of the window's draw list, the rest in channel 0.
    // Split at the start of the preview's body; merged when this goes out of scope (every return of the body).
    struct layer
    {
        state&      m_S;
        ImDrawList& m_DL;
        layer(state& S, ImDrawList& DL) noexcept : m_S(S), m_DL(DL) { m_S.m_Splitter.Split(&m_DL, 2); m_S.m_Splitter.SetCurrentChannel(&m_DL, 0); }
        ~layer() noexcept { m_S.m_Splitter.Merge(&m_DL); }
    };

    //---------------------------------------------------------------------------------------------------------------------------------------------
    // The gizmo, over the view's rectangle Min, Size, with the camera View (an xgpu::tools::view: last frame's, which the preview updates after).
    // True when it is hovered or dragged: the preview then submits ImGui::Dummy(Size) instead of its InvisibleButton, which would claim the hover
    // ImGuizmo needs to activate. The edit is written into the descriptor as it is dragged, and one SnapshotEdit is run on the release.
    // Display: where the view draws the asset's space (the Skeleton view's "Resize to 1m"), identity when it draws it as is.
    //---------------------------------------------------------------------------------------------------------------------------------------------
    template<typename T_VIEW>
    bool Run(state& S, descriptor_editor& Editor, layer& Layer, const T_VIEW& View, const ImVec2& Min, const ImVec2& Size, const target& Target
           , const xmath::fmat4& Display = xmath::fmat4::fromIdentity()) noexcept
    {
        auto Commit = [&]
        {
            S.m_bWasUsing = false;
            if (!Editor.m_Document.isLoaded()) return;
            xproperty::settings::context Context;
            const std::string After = xproperty::ui::undo::SnapshotToString(*Editor.m_Document.m_pDescriptor->getProperties(), Editor.m_Document.m_pDescriptor.get(), Context);
            if (After == S.m_Before) return;
            const char* pLabel = S.m_Tool == TOOL_ROTATE ? "Gizmo Rotate" : S.m_Tool == TOOL_SCALE ? "Gizmo Scale" : "Gizmo Move";
            const std::string Line = std::format("SnapshotEdit -Label {} -Before {} -After {}", Quote(pLabel), Quote(S.m_Before), Quote(After));
            LogConsole(std::format("SnapshotEdit \"{}\"", pLabel), log_source::User);
            if (auto Err = Editor.m_Undo.Execute(Line); !Err.empty()) NotifyToast(std::format("edit failed: {}", Err));
        };

        if (S.m_Tool < TOOL_MOVE || S.m_Tool > TOOL_SCALE || !Target.isValid() || !Editor.m_Document.isLoaded() || Size.x <= 1.0f || Size.y <= 1.0f)
        {
            if (S.m_bWasUsing) Commit();
            return false;
        }

        Layer.m_S.m_Splitter.SetCurrentChannel(&Layer.m_DL, 1);
        ImGuizmo::BeginFrame();
        ImGuizmo::SetOrthographic(false);
        ImGuizmo::SetDrawlist();
        ImGuizmo::SetRect(Min.x, Min.y, Size.x, Size.y);

        // ImGuizmo is OpenGL-convention: undo the Vulkan Y flip of the projection (clip-space row 1), as the Level editor does
        const xmath::fmat4 W2V        = View.getW2V();
        xmath::fmat4       Projection = View.getV2C();
        Projection.m_10 = -Projection.m_10;
        Projection.m_11 = -Projection.m_11;
        Projection.m_12 = -Projection.m_12;
        Projection.m_13 = -Projection.m_13;

        const auto  Operation = S.m_Tool == TOOL_MOVE ? ImGuizmo::TRANSLATE : S.m_Tool == TOOL_ROTATE ? ImGuizmo::ROTATE : ImGuizmo::SCALE;
        const auto  Mode      = S.m_bLocal ? ImGuizmo::LOCAL : ImGuizmo::WORLD;
        const pre   Now       = Target.Read();
        xmath::fmat4 World    = Display * Matrix(Now);

        const float Step  = S.m_Tool == TOOL_ROTATE ? 15.0f : 0.1f;
        const float Snap[3] = { Step, Step, Step };
        const bool  bChanged = ImGuizmo::Manipulate(reinterpret_cast<const float*>(&W2V), reinterpret_cast<const float*>(&Projection), Operation, Mode
                                                   , reinterpret_cast<float*>(&World), nullptr, ImGui::GetIO().KeyCtrl ? Snap : nullptr);

        // The drag starts: the descriptor as it was (nothing is written to it before this)
        if (ImGuizmo::IsUsing() && !S.m_bWasUsing)
        {
            xproperty::settings::context Context;
            S.m_Before    = xproperty::ui::undo::SnapshotToString(*Editor.m_Document.m_pDescriptor->getProperties(), Editor.m_Document.m_pDescriptor.get(), Context);
            S.m_bWasUsing = true;
        }

        // Only the channel this tool edits is written (xmath's Extract*, the inverse of the matrix above), so the other two stay exact
        if (bChanged && S.m_bWasUsing)
        {
            World = Display.Inverse() * World;
            switch (S.m_Tool)
            {
            case TOOL_MOVE:
                *Target.m_pTranslation = World.ExtractPosition();
                break;
            case TOOL_ROTATE:
            {
                const xmath::radian3 E = World.ExtractRotation().ToEuler();
                *Target.m_pRotationDeg = xmath::fvec3( xmath::RadToDeg(E.m_Pitch.m_Value), xmath::RadToDeg(E.m_Yaw.m_Value), xmath::RadToDeg(E.m_Roll.m_Value) );
                break;
            }
            case TOOL_SCALE:
            {
                const xmath::fvec3 Got = World.ExtractScale();      // magnitudes: the signs (a mirror) stay the descriptor's
                const float Old[3] = { Now.m_Scale.m_X, Now.m_Scale.m_Y, Now.m_Scale.m_Z };
                float       New[3] = { std::copysign(Got.m_X, Old[0]), std::copysign(Got.m_Y, Old[1]), std::copysign(Got.m_Z, Old[2]) };
                if (Target.m_pLockScale && *Target.m_pLockScale)
                {
                    // Locked: the axis that changed the most sets the factor of all three
                    int   iAxis = -1;
                    float Most  = 0;
                    for (int i = 0; i < 3; ++i)
                    {
                        if (std::abs(Old[i]) < 1.0e-12f) continue;
                        const float D = std::abs(New[i] / Old[i] - 1.0f);
                        if (iAxis == -1 || D > Most) { iAxis = i; Most = D; }
                    }
                    if (iAxis >= 0)
                    {
                        const float F = New[iAxis] / Old[iAxis];
                        for (int i = 0; i < 3; ++i) New[i] = Old[i] * F;
                    }
                }
                *Target.m_pScale = xmath::fvec3(New[0], New[1], New[2]);
                break;
            }
            default: break;
            }
        }

        const bool bInteracting = ImGuizmo::IsOver(Operation) || ImGuizmo::IsUsing();

        // The mouse was released: one undo entry for the whole drag
        if (S.m_bWasUsing && !ImGuizmo::IsUsing()) Commit();

        Layer.m_S.m_Splitter.SetCurrentChannel(&Layer.m_DL, 0);
        return bInteracting;
    }

    XPROPERTY_REG(actions)
    XIMGUI_ACTIONS_OWNER(actions)
}

#endif // XEDITOR_TRANSFORM_GIZMO_H
