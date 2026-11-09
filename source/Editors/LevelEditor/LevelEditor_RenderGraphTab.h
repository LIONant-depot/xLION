#pragma once
// The drawer's Render Graph tab (R3a, xLION_Docs/render_graph_design_2026-11-09.md section 6): the render graph's declarations of a Level's
// last frame, read only - every scope in recording order (managed, or a legacy group), what it reads and writes (resource, version, usage,
// content policy, lifetime), and the declaration errors. A resource clicked: every scope that touches it lit, its writers orange and its
// readers blue - the graph's edges for that resource. The data: xlionrender::xRenderEditor::DescribeGraph (rg::graph::Text).
// Post chain (render graph P5, read only): the chain's recipe - its nodes in order, its parameters with the value a frame used, where it
// came from and its range (a clamped one says the Scene's value) - and what it expands to: every pass with its size, dispatch, the
// setting it runs on and whether it ran last frame; a node clicked lights its passes. The data: xRenderEditor::DescribePost.
#include "dependencies/xgraph/source/xgraph_view.h"      // (the Frame graph: the layout, routes and canvas frame the material stack and the RenderGraph editor use)
#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <format>
#include <functional>
#include <memory>
#include <unordered_map>
#include <string>
#include <string_view>
#include <vector>

namespace level_editor::render_graph_tab
{
    struct access { bool m_bWrite = false; std::string m_Version, m_Usage, m_Policy, m_Life, m_Res; };
    struct scope  { bool m_bManaged = true; std::string m_Name, m_Recorded; std::vector<access> m_Accesses; };

    struct post_param { std::string m_Name, m_Value, m_Source, m_Min, m_Max, m_Raw; };
    struct post_pass  { bool m_bInit = false, m_bRan = false; int m_Node = -1; std::string m_Source, m_Scope, m_Kernel, m_W, m_H, m_GX, m_GY, m_When; };
    struct post_state
    {
        std::vector<bool>        m_On;                       // each node's bypass state (N lines' last field)
        std::string              m_LastReply;                // the last edit's reply (a refusal says why)
        std::vector<char>        m_Buffer = std::vector<char>(16 * 1024);
        std::string              m_Error;
        std::vector<std::string> m_Nodes;
        std::vector<post_param>  m_Params;
        std::vector<post_pass>   m_Passes;
        int                      m_Selected = -1;            // the node clicked (-1: none)
        bool                     m_bInits = false;           // show the initialisations too
    };

    struct frame_graph_state { xgraph::view::view m_View; int m_Selected = -1; std::string m_Hidden; bool m_bFit = true; std::string m_Key; std::shared_ptr<xgraph::routes::result> m_pRoutes; };      // (Key, Routes: the layout made again only when the frame's structure changes - every frame it cost the editor most of its frame rate)      // (Fit: the whole frame in view - at the first show and on the Fit button)

    struct state
    {
        post_state               m_Post;
        frame_graph_state        m_Frame;
        std::vector<char>        m_Buffer = std::vector<char>(64 * 1024);
        std::vector<std::string> m_Errors;
        std::vector<scope>       m_Scopes;
        std::string              m_Selected;                // the resource clicked ("": none)
        char                     m_Filter[128] = {};
        bool                     m_bFrozen = false;          // keep the frame shown (the declarations change with what the view draws)
        int                      m_Refresh = 0;              // frames to the next read
    };

    inline std::vector<std::string_view> Split(std::string_view L) noexcept
    {
        std::vector<std::string_view> F;
        for (std::size_t b = 0;;)
        {
            const std::size_t e = L.find('\t', b);
            F.push_back(L.substr(b, e == std::string_view::npos ? std::string_view::npos : e - b));
            if (e == std::string_view::npos) return F;
            b = e + 1;
        }
    }

    // rg::graph::Text: "E <error>", "S <managed> <name> <recorded>", "A <write> <version> <usage> <policy> <lifetime> <resource>"
    inline void Parse(state& S, std::string_view T) noexcept
    {
        S.m_Errors.clear(); S.m_Scopes.clear();
        while (!T.empty())
        {
            const std::size_t e = T.find('\n');
            const auto F = Split(T.substr(0, e));
            T = e == std::string_view::npos ? std::string_view() : T.substr(e + 1);
            if (F[0] == "E" && F.size() >= 2) S.m_Errors.emplace_back(F[1]);
            else if (F[0] == "S" && F.size() >= 4) S.m_Scopes.push_back({ F[1] == "1", std::string(F[2]), std::string(F[3]), {} });
            else if (F[0] == "A" && F.size() >= 7 && !S.m_Scopes.empty())
                S.m_Scopes.back().m_Accesses.push_back({ F[1] == "1", std::string(F[2]), std::string(F[3]), std::string(F[4]), std::string(F[5]), std::string(F[6]) });
        }
    }

