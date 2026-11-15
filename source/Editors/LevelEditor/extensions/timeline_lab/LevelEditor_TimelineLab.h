#ifndef LEVELEDITOR_TIMELINE_LAB_H
#define LEVELEDITOR_TIMELINE_LAB_H
#pragma once
// The Timeline Lab: the editor timeline's core (source/Tools/Editor/xeditor_timeline.h; xLION_Docs editor_timeline_framework_design T1 + T1b)
// on a small fake document, to try it and to drive it from tests. The document is plain data with a revision; every edit is ONE undoable
// command (TimelineLabEdit: the whole document before and after), made by a drag (an edit plan) or typed in the console.
//      TimelineLab -Show true | -Reset | -Time s | -Play s       (-Play: the transport plays s seconds: events crossed are dispatched)
//      TimelineLab                                               the document, revision, dirty, dispatches, selection, layout, timings
//      TimelineLabEdit -Ops "rev 3; seg 2 1 600 12600 0 1500 1500; key 4 2 9000"   a plan's text (resolved values, the revision it
//          was made from); also "delete r i", "dup r i", "marker t name", "flag r mute|lock 0|1", "range a b" (ticks: 6000 a second)
// Rows: a group (a summary of its children: dragging a summary item moves the child's), segments, keys, events (points and intervals:
// move and trim only), a dense row (200 000 generated keys: queries by window, pixel-bin aggregates; read only) and a row of a type no
// one registered (a read-only placeholder; its data survives save and load). Not the animation layers: those are T2.
#include "source/Tools/Editor/xeditor_timeline.h"
#include "dependencies/xeditor/include/xeditor/serialize.h"
#include <sstream>

namespace level_editor::timeline_lab
{
    namespace tl = xeditor::timeline;
    inline constexpr tl::tick tps_v = tl::animation_ticks_per_second_v;

    enum kind : int { group = 0, segments = 1, keys = 2, dense = 3, events = 4, unknown = 9 };

    struct lab_row
    {
        std::uint64_t m_Id = 0, m_Parent = 0;          // 0: top level
        int           m_Kind = 0;
        std::string   m_Name;
        bool          m_bMute = false, m_bLock = false;
        std::vector<std::pair<std::uint64_t, tl::segment>> m_Segments;      // segments; events' intervals; the unknown row's payload
        std::vector<std::pair<std::uint64_t, tl::tick>>    m_Keys;          // keys; events' points
        std::int64_t  m_DenseCount = 0, m_DenseStep = 0;                     // dense: key i at i * step (+ a jitter under 13 ticks: sorted when step > 12), ids i + 1
        tl::tick DenseKey(std::int64_t i) const noexcept { return i * m_DenseStep + (i * 7919 % 13); }
    };
    struct lab_doc
    {
        std::vector<lab_row>    m_Rows;                // pre-order: a child after its parent
        std::vector<tl::marker> m_Markers;
        tl::tick                m_RangeA = 0, m_RangeB = 4 * tps_v;
        std::uint64_t           m_NextId = 100;
        std::uint64_t           m_Revision = 1;        // identifies this content: a new edit takes a new number, an undo restores the old one

        lab_row* Row(std::uint64_t Id) noexcept { for (auto& R : m_Rows) if (R.m_Id == Id) return &R; return nullptr; }
    };

    inline lab_doc Sample()
    {
        constexpr tl::tick S = tps_v;
        lab_doc D;
        lab_row G{ .m_Id = 1, .m_Kind = group, .m_Name = "Body" };
        lab_row A{ .m_Id = 2, .m_Parent = 1, .m_Kind = segments, .m_Name = "Walk" };
        A.m_Segments = { { 1, { 0, 2 * S, 0, S / 4, S / 4, 6 * S } }, { 2, { 2 * S + S / 2, 4 * S, S, S / 5, 0, 6 * S } } };
        lab_row B{ .m_Id = 3, .m_Parent = 1, .m_Kind = segments, .m_Name = "Wave left arm" };
        B.m_Segments = { { 1, { S, 3 * S, 0, S / 3, S / 3, 3 * S } } };
        lab_row K{ .m_Id = 4, .m_Kind = keys, .m_Name = "Pose keys" };
        K.m_Keys = { { 1, S / 2 }, { 2, S + S / 2 }, { 3, 3 * S } };
        lab_row E{ .m_Id = 5, .m_Kind = events, .m_Name = "Events" };
        E.m_Keys = { { 1, S }, { 2, 2 * S + S / 3 } };
        E.m_Segments = { { 3, { 3 * S, 3 * S + S / 2, 0, 0, 0, -1 } } };
        lab_row X{ .m_Id = 6, .m_Kind = dense, .m_Name = "Dense (200k keys)", .m_DenseCount = 200000, .m_DenseStep = 15 };    // 200k keys over 500 s, irregular but sorted (BinKeys needs them sorted)
        lab_row U{ .m_Id = 7, .m_Kind = unknown, .m_Name = "Plugin row (missing type)" };
        U.m_Segments = { { 1, { S / 2, S + S / 2, 0, 0, 0, -1 } } };
        D.m_Rows = { G, A, B, K, E, X, U };
        D.m_Markers = { { 1, 2 * S, "contact" } };
        return D;
    }

