#ifndef XEDITOR_TIMELINE_CORE_H
#define XEDITOR_TIMELINE_CORE_H
#pragma once
// xeditor::timeline - the pure part of the editor's timeline (xLION_Docs editor_timeline_framework_design_2026-11-15.md, T1): time in
// ticks, the view's tick <-> pixel mapping and zoom, the ruler's label step, snapping, the drag math of segments and keys, the marquee and
// the text form of an edit. No ImGui, no data: tests build it alone (tests/test_timeline_core.cpp). The view and the interaction are
// xeditor_timeline.h; the data is always the document's (a row adapter), edited only through its commands.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <format>
#include <limits>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace xeditor::timeline
{
    using tick = std::int64_t;
    inline constexpr tick ticks_per_second_v = 6000;           // the layer contract's unit: divides 24, 25, 30, 50, 60 and 120 fps

    //--------------------------------------------------------------------------------------------
    // The view: which ticks are on screen. The frame rate is a view setting; data is in ticks and never moves when it changes.
    //--------------------------------------------------------------------------------------------
    struct view
    {
        double m_Left      = 0;         // the tick at the body's left edge
        double m_PxPerTick = 0.05;      // zoom (0.05: 300 px a second)
        double m_FPS       = 30;
        double m_Width     = 800;       // the body's width in pixels (the view sets it every frame)

        double X(double T) const noexcept { return (T - m_Left) * m_PxPerTick; }              // pixels from the body's left
        double T(double X) const noexcept { return m_Left + X / m_PxPerTick; }                // and back
        tick   FrameTicks() const noexcept { return std::max<tick>(1, static_cast<tick>(std::llround(ticks_per_second_v / std::max(1.0, m_FPS)))); }
        tick   SnapFrame(double T) const noexcept { const tick F = FrameTicks(); return static_cast<tick>(std::llround(T / double(F))) * F; }

        // zoom by Factor keeping the tick under pixel X where it is
        void ZoomAt(double Xpx, double Factor, double MinPx = 1e-4, double MaxPx = 4.0) noexcept
        {
            const double At = T(Xpx);
            m_PxPerTick = std::clamp(m_PxPerTick * Factor, MinPx, MaxPx);
            m_Left = At - Xpx / m_PxPerTick;
        }
        void Pan(double Px) noexcept { m_Left -= Px / m_PxPerTick; }
        // A..B on screen with a margin on both sides (an empty range: one second)
        void Frame(tick A, tick B, double Margin = 0.05) noexcept
        {
            if (B <= A) { A -= ticks_per_second_v / 2; B = A + ticks_per_second_v; }
            const double Span = double(B - A);
            m_PxPerTick = std::clamp(m_Width / (Span * (1.0 + 2.0 * Margin)), 1e-4, 4.0);
            m_Left = double(A) - (m_Width / m_PxPerTick - Span) * 0.5;
        }
    };

    // The ruler's label step: the smallest "nice" step (in frames below a second, in seconds above) whose labels are MinPx apart
    inline tick RulerStep(const view& V, double MinPx = 70) noexcept
    {
        const tick F = V.FrameTicks(), S = ticks_per_second_v;
        const tick Steps[] = { F, 2 * F, 5 * F, 10 * F, 15 * F, S, 2 * S, 5 * S, 10 * S, 15 * S, 30 * S, 60 * S, 120 * S, 300 * S, 600 * S, 1800 * S, 3600 * S };
        for (tick St : Steps) if (St > 0 && double(St) * V.m_PxPerTick >= MinPx) return St;
        return 3600 * S;
    }
    // "2s" on whole seconds, "2:15" (second:frame) between
    inline std::string Label(tick T, const view& V)
    {
        const tick S = ticks_per_second_v, F = V.FrameTicks();
        const bool bNeg = T < 0; const tick A = bNeg ? -T : T;
        if (A % S == 0) return std::format("{}{}s", bNeg ? "-" : "", A / S);
        return std::format("{}{}:{:02}", bNeg ? "-" : "", A / S, (A % S) / F);
    }

    //--------------------------------------------------------------------------------------------
    // Items, handles, edits
    //--------------------------------------------------------------------------------------------
    enum class handle : std::uint8_t { none, body, trim_start, trim_end, ease_in, ease_out, slip, key, custom };

    struct item_ref
    {
        std::uint64_t m_Row = 0, m_Item = 0;
        bool operator==(const item_ref&) const noexcept = default;
        bool operator<(const item_ref& O) const noexcept { return m_Row != O.m_Row ? m_Row < O.m_Row : m_Item < O.m_Item; }
    };

    // A segment as the drag math sees it. Offset: where the segment's start is in its source (slip). SourceLength < 0: unlimited.
    struct segment
    {
        tick m_Start = 0, m_End = 0, m_Offset = 0, m_EaseIn = 0, m_EaseOut = 0, m_SourceLength = -1;
        bool operator==(const segment&) const noexcept = default;
    };

    // The one place a drag changes a segment: the preview draws it and the commit sends the same delta. Trims keep at least MinLength
    // and never reveal past the source's ends; a trim of the start moves the offset with it (the content stays where it was); slip moves
    // the content under fixed edges (dragging right shows earlier content); eases stay inside the segment and never overlap.
    inline segment Drag(const segment& S, handle H, tick D, tick MinLength) noexcept
    {
        constexpr tick Lo = std::numeric_limits<tick>::min() / 4, Hi = std::numeric_limits<tick>::max() / 4;
        segment R = S;
        switch (H)
        {
        case handle::body: R.m_Start += D; R.m_End += D; break;
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
        const tick Len = R.m_End - R.m_Start;              // a trim shorter than the eases: the eases shrink with it
        R.m_EaseIn = std::min(R.m_EaseIn, Len); R.m_EaseOut = std::min(R.m_EaseOut, Len - R.m_EaseIn);
        return R;
    }

    // What a gesture asks the document to do: one per item touched; all of a gesture go to the document together (one command, one undo step)
    struct edit
    {
        handle   m_Handle = handle::none;
        item_ref m_Ref;
        tick     m_Delta = 0;
        bool operator==(const edit&) const noexcept = default;
    };

    inline constexpr const char* handle_names_v[] = { "none", "move", "trim_start", "trim_end", "ease_in", "ease_out", "slip", "key", "custom" };
    inline const char* Name(handle H) noexcept { return handle_names_v[static_cast<int>(H)]; }
    inline handle HandleFromName(std::string_view N) noexcept
    {
        for (int i = 0; i < int(std::size(handle_names_v)); ++i) if (N == handle_names_v[i]) return static_cast<handle>(i);
        return handle::none;
    }
    // "move 3 1 600": the stable text of one edit; a gesture is its edits joined by "; "
    inline std::string ToText(const edit& E) { return std::format("{} {} {} {}", Name(E.m_Handle), E.m_Ref.m_Row, E.m_Ref.m_Item, E.m_Delta); }
    inline std::string ToText(std::span<const edit> Edits)
    {
        std::string S;
        for (const auto& E : Edits) { if (!S.empty()) S += "; "; S += ToText(E); }
        return S;
    }
    inline bool FromText(std::string_view Text, std::vector<edit>& Out)
    {
        Out.clear();
        while (!Text.empty())
        {
            const auto Semi = Text.find(';');
            std::string Part(Text.substr(0, Semi));
            Text = Semi == std::string_view::npos ? std::string_view{} : Text.substr(Semi + 1);
            char Op[32] = {}; unsigned long long R = 0, I = 0; long long D = 0;
            if (std::all_of(Part.begin(), Part.end(), [](char c) { return c == ' '; })) continue;
            if (std::sscanf(Part.c_str(), " %31s %llu %llu %lld", Op, &R, &I, &D) != 4) return false;
            const auto H = HandleFromName(Op);
            if (H == handle::none) return false;
            Out.push_back({ H, { R, I }, D });
        }
        return !Out.empty();
    }

    //--------------------------------------------------------------------------------------------
    // Snapping: a moving set of times (a segment's edges, keys) and the points they can snap to (other items' edges and keys, the
    // playhead, markers - every row type gives its own), within RadiusPx; else the frame grid (when on); off: whole ticks.
    //--------------------------------------------------------------------------------------------
    struct snap_point { tick m_Time = 0; const char* m_pWhat = ""; };
    struct snap_result
    {
        tick        m_Delta    = 0;
        bool        m_bSnapped = false;      // to a point (not just the frame grid)
        tick        m_Target   = 0;          // the point snapped to
        const char* m_pWhat    = "";
    };
    inline snap_result SnapDelta(std::span<const tick> Moving, double Delta, std::span<const snap_point> Points, const view& V, double RadiusPx, bool bMagnet, bool bFrames) noexcept
    {
        snap_result R; R.m_Delta = static_cast<tick>(std::llround(Delta));
        if (!bMagnet) return R;
        double Best = RadiusPx / V.m_PxPerTick;      // ticks
        for (tick M : Moving)
            for (const auto& P : Points)
            {
                const double Want = double(P.m_Time - M);
                if (std::abs(Want - Delta) < Best) { Best = std::abs(Want - Delta); R.m_Delta = P.m_Time - M; R.m_bSnapped = true; R.m_Target = P.m_Time; R.m_pWhat = P.m_pWhat; }
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
    // the next (Dir > 0) or previous key or edge from Now; Now itself when there is none
    inline tick JumpTo(std::span<const item_box> Items, tick Now, int Dir) noexcept
    {
        tick Best = Now; bool bFound = false;
        for (const auto& I : Items)
            for (tick T : { I.m_T0, I.m_T1 })
                if ((Dir > 0 ? T > Now : T < Now) && (!bFound || (Dir > 0 ? T < Best : T > Best))) { Best = T; bFound = true; }
        return Best;
    }
}
#endif