    // xlionrender::post::Describe: "E <error>", "N <i> <type>", "P <name> <value> <source> <min> <max> <raw>", "X|I <node> <ran> <source> <scope> <kernel> <W> <H> <gx> <gy> <when>"
    inline void ParsePost(post_state& S, std::string_view T) noexcept
    {
        S.m_Error.clear(); S.m_Nodes.clear(); S.m_On.clear(); S.m_Params.clear(); S.m_Passes.clear();
        while (!T.empty())
        {
            const std::size_t e = T.find('\n');
            const auto F = Split(T.substr(0, e));
            T = e == std::string_view::npos ? std::string_view() : T.substr(e + 1);
            if (F[0] == "E" && F.size() >= 2) S.m_Error = std::string(F[1]);
            else if (F[0] == "N" && F.size() >= 3) { S.m_Nodes.emplace_back(F[2]); S.m_On.push_back(F.size() < 4 || F[3] == "1"); }
            else if (F[0] == "P" && F.size() >= 7) S.m_Params.push_back({ std::string(F[1]), std::string(F[2]), std::string(F[3]), std::string(F[4]), std::string(F[5]), std::string(F[6]) });
            else if ((F[0] == "X" || F[0] == "I") && F.size() >= 11)
                S.m_Passes.push_back({ F[0] == "I", F[2] == "1", std::atoi(std::string(F[1]).c_str()), std::string(F[3]), std::string(F[4]), std::string(F[5]), std::string(F[6]), std::string(F[7]), std::string(F[8]), std::string(F[9]), std::string(F[10]) });
        }
    }

    inline bool Contains(std::string_view Text, std::string_view Pattern) noexcept
    {
        return std::search(Text.begin(), Text.end(), Pattern.begin(), Pattern.end(),
            [](char a, char b) { return std::tolower(static_cast<unsigned char>(a)) == std::tolower(static_cast<unsigned char>(b)); }) != Text.end();
    }

    // The post chain: the recipe (nodes, parameters) and what it expands to (passes), read only
    using edit_fn = std::function<std::string(const std::string&)>;     // a Level's PostEdit: its reply