    // the whole document as text (an undo step's before and after; also what a save would write) and back
    inline std::string Save(const lab_doc& D)
    {
        std::string T = std::format("range {} {} {}\nrev {}\n", D.m_RangeA, D.m_RangeB, D.m_NextId, D.m_Revision);
        for (const auto& M : D.m_Markers) T += std::format("marker {} {} {}\n", M.m_Id, M.m_Time, M.m_Name);
        for (const auto& R : D.m_Rows)
        {
            T += std::format("row {} {} {} {} {} {}\n", R.m_Id, R.m_Parent, R.m_Kind, int(R.m_bMute), int(R.m_bLock), R.m_Name);
            if (R.m_Kind == dense) T += std::format("dense {} {}\n", R.m_DenseCount, R.m_DenseStep);
            for (const auto& [Id, S] : R.m_Segments) T += std::format("seg {} {} {} {} {} {} {}\n", Id, S.m_Start, S.m_End, S.m_Offset, S.m_EaseIn, S.m_EaseOut, S.m_SourceLength);
            for (const auto& [Id, K] : R.m_Keys) T += std::format("key {} {}\n", Id, K);
        }
        return T;
    }
    inline bool Load(lab_doc& D, const std::string& Text)
    {
        lab_doc N; std::istringstream In(Text); std::string Line;
        while (std::getline(In, Line))
        {
            std::istringstream L(Line); std::string W; L >> W;
            if (W == "range") L >> N.m_RangeA >> N.m_RangeB >> N.m_NextId;
            else if (W == "rev") L >> N.m_Revision;
            else if (W == "marker") { tl::marker M; L >> M.m_Id >> M.m_Time; std::getline(L >> std::ws, M.m_Name); N.m_Markers.push_back(M); }
            else if (W == "row")
            {
                lab_row R; int m, l; L >> R.m_Id >> R.m_Parent >> R.m_Kind >> m >> l; std::getline(L >> std::ws, R.m_Name);
                R.m_bMute = m; R.m_bLock = l; N.m_Rows.push_back(R);
            }
            else if (W == "dense" && !N.m_Rows.empty()) L >> N.m_Rows.back().m_DenseCount >> N.m_Rows.back().m_DenseStep;
            else if (W == "seg" && !N.m_Rows.empty()) { std::uint64_t Id; tl::segment S; L >> Id >> S.m_Start >> S.m_End >> S.m_Offset >> S.m_EaseIn >> S.m_EaseOut >> S.m_SourceLength; N.m_Rows.back().m_Segments.push_back({ Id, S }); }
            else if (W == "key" && !N.m_Rows.empty()) { std::uint64_t Id; tl::tick K; L >> Id >> K; N.m_Rows.back().m_Keys.push_back({ Id, K }); }
            else if (!W.empty()) return false;
        }
        D = std::move(N);
        return true;
    }

    struct lab_state
    {
        lab_doc             m_Doc = Sample();
        std::uint64_t       m_RevCounter = 1;           // revisions handed out (unique: a revision names one content)
        bool                m_bDirty = false;           // only edits make it dirty (scrub, fold, zoom, selection never)
        std::int64_t        m_nDispatched = 0, m_nSeeks = 0;
        tl::transport       m_Transport;
        tl::state           m_View;
        bool                m_bVisible = false;
        xundo::system*      m_pUndo = nullptr;
        std::string         m_LastSelection;
    };
    inline lab_state& State() noexcept { static lab_state s_State; return s_State; }

