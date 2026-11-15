#ifndef XEDITOR_TIMELINE_CORE_H
#define XEDITOR_TIMELINE_CORE_H
#pragma once
// xeditor::timeline - the pure part of the editor's timeline (xLION_Docs editor_timeline_framework_design_2026-11-15.md: T1, then T1b = the
// v2 contract). No ImGui, no data: tests build it alone (tests/test_timeline_core.cpp). The view and the interaction are xeditor_timeline.h.
//  - time: integer ticks of the HOST's time base (the animation documents: 6000 a second); the frame grid is a view setting, a rational
//    rate; frame times come from the grid INDEX (no drift), rounded once
//  - items: what a row shows, declared (segment, key, interval, marker) with a stable ref, capabilities and an optional aggregate of the
//    items it stands for; the core draws and picks them the same way for every row type
//  - the edit plan: a gesture's result computed from the ORIGINAL items (resolved new values, one common feasible delta, conflicts); the
//    document validates it and commits it once against the revision it was made from
//  - snapping (bounded search, hysteresis, a stable tie-break, the dragged items excluded), the marquee, key jumps, event crossings
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <format>
#include <limits>
#include <set>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace xeditor::timeline
{
    using tick = std::int64_t;                                  // document time, in the host's ticks
    inline constexpr tick animation_ticks_per_second_v = 6000;  // the animation documents' time base (divides 24, 25, 30, 50, 60 and 120 fps)

    //--------------------------------------------------------------------------------------------
    // The view: which ticks are on screen, at what zoom, on which frame grid. Data never moves when the grid changes.
    //--------------------------------------------------------------------------------------------
    struct view
    {
        double m_Left      = 0;                                 // the tick at the body's left edge
        double m_PxPerTick = 0.05;
        tick   m_TPS       = animation_ticks_per_second_v;      // the host's ticks per second
        tick   m_RateNum   = 30, m_RateDen = 1;                 // the frame grid: RateNum / RateDen frames a second (30000/1001 is fine)
        double m_Width     = 800;                               // the body's width in pixels (set every frame)

        double X(double T) const noexcept { return (T - m_Left) * m_PxPerTick; }
        double T(double X) const noexcept { return m_Left + X / m_PxPerTick; }
        double FPS() const noexcept { return double(m_RateNum) / double(std::max<tick>(1, m_RateDen)); }
        // frame I's time: computed from the index every time (stepping never accumulates rounding); rounded to the nearest tick, once
        tick   FrameTime(std::int64_t I) const noexcept
        {
            const long double T = (long double)I * (long double)m_TPS * (long double)m_RateDen / (long double)std::max<tick>(1, m_RateNum);
            return static_cast<tick>(std::llround((double)T));
        }
        std::int64_t FrameIndex(double T) const noexcept { return static_cast<std::int64_t>(std::llround(T * double(m_RateNum) / (double(m_TPS) * double(std::max<tick>(1, m_RateDen))))); }
        tick   SnapFrame(double T) const noexcept { return FrameTime(FrameIndex(T)); }
        tick   StepFrame(tick T, int Dir) const noexcept { return FrameTime(FrameIndex(double(T)) + Dir); }
        tick   FrameTicks() const noexcept { return std::max<tick>(1, FrameTime(1)); }          // a frame's length (approximate on fractional grids)

        void ZoomAt(double Xpx, double Factor, double MinPx = 1e-5, double MaxPx = 4.0) noexcept
        {
            const double At = T(Xpx);
            m_PxPerTick = std::clamp(m_PxPerTick * Factor, MinPx, MaxPx);
            m_Left = At - Xpx / m_PxPerTick;
        }
        void Pan(double Px) noexcept { m_Left -= Px / m_PxPerTick; }
        void Frame(tick A, tick B, double Margin = 0.05) noexcept
        {
            if (B <= A) { A -= m_TPS / 2; B = A + m_TPS; }
            const double Span = double(B - A);
            m_PxPerTick = std::clamp(m_Width / (Span * (1.0 + 2.0 * Margin)), 1e-5, 4.0);
            m_Left = double(A) - (m_Width / m_PxPerTick - Span) * 0.5;
        }
    };

    inline tick RulerStep(const view& V, double MinPx = 70) noexcept
    {
        const tick F = V.FrameTicks(), S = V.m_TPS;
        const tick Steps[] = { F, 2 * F, 5 * F, 10 * F, 15 * F, S, 2 * S, 5 * S, 10 * S, 15 * S, 30 * S, 60 * S, 120 * S, 300 * S, 600 * S, 1800 * S, 3600 * S };
        for (tick St : Steps) if (St > 0 && double(St) * V.m_PxPerTick >= MinPx) return St;
        return 3600 * S;
    }
    // "2s" on whole seconds, "2:15" (second:frame) between
    inline std::string Label(tick T, const view& V)
    {
        const tick S = V.m_TPS;
        const bool bNeg = T < 0; const tick A = bNeg ? -T : T;
        if (A % S == 0) return std::format("{}{}s", bNeg ? "-" : "", A / S);
        return std::format("{}{}:{:02}", bNeg ? "-" : "", A / S, V.FrameIndex(double(A % S)));
    }

    //--------------------------------------------------------------------------------------------
    // Items: declared by the row types, drawn and picked by the core
    //--------------------------------------------------------------------------------------------
    enum class handle : std::uint8_t { none, body, trim_start, trim_end, ease_in, ease_out, slip, key, custom };
    enum class item_kind : std::uint8_t { segment, key, interval, marker };

    namespace caps { enum : std::uint32_t { none = 0, move = 1, trim = 2, slip = 4, ease = 8, del = 16, duplicate = 32, overlap = 64, ripple = 128, all_segment = 1 | 2 | 4 | 8 | 16 | 32, all_key = 1 | 16 | 32 }; }

    struct item_ref
    {
        std::uint64_t m_Row = 0, m_Item = 0;
        bool operator==(const item_ref&) const noexcept = default;
        bool operator<(const item_ref& O) const noexcept { return m_Row != O.m_Row ? m_Row < O.m_Row : m_Item < O.m_Item; }
    };

    // A segment (or an interval: the same without source or eases). Offset: where the start is in its source (slip). SourceLength < 0: unlimited.
    struct segment
    {
        tick m_Start = 0, m_End = 0, m_Offset = 0, m_EaseIn = 0, m_EaseOut = 0, m_SourceLength = -1;
        bool operator==(const segment&) const noexcept = default;
    };

    struct item
    {
        item_ref                m_Ref;
        item_kind               m_Kind = item_kind::key;
        segment                 m_Seg;                      // segment / interval: the span; key / marker: m_Start (= m_End)
        std::uint32_t           m_Caps = caps::none;
        std::uint32_t           m_Color = 0;                // 0: the row's colour
        std::string             m_Label;
        std::uint32_t           m_Count = 1;                // > 1: an aggregate (a summary diamond, a pixel bin) standing for m_Represents
        std::vector<item_ref>   m_Represents;               // the real items behind an aggregate (selection and edits resolve to these)
        tick Time() const noexcept { return m_Seg.m_Start; }
    };

    // The one place a drag changes a segment: trims keep at least MinLength and never reveal past the source's ends (a start trim moves the
    // offset with it: the content stays put); slip moves the content under fixed edges; eases stay inside and never overlap.
    inline segment Drag(const segment& S, handle H, tick D, tick MinLength) noexcept
    {
        constexpr tick Lo = std::numeric_limits<tick>::min() / 4, Hi = std::numeric_limits<tick>::max() / 4;
        segment R = S;
        switch (H)
        {
        case handle::body: case handle::key: R.m_Start += D; R.m_End += D; break;
        case handle::trim_start:
        {
            const tick Min = S.m_SourceLength >= 0 ? S.m_Start - S.m_Offset : Lo;
            const tick NS = std::clamp(S.m_Start + D, Min, S.m_End - MinLength);
            R.m_Offset = S.m_Offset + (NS - S.m_Start); R.m_Start = NS;
            break;
        }
        case handle::trim_end:
        {
            const tick Max = S.m_SourceLength >= 0 ? S.m_Start + (S.m_SourceLength - S.m_Offset) : Hi;
            R.m_End = std::clamp(S.m_End + D, S.m_Start + MinLength, std::max(S.m_Start + MinLength, Max));
            break;
        }
        case handle::slip:
            R.m_Offset = S.m_SourceLength >= 0 ? std::clamp(S.m_Offset - D, tick(0), std::max(tick(0), S.m_SourceLength - (S.m_End - S.m_Start))) : S.m_Offset - D;
            break;
        case handle::ease_in:  R.m_EaseIn  = std::clamp(S.m_EaseIn + D,  tick(0), std::max(tick(0), (S.m_End - S.m_Start) - S.m_EaseOut)); break;
        case handle::ease_out: R.m_EaseOut = std::clamp(S.m_EaseOut - D, tick(0), std::max(tick(0), (S.m_End - S.m_Start) - S.m_EaseIn)); break;
        default: break;
        }
        const tick Len = R.m_End - R.m_Start;
        R.m_EaseIn = std::min(R.m_EaseIn, Len); R.m_EaseOut = std::min(R.m_EaseOut, Len - R.m_EaseIn);
        return R;
    }

    inline constexpr const char* handle_names_v[] = { "none", "move", "trim_start", "trim_end", "ease_in", "ease_out", "slip", "key", "custom" };
    inline const char* Name(handle H) noexcept { return handle_names_v[static_cast<int>(H)]; }

    // The capability a handle needs, and why it is refused
    inline std::uint32_t CapOf(handle H) noexcept
    {
        switch (H)
        {
        case handle::body: case handle::key: return caps::move;
        case handle::trim_start: case handle::trim_end: return caps::trim;
        case handle::slip: return caps::slip;
        case handle::ease_in: case handle::ease_out: return caps::ease;
        default: return caps::none;
        }
    }
    struct eligibility { bool m_bOk = true; std::string m_Reason; };
    // A mixed selection: every item must allow the operation; the first that does not says why
    inline eligibility Eligible(std::span<const item> Items, std::uint32_t Cap, std::string_view What)
    {
        for (const auto& I : Items)
            if ((I.m_Caps & Cap) == 0) return { false, std::format("{} is not possible on '{}' ({} {}:{})", What, I.m_Label.empty() ? "this item" : I.m_Label, I.m_Kind == item_kind::segment ? "segment" : I.m_Kind == item_kind::interval ? "interval" : I.m_Kind == item_kind::marker ? "marker" : "key", I.m_Ref.m_Row, I.m_Ref.m_Item) };
        return {};
    }

    //--------------------------------------------------------------------------------------------
    // The edit plan: from the ORIGINAL items (captured when the gesture began), what the gesture does - resolved values, never deltas
    // replayed against whatever is there later. One common delta for the whole selection (the most each item allows), so the
    // selection keeps its spacing. Conflicts (a capability missing, a locked row, a key landing on another key) make the plan invalid:
    // it is shown, never committed.
    //--------------------------------------------------------------------------------------------
    struct plan_entry
    {
        item_ref    m_Ref;
        item_kind   m_Kind = item_kind::key;
        segment     m_Old, m_New;
    };
    struct plan
    {
        handle                      m_Handle = handle::none;
        tick                        m_Delta = 0;            // the delta applied (after the common clamp)
        std::uint64_t               m_Revision = 0;         // the document revision the originals came from
        std::vector<plan_entry>     m_Entries;
        std::vector<std::string>    m_Conflicts;
        bool Valid() const noexcept { return m_Conflicts.empty() && !m_Entries.empty(); }
        bool NoOp() const noexcept { for (const auto& E : m_Entries) if (!(E.m_Old == E.m_New)) return false; return true; }
    };

    struct plan_inputs
    {
        std::span<const item>       m_Dragged;              // the original items moved (the real ones, aggregates already resolved)
        std::span<const item>       m_Others;               // the rest of the rows (collisions)
        std::set<std::uint64_t>     m_LockedRows;
        handle                      m_Handle = handle::none;
        tick                        m_Delta = 0;
        tick                        m_MinLength = 1;
        std::uint64_t               m_Revision = 0;
        bool                        m_bRejectKeyCollisions = true;
    };

    inline plan MakePlan(const plan_inputs& In)
    {
        plan P; P.m_Handle = In.m_Handle; P.m_Revision = In.m_Revision;
        if (In.m_Dragged.empty()) return P;
        const auto Cap = CapOf(In.m_Handle);
        if (Cap) if (auto E = Eligible(In.m_Dragged, Cap, Name(In.m_Handle)); !E.m_bOk) P.m_Conflicts.push_back(E.m_Reason);
        for (const auto& I : In.m_Dragged) if (In.m_LockedRows.count(I.m_Ref.m_Row)) { P.m_Conflicts.push_back(std::format("row {} is locked", I.m_Ref.m_Row)); break; }

        // the common feasible delta: each item clamps the delta its own way (a trim at its source end, an ease at its limit); take the
        // smallest in size, same direction, so every item moves by the same amount
        tick D = In.m_Delta;
        auto Moved = [&](const item& I, tick d) -> tick
        {
            const segment N = Drag(I.m_Seg, In.m_Handle, d, In.m_MinLength);
            switch (In.m_Handle)
            {
            case handle::trim_end:   return N.m_End - I.m_Seg.m_End;
            case handle::trim_start: return N.m_Start - I.m_Seg.m_Start;
            case handle::slip:       return I.m_Seg.m_Offset - N.m_Offset;
            case handle::ease_in:    return N.m_EaseIn - I.m_Seg.m_EaseIn;
            case handle::ease_out:   return I.m_Seg.m_EaseOut - N.m_EaseOut;
            default:                 return d;
            }
        };
        for (const auto& I : In.m_Dragged) { const tick m = Moved(I, D); if (std::abs(m) < std::abs(D)) D = m; }
        P.m_Delta = D;
        for (const auto& I : In.m_Dragged) P.m_Entries.push_back({ I.m_Ref, I.m_Kind, I.m_Seg, Drag(I.m_Seg, In.m_Handle, D, In.m_MinLength) });

        // a key moved onto another key of its row is refused (replace, merge and swap are explicit operations)
        if (In.m_bRejectKeyCollisions && (In.m_Handle == handle::key || In.m_Handle == handle::body))
        {
            std::set<item_ref> Moving; for (const auto& E : P.m_Entries) Moving.insert(E.m_Ref);
            for (const auto& E : P.m_Entries)
            {
                if (E.m_Kind != item_kind::key || E.m_Old == E.m_New) continue;
                for (const auto& O : In.m_Others)
                    if (O.m_Kind == item_kind::key && O.m_Ref.m_Row == E.m_Ref.m_Row && !Moving.count(O.m_Ref) && O.Time() == E.m_New.m_Start)
                    { P.m_Conflicts.push_back(std::format("the key would land on key {} at the same time (replace or merge it explicitly)", O.m_Ref.m_Item)); break; }
                for (const auto& O : P.m_Entries)
                    if (&O != &E && O.m_Kind == item_kind::key && O.m_Ref.m_Row == E.m_Ref.m_Row && O.m_New.m_Start == E.m_New.m_Start)
                    { P.m_Conflicts.push_back("two moved keys would land on the same time"); break; }
                if (!P.m_Conflicts.empty()) break;
            }
        }
        return P;
    }

    // "rev 7; seg 3 1 6600 12600 1000 600 600; key 4 2 9000": a plan as text - resolved ids and values (replaying it gives the same result
    // whatever the zoom, the snap settings or the selection are then)
    inline std::string ToText(const plan& P)
    {
        std::string S = std::format("rev {}", P.m_Revision);
        for (const auto& E : P.m_Entries)
        {
            if (E.m_Kind == item_kind::segment || E.m_Kind == item_kind::interval)
                S += std::format("; seg {} {} {} {} {} {} {}", E.m_Ref.m_Row, E.m_Ref.m_Item, E.m_New.m_Start, E.m_New.m_End, E.m_New.m_Offset, E.m_New.m_EaseIn, E.m_New.m_EaseOut);
            else S += std::format("; key {} {} {}", E.m_Ref.m_Row, E.m_Ref.m_Item, E.m_New.m_Start);
        }
        return S;
    }
    // Parses the text back (the document applies it): false on anything malformed
    struct text_op { char m_Kind = 0; item_ref m_Ref; segment m_Seg; };      // 's' segment, 'k' key
    inline bool FromText(std::string_view Text, std::uint64_t& Revision, std::vector<text_op>& Out)
    {
        Out.clear(); Revision = 0; bool bRev = false;
        while (!Text.empty())
        {
            const auto Semi = Text.find(';');
            std::string Part(Text.substr(0, Semi));
            Text = Semi == std::string_view::npos ? std::string_view{} : Text.substr(Semi + 1);
            if (std::all_of(Part.begin(), Part.end(), [](char c) { return c == ' '; })) continue;
            char Op[16] = {}; unsigned long long R = 0, I = 0; long long a = 0, b = 0, c = 0, d = 0, e = 0;
            const int n = std::sscanf(Part.c_str(), " %15s %llu %llu %lld %lld %lld %lld %lld", Op, &R, &I, &a, &b, &c, &d, &e);
            const std::string_view O(Op);
            if (O == "rev" && n == 2) { Revision = R; bRev = true; continue; }
            if (O == "seg" && n == 8) { Out.push_back({ 's', { R, I }, { a, b, c, d, e, -1 } }); continue; }
            if (O == "key" && n == 4) { Out.push_back({ 'k', { R, I }, { a, a, 0, 0, 0, -1 } }); continue; }
            return false;
        }
        return bRev && !Out.empty();
    }

    //--------------------------------------------------------------------------------------------
    // Snapping: the moving times and the points they may snap to (other items' edges and keys, the playhead, markers; the dragged items'
    // own excluded by the caller). Points sorted by time: only those within the radius are looked at. Ties: the nearer, then the earlier
    // time, then the earlier point in the list (stable). Hysteresis: a target kept while it stays within 1.5x the radius.
    //--------------------------------------------------------------------------------------------
    struct snap_point { tick m_Time = 0; const char* m_pWhat = ""; };
    struct snap_result
    {
        tick        m_Delta    = 0;
        bool        m_bSnapped = false;
        tick        m_Target   = 0;
        const char* m_pWhat    = "";
    };
    inline void SortPoints(std::vector<snap_point>& P) { std::stable_sort(P.begin(), P.end(), [](const snap_point& A, const snap_point& B) { return A.m_Time < B.m_Time; }); }
    inline snap_result SnapDelta(std::span<const tick> Moving, double Delta, std::span<const snap_point> Sorted, const view& V, double RadiusPx, bool bMagnet, bool bFrames, const snap_result* pPrev = nullptr) noexcept
    {
        snap_result R; R.m_Delta = static_cast<tick>(std::llround(Delta));
        if (!bMagnet) return R;
        const double Radius = RadiusPx / V.m_PxPerTick;
        // keep the previous target while it is still near
        if (pPrev && pPrev->m_bSnapped)
            for (tick M : Moving)
                if (std::abs(double(pPrev->m_Target - M) - Delta) < Radius * 1.5)
                { R.m_Delta = pPrev->m_Target - M; R.m_bSnapped = true; R.m_Target = pPrev->m_Target; R.m_pWhat = pPrev->m_pWhat; return R; }
        double Best = Radius;
        for (tick M : Moving)
        {
            const double Want = double(M) + Delta;
            auto It = std::lower_bound(Sorted.begin(), Sorted.end(), Want - Radius, [](const snap_point& P, double T) { return double(P.m_Time) < T; });
            for (; It != Sorted.end() && double(It->m_Time) <= Want + Radius; ++It)
            {
                const double Dist = std::abs(double(It->m_Time) - Want);
                if (Dist < Best || (R.m_bSnapped && Dist == Best && It->m_Time < R.m_Target))
                { Best = Dist; R.m_Delta = It->m_Time - M; R.m_bSnapped = true; R.m_Target = It->m_Time; R.m_pWhat = It->m_pWhat; }
            }
        }
        if (!R.m_bSnapped && bFrames && !Moving.empty()) R.m_Delta = V.SnapFrame(double(Moving[0]) + Delta) - Moving[0];
        return R;
    }

    //--------------------------------------------------------------------------------------------
    // Items as boxes (time span x row index): the marquee, framing the selection, key jumps
    //--------------------------------------------------------------------------------------------
    struct item_box { item_ref m_Ref; tick m_T0 = 0, m_T1 = 0; int m_Row = 0; };

    inline std::vector<item_ref> Marquee(std::span<const item_box> Items, tick A, tick B, int Row0, int Row1)
    {
        if (A > B) std::swap(A, B);
        if (Row0 > Row1) std::swap(Row0, Row1);
        std::vector<item_ref> Out;
        for (const auto& I : Items) if (I.m_Row >= Row0 && I.m_Row <= Row1 && I.m_T1 >= A && I.m_T0 <= B) Out.push_back(I.m_Ref);
        return Out;
    }
    inline tick JumpTo(std::span<const item_box> Items, tick Now, int Dir) noexcept
    {
        tick Best = Now; bool bFound = false;
        for (const auto& I : Items)
            for (tick T : { I.m_T0, I.m_T1 })
                if ((Dir > 0 ? T > Now : T < Now) && (!bFound || (Dir > 0 ? T < Best : T > Best))) { Best = T; bFound = true; }
        return Best;
    }

    // Many keys on few pixels: one aggregate per pixel bin (its count and the keys it stands for); the keys themselves never change
    inline void BinKeys(std::span<const std::pair<item_ref, tick>> Sorted, const view& V, double BinPx, std::uint64_t Row, std::uint32_t Caps, std::vector<item>& Out)
    {
        std::size_t i = 0;
        while (i < Sorted.size())
        {
            const double Bin = std::floor(V.X(double(Sorted[i].second)) / BinPx);
            std::size_t j = i;
            item A; A.m_Kind = item_kind::key; A.m_Ref = { Row, Sorted[i].first.m_Item }; A.m_Seg.m_Start = A.m_Seg.m_End = Sorted[i].second; A.m_Caps = Caps;
            while (j < Sorted.size() && std::floor(V.X(double(Sorted[j].second)) / BinPx) == Bin) { A.m_Represents.push_back(Sorted[j].first); ++j; }
            A.m_Count = std::uint32_t(j - i);
            if (A.m_Count == 1) A.m_Represents.clear();
            Out.push_back(std::move(A));
            i = j;
        }
    }

    //--------------------------------------------------------------------------------------------
    // Events: sampling is not dispatch. Playback (Advance) fires the events crossed: forward (Old, New], backward [New, Old). Drawing, a
    // seek, a scrub, cache warming never fire anything.
    //--------------------------------------------------------------------------------------------
    inline bool Crossed(tick T, tick Old, tick New) noexcept { return New >= Old ? (T > Old && T <= New) : (T >= New && T < Old); }
}
#endif