    inline void DrawPost(state& St, xlionrender::xRenderEditor* pRender, const void* pWorld, const edit_fn& EditFn) noexcept
    {
        auto& S = St.m_Post;
        if (!St.m_bFrozen && St.m_Refresh == 30)        // (read with the scopes: the same frame)
        {
            int n = pRender->DescribePost(pWorld, S.m_Buffer.data(), static_cast<int>(S.m_Buffer.size()));
            if (n >= static_cast<int>(S.m_Buffer.size())) { S.m_Buffer.resize(static_cast<std::size_t>(n) * 2); n = pRender->DescribePost(pWorld, S.m_Buffer.data(), static_cast<int>(S.m_Buffer.size())); }
            ParsePost(S, n > 0 ? std::string_view(S.m_Buffer.data(), std::min<std::size_t>(static_cast<std::size_t>(n), S.m_Buffer.size() - 1)) : std::string_view());
        }
        const ImVec4 kNode(0.45f, 0.75f, 1.0f, 1.0f), kDim(0.55f, 0.55f, 0.55f, 1.0f), kWarn(1.0f, 0.62f, 0.25f, 1.0f);
        if (!S.m_Error.empty()) ImGui::TextColored(ImVec4(1.0f, 0.35f, 0.3f, 1.0f), "The chain's description is not valid - tone map only: %s", S.m_Error.c_str());
        if (S.m_Nodes.empty()) { ImGui::TextDisabled("No post chain yet (the Level has not rendered)."); return; }

        // The recipe: its nodes in order (a node clicked lights its passes below). Editing (P6): each node's checkbox bypasses it, "x" removes
        // it, a "+" between nodes offers only the types that keep the chain valid. Every action is a PostEdit command (the console's text)
        const auto Send = [&](const std::string& Edit)
        {
            S.m_LastReply = Edit + ": " + EditFn(Edit);
            St.m_Refresh = 0;       // (read again next frame)
        };
        {   // where the edits go: the Level's RenderGraph resource (saved; it compiles, the view follows) or the view (lost on reload)
            char Source[32] = {};
            pRender->EditPost(pWorld, "source", Source, static_cast<int>(sizeof(Source)));
            if (std::strtoull(Source, nullptr, 16)) ImGui::TextDisabled("Edits are saved in the Level's RenderGraph %s (its Environment's)", Source);
            else ImGui::TextDisabled("Edits apply to this view only (the built-in chain: give the Environment a RenderGraph to keep them)");
        }
        const auto Plus = [&](int Gap)
        {
            ImGui::PushID(1000 + Gap);
            if (ImGui::SmallButton("+")) ImGui::OpenPopup("##insert");
            if (ImGui::IsItemHovered()) ImGui::SetTooltip("Insert a node here (only those that keep the chain valid are offered)");
            if (ImGui::BeginPopup("##insert"))
            {
                char Types[256] = {};
                pRender->EditPost(pWorld, std::format("insertable {}", Gap).c_str(), Types, static_cast<int>(sizeof(Types)));
                std::string_view T(Types); int nOffered = 0;
                for (std::size_t b = 0; b < T.size(); )
                {
                    std::size_t e = T.find(' ', b); if (e == std::string_view::npos) e = T.size();
                    if (e > b) { const std::string Name(T.substr(b, e - b)); ++nOffered; if (ImGui::MenuItem(Name.c_str())) Send(std::format("insert {} {}", Gap, Name)); }
                    b = e + 1;
                }
                if (!nOffered) ImGui::TextDisabled("Nothing fits here (each node once; TAA first, the tone map last)");
                ImGui::EndPopup();
            }
            ImGui::PopID();
        };
        ImGui::TextDisabled("Recipe");
        ImGui::SameLine(); Plus(0);
        for (int i = 0; i < static_cast<int>(S.m_Nodes.size()); ++i)
        {
            if (i) { ImGui::SameLine(); ImGui::TextDisabled("->"); }
            ImGui::SameLine();
            ImGui::PushID(i);
            bool bOn = i < static_cast<int>(S.m_On.size()) ? S.m_On[static_cast<std::size_t>(i)] : true;
            if (ImGui::Checkbox("##on", &bOn)) Send(std::format("bypass {} {}", i, bOn ? 1 : 0));
            if (ImGui::IsItemHovered()) ImGui::SetTooltip(bOn ? "On: uncheck to bypass it (kept in the recipe, left out of the frame)" : "Bypassed: check to put it back");
            ImGui::SameLine(0, 2);
            if (!bOn) ImGui::PushStyleVar(ImGuiStyleVar_Alpha, ImGui::GetStyle().Alpha * 0.45f);
            const bool bSel = S.m_Selected == i;
            if (bSel) ImGui::PushStyleColor(ImGuiCol_Button, ImGui::GetStyleColorVec4(ImGuiCol_ButtonActive));
            if (ImGui::Button(S.m_Nodes[static_cast<std::size_t>(i)].c_str())) S.m_Selected = bSel ? -1 : i;
            if (bSel) ImGui::PopStyleColor();
            if (ImGui::IsItemHovered())
            {
                int nPasses = 0; for (const auto& P : S.m_Passes) nPasses += !P.m_bInit && P.m_Node == i;
                ImGui::SetTooltip("%s: %d pass%s this frame%s", S.m_Nodes[static_cast<std::size_t>(i)].c_str(), nPasses, nPasses == 1 ? "" : "es", bSel ? " (click: show all)" : " (click: light them)");
            }
            if (!bOn) ImGui::PopStyleVar();
            ImGui::SameLine(0, 2);
            if (ImGui::SmallButton("x")) Send(std::format("remove {}", i));
            if (ImGui::IsItemHovered()) ImGui::SetTooltip("Remove it from the recipe (refused if the chain would be invalid: the tone map stays)");
            ImGui::SameLine(); Plus(i + 1);
            ImGui::PopID();
        }
        if (!S.m_LastReply.empty()) ImGui::TextColored(S.m_LastReply.find("refused") != std::string::npos || S.m_LastReply.find("not an edit") != std::string::npos || S.m_LastReply.find("no node type") != std::string::npos ? kWarn : kDim, "%s", S.m_LastReply.c_str());
        ImGui::Spacing();

        // Side by side (the drawer is wide and short): the parameters on the left, the passes on the right
        if (!ImGui::BeginTable("##postlayout", 2, ImGuiTableFlags_Resizable | ImGuiTableFlags_BordersInnerV)) return;
        ImGui::TableSetupColumn("params", ImGuiTableColumnFlags_WidthStretch, 0.42f);
        ImGui::TableSetupColumn("passes", ImGuiTableColumnFlags_WidthStretch, 0.58f);
        ImGui::TableNextRow(); ImGui::TableNextColumn();
        ImGui::BeginChild("##postparamsc");
        // Its parameters: the value the last frame used, where it came from, its range
        if (ImGui::BeginTable("##postparams", 4, ImGuiTableFlags_RowBg | ImGuiTableFlags_BordersInnerV | ImGuiTableFlags_SizingFixedFit | ImGuiTableFlags_ScrollY))
        {
            ImGui::TableSetupScrollFreeze(0, 1);
            ImGui::TableSetupColumn("parameter"); ImGui::TableSetupColumn("value"); ImGui::TableSetupColumn("range"); ImGui::TableSetupColumn("from", ImGuiTableColumnFlags_WidthStretch);
            ImGui::TableHeadersRow();
            for (const auto& P : S.m_Params)
            {
                ImGui::TableNextRow();
                ImGui::TableNextColumn(); ImGui::TextUnformatted(P.m_Name.c_str());
                ImGui::TableNextColumn();
                if (P.m_Raw.empty()) ImGui::TextUnformatted(P.m_Value.c_str());
                else
                {
                    ImGui::TextColored(kWarn, "%s (clamped)", P.m_Value.c_str());
                    if (ImGui::IsItemHovered()) ImGui::SetTooltip("The Scene says %s, outside %s .. %s: %s is used", P.m_Raw.c_str(), P.m_Min.c_str(), P.m_Max.c_str(), P.m_Value.c_str());
                }
                ImGui::TableNextColumn();
                if (P.m_Value == "on" || P.m_Value == "off") ImGui::TextColored(kDim, "on / off"); else ImGui::TextColored(kDim, "%s .. %s", P.m_Min.c_str(), P.m_Max.c_str());
                ImGui::TableNextColumn(); ImGui::TextColored(kDim, "%s", P.m_Source.c_str());
            }
            ImGui::EndTable();
        }
        ImGui::EndChild();
        ImGui::TableNextColumn();

        // What it expands to: the passes in order, those that did not run last frame dimmed (and why: the setting they run on)
        int nRan = 0, nFrame = 0; for (const auto& P : S.m_Passes) if (!P.m_bInit) { ++nFrame; nRan += P.m_bRan; }
        ImGui::TextDisabled("Expanded: %d passes, %d ran last frame", nFrame, nRan);
        ImGui::SameLine(); ImGui::Checkbox("show the initialisations", &S.m_bInits);
        if (!ImGui::BeginTable("##postpasses", 5, ImGuiTableFlags_RowBg | ImGuiTableFlags_BordersInnerV | ImGuiTableFlags_ScrollY | ImGuiTableFlags_Resizable | ImGuiTableFlags_SizingFixedFit)) { ImGui::EndTable(); return; }
        ImGui::TableSetupScrollFreeze(0, 1);
        ImGui::TableSetupColumn("pass", ImGuiTableColumnFlags_WidthStretch);
        ImGui::TableSetupColumn("kernel"); ImGui::TableSetupColumn("dispatch"); ImGui::TableSetupColumn("runs when"); ImGui::TableSetupColumn("last frame");
        ImGui::TableHeadersRow();
        for (const auto& P : S.m_Passes)
        {
            if (P.m_bInit && !S.m_bInits) continue;
            const bool bLit = S.m_Selected >= 0 && P.m_Node == S.m_Selected, bDim = S.m_Selected >= 0 ? !bLit : (!P.m_bRan && !P.m_bInit);
            const ImVec4 Col = bLit ? kNode : bDim ? kDim : ImGui::GetStyleColorVec4(ImGuiCol_Text);
            ImGui::TableNextRow();
            ImGui::TableNextColumn(); ImGui::TextColored(Col, "%s", P.m_Source.c_str());
            if (ImGui::IsItemHovered()) ImGui::SetTooltip("render graph scope: %s", P.m_Scope.c_str());
            ImGui::TableNextColumn(); ImGui::TextColored(Col, "%s", P.m_Kernel.c_str());
            ImGui::TableNextColumn(); ImGui::TextColored(Col, "%s", P.m_Kernel.find("raster") != std::string::npos ? "a triangle" : (P.m_GX + " x " + P.m_GY + " groups").c_str());
            ImGui::TableNextColumn(); ImGui::TextColored(Col, "%s", P.m_bInit ? "once" : P.m_When.c_str());
            ImGui::TableNextColumn(); ImGui::TextColored(P.m_bRan ? Col : kDim, "%s", P.m_bInit ? "" : P.m_bRan ? "ran" : "skipped");
        }
        ImGui::EndTable();
        ImGui::EndTable();      // (the layout)
    }