    // The document's own validation of a plan (the core already checked capabilities, locks and key collisions)
    inline std::string ValidateOps(lab_doc& D, std::uint64_t Revision, std::uint64_t Now, std::span<const tl::text_op> Ops)
    {
        if (Revision != Now) return std::format("stale plan: made at revision {}, the document is at {}", Revision, Now);
        for (const auto& O : Ops)
        {
            lab_row* pR = D.Row(O.m_Ref.m_Row);
            if (!pR) return std::format("no row {}", O.m_Ref.m_Row);
            if (pR->m_bLock) return std::format("row '{}' is locked", pR->m_Name);
            if (pR->m_Kind == unknown) return std::format("row '{}': its type is unknown, read only", pR->m_Name);
            if (pR->m_Kind == dense || pR->m_Kind == group) return std::format("row '{}' is read only", pR->m_Name);
            if (pR->m_Kind == events && O.m_Seg.m_Start < 0) return "events cannot be before 0";
            if (O.m_Kind == 's' && O.m_Seg.m_End <= O.m_Seg.m_Start) return "a segment needs a length";
            if (O.m_Kind == 'k')
                for (const auto& [Id, K] : pR->m_Keys)
                    if (Id != O.m_Ref.m_Item && K == O.m_Seg.m_Start && std::none_of(Ops.begin(), Ops.end(), [&](const tl::text_op& o) { return o.m_Ref == tl::item_ref{ pR->m_Id, Id }; }))
                        return std::format("the key would land on key {} (replace or merge it explicitly)", Id);
        }
        return {};
    }

    // The ops of one TimelineLabEdit, applied in order; any error and nothing is applied (the caller restores)
    inline std::string Apply(lab_doc& D, const std::string& Ops)
    {
        if (Ops.rfind("rev", 0) == 0 || Ops.find(" rev ") != std::string::npos)
        {
            std::uint64_t Rev = 0; std::vector<tl::text_op> P;
            if (!tl::FromText(Ops, Rev, P)) return std::format("bad plan '{}'", Ops);
            if (auto E = ValidateOps(D, Rev, D.m_Revision, P); !E.empty()) return E;
            for (const auto& O : P)
            {
                lab_row* pR = D.Row(O.m_Ref.m_Row);
                bool bFound = false;
                if (O.m_Kind == 's') for (auto& [Id, S] : pR->m_Segments) if (Id == O.m_Ref.m_Item) { const auto L = S.m_SourceLength; S = O.m_Seg; S.m_SourceLength = L; bFound = true; }
                if (O.m_Kind == 'k') for (auto& [Id, K] : pR->m_Keys) if (Id == O.m_Ref.m_Item) { K = O.m_Seg.m_Start; bFound = true; }
                if (!bFound) return std::format("no item {} in row {}", O.m_Ref.m_Item, O.m_Ref.m_Row);
            }
            return {};
        }
        std::size_t a = 0;
        while (a <= Ops.size())
        {
            auto b = Ops.find(';', a); if (b == std::string::npos) b = Ops.size();
            const std::string Op = Ops.substr(a, b - a); a = b + 1;
            std::istringstream L(Op); std::string W; L >> W;
            if (W.empty()) continue;
            if (W == "delete" || W == "dup")
            {
                std::uint64_t R = 0, I = 0; L >> R >> I;
                lab_row* pR = D.Row(R); if (!pR) return std::format("no row {}", R);
                if (pR->m_bLock) return std::format("row '{}' is locked", pR->m_Name);
                if (pR->m_Kind == unknown || pR->m_Kind == dense) return std::format("row '{}' is read only", pR->m_Name);
                if (W == "delete")
                {
                    std::erase_if(pR->m_Segments, [&](const auto& P) { return P.first == I; });
                    std::erase_if(pR->m_Keys, [&](const auto& P) { return P.first == I; });
                }
                else
                {
                    for (std::size_t k = 0, n = pR->m_Segments.size(); k < n; ++k) if (pR->m_Segments[k].first == I) { auto S = pR->m_Segments[k].second; const auto L2 = S.m_End - S.m_Start; S.m_Start += L2; S.m_End += L2; pR->m_Segments.push_back({ D.m_NextId++, S }); }
                    for (std::size_t k = 0, n = pR->m_Keys.size(); k < n; ++k) if (pR->m_Keys[k].first == I) pR->m_Keys.push_back({ D.m_NextId++, pR->m_Keys[k].second + tps_v / 6 });
                }
            }
            else if (W == "marker") { tl::marker M; L >> M.m_Time; std::getline(L >> std::ws, M.m_Name); M.m_Id = D.m_NextId++; D.m_Markers.push_back(M); }
            else if (W == "flag")
            {
                std::uint64_t R = 0; std::string F; int V = 0; L >> R >> F >> V;
                lab_row* pR = D.Row(R); if (!pR) return std::format("no row {}", R);
                if (F == "mute") pR->m_bMute = V; else if (F == "lock") pR->m_bLock = V; else return std::format("no flag '{}' (mute, lock; fold and solo are not the document's)", F);
            }
            else if (W == "range") { tl::tick A, B; L >> A >> B; if (B <= A) return "range: the end must be after the start"; D.m_RangeA = A; D.m_RangeB = B; }
            else return std::format("unknown op '{}'", W);
        }
        return {};
    }

