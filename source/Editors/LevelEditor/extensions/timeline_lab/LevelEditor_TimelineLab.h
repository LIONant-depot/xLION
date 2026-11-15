#ifndef LEVELEDITOR_TIMELINE_LAB_H
#define LEVELEDITOR_TIMELINE_LAB_H
#pragma once
// The Timeline Lab: the editor timeline's core (source/Tools/Editor/xeditor_timeline.h, T1 of xLION_Docs
// editor_timeline_framework_design_2026-11-15.md) on a small fake document, to try it and to drive it from tests. The document is plain
// data; every edit is ONE undoable command (TimelineLabEdit, its whole state before and after), typed in the console or made by a drag.
//      TimelineLab -Show true            opens the window (false closes it)       TimelineLab            the document, the selection and the layout
//      TimelineLab -Reset                the sample document again                TimelineLab -Time 1.5  the playhead (seconds)
//      TimelineLabEdit -Ops "move 2 1 600; trim_end 3 1 -300"   the timeline's edits as text (xeditor::timeline::ToText); also
//          "delete r i", "dup r i", "marker t name", "flag r mute|solo|lock|fold 0|1", "range a b" (ticks: 6000 a second)
// Three row types: a group (its children's items as a summary), a segment row, a key row. Not the animation layers: those are T2.
#include "source/Tools/Editor/xeditor_timeline.h"
#include "dependencies/xeditor/include/xeditor/serialize.h"
#include <sstream>

namespace level_editor::timeline_lab
{
    namespace tl = xeditor::timeline;

    struct lab_row
    {
        std::uint64_t m_Id = 0, m_Parent = 0;          // 0: top level
        int           m_Kind = 0;                      // 0 group, 1 segments, 2 keys
        std::string   m_Name;
        bool          m_bFolded = false, m_bMute = false, m_bSolo = false, m_bLock = false;
        std::vector<std::pair<std::uint64_t, tl::segment>> m_Segments;
        std::vector<std::pair<std::uint64_t, tl::tick>>    m_Keys;
    };
    struct lab_doc
    {
        std::vector<lab_row>    m_Rows;                // pre-order: a child after its parent
        std::vector<tl::marker> m_Markers;
        tl::tick                m_RangeA = 0, m_RangeB = 4 * tl::ticks_per_second_v;
        std::uint64_t           m_NextId = 100;

        lab_row* Row(std::uint64_t Id) noexcept { for (auto& R : m_Rows) if (R.m_Id == Id) return &R; return nullptr; }
    };

    inline lab_doc Sample()
    {
        constexpr tl::tick S = tl::ticks_per_second_v;
        lab_doc D;
        lab_row G{ .m_Id = 1, .m_Kind = 0, .m_Name = "Body" };
        lab_row A{ .m_Id = 2, .m_Parent = 1, .m_Kind = 1, .m_Name = "Walk" };
        A.m_Segments = { { 1, { 0, 2 * S, 0, S / 4, S / 4, 6 * S } }, { 2, { 2 * S + S / 2, 4 * S, S, S / 5, 0, 6 * S } } };
        lab_row B{ .m_Id = 3, .m_Parent = 1, .m_Kind = 1, .m_Name = "Wave left arm" };
        B.m_Segments = { { 1, { S, 3 * S, 0, S / 3, S / 3, 3 * S } } };
        lab_row K{ .m_Id = 4, .m_Kind = 2, .m_Name = "Pose keys" };
        K.m_Keys = { { 1, S / 2 }, { 2, S + S / 2 }, { 3, 3 * S } };
        lab_row E{ .m_Id = 5, .m_Kind = 2, .m_Name = "Events" };
        E.m_Keys = { { 1, S }, { 2, 2 * S + S / 3 } };
        D.m_Rows = { G, A, B, K, E };
        D.m_Markers = { { 1, 2 * S, "contact" } };
        return D;
    }