    inline void DrawScopes(state& S) noexcept;

    // The whole frame as a graph (read only): every scope of the last frame a step in recording order - its inputs the resources it reads,
    // its outputs the ones it writes - and a wire from the scope that wrote a resource's version to each scope that reads that version.
    // A read with no writer this frame (the lit image's imports, last frame's history, GPU data kept across frames) is an unconnected
    // input. Colour by lifetime: frame grey, history amber, retained green, external blue. Laid out and routed by xgraph.
    inline std::string ShortName(std::string_view R) noexcept
    {
        for (std::string_view P : { "Render target: ", "Shadows: ", "Frame: " }) if (R.starts_with(P)) return std::string(R.substr(P.size()));
        return std::string(R);
    }
    inline void DrawFrameGraph(state& St) noexcept
    {
        namespace gl = xgraph::layout; namespace gr = xgraph::routes;
        auto& F = St.m_Frame;
        if (St.m_Scopes.empty()) { ImGui::TextDisabled("No frame declared yet (the Level has not rendered)."); return; }
        struct step { std::string m_Name, m_Recorded; bool m_bManaged = true; std::vector<std::string> m_In, m_Out; std::vector<std::string> m_InLife, m_OutLife; };
        std::vector<step> Steps;
        std::vector<gl::edge> Edges;
        std::vector<std::string> SourceLife;           // per edge: the lifetime of what it carries
        std::unordered_map<std::string, std::pair<int, int>> Writer;      // "resource#version" -> (step, output row)
        for (const auto& Sc : St.m_Scopes)
        {
            step S{ Sc.m_Name, Sc.m_Recorded, Sc.m_bManaged, {}, {}, {}, {} };
            const int s = static_cast<int>(Steps.size());
            for (const auto& A : Sc.m_Accesses)
            {
                // a read of a version; a write that keeps the contents (preserve, partial) reads the version before it - drawing onto the
                // prepass's image, the tile pass consumes it (Tomas 2026-11-09: its output looked unconnected)
                const bool bKeeps = A.m_bWrite && (A.m_Policy == "preserve" || A.m_Policy == "partial");
                if (A.m_bWrite && !bKeeps) continue;
                const std::string Version = bKeeps ? std::to_string(std::atoi(A.m_Version.c_str()) - 1) : A.m_Version;
                const auto Name = ShortName(A.m_Res);
                if (std::find(S.m_In.begin(), S.m_In.end(), Name) != S.m_In.end()) continue;
                const int Row = static_cast<int>(S.m_In.size());
                S.m_In.push_back(Name); S.m_InLife.push_back(A.m_Life);
                if (const auto It = Writer.find(A.m_Res + "#" + Version); It != Writer.end())
                {
                    Edges.push_back({ It->second.first, It->second.second, s, Row, std::hash<std::string>{}(A.m_Res + "#" + Version), Edges.size() });
                    SourceLife.push_back(A.m_Life);
                }
            }
            for (const auto& A : Sc.m_Accesses)
            {
                if (!A.m_bWrite) continue;
                const auto Name = ShortName(A.m_Res);
                int Row = static_cast<int>(std::find(S.m_Out.begin(), S.m_Out.end(), Name) - S.m_Out.begin());
                if (Row == static_cast<int>(S.m_Out.size())) { S.m_Out.push_back(Name); S.m_OutLife.push_back(A.m_Policy == "discard" ? std::string("scratch") : A.m_Life); }      // (discard: a pass's scratch attachment - nothing should read it)
                Writer[A.m_Res + "#" + A.m_Version] = { s, Row };
            }
            Steps.push_back(std::move(S));
        }
        gl::input In(1);
        for (const auto& S : Steps)
        {
            const std::size_t nRows = std::max<std::size_t>(std::max(S.m_In.size(), S.m_Out.size()), 1);
            float W = ImGui::CalcTextSize(S.m_Name.c_str()).x + 16;
            for (std::size_t r = 0; r < nRows; ++r)
                W = std::max(W, (r < S.m_In.size() ? ImGui::CalcTextSize(S.m_In[r].c_str()).x : 0.0f) + (r < S.m_Out.size() ? ImGui::CalcTextSize(S.m_Out[r].c_str()).x : 0.0f) + gl::geo::MID_GAP);
            In[0].m_Steps.push_back({ static_cast<std::uint64_t>(In[0].m_Steps.size() + 1), gl::StepW(W), static_cast<int>(nRows) });
        }
        {   // (the steps and wires are cheap; the layout and routes are not: made again when the structure changes - names, rows, wires)
            std::string Key;
            for (const auto& S : Steps) { Key += S.m_Name; Key += '\x1'; for (const auto& n : S.m_In) { Key += n; Key += ','; } Key += '\x2'; for (const auto& n : S.m_Out) { Key += n; Key += ','; } Key += '\x3'; }
            for (const auto& E : Edges) Key += std::format("{}.{}>{}.{};", E.m_From, E.m_FromRow, E.m_To, E.m_ToRow);
            Key += std::format("#{}", ImGui::GetFontSize());
            if (Key != F.m_Key || !F.m_pRoutes) { F.m_pRoutes = std::make_shared<gr::result>(gr::Build(In, Edges)); F.m_Key = std::move(Key); }
        }
        const auto& R = *F.m_pRoutes;
        const auto LifeColor = [](std::string_view L) -> ImU32
        {
            if (L == "history")  return IM_COL32(230, 170, 80, 255);
            if (L == "retained") return IM_COL32(120, 200, 130, 255);
            if (L == "external") return IM_COL32(120, 170, 235, 255);
            if (L == "scratch")  return IM_COL32(90, 90, 95, 255);
            return IM_COL32(175, 175, 185, 255);
        };
        std::vector<ImU32> SourceColor(R.m_Sources.size(), IM_COL32(175, 175, 185, 255));
        for (std::size_t e = 0; e < Edges.size(); ++e) SourceColor[std::size_t(R.m_RouteSource[e])] = LifeColor(SourceLife[e]);

        if (ImGui::SmallButton("Fit")) F.m_bFit = true;
        ImGui::SameLine(); ImGui::TextDisabled("%d scopes, %d wires - click a step to light what it reads and writes; right drag pans, the wheel zooms. Grey outputs: scratch (a pass's own attachments, never read)", static_cast<int>(Steps.size()), static_cast<int>(Edges.size()));
        ImGui::BeginChild("##framegraph", ImVec2(0, 0), false, ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoScrollWithMouse);
        static const xgraph::view::style Style = [] { xgraph::view::style S; S.m_ZoomMin = 0.1f; return S; }();     // (a whole frame: zoomed far out)
        const ImVec2 Avail = ImGui::GetContentRegionAvail();
        if (F.m_bFit && R.m_Layout.m_Width > 0 && R.m_Layout.m_Height > 0)
        {
            F.m_View.m_Zoom = std::clamp(std::min(Avail.x / R.m_Layout.m_Width, Avail.y / R.m_Layout.m_Height) * 0.95f, Style.m_ZoomMin, Style.m_ZoomMax);
            F.m_View.m_Pan  = { (Avail.x - R.m_Layout.m_Width * F.m_View.m_Zoom) * 0.5f, (Avail.y - R.m_Layout.m_Height * F.m_View.m_Zoom) * 0.5f };
            F.m_bFit = false;
        }
        (void)F.m_View.Input(Style, Avail);
        auto* pDL = ImGui::GetWindowDrawList();
        auto& V = F.m_View;
        V.DrawBackground(pDL, Style);
        const ImVec2 Mouse = ImGui::GetIO().MousePos;
        int Hover = -1;
        for (std::size_t i = 0; i < Steps.size(); ++i)
        {
            const auto& B = R.m_Layout.m_Steps[i];
            const ImVec2 a = V.ToScreen(B.m_X, B.m_Y), b = V.ToScreen(B.m_X + B.m_W, B.m_Y + B.m_H);
            if (ImGui::IsWindowHovered() && Mouse.x >= a.x && Mouse.x < b.x && Mouse.y >= a.y && Mouse.y < b.y) Hover = static_cast<int>(i);
        }
        if (ImGui::IsWindowHovered() && ImGui::IsMouseClicked(ImGuiMouseButton_Left)) F.m_Selected = Hover;
        if (F.m_Selected >= static_cast<int>(Steps.size())) F.m_Selected = -1;
        std::vector<float> Lit(Edges.size(), 0.0f);
        for (const int Focus : { F.m_Selected, Hover })
            if (Focus >= 0) for (std::size_t e = 0; e < Edges.size(); ++e) if (Edges[e].m_From == Focus || Edges[e].m_To == Focus) Lit[e] = Focus == F.m_Selected ? 1.0f : std::max(Lit[e], 0.9f);
        V.DrawRoutes(pDL, Style, R, SourceColor, Lit);
        ImFont* pFont = ImGui::GetFont();
        const float Font = ImGui::GetFontSize() * V.m_Zoom;
        for (std::size_t i = 0; i < Steps.size(); ++i)
        {
            const auto& S = Steps[i]; const auto& B = R.m_Layout.m_Steps[i];
            const ImVec2 a = V.ToScreen(B.m_X, B.m_Y), b = V.ToScreen(B.m_X + B.m_W, B.m_Y + B.m_H);
            if (b.x < V.m_Origin.x || a.x > V.m_Max.x || b.y < V.m_Origin.y || a.y > V.m_Max.y) continue;     // (off screen)
            pDL->AddRectFilled(a, b, IM_COL32(48, 52, 60, 255), V.Len(4.0f));
            pDL->AddRectFilled(a, ImVec2(b.x, a.y + V.Len(gl::geo::HEADER_H)), S.m_bManaged ? IM_COL32(70, 90, 120, 255) : IM_COL32(90, 80, 60, 255), V.Len(4.0f), ImDrawFlags_RoundCornersTop);
            if (static_cast<int>(i) == F.m_Selected) pDL->AddRect(a, b, IM_COL32(230, 180, 90, 255), V.Len(4.0f), 0, 2.0f);
            pDL->AddText(pFont, Font, ImVec2(a.x + V.Len(8), a.y + V.Len(5)), IM_COL32(230, 230, 230, 255), S.m_Name.c_str());
            for (std::size_t r = 0; r < S.m_In.size(); ++r)
            {
                const float y = a.y + V.Len(gl::RowY(static_cast<int>(r)));
                pDL->AddCircleFilled(ImVec2(a.x, y), V.Len(4.0f), LifeColor(S.m_InLife[r]));
                pDL->AddText(pFont, Font, ImVec2(a.x + V.Len(8), y - Font * 0.5f), IM_COL32(150, 150, 150, 255), S.m_In[r].c_str());
            }
            for (std::size_t r = 0; r < S.m_Out.size(); ++r)
            {
                const float y = a.y + V.Len(gl::RowY(static_cast<int>(r)));
                pDL->AddCircleFilled(ImVec2(b.x, y), V.Len(4.0f), LifeColor(S.m_OutLife[r]));
                const bool bScratch = S.m_OutLife[r] == "scratch";
                pDL->AddText(pFont, Font, ImVec2(b.x - V.Len(8) - ImGui::CalcTextSize(S.m_Out[r].c_str()).x * V.m_Zoom, y - Font * 0.5f), bScratch ? IM_COL32(120, 120, 120, 255) : IM_COL32(230, 230, 230, 255), S.m_Out[r].c_str());
            }
        }
        if (Hover >= 0 && !Steps[std::size_t(Hover)].m_Recorded.empty())
        {
            // brown: not managed by the graph - a group of xGPU works declared as one (its inside not yet in the graph), or one render pass
            // whose barriers xGPU still places (declared, not scheduled by the graph)
            const auto& H = Steps[std::size_t(Hover)];
            const bool bGroup = H.m_Recorded.starts_with("group:");
            ImGui::SetTooltip("%s\nrecorded as: %s%s", H.m_Name.c_str(), H.m_Recorded.c_str(), H.m_bManaged ? "" : bGroup ? "\n(a group of passes declared as one: its inside is not in the graph yet)" : "\n(declared; its barriers are still placed by xGPU, not scheduled by the graph yet)");
        }
        ImGui::EndChild();
    }

