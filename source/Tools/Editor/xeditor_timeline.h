#ifndef XEDITOR_TIMELINE_H
#define XEDITOR_TIMELINE_H
#pragma once
// xeditor::timeline - the editor's timeline (xLION_Docs editor_timeline_framework_design_2026-11-15.md, T1). A VIEW over a document: the
// document gives the rows (a row adapter), the markers and the clock, and is edited ONLY through the commands it runs (its undo, its
// console). Rows are drawn and hit-tested by row types registered by the editor that uses the timeline (an animation layer, a pose
// layer, events...); this file knows nothing about them. What it does for every row type:
//  - the ruler (labels adapt to the zoom; frames below a second), scrub anywhere in it (Shift snaps), the playback range's ends to drag,
//    markers, the playhead through the rows
//  - Ctrl+wheel zooms at the cursor, the middle button or Shift+wheel pans, the wheel scrolls the rows; F frames the selection, Home all
//  - selection: click, Shift adds, Ctrl toggles, a marquee across rows
//  - snapping: every row type's edges and keys, the playhead and the markers within 8 px, else the frame grid; the magnet button turns it
//    off and holding Ctrl while dragging overrides it; a snap line and the time / delta while dragging
//  - drags: move, trim start / end, ease in / out, slip (Alt), keys - previewed (the row type draws xeditor::timeline::Drag of its
//    segment) and committed ONCE on release as one command (one undo step); Esc cancels and nothing has changed
//  - keys: , . a frame; Alt+, Alt+. the previous / next key or edge; Del; Ctrl+D; M a marker; F; Home
#include "xeditor_timeline_core.h"
#include "imgui.h"
#include "imgui_internal.h"
#include <functional>
#include <set>
#include <unordered_map>

namespace xeditor::timeline
{
    struct row_desc
    {
        std::uint64_t m_Id = 0, m_Type = 0;
        int           m_Depth = 0;                      // children come after their parent (pre-order), one deeper
        bool          m_bHasChildren = false, m_bFolded = false, m_bMute = false, m_bSolo = false, m_bLock = false;
        std::string   m_Name;
        ImU32         m_Color = IM_COL32(86, 132, 210, 255);
    };
    struct marker { std::uint64_t m_Id = 0; tick m_Time = 0; std::string m_Name; };
    enum class row_flag : std::uint8_t { fold, mute, solo, lock };

    // The document side. Every function that changes something returns the reply of the command it ran ("" when it has none).
    struct document
    {
        virtual ~document() = default;
        virtual void        Rows(std::vector<row_desc>& Out) = 0;
        virtual void        Markers(std::vector<marker>&) {}
        virtual tick        Time() = 0;
        virtual void        SetTime(tick T) = 0;                                    // the playhead (view state: not undoable)
        virtual void        PlaybackRange(tick& A, tick& B) = 0;
        virtual std::string SetPlaybackRange(tick A, tick B) = 0;
        virtual std::string Commit(std::span<const edit> Edits) = 0;                // ONE gesture: one command, one undo step
        virtual std::string Delete(std::span<const item_ref>) { return {}; }
        virtual std::string Duplicate(std::span<const item_ref>) { return {}; }
        virtual std::string AddMarker(tick) { return {}; }
        virtual std::string SetRowFlag(std::uint64_t, row_flag, bool) { return {}; }
        virtual void        OnSelection(const std::set<item_ref>&) {}               // the editor shows the selection's properties
    };

    // What a row type gets to draw and hit-test with: its rect, the view, the selection, and the gesture being dragged (to preview it)
    struct draw_args
    {
        const view*               m_pView = nullptr;
        ImVec2                    m_Min{}, m_Max{};
        const std::set<item_ref>* m_pSelection = nullptr;
        const std::set<item_ref>* m_pDragged = nullptr;
        handle                    m_Handle = handle::none;
        tick                      m_Delta = 0;
        tick                      m_MinLength = 1;

        float X(tick T) const noexcept { return m_Min.x + static_cast<float>(m_pView->X(double(T))); }
        bool  Selected(std::uint64_t Row, std::uint64_t Item) const noexcept { return m_pSelection && m_pSelection->count({ Row, Item }); }
        bool  Dragged(std::uint64_t Row, std::uint64_t Item) const noexcept { return m_pDragged && m_Handle != handle::none && m_pDragged->count({ Row, Item }); }
        // a segment as the preview shows it
        segment Preview(std::uint64_t Row, std::uint64_t Item, const segment& S) const noexcept { return Dragged(Row, Item) ? Drag(S, m_Handle, m_Delta, m_MinLength) : S; }
        tick    Preview(std::uint64_t Row, std::uint64_t Item, tick Key) const noexcept { return Dragged(Row, Item) ? Key + m_Delta : Key; }
    };
    struct hit { handle m_Handle = handle::none; std::uint64_t m_Item = 0; };

