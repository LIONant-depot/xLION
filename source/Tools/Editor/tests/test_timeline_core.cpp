// The timeline core's pure parts (xeditor_timeline_core.h, T1 + T1b): the time base and the frame grid (exact rates, fractional grids
// without drift, negative and large times), mapping and zoom, the ruler, snapping (bounded, tie-break, hysteresis), the drag math, the
// edit plan (common feasible delta, capabilities, locks, key collisions, no-op, the text form, zoom and fps independence), aggregates,
// event crossings, the marquee and key jumps. Ids in brackets: research/timeline_test_matrix_2026-11-15.md.
// Built alone: python -I xLION_Docs/tools/timeline_test.py
#include "../xeditor_timeline_core.h"
#include <cstdio>
using namespace xeditor::timeline;
static int g_Fails = 0;
static void Check(const char* N, bool Ok) { if (!Ok) { ++g_Fails; std::printf("FAIL %s\n", N); } }

static item Seg(std::uint64_t r, std::uint64_t i, segment S, std::uint32_t C = caps::all_segment) { item I; I.m_Ref = { r, i }; I.m_Kind = item_kind::segment; I.m_Seg = S; I.m_Caps = C; I.m_Label = "seg"; return I; }
static item Key(std::uint64_t r, std::uint64_t i, tick t, std::uint32_t C = caps::all_key) { item I; I.m_Ref = { r, i }; I.m_Kind = item_kind::key; I.m_Seg = { t, t }; I.m_Caps = C; I.m_Label = "key"; return I; }