    // The fake document as the timeline sees it
    struct lab_document final : tl::document
    {
        lab_state& m_S;
        explicit lab_document(lab_state& S) noexcept : m_S(S) {}
        std::string Run(const std::string& Ops)
        {
            if (!m_S.m_pUndo) return "no undo system";
            const auto Err = m_S.m_pUndo->Execute(std::format("TimelineLabEdit -Ops {}", xeditor::Quote(Ops)));
            return Err.empty() ? Ops : Err;
        }
        void Rows(std::vector<tl::row_desc>& Out) override
        {
            for (const auto& R : m_S.m_Doc.m_Rows)
            {
                tl::row_desc D; D.m_Id = R.m_Id; D.m_Type = std::uint64_t(R.m_Kind); D.m_Name = R.m_Name;
                for (std::uint64_t p = R.m_Parent; p; p = m_S.m_Doc.Row(p) ? m_S.m_Doc.Row(p)->m_Parent : 0) ++D.m_Depth;
                for (const auto& C : m_S.m_Doc.m_Rows) if (C.m_Parent == R.m_Id) D.m_bHasChildren = true;
                D.m_bMute = R.m_bMute; D.m_bLock = R.m_bLock;
                D.m_Color = R.m_Kind == group ? IM_COL32(150, 150, 160, 255) : R.m_Kind == segments ? IM_COL32(86, 132, 210, 255) : R.m_Kind == events ? IM_COL32(120, 190, 120, 255) : IM_COL32(210, 150, 70, 255);
                Out.push_back(D);
            }
        }
        void          Markers(std::vector<tl::marker>& Out) override { Out = m_S.m_Doc.m_Markers; }
        void          PlaybackRange(tl::tick& A, tl::tick& B) override { A = m_S.m_Doc.m_RangeA; B = m_S.m_Doc.m_RangeB; }
        std::string   SetPlaybackRange(tl::tick A, tl::tick B) override { return Run(std::format("range {} {}", A, B)); }
        std::uint64_t Revision() override { return m_S.m_Doc.m_Revision; }
        std::string   Validate(const tl::plan& P) override
        {
            std::uint64_t Rev = 0; std::vector<tl::text_op> Ops;
            if (!tl::FromText(tl::ToText(P), Rev, Ops)) return "the plan could not be read";
            return ValidateOps(m_S.m_Doc, Rev, m_S.m_Doc.m_Revision, Ops);
        }
        std::string   Commit(const tl::plan& P) override { return Run(tl::ToText(P)); }
        std::string   Delete(std::span<const tl::item_ref> R) override { std::string Ops; for (auto& r : R) Ops += std::format("delete {} {}; ", r.m_Row, r.m_Item); return Run(Ops); }
        std::string   Duplicate(std::span<const tl::item_ref> R) override { std::string Ops; for (auto& r : R) Ops += std::format("dup {} {}; ", r.m_Row, r.m_Item); return Run(Ops); }
        std::string   AddMarker(tl::tick T) override { return Run(std::format("marker {} M{}", T, m_S.m_Doc.m_Markers.size() + 1)); }
        std::string   SetRowFlag(std::uint64_t Row, tl::row_flag F, bool bOn) override { return Run(std::format("flag {} {} {}", Row, F == tl::row_flag::mute ? "mute" : "lock", int(bOn))); }
        void          OnSelection(const std::set<tl::item_ref>& Sel) override
        {
            m_S.m_LastSelection.clear();
            for (const auto& r : Sel) m_S.m_LastSelection += std::format("{}:{} ", r.m_Row, r.m_Item);
        }
        void          Seek(tl::tick) override { ++m_S.m_nSeeks; }                  // sample only: nothing is dispatched
    };