    // the whole document as text (an undo step's before and after) and back
    inline std::string Save(const lab_doc& D)
    {
        std::string T = std::format("range {} {} {}\n", D.m_RangeA, D.m_RangeB, D.m_NextId);
        for (const auto& M : D.m_Markers) T += std::format("marker {} {} {}\n", M.m_Id, M.m_Time, M.m_Name);
        for (const auto& R : D.m_Rows)
        {
            T += std::format("row {} {} {} {} {} {} {} {}\n", R.m_Id, R.m_Parent, R.m_Kind, int(R.m_bFolded), int(R.m_bMute), int(R.m_bSolo), int(R.m_bLock), R.m_Name);
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
            else if (W == "marker") { tl::marker M; L >> M.m_Id >> M.m_Time; std::getline(L >> std::ws, M.m_Name); N.m_Markers.push_back(M); }
            else if (W == "row")
            {
                lab_row R; int f, m, s, l; L >> R.m_Id >> R.m_Parent >> R.m_Kind >> f >> m >> s >> l; std::getline(L >> std::ws, R.m_Name);
                R.m_bFolded = f; R.m_bMute = m; R.m_bSolo = s; R.m_bLock = l; N.m_Rows.push_back(R);
            }
            else if (W == "seg" && !N.m_Rows.empty()) { std::uint64_t Id; tl::segment S; L >> Id >> S.m_Start >> S.m_End >> S.m_Offset >> S.m_EaseIn >> S.m_EaseOut >> S.m_SourceLength; N.m_Rows.back().m_Segments.push_back({ Id, S }); }
            else if (W == "key" && !N.m_Rows.empty()) { std::uint64_t Id; tl::tick K; L >> Id >> K; N.m_Rows.back().m_Keys.push_back({ Id, K }); }
            else if (!W.empty()) return false;
        }
        D = std::move(N);
        return true;
    }

    // The ops of one TimelineLabEdit, applied in order; any error and nothing is applied (the caller restores)
    inline std::string Apply(lab_doc& D, const std::string& Ops, tl::tick MinLength)
    {
        std::string Rest = Ops;
        std::size_t a = 0;
        while (a <= Rest.size())
        {
            auto b = Rest.find(';', a); if (b == std::string::npos) b = Rest.size();
            const std::string Op = Rest.substr(a, b - a); a = b + 1;
            std::istringstream L(Op); std::string W; L >> W;
            if (W.empty()) continue;
            if (const auto H = tl::HandleFromName(W); H != tl::handle::none)
            {
                std::vector<tl::edit> E;
                if (!tl::FromText(Op, E)) return std::format("bad edit '{}'", Op);
                lab_row* pR = D.Row(E[0].m_Ref.m_Row);
                if (!pR) return std::format("no row {}", E[0].m_Ref.m_Row);
                if (pR->m_bLock) return std::format("row '{}' is locked", pR->m_Name);
                bool bFound = false;
                for (auto& [Id, S] : pR->m_Segments) if (Id == E[0].m_Ref.m_Item) { S = tl::Drag(S, H, E[0].m_Delta, MinLength); bFound = true; }
                for (auto& [Id, K] : pR->m_Keys)     if (Id == E[0].m_Ref.m_Item) { K += E[0].m_Delta; bFound = true; }
                if (!bFound) return std::format("no item {} in row {}", E[0].m_Ref.m_Item, E[0].m_Ref.m_Row);
            }
            else if (W == "delete" || W == "dup")
            {
                std::uint64_t R = 0, I = 0; L >> R >> I;
                lab_row* pR = D.Row(R); if (!pR) return std::format("no row {}", R);
                if (W == "delete")
                {
                    std::erase_if(pR->m_Segments, [&](const auto& P) { return P.first == I; });
                    std::erase_if(pR->m_Keys, [&](const auto& P) { return P.first == I; });
                }
                else
                {
                    for (std::size_t k = 0, n = pR->m_Segments.size(); k < n; ++k) if (pR->m_Segments[k].first == I) { auto S = pR->m_Segments[k].second; const auto L2 = S.m_End - S.m_Start; S.m_Start += L2; S.m_End += L2; pR->m_Segments.push_back({ D.m_NextId++, S }); }
                    for (std::size_t k = 0, n = pR->m_Keys.size(); k < n; ++k) if (pR->m_Keys[k].first == I) pR->m_Keys.push_back({ D.m_NextId++, pR->m_Keys[k].second + MinLength * 5 });
                }
            }
            else if (W == "marker") { tl::marker M; L >> M.m_Time; std::getline(L >> std::ws, M.m_Name); M.m_Id = D.m_NextId++; D.m_Markers.push_back(M); }
            else if (W == "flag")
            {
                std::uint64_t R = 0; std::string F; int V = 0; L >> R >> F >> V;
                lab_row* pR = D.Row(R); if (!pR) return std::format("no row {}", R);
                if (F == "mute") pR->m_bMute = V; else if (F == "solo") pR->m_bSolo = V; else if (F == "lock") pR->m_bLock = V; else if (F == "fold") pR->m_bFolded = V; else return std::format("no flag '{}'", F);
            }
            else if (W == "range") { tl::tick A, B; L >> A >> B; if (B <= A) return "range: the end must be after the start"; D.m_RangeA = A; D.m_RangeB = B; }
            else return std::format("unknown op '{}'", W);
        }
        return {};
    }

