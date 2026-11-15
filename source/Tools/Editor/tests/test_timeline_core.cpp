// The timeline core's pure parts (xeditor_timeline_core.h): tick <-> pixel at zooms, zoom at the cursor, framing, the ruler step, snapping,
// the drag math (moves, trims and their limits, slip, eases), the marquee, key jumps, the edit text round trip.
// Built alone: python -I xLION_Docs/tools/timeline_test.py
#include "../xeditor_timeline_core.h"
#include <cstdio>
using namespace xeditor::timeline;
static int g_Fails = 0;
static void Check(const char* N, bool Ok) { if (!Ok) { ++g_Fails; std::printf("FAIL %s\n", N); } }

int main()
{
    // mapping and zoom
    {
        view V; V.m_Left = 1000; V.m_PxPerTick = 0.05;
        bool Ok = true;
        for (double Z : { 0.0001, 0.003, 0.05, 1.0, 3.9 }) { V.m_PxPerTick = Z; for (double T : { -6000.0, 0.0, 1234.0, 600000.0 }) Ok = Ok && std::abs(V.T(V.X(T)) - T) < 1e-6 * std::max(1.0, std::abs(T)); }
        Check("tick -> pixel -> tick at every zoom", Ok);
        V.m_PxPerTick = 0.05; V.m_Left = 0;
        const double Under = V.T(250);
        V.ZoomAt(250, 2.0);
        Check("zoom at the cursor keeps the tick under it", std::abs(V.T(250) - Under) < 1e-6 && std::abs(V.m_PxPerTick - 0.1) < 1e-12);
        V.ZoomAt(0, 1e9); Check("zoom is clamped", V.m_PxPerTick <= 4.0);
        V.m_Width = 600; V.Frame(6000, 12000);
        Check("frame: the range is centred with its margin", std::abs(V.X(6000) - (600 - 6000 * V.m_PxPerTick) * 0.5) < 1e-6 && V.X(12000) < 600 && V.X(6000) > 0);
        V.m_FPS = 30; Check("a frame at 30 fps is 200 ticks", V.FrameTicks() == 200 && V.SnapFrame(299) == 200 && V.SnapFrame(301) == 400);
        V.m_FPS = 24; Check("24 fps: 250 ticks", V.FrameTicks() == 250);
    }
    // ruler
    {
        view V; V.m_FPS = 30;
        V.m_PxPerTick = 1.0;   Check("very close: one frame per label", RulerStep(V) == 200);
        V.m_PxPerTick = 0.05;  Check("300 px a second: labels every 10 frames (70 px)", RulerStep(V) == 2000);
        V.m_PxPerTick = 0.001; Check("6 px a second: labels every 15 s", RulerStep(V) == 15 * 6000);
        Check("labels", Label(12000, V) == "2s" && Label(12000 + 3 * 200, V) == "2:03" && Label(-6000, V) == "-1s");
    }
    // snapping
    {
        view V; V.m_PxPerTick = 0.05; V.m_FPS = 30;           // 8 px = 160 ticks
        const snap_point P[] = { { 6000, "key" }, { 9000, "playhead" } };
        const tick Moving[] = { 1000, 3000 };                 // a segment's two edges
        auto R = SnapDelta(Moving, 4950, P, V, 8, true, true);
        Check("snaps the closer edge (1000 + 4950 near 6000)", R.m_bSnapped && R.m_Delta == 5000 && R.m_Target == 6000);
        R = SnapDelta(Moving, 5950, P, V, 8, true, true);
        Check("snaps the end edge (3000 + 5950 near 9000)", R.m_bSnapped && R.m_Delta == 6000 && std::string(R.m_pWhat) == "playhead");
        R = SnapDelta(Moving, 4500, P, V, 8, true, true);
        Check("out of the radius: the frame grid", !R.m_bSnapped && (1000 + R.m_Delta) % 200 == 0 && std::abs(R.m_Delta - 4500) <= 100);
        R = SnapDelta(Moving, 4950, P, V, 8, false, true);
        Check("magnet off (or overridden): exact", !R.m_bSnapped && R.m_Delta == 4950);
    }
    // drag math
    {
        const tick F = 200;
        segment S{ 6000, 12000, 1000, 600, 600, 9000 };       // 1 s .. 2 s, the content from 1000 of a 9000-tick source
        Check("move", Drag(S, handle::body, 600, F) == segment{ 6600, 12600, 1000, 600, 600, 9000 });
        auto T = Drag(S, handle::trim_start, -400, F);
        Check("trim start left: the offset follows (the content stays put)", T.m_Start == 5600 && T.m_Offset == 600 && T.m_End == 12000);
        T = Drag(S, handle::trim_start, -5000, F);
        Check("trim start cannot reveal before the source", T.m_Start == 5000 && T.m_Offset == 0);
        T = Drag(S, handle::trim_start, 99999, F);
        Check("trim start keeps a frame", T.m_Start == 12000 - F && T.m_EaseIn + T.m_EaseOut <= F);
        T = Drag(S, handle::trim_end, 99999, F);
        Check("trim end stops at the source's end", T.m_End == 6000 + (9000 - 1000));
        T = Drag(S, handle::trim_end, -99999, F);
        Check("trim end keeps a frame", T.m_End == 6000 + F);
        T = Drag(S, handle::slip, 300, F);
        Check("slip right shows earlier content", T.m_Offset == 700 && T.m_Start == 6000 && T.m_End == 12000);
        T = Drag(S, handle::slip, -99999, F);
        Check("slip stops at the source's end", T.m_Offset == 9000 - 6000);
        T = Drag(S, handle::ease_in, 99999, F);
        Check("ease in stops at the ease out", T.m_EaseIn == 6000 - 600);
        T = Drag(S, handle::ease_out, 300, F);
        Check("ease out: dragging its handle right shortens it", T.m_EaseOut == 300);
        segment U{ 0, 1000, 0, 0, 0, -1 };
        Check("no source length: free trims", Drag(U, handle::trim_start, -5000, F).m_Start == -5000 && Drag(U, handle::trim_end, 5000, F).m_End == 6000);
    }
    // marquee and jumps
    {
        const item_box B[] = { { { 1, 1 }, 0, 1000, 0 }, { { 1, 2 }, 2000, 3000, 0 }, { { 2, 7 }, 1500, 1500, 1 }, { { 3, 9 }, 500, 2500, 2 } };
        auto M = Marquee(B, 900, 1600, 0, 1);
        Check("marquee: overlapping items of the rows inside", M.size() == 2 && M[0] == item_ref{ 1, 1 } && M[1] == item_ref{ 2, 7 });
        M = Marquee(B, 1600, 900, 2, 0);
        Check("marquee: reversed corners", M.size() == 3);
        Check("jump to the next edge or key", JumpTo(B, 1000, +1) == 1500 && JumpTo(B, 1500, -1) == 1000 && JumpTo(B, 3000, +1) == 3000);
    }
    // edit text
    {
        const edit E[] = { { handle::body, { 3, 1 }, 600 }, { handle::trim_end, { 18446744073709551615ull, 2 }, -300 }, { handle::key, { 4, 5 }, 0 } };
        const auto Text = ToText(std::span<const edit>(E));
        std::vector<edit> Back;
        Check("edit text round trip", FromText(Text, Back) && Back.size() == 3 && Back[0] == E[0] && Back[1] == E[1] && Back[2] == E[2]);
        Check("edit text form", Text.starts_with("move 3 1 600; trim_end 18446744073709551615 2 -300"));
        Check("bad edit text is refused", !FromText("teleport 1 2 3", Back) && !FromText("move 1 2", Back));
    }
    std::printf(g_Fails ? "%d FAILED\n" : "timeline core: all pass\n", g_Fails);
    return g_Fails;
}