    // Playback: the transport moves and the events it crosses are dispatched (forward (old, new], backward [new, old))
    inline void Advance(lab_state& S, tl::tick To)
    {
        const tl::tick From = S.m_Transport.m_Time;
        for (const auto& R : S.m_Doc.m_Rows)
            if (R.m_Kind == events && !R.m_bMute)
            {
                for (const auto& [Id, K] : R.m_Keys) if (tl::Crossed(K, From, To)) ++S.m_nDispatched;
                for (const auto& [Id, Sg] : R.m_Segments) if (tl::Crossed(Sg.m_Start, From, To)) ++S.m_nDispatched;     // an interval fires on entry
            }
        S.m_Transport.m_Time = To;
    }

    // Row types of the lab: they DECLARE items; the core draws, picks, selects, snaps and drags them
    inline void SegItems(const lab_row& R, const tl::query& Q, std::uint32_t Caps, tl::item_kind Kind, std::vector<tl::item>& Out)
    {
        for (const auto& [Id, S] : R.m_Segments)
            if (!Q.m_bAggregate || (S.m_End >= Q.m_T0 && S.m_Start <= Q.m_T1))
            { tl::item I; I.m_Ref = { R.m_Id, Id }; I.m_Kind = Kind; I.m_Seg = S; I.m_Caps = Caps; I.m_Label = std::format("{} #{}", R.m_Name, Id); Out.push_back(std::move(I)); }
    }
    inline void KeyItems(const lab_row& R, const tl::query& Q, std::uint32_t Caps, tl::item_kind Kind, std::vector<tl::item>& Out)
    {
        for (const auto& [Id, K] : R.m_Keys)
            if (!Q.m_bAggregate || (K >= Q.m_T0 && K <= Q.m_T1))
            { tl::item I; I.m_Ref = { R.m_Id, Id }; I.m_Kind = Kind; I.m_Seg = { K, K }; I.m_Caps = Caps; I.m_Label = std::format("{} key {}", R.m_Name, Id); Out.push_back(std::move(I)); }
    }
    struct segment_rows final : tl::row_type
    {
        lab_state& m_S; explicit segment_rows(lab_state& S) noexcept : m_S(S) {}
        void Query(const tl::row_desc& R, const tl::query& Q, std::vector<tl::item>& Out) override { if (auto* p = m_S.m_Doc.Row(R.m_Id)) SegItems(*p, Q, tl::caps::all_segment | tl::caps::overlap, tl::item_kind::segment, Out); }
    };
    struct key_rows final : tl::row_type
    {
        lab_state& m_S; explicit key_rows(lab_state& S) noexcept : m_S(S) {}
        void Query(const tl::row_desc& R, const tl::query& Q, std::vector<tl::item>& Out) override { if (auto* p = m_S.m_Doc.Row(R.m_Id)) KeyItems(*p, Q, tl::caps::all_key, tl::item_kind::key, Out); }
    };
    // events: points (markers) and intervals; move and trim only (no slip, no ease, no blending)
    struct event_rows final : tl::row_type
    {
        lab_state& m_S; explicit event_rows(lab_state& S) noexcept : m_S(S) {}
        void Query(const tl::row_desc& R, const tl::query& Q, std::vector<tl::item>& Out) override
        {
            if (auto* p = m_S.m_Doc.Row(R.m_Id))
            {
                KeyItems(*p, Q, tl::caps::move | tl::caps::del | tl::caps::duplicate, tl::item_kind::marker, Out);
                SegItems(*p, Q, tl::caps::move | tl::caps::trim | tl::caps::del, tl::item_kind::interval, Out);
            }
        }
    };
    // 200 000 keys: a window query by binary search, aggregated per 4 px bin when dense; read only
    struct dense_rows final : tl::row_type
    {
        lab_state& m_S; explicit dense_rows(lab_state& S) noexcept : m_S(S) {}
        void Query(const tl::row_desc& R, const tl::query& Q, std::vector<tl::item>& Out) override
        {
            const auto* p = m_S.m_Doc.Row(R.m_Id);
            if (!p || p->m_DenseCount <= 0 || p->m_DenseStep <= 0) return;
            const std::int64_t i0 = Q.m_bAggregate ? std::clamp<std::int64_t>(Q.m_T0 / p->m_DenseStep - 1, 0, p->m_DenseCount) : 0;
            const std::int64_t i1 = Q.m_bAggregate ? std::clamp<std::int64_t>(Q.m_T1 / p->m_DenseStep + 1, 0, p->m_DenseCount) : p->m_DenseCount;
            if (!Q.m_bAggregate)
            {
                for (std::int64_t i = i0; i < i1; ++i) { tl::item I; I.m_Ref = { R.m_Id, std::uint64_t(i + 1) }; I.m_Seg = { p->DenseKey(i), p->DenseKey(i) }; Out.push_back(std::move(I)); }
                return;
            }
            std::vector<std::pair<tl::item_ref, tl::tick>> Keys; Keys.reserve(std::size_t(std::max<std::int64_t>(0, i1 - i0)));
            for (std::int64_t i = i0; i < i1; ++i) Keys.push_back({ { R.m_Id, std::uint64_t(i + 1) }, p->DenseKey(i) });
            tl::BinKeys(Keys, *Q.m_pView, 4.0, R.m_Id, tl::caps::none, Out);
            for (auto& I : Out) I.m_Label = "dense key";
        }
    };
    // a group: its children's items as a summary (each stands for the child's item: dragging it moves the child's)
    struct group_rows final : tl::row_type
    {
        lab_state& m_S; explicit group_rows(lab_state& S) noexcept : m_S(S) {}
        void Query(const tl::row_desc& R, const tl::query& Q, std::vector<tl::item>& Out) override
        {
            if (!Q.m_bAggregate) return;           // a summary has no items of its own
            for (const auto& C : m_S.m_Doc.m_Rows)
                if (C.m_Parent == R.m_Id && C.m_Kind == segments)
                {
                    std::vector<tl::item> Items; SegItems(C, Q, C.m_bLock ? tl::caps::none : tl::caps::move, tl::item_kind::interval, Items);
                    for (auto& I : Items) { I.m_Represents = { I.m_Ref }; I.m_Color = IM_COL32(150, 150, 165, 200); I.m_Label.clear(); Out.push_back(std::move(I)); }
                }
        }
    };

