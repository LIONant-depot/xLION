#ifndef XEDITOR_TIMELINE_H
#define XEDITOR_TIMELINE_H
#pragma once
// xeditor::timeline - the editor's timeline (xLION_Docs editor_timeline_framework_design_2026-11-15.md: T1 + T1b, the v2 contract).
// The core standardizes interaction and expresses intent; the document decides meaning, validates and commits.
//  - A VIEW over a document: rows, markers, the playback range and its revision come from the document; it changes only through the
//    document's commands (its undo, its console). View state (zoom, scroll, folds, selection) and the TRANSPORT (playhead, play, solo /
//    audition) are never the document's: scrubbing, folding or selecting never dirty it.
//  - Row types DECLARE items (segments, keys, intervals, markers; aggregates for dense or summary rows) for a time window; the core draws
//    them and builds their hit regions in the same pass (what is seen is what is picked), and owns selection, snapping, drags, focus and
//    tooltips. A row type may add an overlay and header widgets. A row whose type is not registered is a read-only placeholder.
//  - A gesture is an EDIT PLAN (xeditor_timeline_core.h): computed from the items as they were when it began, validated by the core
//    (capabilities, locks, key collisions) and the document, previewed (ghosts, the affected count, the conflicts), committed ONCE on
//    release against the document revision it came from (stale: refused). Esc cancels; a no-op commits nothing.
//  - The ruler (labels adapt to the zoom), scrub (Shift snaps), the playback range's ends, markers; Ctrl+wheel zooms at the cursor, the
//    middle button or Shift+wheel pans, the wheel scrolls; F frames the selection, Home all; , . a frame (from the grid index), Alt+, .
//    the previous / next key; Del, Ctrl+D, M a marker.
//  - Snapping: the visible items' edges and keys (the dragged ones excluded), the playhead, the markers; bounded, with hysteresis; the
//    magnet button, Ctrl overrides; a snap line and the tooltip.
#include "xeditor_timeline_core.h"
#include "imgui.h"
#include "imgui_internal.h"
#include <chrono>
#include <functional>
#include <map>
#include <set>
#include <unordered_map>

namespace xeditor::timeline
{
    struct row_desc
    {
        std::uint64_t m_Id = 0, m_Type = 0;
        int           m_Depth = 0;                      // children come after their parent (pre-order), one deeper
        bool          m_bHasChildren = false, m_bMute = false, m_bLock = false;
        bool          m_bToggles = true;                // eye / solo / lock in its header (off: a child row that shares its parent's, a read-only row)
        std::string   m_Name;
        ImU32         m_Color = IM_COL32(86, 132, 210, 255);
    };
    struct marker { std::uint64_t m_Id = 0; tick m_Time = 0; std::string m_Name; };
    enum class row_flag : std::uint8_t { mute, lock };              // authoring flags (the document's); fold is the view's, solo the transport's

    // The editing session's transport: shared by the timeline, the viewport and curves; never part of the document
    struct transport
    {
        tick                    m_Time = 0;
        bool                    m_bPlaying = false;
        std::set<std::uint64_t> m_Solo;                 // audition only: export and compile never see it
    };

    // The document side. Every function that changes something returns the reply of the command it ran ("" when it has none).
    struct document
    {
        virtual ~document() = default;
        virtual void          Rows(std::vector<row_desc>& Out) = 0;
        virtual void          Markers(std::vector<marker>&) {}
        virtual void          PlaybackRange(tick& A, tick& B) = 0;
        virtual std::string   SetPlaybackRange(tick A, tick B) = 0;
        virtual std::uint64_t Revision() = 0;                                       // changes with every committed edit (and undo)
        virtual std::string   Validate(const plan&) { return {}; }                  // the document's own rules ("" = fine); runs during the preview too
        virtual std::string   Commit(const plan& P) = 0;                            // ONE gesture: one command, one undo step (P.m_Revision checked)
        virtual std::string   Delete(std::span<const item_ref>) { return {}; }
        virtual std::string   Duplicate(std::span<const item_ref>) { return {}; }
        virtual std::string   AddMarker(tick) { return {}; }
        virtual std::string   SetRowFlag(std::uint64_t, row_flag, bool) { return {}; }
        virtual bool          CanMoveRow(std::uint64_t) { return false; }                               // its header can be dragged to reorder
        virtual std::string   MoveRow(std::uint64_t, std::uint64_t /*Above: the row it goes above; 0 = the bottom*/) { return {}; }
        virtual bool          CanDropInto(std::uint64_t /*Row*/) { return false; }                     // a container row (a folder, a group): a dragged row dropped on its middle goes inside
        virtual std::string   DropInto(std::uint64_t /*Row*/, std::uint64_t /*Into*/) { return {}; }
        virtual void          OnSelection(const std::set<item_ref>&) {}             // the editor shows the selection's properties
        virtual void          Seek(tick) {}                                         // navigation: sample only, never dispatch
    };

    // What a row type is asked for: the items in [T0, T1] at this zoom (aggregate when dense), or every real item (m_bAggregate false)
    struct query
    {
        const view* m_pView = nullptr;
        tick        m_T0 = 0, m_T1 = 0;
        bool        m_bAggregate = true;
    };
    struct draw_args
    {
        const view* m_pView = nullptr;
        ImVec2      m_Min{}, m_Max{};
        float X(tick T) const noexcept { return m_Min.x + static_cast<float>(m_pView->X(double(T))); }
    };
    struct row_type
    {
        virtual ~row_type() = default;
        virtual void Query(const row_desc&, const query&, std::vector<item>& Out) = 0;
        virtual void Overlay(const row_desc&, ImDrawList&, const draw_args&) {}          // optional custom drawing over the standard items
        // the row type's own header widgets (a weight, a mode, a mask chip...): it says how wide they are, the core gives them that box,
        // between the name (never covered: it is clipped before them) and the eye / solo / lock toggles
        virtual float HeaderWidth(const row_desc&) { return 0; }
        virtual void  Header(const row_desc&, document&, const ImRect& /*Box*/) {}
    };
    using registry = std::unordered_map<std::uint64_t, row_type*>;

    //--------------------------------------------------------------------------------------------
    // The timeline's own state (one per timeline shown): view state, never the document's
    //--------------------------------------------------------------------------------------------
    struct hit_region { ImRect m_Rect; item_ref m_Ref; handle m_Handle = handle::none; int m_Priority = 0; int m_iRow = 0; std::vector<item_ref> m_Represents; };