    // pRender, pWorld: the Level whose last frame is shown (null: none open with a render module)
    inline void Draw(state& S, xlionrender::xRenderEditor* pRender, const void* pWorld, const edit_fn& EditFn) noexcept
    {
        if (!pRender || !pWorld) { ImGui::TextDisabled("No Level with a render module is open."); return; }
        if (!S.m_bFrozen && S.m_Refresh-- <= 0)
        {
            int n = pRender->DescribeGraph(pWorld, S.m_Buffer.data(), static_cast<int>(S.m_Buffer.size()));
            if (n >= static_cast<int>(S.m_Buffer.size())) { S.m_Buffer.resize(static_cast<std::size_t>(n) * 2); n = pRender->DescribeGraph(pWorld, S.m_Buffer.data(), static_cast<int>(S.m_Buffer.size())); }
            Parse(S, n > 0 ? std::string_view(S.m_Buffer.data(), std::min<std::size_t>(static_cast<std::size_t>(n), S.m_Buffer.size() - 1)) : std::string_view());
            S.m_Refresh = 30;
        }
        if (!ImGui::BeginTabBar("##rgviews")) return;
        if (ImGui::BeginTabItem("Post chain")) { ImGui::Checkbox("Freeze", &S.m_bFrozen); DrawPost(S, pRender, pWorld, EditFn); ImGui::EndTabItem(); }
        if (ImGui::BeginTabItem("Frame graph")) { ImGui::Checkbox("Freeze", &S.m_bFrozen); DrawFrameGraph(S); ImGui::EndTabItem(); }
        if (ImGui::BeginTabItem("Frame scopes")) { DrawScopes(S); ImGui::EndTabItem(); }
        ImGui::EndTabBar();
    }