    // Each frame (over the editors): the lab's window when it is shown
    inline void Draw() noexcept
    {
        auto& S = State();
        if (!S.m_bVisible) return;
        static segment_rows s_Seg(S); static key_rows s_Key(S); static group_rows s_Group(S); static event_rows s_Ev(S); static dense_rows s_Dense(S);
        static const tl::registry s_Types = { { group, &s_Group }, { segments, &s_Seg }, { keys, &s_Key }, { events, &s_Ev }, { dense, &s_Dense } };   // 'unknown' on purpose not registered
        lab_document Doc(S);
        const ImGuiViewport* pMain = ImGui::GetMainViewport();
        ImGui::SetNextWindowViewport(pMain->ID);
        ImGui::SetNextWindowSize({ std::min(1100.0f, pMain->Size.x - 40), 380 }, ImGuiCond_Appearing);
        ImGui::SetNextWindowPos({ pMain->Pos.x + 20, pMain->Pos.y + pMain->Size.y - 400 }, ImGuiCond_Appearing);
        if (ImGui::Begin("Timeline Lab", &S.m_bVisible, ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoScrollWithMouse | ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_NoDocking))
        {
            ImGui::BringWindowToDisplayFront(ImGui::GetCurrentWindow());
            S.m_View.m_View.m_TPS = tps_v;
            tl::Draw(S.m_View, S.m_Transport, Doc, s_Types);
        }
        ImGui::End();
    }
}