    struct row_type
    {
        virtual ~row_type() = default;
        virtual void Items(const row_desc&, int iRow, std::vector<item_box>&) = 0;            // its segments and keys as time spans
        virtual bool Segment(const row_desc&, std::uint64_t Item, segment& Out) { (void)Item; (void)Out; return false; }
        virtual void Draw(const row_desc&, ImDrawList&, const draw_args&) = 0;
        virtual hit  HitTest(const row_desc&, const draw_args&, ImVec2 Mouse) = 0;
        virtual void Header(const row_desc&, document&) {}                                    // its own widgets after the standard ones
    };
    using registry = std::unordered_map<std::uint64_t, row_type*>;

    //--------------------------------------------------------------------------------------------
    // Drawing and hit-testing helpers the row types share
    //--------------------------------------------------------------------------------------------
    inline ImU32 Shade(ImU32 C, float K) noexcept
    {
        auto Ch = [&](int s) { return static_cast<ImU32>(std::clamp((float((C >> s) & 0xFF)) * K, 0.0f, 255.0f)) << s; };
        return Ch(IM_COL32_R_SHIFT) | Ch(IM_COL32_G_SHIFT) | Ch(IM_COL32_B_SHIFT) | (C & IM_COL32_A_MASK);
    }

    // A segment bar: body, the ease ramps (dark triangles), their handles (dots at the top corners), the name
    inline void DrawSegment(ImDrawList& D, const draw_args& A, const segment& S, ImU32 Color, bool bSelected, const char* pLabel)
    {
        const float x0 = A.X(S.m_Start), x1 = A.X(S.m_End), y0 = A.m_Min.y + 3, y1 = A.m_Max.y - 3;
        if (x1 < A.m_Min.x || x0 > A.m_Max.x) return;
        D.AddRectFilled({ x0, y0 }, { x1, y1 }, bSelected ? Shade(Color, 1.25f) : Color, 3.0f);
        const float ei = A.X(S.m_Start + S.m_EaseIn), eo = A.X(S.m_End - S.m_EaseOut);
        if (S.m_EaseIn > 0)  D.AddTriangleFilled({ x0, y0 }, { ei, y0 }, { x0, y1 }, IM_COL32(0, 0, 0, 70));
        if (S.m_EaseOut > 0) D.AddTriangleFilled({ eo, y0 }, { x1, y0 }, { x1, y1 }, IM_COL32(0, 0, 0, 70));
        D.AddRect({ x0, y0 }, { x1, y1 }, bSelected ? IM_COL32(255, 255, 255, 230) : Shade(Color, 0.6f), 3.0f, 0, bSelected ? 2.0f : 1.0f);
        D.AddCircleFilled({ ei, y0 + 1 }, 3.0f, IM_COL32(255, 255, 255, 160));
        D.AddCircleFilled({ eo, y0 + 1 }, 3.0f, IM_COL32(255, 255, 255, 160));
        if (pLabel && x1 - x0 > 20)
        {
            D.PushClipRect({ std::max(x0, A.m_Min.x) + 4, y0 }, { std::min(x1, A.m_Max.x) - 4, y1 }, true);
            D.AddText({ std::max(x0, A.m_Min.x) + 6, y0 + (y1 - y0 - ImGui::GetFontSize()) * 0.5f }, IM_COL32(255, 255, 255, 230), pLabel);
            D.PopClipRect();
        }
    }
    inline void DrawKey(ImDrawList& D, ImVec2 C, ImU32 Color, bool bSelected)
    {
        const float r = 5.5f;
        D.AddQuadFilled({ C.x, C.y - r }, { C.x + r, C.y }, { C.x, C.y + r }, { C.x - r, C.y }, bSelected ? IM_COL32(255, 210, 90, 255) : Color);
        D.AddQuad({ C.x, C.y - r }, { C.x + r, C.y }, { C.x, C.y + r }, { C.x - r, C.y }, bSelected ? IM_COL32(255, 255, 255, 255) : IM_COL32(0, 0, 0, 160), 1.2f);
    }
    // which part of a segment the mouse is on: the ease dots, the edges (6 px), the body (slip with Alt)
    inline handle HitSegment(const draw_args& A, const segment& S, ImVec2 M) noexcept
    {
        const float x0 = A.X(S.m_Start), x1 = A.X(S.m_End), y0 = A.m_Min.y + 3;
        if (M.x < x0 - 6 || M.x > x1 + 6) return handle::none;
        const float ei = A.X(S.m_Start + S.m_EaseIn), eo = A.X(S.m_End - S.m_EaseOut);
        if (M.y < y0 + 7 && std::abs(M.x - ei) < 6 && x1 - x0 > 24) return handle::ease_in;
        if (M.y < y0 + 7 && std::abs(M.x - eo) < 6 && x1 - x0 > 24) return handle::ease_out;
        if (std::abs(M.x - x0) < 6) return handle::trim_start;
        if (std::abs(M.x - x1) < 6) return handle::trim_end;
        if (M.x >= x0 && M.x <= x1) return ImGui::GetIO().KeyAlt ? handle::slip : handle::body;
        return handle::none;
    }