    struct lab_state
    {
        lab_doc             m_Doc = Sample();
        tl::tick            m_Time = 0;
        tl::state           m_View;
        bool                m_bVisible = false;
        xundo::system*      m_pUndo = nullptr;       // where TimelineLabEdit is registered (the workspace's: its undo, its console)
        std::string         m_LastSelection;
    };
    inline lab_state& State() noexcept { static lab_state s_State; return s_State; }

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
                D.m_bFolded = R.m_bFolded; D.m_bMute = R.m_bMute; D.m_bSolo = R.m_bSolo; D.m_bLock = R.m_bLock;
                D.m_Color = R.m_Kind == 0 ? IM_COL32(150, 150, 160, 255) : R.m_Kind == 1 ? IM_COL32(86, 132, 210, 255) : IM_COL32(210, 150, 70, 255);
                Out.push_back(D);
            }
        }
        void        Markers(std::vector<tl::marker>& Out) override { Out = m_S.m_Doc.m_Markers; }
        tl::tick    Time() override { return m_S.m_Time; }
        void        SetTime(tl::tick T) override { m_S.m_Time = T; }
        void        PlaybackRange(tl::tick& A, tl::tick& B) override { A = m_S.m_Doc.m_RangeA; B = m_S.m_Doc.m_RangeB; }
        std::string SetPlaybackRange(tl::tick A, tl::tick B) override { return Run(std::format("range {} {}", A, B)); }
        std::string Commit(std::span<const tl::edit> E) override { return Run(tl::ToText(E)); }
        std::string Delete(std::span<const tl::item_ref> R) override { std::string Ops; for (auto& r : R) Ops += std::format("delete {} {}; ", r.m_Row, r.m_Item); return Run(Ops); }
        std::string Duplicate(std::span<const tl::item_ref> R) override { std::string Ops; for (auto& r : R) Ops += std::format("dup {} {}; ", r.m_Row, r.m_Item); return Run(Ops); }
        std::string AddMarker(tl::tick T) override { return Run(std::format("marker {} M{}", T, m_S.m_Doc.m_Markers.size() + 1)); }
        std::string SetRowFlag(std::uint64_t Row, tl::row_flag F, bool bOn) override
        {
            static constexpr const char* Names[] = { "fold", "mute", "solo", "lock" };
            return Run(std::format("flag {} {} {}", Row, Names[int(F)], int(bOn)));
        }
        void OnSelection(const std::set<tl::item_ref>& Sel) override
        {
            m_S.m_LastSelection.clear();
            for (const auto& r : Sel) m_S.m_LastSelection += std::format("{}:{} ", r.m_Row, r.m_Item);
        }
    };

    // Row types of the lab
    struct segment_rows final : tl::row_type
    {
        lab_state& m_S; explicit segment_rows(lab_state& S) noexcept : m_S(S) {}
        void Items(const tl::row_desc& R, int iRow, std::vector<tl::item_box>& Out) override
        {
            if (auto* p = m_S.m_Doc.Row(R.m_Id)) for (const auto& [Id, S] : p->m_Segments) Out.push_back({ { R.m_Id, Id }, S.m_Start, S.m_End, iRow });
        }
        bool Segment(const tl::row_desc& R, std::uint64_t Item, tl::segment& Out) override
        {
            if (auto* p = m_S.m_Doc.Row(R.m_Id)) for (const auto& [Id, S] : p->m_Segments) if (Id == Item) { Out = S; return true; }
            return false;
        }
        void Draw(const tl::row_desc& R, ImDrawList& D, const tl::draw_args& A) override
        {
            if (auto* p = m_S.m_Doc.Row(R.m_Id))
                for (const auto& [Id, S] : p->m_Segments)
                    tl::DrawSegment(D, A, A.Preview(R.m_Id, Id, S), R.m_Color, A.Selected(R.m_Id, Id), std::format("{} #{}", R.m_Name, Id).c_str());
        }
        tl::hit HitTest(const tl::row_desc& R, const tl::draw_args& A, ImVec2 M) override
        {
            if (auto* p = m_S.m_Doc.Row(R.m_Id))
                for (auto It = p->m_Segments.rbegin(); It != p->m_Segments.rend(); ++It)
                    if (const auto H = tl::HitSegment(A, It->second, M); H != tl::handle::none) return { H, It->first };
            return {};
        }
    };
    struct key_rows final : tl::row_type
    {
        lab_state& m_S; explicit key_rows(lab_state& S) noexcept : m_S(S) {}
        void Items(const tl::row_desc& R, int iRow, std::vector<tl::item_box>& Out) override
        {
            if (auto* p = m_S.m_Doc.Row(R.m_Id)) for (const auto& [Id, K] : p->m_Keys) Out.push_back({ { R.m_Id, Id }, K, K, iRow });
        }
        void Draw(const tl::row_desc& R, ImDrawList& D, const tl::draw_args& A) override
        {
            if (auto* p = m_S.m_Doc.Row(R.m_Id))
                for (const auto& [Id, K] : p->m_Keys) tl::DrawKey(D, { A.X(A.Preview(R.m_Id, Id, K)), (A.m_Min.y + A.m_Max.y) * 0.5f }, R.m_Color, A.Selected(R.m_Id, Id));
        }
        tl::hit HitTest(const tl::row_desc& R, const tl::draw_args& A, ImVec2 M) override
        {
            if (auto* p = m_S.m_Doc.Row(R.m_Id))
                for (const auto& [Id, K] : p->m_Keys) if (std::abs(M.x - A.X(K)) < 7) return { tl::handle::key, Id };
            return {};
        }
    };
    // a group: its children's segments and keys as a thin summary (not editable from the group's row in T1)
    struct group_rows final : tl::row_type
    {
        lab_state& m_S; explicit group_rows(lab_state& S) noexcept : m_S(S) {}
        void Items(const tl::row_desc&, int, std::vector<tl::item_box>&) override {}
        void Draw(const tl::row_desc& R, ImDrawList& D, const tl::draw_args& A) override
        {
            const float y = (A.m_Min.y + A.m_Max.y) * 0.5f;
            for (const auto& C : m_S.m_Doc.m_Rows)
                if (C.m_Parent == R.m_Id)
                {
                    for (const auto& [Id, S] : C.m_Segments) D.AddRectFilled({ A.X(S.m_Start), y - 2 }, { A.X(S.m_End), y + 2 }, IM_COL32(150, 150, 165, 160));
                    for (const auto& [Id, K] : C.m_Keys) D.AddCircleFilled({ A.X(K), y }, 2.5f, IM_COL32(200, 200, 210, 200));
                }
        }
        tl::hit HitTest(const tl::row_desc&, const tl::draw_args&, ImVec2) override { return {}; }
    };

    // Each frame (over the editors): the lab's window when it is shown
    inline void Draw() noexcept
    {
        auto& S = State();
        if (!S.m_bVisible) return;
        static segment_rows s_Seg(S); static key_rows s_Key(S); static group_rows s_Group(S);
        static const tl::registry s_Types = { { 0, &s_Group }, { 1, &s_Seg }, { 2, &s_Key } };
        lab_document Doc(S);
        // inside the main window (not a window of its own: CaptureWindow and the person see it there)
        const ImGuiViewport* pMain = ImGui::GetMainViewport();
        ImGui::SetNextWindowViewport(pMain->ID);
        ImGui::SetNextWindowSize({ std::min(980.0f, pMain->Size.x - 40), 330 }, ImGuiCond_Appearing);
        ImGui::SetNextWindowPos({ pMain->Pos.x + 20, pMain->Pos.y + pMain->Size.y - 350 }, ImGuiCond_Appearing);
        if (ImGui::Begin("Timeline Lab", &S.m_bVisible, ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoScrollWithMouse | ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_NoDocking))
        {
            ImGui::BringWindowToDisplayFront(ImGui::GetCurrentWindow());      // over the docked panels while it is shown (a lab, not a panel)
            tl::Draw(S.m_View, Doc, s_Types);
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
            return "Edits the Timeline Lab's document (one undo step for all the ops). Ops: the timeline's edits (\"move r i dt; trim_start r i dt; trim_end ...; "
                   "ease_in ...; ease_out ...; slip ...; key r i dt\"), \"delete r i\", \"dup r i\", \"marker t name\", \"flag r mute|solo|lock|fold 0|1\", \"range a b\" "
                   "(ticks: 6000 a second). Usage: TimelineLabEdit -Ops \"...; ...\"";
        }
        void RegisterArguments() noexcept override { m_hOps = m_Parser.addOption("Ops", "The ops, separated by ;", true, 1); }
        std::string Redo() noexcept override
        {
            auto V = m_Parser.getOptionArgAs<std::string>(m_hOps, 0);
            if (std::holds_alternative<xerr>(V)) return "TimelineLabEdit: -Ops is needed";
            auto& S = timeline_lab::State();
            const auto Before = timeline_lab::Save(S.m_Doc);
            if (auto Err = timeline_lab::Apply(S.m_Doc, std::get<std::string>(V), S.m_View.m_View.FrameTicks()); !Err.empty()) { timeline_lab::Load(S.m_Doc, Before); return "TimelineLabEdit: " + Err; }
            return {};
        }
        void BackupCurrenState(xundo::undo_file& File) noexcept override { xeditor::WriteString(File, timeline_lab::Save(timeline_lab::State().m_Doc)); }
        void Undo(xundo::undo_file& File) noexcept override { timeline_lab::Load(timeline_lab::State().m_Doc, xeditor::ReadString(File)); }
        xcmdline::parser::handle m_hOps;
    };

    struct timeline_lab_cmd : xundo::query_command_base
    {
        timeline_lab_cmd(xundo::system& System, void*) noexcept : query_command_base(System, "TimelineLab", nullptr) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override
        {
            return "The Timeline Lab: the editor timeline's core on a small fake document. -Show true|false opens or closes its window; -Reset the sample "
                   "document; -Time s the playhead; without arguments: the document, the selection, the view and where each row is on screen. "
                   "Usage: TimelineLab [-Show true|false] [-Reset] [-Time s]";
        }
        void RegisterArguments() noexcept override
        {
            m_hShow  = m_Parser.addOption("Show",  "true: open the window, false: close it", false, 1);
            m_hReset = m_Parser.addOption("Reset", "The sample document again (not undoable)", false, 0);
            m_hTime  = m_Parser.addOption("Time",  "The playhead, in seconds", false, 1);
        }
        std::string Query() noexcept override
        {
            namespace tl = xeditor::timeline;
            auto& S = timeline_lab::State();
            if (m_Parser.hasOption(m_hShow)) { auto V = m_Parser.getOptionArgAs<std::string>(m_hShow, 0); if (!std::holds_alternative<xerr>(V)) S.m_bVisible = std::get<std::string>(V) != "false" && std::get<std::string>(V) != "0"; }
            if (m_Parser.hasOption(m_hReset)) { S.m_Doc = timeline_lab::Sample(); S.m_View.m_Selection.clear(); S.m_View.m_bFramed = false; }
            if (m_Parser.hasOption(m_hTime)) { auto V = m_Parser.getOptionArgAs<std::string>(m_hTime, 0); if (!std::holds_alternative<xerr>(V)) S.m_Time = tl::tick(std::llround(std::atof(std::get<std::string>(V).c_str()) * tl::ticks_per_second_v)); }
            std::string T = std::format("TimelineLab: {}; time {} ticks; selection [{}]; view left {:.0f} px/tick {:.5f} fps {:g}; last reply '{}'\n", S.m_bVisible ? "shown" : "hidden", S.m_Time,
                                        S.m_LastSelection, S.m_View.m_View.m_Left, S.m_View.m_View.m_PxPerTick, S.m_View.m_View.m_FPS, S.m_View.m_Reply);
            T += std::format("ruler {:.0f},{:.0f}..{:.0f},{:.0f}; body {:.0f},{:.0f}..{:.0f},{:.0f}\n", S.m_View.m_Ruler.Min.x, S.m_View.m_Ruler.Min.y, S.m_View.m_Ruler.Max.x, S.m_View.m_Ruler.Max.y,
                             S.m_View.m_Body.Min.x, S.m_View.m_Body.Min.y, S.m_View.m_Body.Max.x, S.m_View.m_Body.Max.y);
            for (const auto& [Id, R] : S.m_View.m_RowRects) T += std::format("row {} at y {:.0f}..{:.0f}\n", Id, R.Min.y, R.Max.y);
            T += timeline_lab::Save(S.m_Doc);
            return T;
        }
        xcmdline::parser::handle m_hShow, m_hReset, m_hTime;
    };
}
#endif