namespace level_editor::commands
{
    // One undoable edit of the lab's document: its state before (the undo) and after
    struct timeline_lab_edit_cmd : xundo::command_base
    {
        timeline_lab_edit_cmd(xundo::system& System, void*) noexcept : command_base(System, "TimelineLabEdit", nullptr) { RegisterArguments(); timeline_lab::State().m_pUndo = &System; }
        const char* getCommandHelp() const noexcept override
        {
            return "Edits the Timeline Lab's document (one undo step for all the ops). Ops: a timeline plan (\"rev N; seg r i start end offset ease_in ease_out; "
                   "key r i t\": resolved values, refused when the document's revision is not N), or \"delete r i\", \"dup r i\", \"marker t name\", "
                   "\"flag r mute|lock 0|1\", \"range a b\" (ticks: 6000 a second). Usage: TimelineLabEdit -Ops \"...; ...\"";
        }
        void RegisterArguments() noexcept override { m_hOps = m_Parser.addOption("Ops", "The ops, separated by ;", true, 1); }
        std::string Redo() noexcept override
        {
            auto V = m_Parser.getOptionArgAs<std::string>(m_hOps, 0);
            if (std::holds_alternative<xerr>(V)) return "TimelineLabEdit: -Ops is needed";
            auto& S = timeline_lab::State();
            const auto Before = timeline_lab::Save(S.m_Doc);
            // a redo runs on the content restored by the undo, revision included: its plan still matches
            if (auto Err = timeline_lab::Apply(S.m_Doc, std::get<std::string>(V)); !Err.empty()) { timeline_lab::Load(S.m_Doc, Before); return "TimelineLabEdit: " + Err; }
            S.m_Doc.m_Revision = ++S.m_RevCounter; S.m_bDirty = true;
            return {};
        }
        void BackupCurrenState(xundo::undo_file& File) noexcept override { xeditor::WriteString(File, timeline_lab::Save(timeline_lab::State().m_Doc)); }
        void Undo(xundo::undo_file& File) noexcept override { auto& S = timeline_lab::State(); timeline_lab::Load(S.m_Doc, xeditor::ReadString(File)); S.m_bDirty = true; }
        xcmdline::parser::handle m_hOps;
    };

