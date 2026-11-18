#ifndef XEDITOR_BONE_FIELD_H
#define XEDITOR_BONE_FIELD_H
#pragma once
// KUX1 (R66): a bone-name field of a component drawn as a picker of its skeleton's bones - a combo whose list is the skeleton's bone names
// (the skeleton compiler's own bone manifest, as the anim package editor reads it), filtered as you type, "(none)" to clear; what you pick
// is written through the inspector's BeginEdit / setProperty / CommitEdit (undoable, as any edit). The component says which skeleton by its
// "<Component>/SkeletonSeen" property (the Animation component's, set where its skin is posed); with none yet, or no manifest, the plain text
// field stays. Wired as an inspector's broadcast value renderer (xlevel_session.h). New because nothing shared listed a skeleton's bones as an
// inspector field (reuse_check "bone name picker": PickBone picks in a viewport, the resource pickers pick resources).
#include "dependencies/xproperty/source/examples/imgui/xPropertyImGuiInspector.h"
#include "dependencies/xtextfile/source/xtextfile.h"
#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_asset_mgr.h"     // (g_LibMgr: the open project)
#include "plugins/xskeleton.plugin/source/xskeleton_bone_manifest.h"
#include "imgui.h"
#include <algorithm>
#include <array>
#include <cctype>
#include <format>
#include <string>
#include <unordered_map>
#include <vector>

namespace xeditor::bone_field
{
    // The Animation component's bone fields
    inline constexpr std::array<std::string_view, 6> fields_v{ "Animation/Overlay/FromBone", "Animation/Springs/From", "Animation/Aim/Bone"
                                                             , "Animation/Copy/From", "Animation/Copy/To", "Animation/Offset/Bone" };
    inline bool IsBoneField(std::string_view Path) noexcept { return std::find(fields_v.begin(), fields_v.end(), Path) != fields_v.end(); }

    inline std::unordered_map<std::uint64_t, std::vector<std::string>> g_Names;            // per skeleton instance (empty: none found yet, asked again)

    inline const std::vector<std::string>& Names(std::uint64_t Skeleton) noexcept
    {
        auto& N = g_Names[Skeleton];
        const std::wstring& Project = xresource_editor::g_LibMgr.m_ProjectPath;
        if (!N.empty() || Project.empty()) return N;
        const auto Path = std::format(L"{}/Cache/Resources/Logs/Skeleton/{:02X}/{:02X}/{:X}.log/AnimPackage.txt", Project, Skeleton & 0xff, (Skeleton & 0xff00) >> 8, Skeleton);
        xtextfile::stream File; xproperty::settings::context C; xskeleton_desc::bone_manifest M;
        if (File.Open(true, Path, xtextfile::file_type::TEXT)) return N;
        if (xproperty::sprop::serializer::Stream(File, M, C)) return N;
        for (const auto& B : M.m_Bones) N.push_back(B.m_Name);
        return N;
    }

    // The skeleton of the component (its "<Component>/SkeletonSeen"), 0: none
    inline std::uint64_t SkeletonOf(void* pInstance, const xproperty::type::object& Obj, std::string_view Path) noexcept
    {
        const std::string Want = std::string(Path.substr(0, Path.find('/'))) + "/SkeletonSeen";
        std::uint64_t S = 0; xproperty::settings::context Context;
        xproperty::sprop::collector(pInstance, Obj, Context, [&](const char* pName, xproperty::any&& Data, const xproperty::type::members&, bool, const void*) noexcept
        {
            if (S == 0 && Want == pName) S = Data.get<std::uint64_t>();
        });
        return S;
    }

    inline void Draw(xproperty::inspector& Inspector, const xproperty::type::object& Obj, void* pInstance, std::string_view Path, const xproperty::any& Value, bool& bHandled) noexcept
    {
        const std::uint64_t Skeleton = SkeletonOf(pInstance, Obj, Path);
        if (Skeleton == 0) return;
        const auto& All = Names(Skeleton);
        if (All.empty()) return;
        bHandled = true;
        const std::string Now = Value.get<std::string>();
        const bool bKnown = Now.empty() || std::find(All.begin(), All.end(), Now) != All.end();
        ImGui::PushID(Path.data(), Path.data() + Path.size());
        if (!bKnown) ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(0.95f, 0.45f, 0.42f, 1.0f));       // (a name that is no bone of it: red, as a broken reference)
        ImGui::SetNextItemWidth(-1);
        const bool bOpen = ImGui::BeginCombo("##bone", Now.empty() ? "(none)" : Now.c_str(), ImGuiComboFlags_HeightLarge);
        if (!bKnown) { ImGui::PopStyleColor(); if (ImGui::IsItemHovered()) ImGui::SetTooltip("'%s' is not a bone of this character's skeleton", Now.c_str()); }
        if (bOpen)
        {
            static char Filter[64] = {};
            if (ImGui::IsWindowAppearing()) { Filter[0] = 0; ImGui::SetKeyboardFocusHere(); }
            ImGui::SetNextItemWidth(-1);
            ImGui::InputTextWithHint("##filter", "type to filter the bones", Filter, sizeof(Filter));
            auto Lower = [](std::string S) { for (auto& c : S) c = char(std::tolower(static_cast<unsigned char>(c))); return S; };
            const std::string F = Lower(Filter);
            auto Pick = [&](const std::string& Name)
            {
                std::string Error; xproperty::settings::context Context; xproperty::any V; V.set<std::string>(Name);
                Inspector.BeginEdit(Obj, pInstance, "Pick bone");
                xproperty::sprop::setProperty(Error, pInstance, Obj, xproperty::sprop::container::prop{ std::string(Path), V }, Context);
                Inspector.CommitEdit(Context);
            };
            if (F.empty() && ImGui::Selectable("(none)", Now.empty())) Pick({});
            for (const auto& N : All)
            {
                if (!F.empty() && Lower(N).find(F) == std::string::npos) continue;
                if (ImGui::Selectable(N.c_str(), N == Now)) Pick(N);
                if (N == Now && ImGui::IsWindowAppearing()) ImGui::SetScrollHereY();
            }
            ImGui::EndCombo();
        }
        ImGui::PopID();
    }
}

#endif
