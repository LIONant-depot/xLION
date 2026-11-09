#pragma once
// The drawer's Render Graph tab (R3a, xLION_Docs/render_graph_design_2026-11-09.md section 6): the render graph's declarations of a Level's
// last frame, read only - every scope in recording order (managed, or a legacy group), what it reads and writes (resource, version, usage,
// content policy, lifetime), and the declaration errors. A resource clicked: every scope that touches it lit, its writers orange and its
// readers blue - the graph's edges for that resource. The data: xlionrender::xRenderEditor::DescribeGraph (rg::graph::Text).
#include <algorithm>
#include <cctype>
#include <string>
#include <string_view>
#include <vector>

namespace level_editor::render_graph_tab
{
    struct access { bool m_bWrite = false; std::string m_Version, m_Usage, m_Policy, m_Life, m_Res; };
    struct scope  { bool m_bManaged = true; std::string m_Name, m_Recorded; std::vector<access> m_Accesses; };

    struct state
    {
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

    inline bool Contains(std::string_view Text, std::string_view Pattern) noexcept
    {
        return std::search(Text.begin(), Text.end(), Pattern.begin(), Pattern.end(),
            [](char a, char b) { return std::tolower(static_cast<unsigned char>(a)) == std::tolower(static_cast<unsigned char>(b)); }) != Text.end();
    }

    // pRender, pWorld: the Level whose last frame is shown (null: none open with a render module)
    inline void Draw(state& S, xlionrender::xRenderEditor* pRender, const void* pWorld) noexcept
    {
        if (!pRender || !pWorld) { ImGui::TextDisabled("No Level with a render module is open."); return; }
        if (!S.m_bFrozen && S.m_Refresh-- <= 0)
        {
            int n = pRender->DescribeGraph(pWorld, S.m_Buffer.data(), static_cast<int>(S.m_Buffer.size()));
            if (n >= static_cast<int>(S.m_Buffer.size())) { S.m_Buffer.resize(static_cast<std::size_t>(n) * 2); n = pRender->DescribeGraph(pWorld, S.m_Buffer.data(), static_cast<int>(S.m_Buffer.size())); }
            Parse(S, n > 0 ? std::string_view(S.m_Buffer.data(), std::min<std::size_t>(static_cast<std::size_t>(n), S.m_Buffer.size() - 1)) : std::string_view());
            S.m_Refresh = 30;
        }

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