    struct timeline_lab_cmd : xundo::query_command_base
    {
        timeline_lab_cmd(xundo::system& System, void*) noexcept : query_command_base(System, "TimelineLab", nullptr) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override
        {
            return "The Timeline Lab: the editor timeline's core on a small fake document. -Show true|false opens or closes its window; -Reset the sample "
                   "document; -Time s the playhead (a seek: nothing dispatched); -Play s plays s seconds (events crossed are dispatched); -Fold r|-Unfold r "
                   "(view state); without arguments: the document, its revision, dirty, the dispatch and seek counts, the selection, the layout, the "
                   "picking regions and the last frame's timings. Usage: TimelineLab [-Show true|false] [-Reset] [-Time s] [-Play s] [-Fold r] [-Unfold r] [-Frame \"a b\"]";
        }
        void RegisterArguments() noexcept override
        {
            m_hShow   = m_Parser.addOption("Show",   "true: open the window, false: close it", false, 1);
            m_hReset  = m_Parser.addOption("Reset",  "The sample document again (not undoable)", false, 0);
            m_hTime   = m_Parser.addOption("Time",   "The playhead, in seconds (a seek)", false, 1);
            m_hPlay   = m_Parser.addOption("Play",   "Play this many seconds from the playhead (negative: backward)", false, 1);
            m_hFold   = m_Parser.addOption("Fold",   "Fold a row (view state)", false, 1);
            m_hUnfold = m_Parser.addOption("Unfold", "Unfold a row (view state)", false, 1);
            m_hFrame  = m_Parser.addOption("Frame",  "\"a b\" seconds: the view frames this range (view state)", false, 1);
        }
        std::string Query() noexcept override
        {
            namespace tl = xeditor::timeline;
            auto& S = timeline_lab::State();
            auto Arg = [&](xcmdline::parser::handle H, std::string& Out) { if (!m_Parser.hasOption(H)) return false; auto V = m_Parser.getOptionArgAs<std::string>(H, 0); if (std::holds_alternative<xerr>(V)) return false; Out = std::get<std::string>(V); return true; };
            std::string A;
            if (Arg(m_hShow, A)) S.m_bVisible = A != "false" && A != "0";
            if (m_Parser.hasOption(m_hReset)) { S.m_Doc = timeline_lab::Sample(); S.m_View.m_Selection.clear(); S.m_View.m_Folded.clear(); S.m_View.m_bFramed = false; S.m_nDispatched = S.m_nSeeks = 0; S.m_bDirty = false; S.m_Doc.m_Revision = ++S.m_RevCounter; S.m_Transport = {}; }
            if (Arg(m_hTime, A)) { S.m_Transport.m_Time = tl::tick(std::llround(std::atof(A.c_str()) * timeline_lab::tps_v)); ++S.m_nSeeks; }
            if (Arg(m_hPlay, A))
            {
                // the transport plays in steps of a frame (as a running game would); every crossed event fires once
                const tl::tick To = S.m_Transport.m_Time + tl::tick(std::llround(std::atof(A.c_str()) * timeline_lab::tps_v));
                const tl::tick Step = timeline_lab::tps_v / 30 * (To >= S.m_Transport.m_Time ? 1 : -1);
                while (S.m_Transport.m_Time != To) timeline_lab::Advance(S, (Step > 0 ? std::min(S.m_Transport.m_Time + Step, To) : std::max(S.m_Transport.m_Time + Step, To)));
            }
            if (Arg(m_hFold, A)) S.m_View.m_Folded.insert(std::strtoull(A.c_str(), nullptr, 10));
            if (Arg(m_hUnfold, A)) S.m_View.m_Folded.erase(std::strtoull(A.c_str(), nullptr, 10));
            if (Arg(m_hFrame, A)) { double a = 0, b = 0; if (std::sscanf(A.c_str(), "%lf %lf", &a, &b) == 2) { S.m_View.m_View.Frame(tl::tick(a * timeline_lab::tps_v), tl::tick(b * timeline_lab::tps_v)); S.m_View.m_bFramed = true; S.m_View.m_ScrollY = 0; } }
            const auto& V = S.m_View.m_View;
            std::string T = std::format("TimelineLab: {}; revision {} dirty {}; dispatched {} seeks {}; time {} ticks; selection [{}]; view left {:.0f} px/tick {:.6f} fps {:g}; last reply '{}'\n",
                                        S.m_bVisible ? "shown" : "hidden", S.m_Doc.m_Revision, int(S.m_bDirty), S.m_nDispatched, S.m_nSeeks, S.m_Transport.m_Time, S.m_LastSelection, V.m_Left, V.m_PxPerTick, V.FPS(), S.m_View.m_Reply);
            T += std::format("snapstate: magnet {} ctrl {} snapped {} target {} ({}) delta {} originals {}\n", int(S.m_View.m_bMagnet), int(ImGui::GetIO().KeyCtrl), int(S.m_View.m_Snap.m_bSnapped), S.m_View.m_Snap.m_Target, S.m_View.m_Snap.m_pWhat, S.m_View.m_Snap.m_Delta, S.m_View.m_Originals.size());
            T += std::format("timings: draw {:.3f} ms, queries {:.3f} ms, snap {:.3f} ms, {} items drawn; frame {:.2f} ms\n", S.m_View.m_DrawMs, S.m_View.m_QueryMs, S.m_View.m_SnapMs, S.m_View.m_nItemsDrawn, ImGui::GetIO().DeltaTime * 1000.0f);
            T += std::format("ruler {:.0f},{:.0f}..{:.0f},{:.0f}; body {:.0f},{:.0f}..{:.0f},{:.0f}\n", S.m_View.m_Ruler.Min.x, S.m_View.m_Ruler.Min.y, S.m_View.m_Ruler.Max.x, S.m_View.m_Ruler.Max.y,
                             S.m_View.m_Body.Min.x, S.m_View.m_Body.Min.y, S.m_View.m_Body.Max.x, S.m_View.m_Body.Max.y);
            for (const auto& [Id, R] : S.m_View.m_RowRects) T += std::format("rowrect {} at y {:.0f}..{:.0f}\n", Id, R.Min.y, R.Max.y);
            T += timeline_lab::Save(S.m_Doc);
            return T;
        }
        xcmdline::parser::handle m_hShow, m_hReset, m_hTime, m_hPlay, m_hFold, m_hUnfold, m_hFrame;
    };
}
#endif