int main()
{
    // [TL-012] whole rates are exact at 6000 ticks a second; [TL-013] a fractional grid stepped 100 000 times does not drift
    {
        view V;
        bool Exact = true;
        for (auto [n, t] : { std::pair{ 24, 250 }, { 25, 240 }, { 30, 200 }, { 50, 120 }, { 60, 100 }, { 120, 50 } })
        { V.m_RateNum = n; V.m_RateDen = 1; for (std::int64_t f : { 1, 7, 1000, 123456 }) Exact = Exact && V.FrameTime(f) == f * t && V.FrameIndex(double(f * t)) == f; }
        Check("[TL-012] 24/25/30/50/60/120 fps frames are exact ticks", Exact);
        V.m_RateNum = 30000; V.m_RateDen = 1001;
        tick T = 0; bool NoDrift = true;
        for (int i = 1; i <= 100000; ++i) { T = V.StepFrame(T, +1); NoDrift = NoDrift && T == V.FrameTime(i); }
        Check("[TL-013] 29.97 fps: 100 000 steps land on the grid index, no drift", NoDrift && std::llabs(T - (tick)std::llround(100000.0 * 6000 * 1001 / 30000)) <= 0);
        Check("[TL-013] and a frame is ~200.2 ticks (rounded once, per index)", V.FrameTime(5) == 1001 && V.FrameTime(1) == 200);
        // [TL-011] the grid is the view's: the stored ticks do not depend on it (a plan built at 24 and at 60 fps writes the same values)
        item K = Key(1, 1, 1234); plan_inputs In; In.m_Dragged = std::span<const item>(&K, 1); In.m_Handle = handle::key; In.m_Delta = 500; In.m_MinLength = 200;
        const auto A = ToText(MakePlan(In)); V.m_RateNum = 60; V.m_RateDen = 1; In.m_MinLength = V.FrameTicks();
        Check("[TL-011] changing the display rate does not change what a plan stores", ToText(MakePlan(In)) == A);
    }
    // [TL-016] negative pre-roll and large times stay ordered and exact
    {
        view V; V.m_RateNum = 30;
        bool Ok = true; tick Prev = std::numeric_limits<tick>::min();
        for (std::int64_t f = -300; f <= 300; ++f) { const tick T = V.FrameTime(f); Ok = Ok && T > Prev && V.FrameIndex(double(T)) == f; Prev = T; }
        const std::int64_t Big = 3600LL * 24 * 30 * 30;     // a month of frames
        Ok = Ok && V.FrameTime(Big) == Big * 200 && V.FrameIndex(double(Big * 200)) == Big;
        Check("[TL-016] negative and large frame times: ordered, exact", Ok);
        V.m_Left = -1.0e9; V.m_PxPerTick = 0.05;
        Check("[TL-016] mapping far from zero round-trips", std::abs(V.T(V.X(-1.0e9 + 123)) - (-1.0e9 + 123)) < 1e-3);
    }
    // mapping, zoom, framing
    {
        view V; V.m_PxPerTick = 0.05;
        const double Under = V.T(250); V.ZoomAt(250, 2.0);
        Check("zoom at the cursor keeps the tick under it", std::abs(V.T(250) - Under) < 1e-6 && std::abs(V.m_PxPerTick - 0.1) < 1e-12);
        V.m_Width = 600; V.Frame(6000, 12000);
        Check("frame: the range centred with its margin", V.X(12000) < 600 && V.X(6000) > 0);
        V.m_RateNum = 30; Check("a 30 fps frame is 200 ticks; snap to the nearest", V.FrameTicks() == 200 && V.SnapFrame(299) == 200 && V.SnapFrame(301) == 400);
        V.m_TPS = 48000; Check("another host time base (48 000 a second): 1600 ticks a frame", V.FrameTicks() == 1600);
    }
    // ruler
    {
        view V; V.m_RateNum = 30;
        V.m_PxPerTick = 1.0;   Check("very close: one frame per label", RulerStep(V) == 200);
        V.m_PxPerTick = 0.05;  Check("300 px a second: labels every 10 frames", RulerStep(V) == 2000);
        Check("labels", Label(12000, V) == "2s" && Label(12000 + 3 * 200, V) == "2:03" && Label(-6000, V) == "-1s");
    }
    // snapping
    {
        view V; V.m_PxPerTick = 0.05; V.m_RateNum = 30;            // 8 px = 160 ticks
        std::vector<snap_point> P = { { 9000, "playhead" }, { 6000, "key" }, { 6100, "edge" } };
        SortPoints(P);
        const tick Moving[] = { 1000, 3000 };
        auto R = SnapDelta(Moving, 4990, P, V, 8, true, true);
        Check("snaps the nearest point (5990 -> 6000)", R.m_bSnapped && R.m_Target == 6000);
        R = SnapDelta(Moving, 5050, P, V, 8, true, true);
        Check("[TL-051] a tie (6050 between 6000 and 6100) goes to the earlier time", R.m_bSnapped && R.m_Target == 6000);
        R = SnapDelta(Moving, 5080, P, V, 8, true, true);
        Check("6080: the nearer (6100)", R.m_Target == 6100);
        const auto Held = SnapDelta(Moving, 5080, P, V, 8, true, true, &R);
        const snap_result Was6000{ 5000, true, 6000, "key" };
        Check("[TL-051] hysteresis: a target kept while within 1.5x the radius", SnapDelta(Moving, 5080, P, V, 8, true, true, &Was6000).m_Target == 6000 && Held.m_Target == 6100);
        R = SnapDelta(Moving, 4500, P, V, 8, true, true);
        Check("out of reach: the frame grid", !R.m_bSnapped && (1000 + R.m_Delta) % 200 == 0);
        Check("magnet off: exact", !SnapDelta(Moving, 4990, P, V, 8, false, true).m_bSnapped);
        // [TL-052] the caller leaves the dragged item's own points out: without them nothing pulls it back to where it was
        std::vector<snap_point> Self = { { 1000, "edge" } };
        Check("[TL-052] with its own old edge in the list it would stick; the view excludes it", SnapDelta(Moving, 60, Self, V, 8, true, true).m_bSnapped);
        // bounded search: 200 000 points, still found
        std::vector<snap_point> Many; for (int i = 0; i < 200000; ++i) Many.push_back({ tick(i) * 37, "key" });
        SortPoints(Many);
        const tick One[] = { 0 };
        R = SnapDelta(One, 37.0 * 150000 + 3, Many, V, 8, true, true);
        Check("bounded snap search in 200 000 points", R.m_bSnapped && R.m_Target == 37 * 150000);
    }
    // drag math
    {
        const tick F = 200;
        segment S{ 6000, 12000, 1000, 600, 600, 9000 };
        Check("move", Drag(S, handle::body, 600, F) == segment{ 6600, 12600, 1000, 600, 600, 9000 });
        auto T = Drag(S, handle::trim_start, -5000, F); Check("trim start stops at the source's start", T.m_Start == 5000 && T.m_Offset == 0);
        T = Drag(S, handle::trim_end, 99999, F);       Check("trim end stops at the source's end", T.m_End == 6000 + (9000 - 1000));
        T = Drag(S, handle::slip, 300, F);             Check("slip right shows earlier content", T.m_Offset == 700 && T.m_Start == 6000);
        T = Drag(S, handle::ease_in, 99999, F);        Check("ease in stops at the ease out", T.m_EaseIn == 6000 - 600);
    }
    // the edit plan
    {
        // [TL-038] two segments trimmed together: one common delta (the shorter source limits both) keeps them alike
        const item A = Seg(1, 1, { 0, 6000, 0, 0, 0, 7000 }), B = Seg(1, 2, { 10000, 16000, 0, 0, 0, 12000 });
        const item Two[] = { A, B };
        plan_inputs In; In.m_Dragged = Two; In.m_Handle = handle::trim_end; In.m_Delta = 3000; In.m_MinLength = 200; In.m_Revision = 7;
        auto P = MakePlan(In);
        Check("[TL-038] a multi-selection trim: one common feasible delta (1000, the shorter source)", P.Valid() && P.m_Delta == 1000 && P.m_Entries[0].m_New.m_End == 7000 && P.m_Entries[1].m_New.m_End == 17000);
        // [TL-006] an operation an item does not allow: refused, with the reason
        const item Ev = [] { item I = Seg(2, 5, { 0, 600 }, caps::move | caps::trim); I.m_Kind = item_kind::interval; I.m_Label = "Footstep"; return I; }();
        const item Mixed[] = { A, Ev };
        In.m_Dragged = Mixed; In.m_Handle = handle::slip; In.m_Delta = 100;
        P = MakePlan(In);
        Check("[TL-006] slip on a mixed selection with an event interval: refused, the reason names it", !P.Valid() && !P.m_Conflicts.empty() && P.m_Conflicts[0].find("Footstep") != std::string::npos);
        // a locked row
        In.m_Dragged = std::span<const item>(&A, 1); In.m_Handle = handle::body; In.m_LockedRows = { 1 };
        Check("a locked row: refused", !MakePlan(In).Valid());
        In.m_LockedRows.clear();
        // key collision: refused visibly; [TL-024] the whole batch with it
        const item K1 = Key(3, 1, 1000), K2 = Key(3, 2, 2000), K3 = Key(3, 3, 5000);
        const item Moving[] = { K1, K3 }; const item Rest[] = { K2 };
        In.m_Dragged = Moving; In.m_Others = Rest; In.m_Handle = handle::key; In.m_Delta = 1000;
        P = MakePlan(In);
        Check("a key dropped on another key is refused", !P.Valid() && P.m_Conflicts[0].find("land on key 2") != std::string::npos);
        Check("[TL-024] the whole batch with it (both keys stay)", !P.Valid() && P.m_Entries.size() == 2);
        In.m_Delta = 1100; P = MakePlan(In);
        Check("next to it: fine", P.Valid());
        // [TL-023] a no-op
        In.m_Delta = 0; Check("[TL-023] a zero drag is a no-op plan", MakePlan(In).NoOp());
        // [TL-027] the text: resolved values and the revision, read back the same
        In.m_Delta = 1100; In.m_Revision = 42; P = MakePlan(In);
        std::uint64_t Rev = 0; std::vector<text_op> Ops;
        Check("[TL-027] plan text round trip (revision, resolved times)", FromText(ToText(P), Rev, Ops) && Rev == 42 && Ops.size() == 2 && Ops[0].m_Kind == 'k' && Ops[0].m_Seg.m_Start == 2100 && Ops[1].m_Seg.m_Start == 6100);
        Check("[TL-027] segment entries carry every resolved field", FromText("rev 3; seg 1 2 10 20 3 4 5", Rev, Ops) && Ops[0].m_Seg == segment{ 10, 20, 3, 4, 5, -1 });
        Check("bad text is refused", !FromText("teleport 1 2 3", Rev, Ops) && !FromText("seg 1 2 3", Rev, Ops) && !FromText("key 1 2 3", Rev, Ops));
        // [TL-054] the plan does not depend on the zoom: the same intent at two zooms writes the same values
        view V1; V1.m_PxPerTick = 0.01; view V2; V2.m_PxPerTick = 2.0;
        const tick Mv[] = { 1000 }; std::vector<snap_point> None;
        const auto D1 = SnapDelta(Mv, 1100, None, V1, 8, false, false), D2 = SnapDelta(Mv, 1100, None, V2, 8, false, false);
        In.m_Delta = D1.m_Delta; const auto T1 = ToText(MakePlan(In)); In.m_Delta = D2.m_Delta;
        Check("[TL-054] the same edit at two zooms: the same plan", T1 == ToText(MakePlan(In)));
    }
    // [TL-044] aggregates: many keys on few pixels become bins with counts; the keys they stand for are the real ids, at any zoom
    {
        std::vector<std::pair<item_ref, tick>> K; for (int i = 0; i < 1000; ++i) K.push_back({ { 9, std::uint64_t(i + 1) }, tick(i * 10) });
        view V; V.m_PxPerTick = 0.01;                 // 1000 keys over 100 px
        std::vector<item> Out; BinKeys(K, V, 4.0, 9, caps::none, Out);
        std::size_t Total = 0; bool Ids = true;
        for (const auto& I : Out) { Total += I.m_Count; if (I.m_Count > 1) for (const auto& r : I.m_Represents) Ids = Ids && r.m_Row == 9 && r.m_Item >= 1 && r.m_Item <= 1000; }
        Check("[TL-044] binned: every key counted once, by its real id", Total == 1000 && Ids && Out.size() < 40);
        V.m_PxPerTick = 1.0; Out.clear(); BinKeys(K, V, 4.0, 9, caps::none, Out);
        Check("[TL-044] zoomed in: one item per key", Out.size() == 1000 && Out[17].m_Ref.m_Item == 18);
    }
    // [TL-004] events: crossings forward (old, new], backward [new, old); a seek is not a crossing (the caller never calls it for seeks)
    {
        Check("forward crossing includes the end, not the start", Crossed(1000, 999, 1000) && !Crossed(999, 999, 1000) && !Crossed(1001, 999, 1000));
        Check("backward crossing includes the end, not the start", Crossed(999, 1000, 999) && !Crossed(1000, 1000, 999));
        int n = 0; for (tick t = 0; t < 6000; t += 200) n += Crossed(3000, t, t + 200);
        Check("stepping forward frame by frame fires an event once", n == 1);
    }
    // marquee and jumps
    {
        const item_box B[] = { { { 1, 1 }, 0, 1000, 0 }, { { 1, 2 }, 2000, 3000, 0 }, { { 2, 7 }, 1500, 1500, 1 }, { { 3, 9 }, 500, 2500, 2 } };
        Check("marquee across rows", Marquee(B, 900, 1600, 0, 1).size() == 2 && Marquee(B, 1600, 900, 2, 0).size() == 3);
        Check("jump to the next edge or key", JumpTo(B, 1000, +1) == 1500 && JumpTo(B, 1500, -1) == 1000 && JumpTo(B, 3000, +1) == 3000);
    }
    std::printf(g_Fails ? "%d FAILED\n" : "timeline core: all pass\n", g_Fails);
    return g_Fails;
}