    struct state
    {
        view                    m_View;
        std::set<item_ref>      m_Selection;            // real items only (an aggregate selects what it stands for)
        std::set<std::uint64_t> m_Folded;
        bool                    m_bMagnet       = true;
        float                   m_HeaderWidth   = 220, m_RowHeight = 26, m_RulerHeight = 30, m_ScrollY = 0;
        enum class mode : std::uint8_t { none, items, marquee, scrub, range_start, range_end, pan };
        mode                    m_Mode          = mode::none;
        handle                  m_Handle        = handle::none;
        double                  m_StartTick     = 0;
        ImVec2                  m_StartMouse{};
        std::vector<item>       m_Originals;            // the dragged items as they were when the gesture began
        std::vector<item>       m_Others;               // the rest of their rows (collisions)
        plan                    m_Plan;                 // the gesture's current plan (the preview draws it)
        snap_result             m_Snap;
        tick                    m_RangeA = 0, m_RangeB = 0;
        std::string             m_Reply;
        bool                    m_bFramed       = false;
        std::uint64_t           m_DragRow       = 0;    // a row header being dragged (reorder): previewed by a line, committed on release
        // the layout and the picking regions of the last frame (tests and virtual input read them)
        ImRect                  m_Body, m_Ruler;
        std::vector<std::pair<std::uint64_t, ImRect>> m_RowRects;
        std::vector<hit_region> m_Hits;
        // timings of the last frame (ms) and what was drawn
        double                  m_DrawMs = 0, m_QueryMs = 0, m_SnapMs = 0;
        std::size_t             m_nItemsDrawn = 0;
    };

    namespace details
    {
        inline ImU32 Shade(ImU32 C, float K) noexcept
        {
            auto Ch = [&](int s) { return static_cast<ImU32>(std::clamp((float((C >> s) & 0xFF)) * K, 0.0f, 255.0f)) << s; };
            return Ch(IM_COL32_R_SHIFT) | Ch(IM_COL32_G_SHIFT) | Ch(IM_COL32_B_SHIFT) | (C & IM_COL32_A_MASK);
        }
        inline std::string Seconds(tick T, const view& V) { return std::format("{:.3f} s ({} f)", double(T) / double(V.m_TPS), V.FrameIndex(double(T))); }
        inline double Ms(std::chrono::steady_clock::time_point A) { return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - A).count(); }