    //--------------------------------------------------------------------------------------------
    // The timeline's own state (one per timeline shown)
    //--------------------------------------------------------------------------------------------
    struct state
    {
        view                    m_View;
        std::set<item_ref>      m_Selection;
        bool                    m_bMagnet       = true;
        float                   m_HeaderWidth   = 200, m_RowHeight = 26, m_RulerHeight = 30, m_ScrollY = 0;
        enum class mode : std::uint8_t { none, items, marquee, scrub, range_start, range_end, pan };
        mode                    m_Mode          = mode::none;
        handle                  m_Handle        = handle::none;
        item_ref                m_Grab;
        std::set<item_ref>      m_Dragged;
        double                  m_StartTick     = 0;
        ImVec2                  m_StartMouse{};
        tick                    m_Delta         = 0;
        snap_result             m_Snap;
        tick                    m_RangeA = 0, m_RangeB = 0;     // the playback range while its end is dragged
        std::string             m_Reply;                        // the last command's reply
        bool                    m_bFramed       = false;
        // the layout of the last frame (tests and virtual input read it: where a row or the ruler is)
        ImRect                  m_Body, m_Ruler;
        std::vector<std::pair<std::uint64_t, ImRect>> m_RowRects;
    };

    namespace details
    {
        struct visible_row { row_desc m_Row; row_type* m_pType = nullptr; int m_Index = 0; };

        inline void AllItems(std::vector<visible_row>& Rows, std::vector<item_box>& Out)
        {
            Out.clear();
            for (auto& R : Rows) if (R.m_pType) R.m_pType->Items(R.m_Row, R.m_Index, Out);
        }
        inline std::string Seconds(tick T, const view& V) { return std::format("{:.3f} s ({} f)", double(T) / ticks_per_second_v, T / V.FrameTicks()); }
    }