    // Every scope of the last frame, what it reads and writes
    inline void DrawScopes(state& S) noexcept
    {

        // the bar: freeze, filter, counts, the selection
        ImGui::Checkbox("Freeze", &S.m_bFrozen);
        ImGui::SameLine(); ImGui::SetNextItemWidth(220);
        ImGui::InputTextWithHint("##rgfilter", "filter scopes and resources", S.m_Filter, sizeof(S.m_Filter));
        int nManaged = 0, nAccesses = 0;
        for (const auto& Sc : S.m_Scopes) { nManaged += Sc.m_bManaged; nAccesses += static_cast<int>(Sc.m_Accesses.size()); }
        ImGui::SameLine();
        ImGui::TextDisabled("%d scopes (%d managed, %d legacy groups), %d accesses", static_cast<int>(S.m_Scopes.size()), nManaged, static_cast<int>(S.m_Scopes.size()) - nManaged, nAccesses);
        if (!S.m_Selected.empty())
        {
            ImGui::SameLine(); ImGui::Text("| %s", S.m_Selected.c_str());
            ImGui::SameLine(); if (ImGui::SmallButton("clear")) S.m_Selected.clear();
        }
        if (S.m_Scopes.empty()) ImGui::TextDisabled("No frame declared yet (the Level has not rendered).");
        for (const auto& E : S.m_Errors) ImGui::TextColored(ImVec4(1.0f, 0.35f, 0.3f, 1.0f), "error: %s", E.c_str());

        const ImVec4 kWrite(1.0f, 0.62f, 0.25f, 1.0f), kRead(0.45f, 0.75f, 1.0f, 1.0f), kDim(0.6f, 0.6f, 0.6f, 1.0f);
        const std::string_view Filter(S.m_Filter);
        if (!ImGui::BeginTable("##rg", 6, ImGuiTableFlags_RowBg | ImGuiTableFlags_BordersInnerV | ImGuiTableFlags_ScrollY | ImGuiTableFlags_Resizable)) return;
        ImGui::TableSetupScrollFreeze(0, 1);
        ImGui::TableSetupColumn("scope / resource", ImGuiTableColumnFlags_WidthStretch);
        ImGui::TableSetupColumn("access");
        ImGui::TableSetupColumn("version");
        ImGui::TableSetupColumn("usage");
        ImGui::TableSetupColumn("content");
        ImGui::TableSetupColumn("lifetime");
        ImGui::TableHeadersRow();
        for (std::size_t s = 0; s < S.m_Scopes.size(); ++s)
        {
            const auto& Sc = S.m_Scopes[s];
            bool bShown = Filter.empty() || Contains(Sc.m_Name, Filter), bWrites = false, bReads = false;
            for (const auto& A : Sc.m_Accesses)
            {
                bShown |= !Filter.empty() && Contains(A.m_Res, Filter);
                if (A.m_Res == S.m_Selected) (A.m_bWrite ? bWrites : bReads) = true;
            }
            if (!bShown) continue;
            ImGui::PushID(static_cast<int>(s));
            ImGui::TableNextRow(); ImGui::TableNextColumn();
            if (bWrites || bReads) ImGui::PushStyleColor(ImGuiCol_Text, bWrites ? kWrite : kRead);
            const bool bOpen = ImGui::TreeNodeEx("##scope", ImGuiTreeNodeFlags_SpanFullWidth, "%s%s", Sc.m_Name.c_str(), Sc.m_bManaged ? "" : "   (legacy group)");
            if (bWrites || bReads) ImGui::PopStyleColor();
            if (ImGui::IsItemHovered() && !Sc.m_Recorded.empty()) ImGui::SetTooltip("recorded as: %s", Sc.m_Recorded.c_str());
            ImGui::TableNextColumn(); ImGui::TextDisabled("%s", bWrites ? "writes it" : bReads ? "reads it" : "");
            if (bOpen)
            {
                for (std::size_t a = 0; a < Sc.m_Accesses.size(); ++a)
                {
                    const auto& A = Sc.m_Accesses[a];
                    ImGui::PushID(static_cast<int>(a));
                    ImGui::TableNextRow(); ImGui::TableNextColumn();
                    ImGui::Indent();
                    ImGui::PushStyleColor(ImGuiCol_Text, A.m_Res == S.m_Selected ? (A.m_bWrite ? kWrite : kRead) : ImGui::GetStyleColorVec4(ImGuiCol_Text));
                    if (ImGui::Selectable(A.m_Res.c_str(), A.m_Res == S.m_Selected, ImGuiSelectableFlags_SpanAllColumns)) S.m_Selected = A.m_Res == S.m_Selected ? std::string() : A.m_Res;
                    ImGui::PopStyleColor();
                    ImGui::Unindent();
                    ImGui::TableNextColumn(); ImGui::TextColored(A.m_bWrite ? kWrite : kRead, "%s", A.m_bWrite ? "write" : "read");
                    ImGui::TableNextColumn(); ImGui::TextUnformatted(A.m_Version.c_str());
                    ImGui::TableNextColumn(); ImGui::TextUnformatted(A.m_Usage.c_str());
                    ImGui::TableNextColumn(); ImGui::TextUnformatted(A.m_Policy.c_str());
                    ImGui::TableNextColumn(); ImGui::TextColored(kDim, "%s", A.m_Life.c_str());
                    ImGui::PopID();
                }
                ImGui::TreePop();
            }
            ImGui::PopID();
        }
        ImGui::EndTable();
    }
}