        // One standard item: drawn, and its hit regions made from the same geometry
        inline void DrawItem(ImDrawList& D, const draw_args& A, const item& I, const segment& S, ImU32 RowColor, bool bSelected, bool bGhost, int iRow, std::vector<hit_region>* pHits)
        {
            const ImU32 C = I.m_Color ? I.m_Color : RowColor;
            const float y0 = A.m_Min.y + 3, y1 = A.m_Max.y - 3, ym = (A.m_Min.y + A.m_Max.y) * 0.5f;
            auto Hit = [&](ImRect R, handle H, int Pri) { if (pHits) pHits->push_back({ R, I.m_Ref, H, Pri, iRow, I.m_Represents }); };
            if (I.m_Kind == item_kind::segment || I.m_Kind == item_kind::interval)
            {
                const float x0 = A.X(S.m_Start), x1 = std::max(A.X(S.m_End), x0 + 2.0f);
                if (x1 < A.m_Min.x || x0 > A.m_Max.x) return;
                if (bGhost) { D.AddRect({ x0, y0 }, { x1, y1 }, IM_COL32(255, 255, 255, 90), 3.0f, 0, 1.0f); return; }
                const float yb0 = I.m_Kind == item_kind::interval ? ym - 5 : y0, yb1 = I.m_Kind == item_kind::interval ? ym + 5 : y1;
                D.AddRectFilled({ x0, yb0 }, { x1, yb1 }, bSelected ? Shade(C, 1.25f) : C, 3.0f);
                D.AddRect({ x0, yb0 }, { x1, yb1 }, bSelected ? IM_COL32(255, 255, 255, 230) : Shade(C, 0.6f), 3.0f, 0, bSelected ? 2.0f : 1.0f);
                const bool bEase = (I.m_Caps & caps::ease) && I.m_Kind == item_kind::segment;
                if (bEase)
                {
                    const float ei = A.X(S.m_Start + S.m_EaseIn), eo = A.X(S.m_End - S.m_EaseOut);
                    if (S.m_EaseIn > 0)  D.AddTriangleFilled({ x0, y0 }, { ei, y0 }, { x0, y1 }, IM_COL32(0, 0, 0, 70));
                    if (S.m_EaseOut > 0) D.AddTriangleFilled({ eo, y0 }, { x1, y0 }, { x1, y1 }, IM_COL32(0, 0, 0, 70));
                    D.AddCircleFilled({ ei, y0 + 1 }, 3.0f, IM_COL32(255, 255, 255, 160));
                    D.AddCircleFilled({ eo, y0 + 1 }, 3.0f, IM_COL32(255, 255, 255, 160));
                    if (x1 - x0 > 24) { Hit(ImRect({ ei - 6, y0 - 2 }, { ei + 6, y0 + 8 }), handle::ease_in, 3); Hit(ImRect({ eo - 6, y0 - 2 }, { eo + 6, y0 + 8 }), handle::ease_out, 3); }
                }
                if (I.m_Caps & caps::trim) { Hit(ImRect({ x0 - 6, yb0 }, { x0 + 6, yb1 }), handle::trim_start, 2); Hit(ImRect({ x1 - 6, yb0 }, { x1 + 6, yb1 }), handle::trim_end, 2); }
                Hit(ImRect({ x0, yb0 }, { x1, yb1 }), handle::body, 1);
                if (!I.m_Label.empty() && x1 - x0 > 20)
                {
                    D.PushClipRect({ std::max(x0, A.m_Min.x) + 4, yb0 }, { std::min(x1, A.m_Max.x) - 4, yb1 }, true);
                    D.AddText({ std::max(x0, A.m_Min.x) + 6, yb0 + (yb1 - yb0 - ImGui::GetFontSize()) * 0.5f }, IM_COL32(255, 255, 255, 230), I.m_Label.c_str());
                    D.PopClipRect();
                }
                return;
            }
            // key / marker: a diamond (a marker: a flag); an aggregate is bigger and shows its count
            const float x = A.X(S.m_Start);
            if (x < A.m_Min.x - 8 || x > A.m_Max.x + 8) return;
            if (I.HasValue())
            {
                // a valued key (a curve lane): a dot at its value's height, picked there (so the lane stays clickable around it)
                const float u = (I.m_Value - I.m_ValueMin) / std::max(1e-6f, I.m_ValueMax - I.m_ValueMin), yv = y1 - std::clamp(u, 0.0f, 1.0f) * (y1 - y0);
                if (bGhost) { D.AddCircle({ x, yv }, 4.5f, IM_COL32(255, 255, 255, 90)); return; }
                D.AddCircleFilled({ x, yv }, 4.5f, bSelected ? IM_COL32(255, 210, 90, 255) : C);
                D.AddCircle({ x, yv }, 4.5f, bSelected ? IM_COL32(255, 255, 255, 255) : IM_COL32(0, 0, 0, 170), 0, 1.2f);
                Hit(ImRect({ x - 7, yv - 7 }, { x + 7, yv + 7 }), handle::key, 2);
                return;
            }
            const float r = I.m_Count > 1 ? 6.5f : 5.5f;
            if (bGhost) { D.AddQuad({ x, ym - r }, { x + r, ym }, { x, ym + r }, { x - r, ym }, IM_COL32(255, 255, 255, 90), 1.0f); return; }
            if (I.m_Kind == item_kind::marker)
            {
                D.AddLine({ x, y0 }, { x, y1 }, bSelected ? IM_COL32(255, 210, 90, 255) : C, 2.0f);
                D.AddTriangleFilled({ x, y0 }, { x + 9, y0 + 4 }, { x, y0 + 8 }, bSelected ? IM_COL32(255, 210, 90, 255) : C);
            }
            else
            {
                D.AddQuadFilled({ x, ym - r }, { x + r, ym }, { x, ym + r }, { x - r, ym }, bSelected ? IM_COL32(255, 210, 90, 255) : C);
                D.AddQuad({ x, ym - r }, { x + r, ym }, { x, ym + r }, { x - r, ym }, bSelected ? IM_COL32(255, 255, 255, 255) : IM_COL32(0, 0, 0, 160), 1.2f);
            }
            if (I.m_Count > 1) D.AddText({ x + r + 1, ym - ImGui::GetFontSize() }, IM_COL32(220, 220, 230, 200), std::to_string(I.m_Count).c_str());
            Hit(ImRect({ x - 7, A.m_Min.y }, { x + 7, A.m_Max.y }), handle::key, 2);
        }
    }

    // Draws the timeline into the current window's remaining space (or Size) and handles its input. Returns the last command's reply.
    inline const std::string& Draw(state& S, transport& Tr, document& Doc, const registry& Types, ImVec2 Size = { 0, 0 })
    {
        using namespace details;
        const auto tDraw = std::chrono::steady_clock::now();
        S.m_QueryMs = S.m_SnapMs = 0;
        auto& IO = ImGui::GetIO();
        view& V = S.m_View;

        // rows: the folded ones' descendants hidden (folds are the view's)
        std::vector<row_desc> All; Doc.Rows(All);
        struct vrow { row_desc m_Row; row_type* m_pType = nullptr; };
        std::vector<vrow> Rows;
        int HideBelow = -1;
        for (auto& R : All)
        {
            if (HideBelow >= 0 && R.m_Depth > HideBelow) continue;
            HideBelow = S.m_Folded.count(R.m_Id) ? R.m_Depth : -1;
            const auto It = Types.find(R.m_Type);
            Rows.push_back({ R, It == Types.end() ? nullptr : It->second });
        }
        tick RangeA = 0, RangeB = 0; Doc.PlaybackRange(RangeA, RangeB);
        std::vector<marker> Markers; Doc.Markers(Markers);
        const tick Now = Tr.m_Time;
        std::set<std::uint64_t> Locked; for (const auto& R : All) if (R.m_bLock) Locked.insert(R.m_Id);

        // every real item of the rows that own Refs, as they are now (a gesture's originals)
        auto RealItems = [&](const std::set<item_ref>& Refs, std::vector<item>& Moving, std::vector<item>& Others)
        {
            Moving.clear(); Others.clear();
            std::set<std::uint64_t> RowIds; for (const auto& r : Refs) RowIds.insert(r.m_Row);
            for (const auto& Vr : Rows)
                if (Vr.m_pType && RowIds.count(Vr.m_Row.m_Id))
                {
                    std::vector<item> Items;
                    Vr.m_pType->Query(Vr.m_Row, { &V, std::numeric_limits<tick>::min() / 4, std::numeric_limits<tick>::max() / 4, false }, Items);
                    for (auto& I : Items) (Refs.count(I.m_Ref) ? Moving : Others).push_back(std::move(I));
                }
            // summary rows show items of other rows (their children): those rows are queried too when hidden by a fold
            if (Moving.size() < Refs.size())
                for (const auto& R : All)
                    if (const auto It = Types.find(R.m_Type); It != Types.end() && RowIds.count(R.m_Id) && std::none_of(Rows.begin(), Rows.end(), [&](const vrow& v) { return v.m_Row.m_Id == R.m_Id; }))
                    {
                        std::vector<item> Items;
                        It->second->Query(R, { &V, std::numeric_limits<tick>::min() / 4, std::numeric_limits<tick>::max() / 4, false }, Items);
                        for (auto& I : Items) (Refs.count(I.m_Ref) ? Moving : Others).push_back(std::move(I));
                    }
        };

        // the toolbar
        ImGui::PushID(&S);
        ImGui::Checkbox("Snap", &S.m_bMagnet);
        if (ImGui::IsItemHovered()) ImGui::SetTooltip("Snap to edges, keys, the playhead and markers (8 px), else to frames. Hold Ctrl while dragging to override.");
        ImGui::SameLine(); ImGui::SetNextItemWidth(90);
        struct rate { tick n, d; const char* p; };
        static constexpr rate Rates[] = { { 24, 1, "24" }, { 24000, 1001, "23.976" }, { 25, 1, "25" }, { 30, 1, "30" }, { 30000, 1001, "29.97" }, { 50, 1, "50" }, { 60, 1, "60" }, { 120, 1, "120" } };
        if (ImGui::BeginCombo("fps", std::format("{:g}", V.FPS()).c_str()))
        { for (const auto& R : Rates) if (ImGui::Selectable(R.p, R.n == V.m_RateNum && R.d == V.m_RateDen)) { V.m_RateNum = R.n; V.m_RateDen = R.d; } ImGui::EndCombo(); }
        ImGui::SameLine(); const bool bFrameAll = ImGui::SmallButton("Frame all (Home)");
        ImGui::SameLine(); ImGui::TextDisabled("%s", Seconds(Now, V).c_str());
        if (!S.m_Reply.empty()) { ImGui::SameLine(); ImGui::TextDisabled("| %s", S.m_Reply.c_str()); }

        // the layout
        ImVec2 Avail = ImGui::GetContentRegionAvail();
        if (Size.x > 0) Avail.x = Size.x;
        if (Size.y > 0) Avail.y = Size.y;
        // a narrow panel: the header column gives way (never wider than the panel: a body drawn past it could not be clicked)
        float HeaderWidth = S.m_HeaderWidth;            // the preferred width (the edge drag changes it)
        if (Avail.x < S.m_HeaderWidth + 160) S.m_HeaderWidth = std::max(110.0f, Avail.x * 0.42f);
        Avail.x = std::max(Avail.x, S.m_HeaderWidth + 60); Avail.y = std::max(Avail.y, S.m_RulerHeight + S.m_RowHeight);
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

        ImGui::SetCursorScreenPos(S.m_Ruler.Min);
        ImGui::InvisibleButton("##timeline", { S.m_Body.Max.x - S.m_Ruler.Min.x, S.m_Body.Max.y - S.m_Ruler.Min.y }, ImGuiButtonFlags_MouseButtonLeft | ImGuiButtonFlags_MouseButtonMiddle);
        const bool bHovered = ImGui::IsItemHovered(), bActive = ImGui::IsItemActive();
        const ImVec2 M = IO.MousePos;
        auto MouseTick = [&]() { return V.T(double(M.x - S.m_Body.Min.x)); };
        auto RowAt = [&](float y) -> int { const int i = int(std::floor((y - S.m_Body.Min.y + S.m_ScrollY) / S.m_RowHeight)); return (i >= 0 && i < int(Rows.size())) ? i : -1; };
        auto RowArgs = [&](int i) -> draw_args
        {
            draw_args A; A.m_pView = &V;
            const float y = S.m_Body.Min.y + float(i) * S.m_RowHeight - S.m_ScrollY;
            A.m_Min = { S.m_Body.Min.x, y }; A.m_Max = { S.m_Body.Max.x, y + S.m_RowHeight };
            return A;
        };
        auto Select = [&](const std::vector<item_ref>& Refs, bool bToggle, bool bAdd)
        {
            if (bToggle) { for (auto& r : Refs) if (!S.m_Selection.erase(r)) S.m_Selection.insert(r); }
            else if (bAdd) S.m_Selection.insert(Refs.begin(), Refs.end());
            else { S.m_Selection.clear(); S.m_Selection.insert(Refs.begin(), Refs.end()); }
            Doc.OnSelection(S.m_Selection);
        };

        // wheel: Ctrl zooms at the cursor, Shift pans, else the rows scroll
        if (bHovered && IO.MouseWheel != 0)
        {
            if (IO.KeyCtrl) V.ZoomAt(double(M.x - S.m_Body.Min.x), std::pow(1.2, double(IO.MouseWheel)));
            else if (IO.KeyShift) V.Pan(double(IO.MouseWheel) * 80.0);
            else S.m_ScrollY -= IO.MouseWheel * S.m_RowHeight * 2;
        }

        // a press starts a gesture: picked from LAST frame's regions (what the person saw), highest priority wins
        if (bHovered && ImGui::IsMouseClicked(ImGuiMouseButton_Middle)) { S.m_Mode = state::mode::pan; S.m_StartMouse = M; }
        if (bHovered && ImGui::IsMouseClicked(ImGuiMouseButton_Left))
        {
            S.m_StartMouse = M; S.m_StartTick = MouseTick(); S.m_Snap = {}; S.m_Plan = {};
            if (S.m_Ruler.Contains(M))
            {
                const float xa = S.m_Body.Min.x + float(V.X(double(RangeA))), xb = S.m_Body.Min.x + float(V.X(double(RangeB)));
                S.m_RangeA = RangeA; S.m_RangeB = RangeB;
                if (M.y < S.m_Ruler.Min.y + 9 && std::abs(M.x - xa) < 7)      S.m_Mode = state::mode::range_start;
                else if (M.y < S.m_Ruler.Min.y + 9 && std::abs(M.x - xb) < 7) S.m_Mode = state::mode::range_end;
                else S.m_Mode = state::mode::scrub;
            }
            else
            {
                const hit_region* pBest = nullptr;
                for (const auto& H : S.m_Hits) if (H.m_Rect.Contains(M) && (!pBest || H.m_Priority > pBest->m_Priority)) pBest = &H;
                if (pBest)
                {
                    std::vector<item_ref> Refs = pBest->m_Represents.empty() ? std::vector<item_ref>{ pBest->m_Ref } : pBest->m_Represents;
                    const bool bAlready = std::all_of(Refs.begin(), Refs.end(), [&](const item_ref& r) { return S.m_Selection.count(r); });
                    if (IO.KeyCtrl) Select(Refs, true, false);
                    else if (IO.KeyShift) Select(Refs, false, true);
                    else if (!bAlready) Select(Refs, false, false);
                    handle H = pBest->m_Handle;
                    if (H == handle::body && IO.KeyAlt) H = handle::slip;
                    const bool bStill = std::all_of(Refs.begin(), Refs.end(), [&](const item_ref& r) { return S.m_Selection.count(r); });
                    if (bStill)
                    {
                        // edges, eases and slip act on the item grabbed; a move or a key drag on the whole selection
                        std::set<item_ref> Dragged = (H == handle::body || H == handle::key) ? S.m_Selection : std::set<item_ref>(Refs.begin(), Refs.end());
                        RealItems(Dragged, S.m_Originals, S.m_Others);
                        S.m_Mode = state::mode::items; S.m_Handle = H;
                    }
                }
                else { S.m_Mode = state::mode::marquee; if (!IO.KeyCtrl && !IO.KeyShift) Select({}, false, false); }
            }
        }

        // the visible window's items per row (drawn below; the snap points and the marquee use them too)
        const tick W0 = tick(std::floor(V.T(-20))), W1 = tick(std::ceil(V.T(V.m_Width + 20)));
        const int First = std::max(0, int(S.m_ScrollY / S.m_RowHeight)), Last = std::min(int(Rows.size()) - 1, int((S.m_ScrollY + S.m_Body.GetHeight()) / S.m_RowHeight));
        std::vector<std::vector<item>> Visible(Rows.size());
        {
            const auto t = std::chrono::steady_clock::now();
            for (int i = First; i <= Last; ++i) if (Rows[i].m_pType) Rows[i].m_pType->Query(Rows[i].m_Row, { &V, W0, W1, true }, Visible[i]);
            S.m_QueryMs = Ms(t);
        }
        auto IsDragged = [&](const item& I)
        {
            if (S.m_Mode != state::mode::items) return false;
            for (const auto& O : S.m_Originals) { if (O.m_Ref == I.m_Ref) return true; for (const auto& r : I.m_Represents) if (r == O.m_Ref) return true; }
            return false;
        };
        auto SnapPoints = [&](bool bSkipDragged)
        {
            std::vector<snap_point> P;
            for (int i = First; i <= Last; ++i)
                for (const auto& I : Visible[i])
                {
                    if (bSkipDragged && IsDragged(I)) continue;
                    if (I.m_Count > 1) continue;            // a pixel bin is not a place: dense aggregates are no snap targets
                    P.push_back({ I.m_Seg.m_Start, I.m_Kind == item_kind::key || I.m_Kind == item_kind::marker ? "key" : "edge" });
                    if (I.m_Seg.m_End != I.m_Seg.m_Start) P.push_back({ I.m_Seg.m_End, "edge" });
                }
            P.push_back({ Now, "playhead" });
            for (const auto& Mk : Markers) P.push_back({ Mk.m_Time, "marker" });
            SortPoints(P);
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
                const double T = MouseTick();
                tick Tt = V.SnapFrame(T);
                if (IO.KeyShift) { const tick Zero[] = { 0 }; const auto P = SnapPoints(false); Tt = SnapDelta(Zero, T, P, V, 10, true, true).m_Delta; }
                if (Tt != Tr.m_Time) { Tr.m_Time = Tt; Doc.Seek(Tt); }        // a seek: sample only, never dispatch
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
                // a click is not a drag: nothing is planned until the mouse has moved 3 px
                if (std::abs(M.x - S.m_StartMouse.x) < 3 && std::abs(M.y - S.m_StartMouse.y) < 3 && S.m_Plan.m_Entries.empty()) break;
                const auto t = std::chrono::steady_clock::now();
                std::vector<tick> Moving;
                for (const auto& O : S.m_Originals)
                {
                    if (S.m_Handle == handle::trim_end || S.m_Handle == handle::ease_out) Moving.push_back(O.m_Seg.m_End);
                    else if (S.m_Handle == handle::slip) {}
                    else { Moving.push_back(O.m_Seg.m_Start); if (O.m_Seg.m_End != O.m_Seg.m_Start && S.m_Handle != handle::trim_start && S.m_Handle != handle::ease_in) Moving.push_back(O.m_Seg.m_End); }
                }
                const auto P = SnapPoints(true);
                const snap_result Prev = S.m_Snap;
                S.m_Snap = SnapDelta(Moving, Raw, P, V, 8, bSnapOn && !Moving.empty(), !Moving.empty(), &Prev);
                S.m_SnapMs = Ms(t);
                plan_inputs In; In.m_Dragged = S.m_Originals; In.m_Others = S.m_Others; In.m_LockedRows = Locked; In.m_Handle = S.m_Handle;
                In.m_Delta = S.m_Snap.m_Delta; In.m_MinLength = V.FrameTicks(); In.m_Revision = Doc.Revision();
                // valued keys: the vertical drag is the value (the lane's height is its range)
                for (const auto& O : S.m_Originals) if (O.HasValue()) { In.m_ValueDelta = -(M.y - S.m_StartMouse.y) / std::max(1.0f, S.m_RowHeight - 6.0f) * (O.m_ValueMax - O.m_ValueMin); break; }
                S.m_Plan = MakePlan(In);
                if (S.m_Plan.m_Conflicts.empty() && !S.m_Plan.NoOp()) if (auto E = Doc.Validate(S.m_Plan); !E.empty()) S.m_Plan.m_Conflicts.push_back(E);
                break;
            }
            default: break;
            }

            // Esc cancels: nothing was changed (the drag is only a preview)
            if (ImGui::IsKeyPressed(ImGuiKey_Escape) && S.m_Mode != state::mode::none) { S.m_Mode = state::mode::none; S.m_Plan = {}; S.m_Originals.clear(); S.m_Reply = "cancelled"; }

            // release: one command for the whole gesture
            if (S.m_Mode != state::mode::pan && S.m_Mode != state::mode::none && !ImGui::IsMouseDown(ImGuiMouseButton_Left))
            {
                if (S.m_Mode == state::mode::items)
                {
                    if (!S.m_Plan.m_Conflicts.empty())           S.m_Reply = "refused: " + S.m_Plan.m_Conflicts.front();
                    else if (S.m_Plan.NoOp())                    {}
                    else if (S.m_Plan.m_Revision != Doc.Revision()) S.m_Reply = "refused: the document changed during the drag (stale plan)";
                    else                                         S.m_Reply = Doc.Commit(S.m_Plan);
                }
                else if (S.m_Mode == state::mode::marquee)
                {
                    if (std::abs(M.x - S.m_StartMouse.x) > 3 || std::abs(M.y - S.m_StartMouse.y) > 3)
                    {
                        const double TA = V.T(double(S.m_StartMouse.x - S.m_Body.Min.x)), TB = MouseTick();
                        const int RA = RowAt(std::clamp(S.m_StartMouse.y, S.m_Body.Min.y, S.m_Body.Max.y - 1)), RB = RowAt(std::clamp(M.y, S.m_Body.Min.y, S.m_Body.Max.y - 1));
                        std::vector<item_box> Boxes; std::map<item_ref, std::vector<item_ref>> Expand;
                        for (int i = First; i <= Last; ++i) for (const auto& I : Visible[i]) { Boxes.push_back({ I.m_Ref, I.m_Seg.m_Start, I.m_Seg.m_End, i }); if (!I.m_Represents.empty()) Expand[I.m_Ref] = I.m_Represents; }
                        std::vector<item_ref> Picked;
                        for (const auto& R : Marquee(Boxes, tick(std::llround(TA)), tick(std::llround(TB)), std::max(0, RA), RB < 0 ? int(Rows.size()) - 1 : RB))
                            if (const auto It = Expand.find(R); It != Expand.end()) Picked.insert(Picked.end(), It->second.begin(), It->second.end()); else Picked.push_back(R);
                        Select(Picked, false, true);
                    }
                }
                else if (S.m_Mode == state::mode::range_start || S.m_Mode == state::mode::range_end)
                {
                    if (S.m_RangeA != RangeA || S.m_RangeB != RangeB) S.m_Reply = Doc.SetPlaybackRange(S.m_RangeA, S.m_RangeB);
                }
                S.m_Mode = state::mode::none; S.m_Plan = {}; S.m_Originals.clear(); S.m_Others.clear();
            }
        }

        // keys (the timeline hovered, or its window focused, and no text field taking them)
        if ((bHovered || ImGui::IsWindowFocused(ImGuiFocusedFlags_ChildWindows)) && !IO.WantTextInput)
        {
            auto Seek = [&](tick T) { if (T != Tr.m_Time) { Tr.m_Time = T; Doc.Seek(T); } };
            auto Boxes = [&]()
            {
                std::vector<item_box> B;
                for (int i = 0; i < int(Rows.size()); ++i) if (Rows[i].m_pType)
                { std::vector<item> It; Rows[i].m_pType->Query(Rows[i].m_Row, { &V, std::numeric_limits<tick>::min() / 4, std::numeric_limits<tick>::max() / 4, true }, It); for (auto& I : It) B.push_back({ I.m_Ref, I.m_Seg.m_Start, I.m_Seg.m_End, i }); }
                return B;
            };
            if (ImGui::IsKeyPressed(ImGuiKey_Comma))  Seek(IO.KeyAlt ? JumpTo(Boxes(), Now, -1) : V.StepFrame(Now, -1));
            if (ImGui::IsKeyPressed(ImGuiKey_Period)) Seek(IO.KeyAlt ? JumpTo(Boxes(), Now, +1) : V.StepFrame(Now, +1));
            std::vector<item_ref> Sel(S.m_Selection.begin(), S.m_Selection.end());
            if (ImGui::IsKeyPressed(ImGuiKey_Delete) && !Sel.empty()) { S.m_Reply = Doc.Delete(Sel); Select({}, false, false); }
            if (IO.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_D) && !Sel.empty()) S.m_Reply = Doc.Duplicate(Sel);
            if (!IO.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_M)) S.m_Reply = Doc.AddMarker(Now);
            if (!IO.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_F) && !Sel.empty())
            {
                tick A = std::numeric_limits<tick>::max(), B = std::numeric_limits<tick>::min();
                std::vector<item> Mv, Ot; RealItems(S.m_Selection, Mv, Ot);
                for (const auto& I : Mv) { A = std::min(A, I.m_Seg.m_Start); B = std::max(B, I.m_Seg.m_End); }
                if (A <= B) V.Frame(A, B, 0.15);
            }
            if (ImGui::IsKeyPressed(ImGuiKey_Home))
            {
                tick A = RangeA, B = RangeB;
                for (const auto& Bx : Boxes()) { A = std::min(A, Bx.m_T0); B = std::max(B, Bx.m_T1); }
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
            const tick Step = RulerStep(V);
            const double Left = V.T(0), Right = V.T(double(R.GetWidth()));
            if (double(V.FrameTicks()) * V.m_PxPerTick >= 5)
                for (std::int64_t f = V.FrameIndex(Left) - 1, fe = V.FrameIndex(Right) + 1; f <= fe; ++f)
                { const float x = R.Min.x + float(V.X(double(V.FrameTime(f)))); D.AddLine({ x, R.Max.y - 4 }, { x, R.Max.y }, IM_COL32(120, 120, 130, 255)); }
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

        // the rows (only those on screen): the standard items, then the row type's overlay; the hit regions made in the same pass
        std::map<item_ref, const plan_entry*> Preview;
        for (const auto& E : S.m_Plan.m_Entries) Preview[E.m_Ref] = &E;
        const bool bPlanOk = S.m_Plan.m_Conflicts.empty();
        S.m_RowRects.clear(); S.m_Hits.clear(); S.m_nItemsDrawn = 0;
        D.PushClipRect({ Whole.Min.x, S.m_Body.Min.y }, S.m_Body.Max, true);
        for (int i = First; i <= Last; ++i)
        {
            auto& Vr = Rows[i];
            const draw_args A = RowArgs(i);
            S.m_RowRects.push_back({ Vr.m_Row.m_Id, ImRect(A.m_Min, A.m_Max) });
            D.AddRectFilled({ Whole.Min.x, A.m_Min.y }, A.m_Max, (i & 1) ? IM_COL32(34, 35, 39, 255) : IM_COL32(31, 32, 36, 255));
            D.AddLine({ Whole.Min.x, A.m_Max.y - 1 }, { A.m_Max.x, A.m_Max.y - 1 }, IM_COL32(22, 22, 25, 255));
            D.AddRectFilled({ Whole.Min.x, A.m_Min.y }, { Whole.Min.x + 3, A.m_Max.y }, Vr.m_Row.m_Color);
            D.PushClipRect(A.m_Min, A.m_Max, true);
            if (!Vr.m_pType)
            {
                // a row type nobody registered: kept as it is, read only
                for (float x = A.m_Min.x - 20; x < A.m_Max.x; x += 14) D.AddLine({ x, A.m_Max.y }, { x + 20, A.m_Min.y }, IM_COL32(70, 70, 76, 255));
                D.AddText({ A.m_Min.x + 8, A.m_Min.y + 5 }, IM_COL32(200, 200, 210, 230), std::format("Unknown row type {}: read only, kept as it is", Vr.m_Row.m_Type).c_str());
            }
            else
            {
                std::vector<hit_region>* pHits = Vr.m_Row.m_bLock ? nullptr : &S.m_Hits;
                // a curve lane: the valued keys joined by lines (where they will be while dragged)
                {
                    struct pt { float x, y; bool bStep; bool operator<(const pt& o) const noexcept { return x < o.x; } };
                    std::vector<pt> Pts;
                    const float y0 = A.m_Min.y + 3, y1 = A.m_Max.y - 3;
                    for (const auto& I : Visible[i])
                    {
                        if (!I.HasValue()) continue;
                        float v = I.m_Value; tick tt = I.m_Seg.m_Start;
                        if (const auto It = Preview.find(I.m_Ref); It != Preview.end()) { v = It->second->HasValue() ? It->second->m_NewValue : v; tt = It->second->m_New.m_Start; }
                        const float u = (v - I.m_ValueMin) / std::max(1e-6f, I.m_ValueMax - I.m_ValueMin);
                        Pts.push_back({ A.X(tt), y1 - std::clamp(u, 0.0f, 1.0f) * (y1 - y0), I.m_bStepValue });
                    }
                    std::stable_sort(Pts.begin(), Pts.end());
                    if (!Pts.empty())
                    {
                        D.AddLine({ A.m_Min.x, Pts.front().y }, { Pts.front().x, Pts.front().y }, Shade(Vr.m_Row.m_Color, 0.8f), 1.5f);
                        for (std::size_t k = 1; k < Pts.size(); ++k)
                        {
                            const auto& P0 = Pts[k - 1]; const auto& P1 = Pts[k];
                            if (P0.bStep) { D.AddLine({ P0.x, P0.y }, { P1.x, P0.y }, Vr.m_Row.m_Color, 1.5f); D.AddLine({ P1.x, P0.y }, { P1.x, P1.y }, Vr.m_Row.m_Color, 1.5f); }   // holds, then jumps
                            else D.AddLine({ P0.x, P0.y }, { P1.x, P1.y }, Vr.m_Row.m_Color, 1.5f);
                        }
                        D.AddLine({ Pts.back().x, Pts.back().y }, { A.m_Max.x, Pts.back().y }, Shade(Vr.m_Row.m_Color, 0.8f), 1.5f);
                    }
                }
                for (const auto& I : Visible[i])
                {
                    const bool bSel = S.m_Selection.count(I.m_Ref) || std::any_of(I.m_Represents.begin(), I.m_Represents.end(), [&](const item_ref& r) { return S.m_Selection.count(r); });
                    const auto It = Preview.find(I.m_Ref);
                    if (It != Preview.end() && (!(It->second->m_Old == It->second->m_New) || (It->second->HasValue() && It->second->m_NewValue != It->second->m_OldValue)))
                    {
                        DrawItem(D, A, I, I.m_Seg, Vr.m_Row.m_Color, false, true, i, nullptr);                       // the ghost where it was
                        item P = I; if (!bPlanOk) P.m_Color = IM_COL32(200, 70, 60, 255);
                        if (It->second->HasValue()) P.m_Value = It->second->m_NewValue;
                        DrawItem(D, A, P, It->second->m_New, Vr.m_Row.m_Color, true, false, i, nullptr);             // where it goes
                    }
                    else DrawItem(D, A, I, I.m_Seg, Vr.m_Row.m_Color, bSel, false, i, pHits);
                    ++S.m_nItemsDrawn;
                }
                Vr.m_pType->Overlay(Vr.m_Row, D, A);
            }
            D.PopClipRect();
            if (Vr.m_Row.m_bMute || (!Tr.m_Solo.empty() && !Tr.m_Solo.count(Vr.m_Row.m_Id))) D.AddRectFilled(A.m_Min, A.m_Max, IM_COL32(20, 20, 22, 140));
        }
        D.PopClipRect();

        // the header column, left to right: the row's colour, fold (the view's), the name (the grip to reorder; clipped, never covered),
        // the row type's widgets, then eye / solo / lock (eye and lock the document's, solo the transport's)
        constexpr float ToggleW = 22, Gap = 4;
        // Segoe MDL2: View, Hide, Headphone, Lock, Unlock
        static constexpr const char *EyeOn = "\xEE\xA2\x90", *EyeOff = "\xEE\xB4\x9A", *SoloIcon = "\xEE\x9F\xB6", *LockOn = "\xEE\x9C\xAE", *LockOff = "\xEE\x9E\x85";
        for (int i = First; i <= Last; ++i)
        {
            auto& Vr = Rows[i];
            const float y = S.m_Body.Min.y + float(i) * S.m_RowHeight - S.m_ScrollY;
            if (y + S.m_RowHeight > Whole.Max.y + 1) break;
            ImGui::PushID(static_cast<int>(Vr.m_Row.m_Id ^ (Vr.m_Row.m_Id >> 32)));
            D.AddRectFilled({ Whole.Min.x, y + 2 }, { Whole.Min.x + 3, y + S.m_RowHeight - 2 }, Vr.m_Row.m_Color);
            const bool  bToggles = Vr.m_pType && Vr.m_Row.m_bToggles;
            const float xToggles = S.m_Body.Min.x - (bToggles ? 3 * ToggleW + 6 : 0);
            const float wType    = Vr.m_pType ? std::min(Vr.m_pType->HeaderWidth(Vr.m_Row), std::max(0.0f, xToggles - Whole.Min.x - 90)) : 0;
            const float xType    = xToggles - wType - (wType > 0 ? Gap : 0);
            ImGui::SetCursorScreenPos({ Whole.Min.x + 8 + float(Vr.m_Row.m_Depth) * 14, y + 4 });
            if (Vr.m_Row.m_bHasChildren)
            {
                const bool bFolded = S.m_Folded.count(Vr.m_Row.m_Id) != 0;
                if (ImGui::ArrowButton("##fold", bFolded ? ImGuiDir_Right : ImGuiDir_Down)) { if (bFolded) S.m_Folded.erase(Vr.m_Row.m_Id); else S.m_Folded.insert(Vr.m_Row.m_Id); }
                ImGui::SameLine(0, 4);
            }
            const ImVec2 NamePos = ImGui::GetCursorScreenPos();
            const float  NameW   = std::max(10.0f, xType - Gap - NamePos.x);
            ImGui::InvisibleButton("##rowname", { NameW, S.m_RowHeight - 6 });
            const bool bNameHovered = ImGui::IsItemHovered();
            if (Doc.CanMoveRow(Vr.m_Row.m_Id) && !Vr.m_Row.m_bLock)
            {
                // the name is the grip: drag it up or down to reorder (the document decides what the order means)
                if (ImGui::IsItemActive() && std::abs(IO.MouseDragMaxDistanceSqr[0]) > 16.0f) S.m_DragRow = Vr.m_Row.m_Id;
                if (bNameHovered && !S.m_DragRow) ImGui::SetTooltip("%s\nDrag up or down to change the order", Vr.m_Row.m_Name.c_str());
            }
            else if (bNameHovered) ImGui::SetTooltip("%s", Vr.m_Row.m_Name.c_str());
            D.PushClipRect(NamePos, { NamePos.x + NameW, y + S.m_RowHeight }, true);
            D.AddText({ NamePos.x, y + (S.m_RowHeight - ImGui::GetTextLineHeight()) * 0.5f }, ImGui::GetColorU32(ImGuiCol_Text), Vr.m_Row.m_Name.c_str());
            D.PopClipRect();
            auto Toggle = [&](int Slot, const char* pId, const char* pIcon, const char* pTip, bool bOn, auto&& Fn)
            {
                ImGui::SetCursorScreenPos({ xToggles + 3 + float(Slot) * ToggleW, y + 3 });
                ImGui::PushStyleColor(ImGuiCol_Button, bOn ? IM_COL32(200, 150, 60, 255) : IM_COL32(52, 54, 60, 255));
                ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, { 2, 1 });
                ImGui::PushID(pId);
                if (ImGui::Button(pIcon, { ToggleW - 2, S.m_RowHeight - 6 })) Fn();
                ImGui::PopID();
                if (ImGui::IsItemHovered()) ImGui::SetTooltip("%s", pTip);
                ImGui::PopStyleVar(); ImGui::PopStyleColor();
            };
            if (Vr.m_pType)
            {
                if (wType > 0) Vr.m_pType->Header(Vr.m_Row, Doc, ImRect({ xType, y + 2 }, { xType + wType, y + S.m_RowHeight - 2 }));
            }
            if (bToggles)
            {
                Toggle(0, "eye", Vr.m_Row.m_bMute ? EyeOff : EyeOn, Vr.m_Row.m_bMute ? "Muted: click to play this row again (saved with the document)" : "Shown: click to mute this row (saved with the document)", Vr.m_Row.m_bMute
                      , [&] { S.m_Reply = Doc.SetRowFlag(Vr.m_Row.m_Id, row_flag::mute, !Vr.m_Row.m_bMute); });
                const bool bSolo = Tr.m_Solo.count(Vr.m_Row.m_Id) != 0;
                Toggle(1, "solo", SoloIcon, "Solo: hear/see only this row - an audition, never saved or compiled", bSolo, [&] { if (bSolo) Tr.m_Solo.erase(Vr.m_Row.m_Id); else Tr.m_Solo.insert(Vr.m_Row.m_Id); });
                Toggle(2, "lock", Vr.m_Row.m_bLock ? LockOn : LockOff, Vr.m_Row.m_bLock ? "Locked: no edits (click to unlock)" : "Unlocked (click to lock: no edits)", Vr.m_Row.m_bLock
                      , [&] { S.m_Reply = Doc.SetRowFlag(Vr.m_Row.m_Id, row_flag::lock, !Vr.m_Row.m_bLock); });
            }
            ImGui::PopID();
        }

        // the header column's edge: drag it to resize the column (the state keeps it; a narrow panel only borrows space for a frame)
        {
            ImGui::SetCursorScreenPos({ S.m_Body.Min.x - 3, Whole.Min.y });
            ImGui::InvisibleButton("##headeredge", { 6, Whole.GetHeight() });
            if (ImGui::IsItemHovered() || ImGui::IsItemActive()) { ImGui::SetMouseCursor(ImGuiMouseCursor_ResizeEW); D.AddLine({ S.m_Body.Min.x, Whole.Min.y }, { S.m_Body.Min.x, Whole.Max.y }, IM_COL32(110, 170, 255, 200), 2.0f); }
            if (ImGui::IsItemActive() && IO.MouseDelta.x != 0) HeaderWidth = std::clamp(S.m_HeaderWidth + IO.MouseDelta.x, 140.0f, std::max(140.0f, Whole.GetWidth() - 160));
        }

        // a row header dragged: the line where it would go; on release the document reorders (one command)
        if (S.m_DragRow)
        {
            const float yRel = M.y - S.m_Body.Min.y + S.m_ScrollY;
            const int i = std::clamp(int(std::floor(yRel / S.m_RowHeight + 0.5f)), 0, int(Rows.size()));      // the gap the row goes into
            const std::uint64_t Above = i < int(Rows.size()) ? Rows[i].m_Row.m_Id : 0;
            // over the middle half of a container row (a folder, a group): into it
            const int iOn = int(std::floor(yRel / S.m_RowHeight));
            const float Frac = yRel / S.m_RowHeight - float(iOn);
            const std::uint64_t Into = (iOn >= 0 && iOn < int(Rows.size()) && Frac > 0.25f && Frac < 0.75f && Rows[iOn].m_Row.m_Id != S.m_DragRow && Doc.CanDropInto(Rows[iOn].m_Row.m_Id)) ? Rows[iOn].m_Row.m_Id : 0;
            if (Into)
            {
                const float y0 = S.m_Body.Min.y + float(iOn) * S.m_RowHeight - S.m_ScrollY;
                D.AddRect({ Whole.Min.x + 1, y0 + 1 }, { Whole.Max.x - 1, y0 + S.m_RowHeight - 1 }, IM_COL32(255, 210, 90, 255), 3.0f, 0, 2.0f);
                ImGui::SetTooltip("Into '%s' (it then mixes as part of it)", Rows[iOn].m_Row.m_Name.c_str());
            }
            else
            {
                const float yLine = S.m_Body.Min.y + float(i) * S.m_RowHeight - S.m_ScrollY;
                D.AddLine({ Whole.Min.x, yLine }, { Whole.Max.x, yLine }, IM_COL32(255, 210, 90, 255), 2.0f);
                ImGui::SetTooltip("Move the row here (the order is the mix order: lower rows are under)");
            }
            if (ImGui::IsKeyPressed(ImGuiKey_Escape)) S.m_DragRow = 0;
            else if (!ImGui::IsMouseDown(ImGuiMouseButton_Left))
            {
                const std::uint64_t R = S.m_DragRow; S.m_DragRow = 0;
                if (Into) S.m_Reply = Doc.DropInto(R, Into);
                else if (Above != R) S.m_Reply = Doc.MoveRow(R, Above);
            }
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
                {
                    std::string Tip = std::format("{} {}\nDelta {:+.3f} s ({:+} f), {} item(s){}", Name(S.m_Handle), S.m_Snap.m_bSnapped ? std::format("snapped to the {} at {}", S.m_Snap.m_pWhat, Seconds(S.m_Snap.m_Target, V)) : std::string{},
                                                  double(S.m_Plan.m_Delta) / double(V.m_TPS), V.FrameIndex(double(S.m_Plan.m_Delta)), S.m_Plan.m_Entries.size(), bSnapOn ? "" : "\n(snap off)");
                    for (const auto& E : S.m_Plan.m_Entries) if (E.HasValue()) { Tip += std::format("\nvalue {:.2f} -> {:.2f}", E.m_OldValue, E.m_NewValue); break; }
                    for (const auto& C : S.m_Plan.m_Conflicts) Tip += "\nREFUSED: " + C;
                    ImGui::SetTooltip("%s", Tip.c_str());
                }
            }
        }

        ImGui::SetCursorScreenPos({ Whole.Min.x, Whole.Max.y });
        ImGui::Dummy({ 0, 0 });
        ImGui::PopID();
        S.m_HeaderWidth = HeaderWidth;      // the preferred width (a narrow panel only borrows it this frame)
        S.m_DrawMs = Ms(tDraw);
        return S.m_Reply;
    }
}
#endif