    // Draws the timeline into the current window's remaining space (or Size) and handles its input. Returns the last command's reply.
    inline const std::string& Draw(state& S, document& Doc, const registry& Types, ImVec2 Size = { 0, 0 })
    {
        using namespace details;
        auto& IO = ImGui::GetIO();
        view& V = S.m_View;

        // rows: the folded ones' descendants hidden
        std::vector<row_desc> All; Doc.Rows(All);
        std::vector<visible_row> Rows;
        int HideBelow = -1;
        for (auto& R : All)
        {
            if (HideBelow >= 0 && R.m_Depth > HideBelow) continue;
            HideBelow = R.m_bFolded ? R.m_Depth : -1;
            const auto It = Types.find(R.m_Type);
            Rows.push_back({ R, It == Types.end() ? nullptr : It->second, int(Rows.size()) });
        }
        std::vector<item_box> Boxes; AllItems(Rows, Boxes);
        tick RangeA = 0, RangeB = 0; Doc.PlaybackRange(RangeA, RangeB);
        std::vector<marker> Markers; Doc.Markers(Markers);
        const tick Now = Doc.Time();

        // the toolbar
        ImGui::PushID(&S);
        if (ImGui::Checkbox("Snap", &S.m_bMagnet)) {}
        if (ImGui::IsItemHovered()) ImGui::SetTooltip("Snap to edges, keys, the playhead and markers (8 px), else to frames. Hold Ctrl while dragging to override.");
        ImGui::SameLine(); ImGui::SetNextItemWidth(70);
        static constexpr double Rates[] = { 24, 25, 30, 50, 60, 120 };
        if (ImGui::BeginCombo("fps", std::format("{:g}", V.m_FPS).c_str())) { for (double R : Rates) if (ImGui::Selectable(std::format("{:g}", R).c_str(), R == V.m_FPS)) V.m_FPS = R; ImGui::EndCombo(); }
        ImGui::SameLine(); const bool bFrameAll = ImGui::SmallButton("Frame all (Home)");
        ImGui::SameLine(); ImGui::TextDisabled("%s", Seconds(Now, V).c_str());
        if (!S.m_Reply.empty()) { ImGui::SameLine(); ImGui::TextDisabled("| %s", S.m_Reply.c_str()); }

        // the layout
        ImVec2 Avail = ImGui::GetContentRegionAvail();
        if (Size.x > 0) Avail.x = Size.x;
        if (Size.y > 0) Avail.y = Size.y;
        Avail.x = std::max(Avail.x, S.m_HeaderWidth + 100); Avail.y = std::max(Avail.y, S.m_RulerHeight + S.m_RowHeight);
        const ImVec2 P0 = ImGui::GetCursorScreenPos();
        const ImRect Whole(P0, { P0.x + Avail.x, P0.y + Avail.y });
        S.m_Ruler = ImRect({ P0.x + S.m_HeaderWidth, P0.y }, { Whole.Max.x, P0.y + S.m_RulerHeight });
        S.m_Body  = ImRect({ P0.x + S.m_HeaderWidth, P0.y + S.m_RulerHeight }, Whole.Max);
        V.m_Width = S.m_Body.GetWidth();
        if (!S.m_bFramed || bFrameAll) { V.Frame(RangeA, RangeB); S.m_bFramed = true; }
        const float RowsHeight = float(Rows.size()) * S.m_RowHeight;
        S.m_ScrollY = std::clamp(S.m_ScrollY, 0.0f, std::max(0.0f, RowsHeight - S.m_Body.GetHeight()));

        ImDrawList& D = *ImGui::GetWindowDrawList();
        D.AddRectFilled(Whole.Min, Whole.Max, IM_COL32(30, 31, 34, 255));
        D.AddRectFilled({ Whole.Min.x, Whole.Min.y }, { S.m_Body.Min.x, Whole.Max.y }, IM_COL32(38, 39, 43, 255));

        // the whole area takes the mouse (the header's buttons are drawn over it afterwards and win their own clicks)
        ImGui::SetCursorScreenPos(S.m_Ruler.Min);
        ImGui::InvisibleButton("##timeline", { S.m_Body.Max.x - S.m_Ruler.Min.x, S.m_Body.Max.y - S.m_Ruler.Min.y }, ImGuiButtonFlags_MouseButtonLeft | ImGuiButtonFlags_MouseButtonMiddle);
        const bool bHovered = ImGui::IsItemHovered(), bActive = ImGui::IsItemActive();
        const ImVec2 M = IO.MousePos;
        auto MouseTick = [&]() { return V.T(double(M.x - S.m_Body.Min.x)); };
        auto RowAt = [&](float y) -> int { const int i = int(std::floor((y - S.m_Body.Min.y + S.m_ScrollY) / S.m_RowHeight)); return (i >= 0 && i < int(Rows.size())) ? i : -1; };
        auto RowArgs = [&](int i) -> draw_args
        {
            draw_args A; A.m_pView = &V; A.m_pSelection = &S.m_Selection; A.m_pDragged = &S.m_Dragged; A.m_MinLength = V.FrameTicks();
            A.m_Handle = S.m_Mode == state::mode::items ? S.m_Handle : handle::none; A.m_Delta = S.m_Delta;
            const float y = S.m_Body.Min.y + float(i) * S.m_RowHeight - S.m_ScrollY;
            A.m_Min = { S.m_Body.Min.x, y }; A.m_Max = { S.m_Body.Max.x, y + S.m_RowHeight };
            return A;
        };

        // wheel: Ctrl zooms at the cursor, Shift pans, else the rows scroll
        if (bHovered && IO.MouseWheel != 0)
        {
            if (IO.KeyCtrl) V.ZoomAt(double(M.x - S.m_Body.Min.x), std::pow(1.2, double(IO.MouseWheel)));
            else if (IO.KeyShift) V.Pan(double(IO.MouseWheel) * 80.0);
            else S.m_ScrollY -= IO.MouseWheel * S.m_RowHeight * 2;
        }

        // a press starts a gesture
        if (bHovered && ImGui::IsMouseClicked(ImGuiMouseButton_Middle)) { S.m_Mode = state::mode::pan; S.m_StartMouse = M; }
        if (bHovered && ImGui::IsMouseClicked(ImGuiMouseButton_Left))
        {
            S.m_StartMouse = M; S.m_StartTick = MouseTick(); S.m_Delta = 0; S.m_Snap = {};
            if (S.m_Ruler.Contains(M))
            {
                const float xa = S.m_Body.Min.x + float(V.X(double(RangeA))), xb = S.m_Body.Min.x + float(V.X(double(RangeB)));
                S.m_RangeA = RangeA; S.m_RangeB = RangeB;
                if (M.y < S.m_Ruler.Min.y + 9 && std::abs(M.x - xa) < 7)      S.m_Mode = state::mode::range_start;
                else if (M.y < S.m_Ruler.Min.y + 9 && std::abs(M.x - xb) < 7) S.m_Mode = state::mode::range_end;
                else S.m_Mode = state::mode::scrub;
            }
            else if (const int i = RowAt(M.y); i >= 0 && Rows[i].m_pType && !Rows[i].m_Row.m_bLock)
            {
                const hit H = Rows[i].m_pType->HitTest(Rows[i].m_Row, RowArgs(i), M);
                if (H.m_Handle != handle::none)
                {
                    const item_ref Ref{ Rows[i].m_Row.m_Id, H.m_Item };
                    if (IO.KeyCtrl) { if (!S.m_Selection.erase(Ref)) S.m_Selection.insert(Ref); }
                    else if (IO.KeyShift) S.m_Selection.insert(Ref);
                    else if (!S.m_Selection.count(Ref)) { S.m_Selection.clear(); S.m_Selection.insert(Ref); }
                    Doc.OnSelection(S.m_Selection);
                    S.m_Mode = state::mode::items; S.m_Handle = H.m_Handle; S.m_Grab = Ref;
                    // edges, eases and slip act on the item grabbed; a move or a key drag on the whole selection
                    S.m_Dragged.clear();
                    if (H.m_Handle == handle::body || H.m_Handle == handle::key) S.m_Dragged = S.m_Selection; else S.m_Dragged.insert(Ref);
                    if (!S.m_Selection.count(Ref)) S.m_Mode = state::mode::none;     // a Ctrl click that deselected it: no drag
                }
                else { S.m_Mode = state::mode::marquee; if (!IO.KeyCtrl && !IO.KeyShift) { S.m_Selection.clear(); Doc.OnSelection(S.m_Selection); } }
            }
            else { S.m_Mode = state::mode::marquee; if (!IO.KeyCtrl && !IO.KeyShift) { S.m_Selection.clear(); Doc.OnSelection(S.m_Selection); } }
        }

        // snap points: every item's edges and keys (but the ones that move), the playhead, the markers
        auto SnapPoints = [&](bool bSkipDragged)
        {
            std::vector<snap_point> P;
            for (const auto& B : Boxes)
            {
                if (bSkipDragged && S.m_Dragged.count(B.m_Ref)) continue;
                P.push_back({ B.m_T0, B.m_T0 == B.m_T1 ? "key" : "edge" });
                if (B.m_T1 != B.m_T0) P.push_back({ B.m_T1, "edge" });
            }
            P.push_back({ Now, "playhead" });
            for (const auto& Mk : Markers) P.push_back({ Mk.m_Time, "marker" });
            return P;
        };
        const bool bSnapOn = S.m_bMagnet && !IO.KeyCtrl;

        // the gesture while held
        if (bActive || S.m_Mode != state::mode::none)
        {
            const double Raw = MouseTick() - S.m_StartTick;
            switch (S.m_Mode)
            {
            case state::mode::pan:
                if (ImGui::IsMouseDown(ImGuiMouseButton_Middle)) { V.Pan(double(IO.MouseDelta.x)); S.m_ScrollY -= IO.MouseDelta.y; } else S.m_Mode = state::mode::none;
                break;
            case state::mode::scrub:
            {
                double T = MouseTick();
                tick Tt = V.SnapFrame(T);
                if (IO.KeyShift) { const tick Zero[] = { 0 }; const auto P = SnapPoints(false); const auto R = SnapDelta(Zero, T, P, V, 10, true, true); Tt = R.m_Delta; }
                Doc.SetTime(Tt);
                break;
            }
            case state::mode::range_start: case state::mode::range_end:
            {
                const tick Edge = S.m_Mode == state::mode::range_start ? RangeA : RangeB;
                const tick Moving[] = { Edge };
                const auto P = SnapPoints(false);
                const auto R = SnapDelta(Moving, Raw, P, V, 8, bSnapOn, true);
                if (S.m_Mode == state::mode::range_start) S.m_RangeA = std::min(Edge + R.m_Delta, RangeB - V.FrameTicks());
                else                                      S.m_RangeB = std::max(Edge + R.m_Delta, RangeA + V.FrameTicks());
                break;
            }
            case state::mode::items:
            {
                // the moving times: the grabbed edge for trims and eases, every dragged item's edges for moves
                std::vector<tick> Moving;
                for (const auto& B : Boxes)
                    if (S.m_Dragged.count(B.m_Ref))
                    {
                        if (S.m_Handle == handle::trim_end || S.m_Handle == handle::ease_out) Moving.push_back(B.m_T1);
                        else if (S.m_Handle == handle::slip) {}
                        else { Moving.push_back(B.m_T0); if (B.m_T1 != B.m_T0 && S.m_Handle != handle::trim_start && S.m_Handle != handle::ease_in) Moving.push_back(B.m_T1); }
                    }
                const auto P = SnapPoints(true);
                S.m_Snap = SnapDelta(Moving, Raw, P, V, 8, bSnapOn && !Moving.empty(), !Moving.empty());
                S.m_Delta = S.m_Snap.m_Delta;
                break;
            }
            default: break;
            }

            // Esc cancels: nothing was changed (the drag is only a preview)
            if (ImGui::IsKeyPressed(ImGuiKey_Escape) && S.m_Mode != state::mode::none) { S.m_Mode = state::mode::none; S.m_Delta = 0; S.m_Dragged.clear(); S.m_Reply = "cancelled"; }

            // release: one command for the whole gesture
            if (S.m_Mode != state::mode::pan && S.m_Mode != state::mode::none && !ImGui::IsMouseDown(ImGuiMouseButton_Left))
            {
                if (S.m_Mode == state::mode::items && S.m_Delta != 0)
                {
                    std::vector<edit> Edits;
                    for (const auto& R : S.m_Dragged) Edits.push_back({ S.m_Handle, R, S.m_Delta });
                    S.m_Reply = Doc.Commit(Edits);
                }
                else if (S.m_Mode == state::mode::marquee)
                {
                    const double TA = V.T(double(S.m_StartMouse.x - S.m_Body.Min.x)), TB = MouseTick();
                    const int RA = RowAt(std::clamp(S.m_StartMouse.y, S.m_Body.Min.y, S.m_Body.Max.y - 1)), RB = RowAt(std::clamp(M.y, S.m_Body.Min.y, S.m_Body.Max.y - 1));
                    if (std::abs(M.x - S.m_StartMouse.x) > 3 || std::abs(M.y - S.m_StartMouse.y) > 3)
                    {
                        for (const auto& R : Marquee(Boxes, tick(std::llround(TA)), tick(std::llround(TB)), std::max(0, RA), RB < 0 ? int(Rows.size()) - 1 : RB)) S.m_Selection.insert(R);
                        Doc.OnSelection(S.m_Selection);
                    }
                }
                else if (S.m_Mode == state::mode::range_start || S.m_Mode == state::mode::range_end)
                {
                    if (S.m_RangeA != RangeA || S.m_RangeB != RangeB) S.m_Reply = Doc.SetPlaybackRange(S.m_RangeA, S.m_RangeB);
                }
                S.m_Mode = state::mode::none; S.m_Delta = 0; S.m_Dragged.clear();
            }
        }

        // keys (the timeline hovered, or its window focused, and no text field taking them)
        if ((bHovered || ImGui::IsWindowFocused(ImGuiFocusedFlags_ChildWindows)) && !IO.WantTextInput)
        {
            const tick F = V.FrameTicks();
            if (ImGui::IsKeyPressed(ImGuiKey_Comma))  Doc.SetTime(IO.KeyAlt ? JumpTo(Boxes, Now, -1) : V.SnapFrame(double(Now - F)));
            if (ImGui::IsKeyPressed(ImGuiKey_Period)) Doc.SetTime(IO.KeyAlt ? JumpTo(Boxes, Now, +1) : V.SnapFrame(double(Now + F)));
            std::vector<item_ref> Sel(S.m_Selection.begin(), S.m_Selection.end());
            if (ImGui::IsKeyPressed(ImGuiKey_Delete) && !Sel.empty()) { S.m_Reply = Doc.Delete(Sel); S.m_Selection.clear(); Doc.OnSelection(S.m_Selection); }
            if (IO.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_D) && !Sel.empty()) S.m_Reply = Doc.Duplicate(Sel);
            if (!IO.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_M)) S.m_Reply = Doc.AddMarker(Now);
            if (!IO.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_F) && !Sel.empty())
            {
                tick A = std::numeric_limits<tick>::max(), B = std::numeric_limits<tick>::min();
                for (const auto& Bx : Boxes) if (S.m_Selection.count(Bx.m_Ref)) { A = std::min(A, Bx.m_T0); B = std::max(B, Bx.m_T1); }
                if (A <= B) V.Frame(A, B, 0.15);
            }
            if (ImGui::IsKeyPressed(ImGuiKey_Home))
            {
                tick A = RangeA, B = RangeB;
                for (const auto& Bx : Boxes) { A = std::min(A, Bx.m_T0); B = std::max(B, Bx.m_T1); }
                V.Frame(A, B);
            }
        }

        // the ruler: the playback range, the labels, frame ticks, markers
        {
            const ImRect& R = S.m_Ruler;
            D.AddRectFilled(R.Min, R.Max, IM_COL32(44, 46, 51, 255));
            const tick A = S.m_Mode == state::mode::range_start ? S.m_RangeA : RangeA, B = S.m_Mode == state::mode::range_end ? S.m_RangeB : RangeB;
            const float xa = R.Min.x + float(V.X(double(A))), xb = R.Min.x + float(V.X(double(B)));
            D.AddRectFilled({ std::max(xa, R.Min.x), R.Min.y }, { std::min(xb, R.Max.x), R.Min.y + 6 }, IM_COL32(90, 170, 110, 200));
            for (float x : { xa, xb }) if (x >= R.Min.x - 6 && x <= R.Max.x + 6) D.AddTriangleFilled({ x - 6, R.Min.y }, { x + 6, R.Min.y }, { x, R.Min.y + 9 }, IM_COL32(120, 210, 140, 255));
            D.PushClipRect(R.Min, R.Max, true);
            const tick Step = RulerStep(V), F = V.FrameTicks();
            const double Left = V.T(0), Right = V.T(double(R.GetWidth()));
            if (double(F) * V.m_PxPerTick >= 5)
                for (tick T = tick(std::floor(Left / double(F))) * F; double(T) <= Right; T += F) D.AddLine({ R.Min.x + float(V.X(double(T))), R.Max.y - 4 }, { R.Min.x + float(V.X(double(T))), R.Max.y }, IM_COL32(120, 120, 130, 255));
            for (tick T = tick(std::floor(Left / double(Step))) * Step; double(T) <= Right; T += Step)
            {
                const float x = R.Min.x + float(V.X(double(T)));
                D.AddLine({ x, R.Max.y - 10 }, { x, R.Max.y }, IM_COL32(190, 190, 200, 255));
                D.AddText({ x + 3, R.Min.y + 8 }, IM_COL32(200, 200, 210, 255), Label(T, V).c_str());
            }
            for (const auto& Mk : Markers)
            {
                const float x = R.Min.x + float(V.X(double(Mk.m_Time)));
                D.AddTriangleFilled({ x - 5, R.Max.y - 10 }, { x + 5, R.Max.y - 10 }, { x, R.Max.y }, IM_COL32(240, 180, 60, 255));
                if (!Mk.m_Name.empty()) D.AddText({ x + 6, R.Max.y - 14 }, IM_COL32(240, 200, 120, 255), Mk.m_Name.c_str());
            }
            D.PopClipRect();
        }

        // the rows (only those on screen)
        S.m_RowRects.clear();
        D.PushClipRect({ Whole.Min.x, S.m_Body.Min.y }, S.m_Body.Max, true);
        const int First = std::max(0, int(S.m_ScrollY / S.m_RowHeight)), Last = std::min(int(Rows.size()) - 1, int((S.m_ScrollY + S.m_Body.GetHeight()) / S.m_RowHeight));
        for (int i = First; i <= Last; ++i)
        {
            auto& Vr = Rows[i];
            const draw_args A = RowArgs(i);
            S.m_RowRects.push_back({ Vr.m_Row.m_Id, ImRect(A.m_Min, A.m_Max) });
            D.AddRectFilled({ Whole.Min.x, A.m_Min.y }, A.m_Max, (i & 1) ? IM_COL32(34, 35, 39, 255) : IM_COL32(31, 32, 36, 255));
            D.AddLine({ Whole.Min.x, A.m_Max.y - 1 }, { A.m_Max.x, A.m_Max.y - 1 }, IM_COL32(22, 22, 25, 255));
            D.AddRectFilled({ Whole.Min.x, A.m_Min.y }, { Whole.Min.x + 3, A.m_Max.y }, Vr.m_Row.m_Color);
            if (Vr.m_pType)
            {
                D.PushClipRect(A.m_Min, A.m_Max, true);
                Vr.m_pType->Draw(Vr.m_Row, D, A);
                D.PopClipRect();
                if (Vr.m_Row.m_bMute) D.AddRectFilled(A.m_Min, A.m_Max, IM_COL32(20, 20, 22, 140));
            }
        }
        D.PopClipRect();

        // the header column: fold, name, eye / solo / lock, the row type's widgets (real ImGui buttons over the timeline's area)
        for (int i = First; i <= Last; ++i)
        {
            auto& Vr = Rows[i];
            const float y = S.m_Body.Min.y + float(i) * S.m_RowHeight - S.m_ScrollY;
            if (y + S.m_RowHeight > Whole.Max.y + 1) break;
            ImGui::PushID(static_cast<int>(Vr.m_Row.m_Id ^ (Vr.m_Row.m_Id >> 32)));
            ImGui::SetCursorScreenPos({ Whole.Min.x + 8 + float(Vr.m_Row.m_Depth) * 14, y + 4 });
            if (Vr.m_Row.m_bHasChildren)
            {
                if (ImGui::ArrowButton("##fold", Vr.m_Row.m_bFolded ? ImGuiDir_Right : ImGuiDir_Down)) S.m_Reply = Doc.SetRowFlag(Vr.m_Row.m_Id, row_flag::fold, !Vr.m_Row.m_bFolded);
                ImGui::SameLine(0, 4);
            }
            ImGui::TextUnformatted(Vr.m_Row.m_Name.c_str());
            auto Toggle = [&](const char* pLabel, const char* pTip, bool bOn, row_flag F, float x)
            {
                ImGui::SetCursorScreenPos({ S.m_Body.Min.x - x, y + 3 });
                ImGui::PushStyleColor(ImGuiCol_Button, bOn ? IM_COL32(200, 150, 60, 255) : IM_COL32(60, 62, 68, 255));
                if (ImGui::SmallButton(pLabel)) S.m_Reply = Doc.SetRowFlag(Vr.m_Row.m_Id, F, !bOn);
                if (ImGui::IsItemHovered()) ImGui::SetTooltip("%s", pTip);
                ImGui::PopStyleColor();
            };
            Toggle(Vr.m_Row.m_bMute ? "-" : "o", "Mute (the eye)", Vr.m_Row.m_bMute, row_flag::mute, 66);
            Toggle("S", "Solo", Vr.m_Row.m_bSolo, row_flag::solo, 46);
            Toggle("L", "Lock: no edits", Vr.m_Row.m_bLock, row_flag::lock, 26);
            if (Vr.m_pType) Vr.m_pType->Header(Vr.m_Row, Doc);
            ImGui::PopID();
        }

        // the playhead, the marquee, the snap line and the drag's tooltip (over everything of the timeline)
        {
            const float x = S.m_Body.Min.x + float(V.X(double(Now)));
            if (x >= S.m_Ruler.Min.x && x <= S.m_Ruler.Max.x)
            {
                D.AddLine({ x, S.m_Ruler.Min.y }, { x, Whole.Max.y }, IM_COL32(235, 70, 60, 255), 1.5f);
                D.AddTriangleFilled({ x - 6, S.m_Ruler.Max.y - 12 }, { x + 6, S.m_Ruler.Max.y - 12 }, { x, S.m_Ruler.Max.y }, IM_COL32(235, 70, 60, 255));
            }
            if (S.m_Mode == state::mode::marquee)
            {
                const ImVec2 A{ std::min(S.m_StartMouse.x, M.x), std::min(S.m_StartMouse.y, M.y) }, B{ std::max(S.m_StartMouse.x, M.x), std::max(S.m_StartMouse.y, M.y) };
                D.AddRectFilled(A, B, IM_COL32(90, 150, 240, 40)); D.AddRect(A, B, IM_COL32(110, 170, 255, 200));
            }
            if (S.m_Mode == state::mode::items || S.m_Mode == state::mode::range_start || S.m_Mode == state::mode::range_end)
            {
                if (S.m_Snap.m_bSnapped)
                {
                    const float sx = S.m_Body.Min.x + float(V.X(double(S.m_Snap.m_Target)));
                    D.AddLine({ sx, S.m_Ruler.Min.y }, { sx, Whole.Max.y }, IM_COL32(255, 230, 90, 220), 1.0f);
                }
                if (S.m_Mode == state::mode::items)
                    ImGui::SetTooltip("%s %s\nDelta %+.3f s (%+lld f)%s", Name(S.m_Handle), S.m_Snap.m_bSnapped ? std::format("snapped to the {} at {}", S.m_Snap.m_pWhat, Seconds(S.m_Snap.m_Target, V)).c_str() : "",
                                      double(S.m_Delta) / ticks_per_second_v, static_cast<long long>(S.m_Delta / V.FrameTicks()), bSnapOn ? "" : "\n(snap off)");
            }
        }

        ImGui::SetCursorScreenPos({ Whole.Min.x, Whole.Max.y });
        ImGui::Dummy({ 0, 0 });
        ImGui::PopID();
        return S.m_Reply;
    }
}
#endif
