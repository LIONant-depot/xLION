#ifndef XEDITOR_INSPECTOR_H
#define XEDITOR_INSPECTOR_H
#pragma once

// Shared ImGui property-inspector helper for the editor framework. Every open editor
// session owns its OWN instance (never a static shared across sessions). Thin wrapper
// around xproperty::inspector so Texture/Material/... editors do not re-copy the same
// AppendEntity / theme / ShowEmbedded boilerplate.
#include "dependencies/xeditor/include/xeditor/hint.h"
#include <algorithm>
#include <format>
#include <string>
#include <unordered_map>
#include "dependencies/xproperty/source/examples/imgui/xPropertyImGuiInspector.h"

namespace xeditor
{
    // The help of a property is the editors' hint (xeditor/hint.h): the property's name as the topic, its help text as the body, the reason it is
    // unavailable when it is, and the type and path as the small print. Every editor's inspector uses it, so a property hint looks like any other.
    inline void BindInspectorHints(xproperty::inspector& Inspector) noexcept
    {
        Inspector.m_OnHelp.Register<+[](xproperty::inspector&, const xproperty::inspector::help_info& H, bool& bHandled)
        {
            const std::string Detail = std::format("{}  -  {}", H.m_pTypeName, H.m_Path);
            hint::Draw({ H.m_pName
                       , (H.m_pHelp && std::string_view(H.m_pHelp) != "<<No help>>") ? std::string_view(H.m_pHelp) : std::string_view{}
                       , {}
                       , H.m_pDisabledReason ? std::string_view(H.m_pDisabledReason) : std::string_view{}
                       , Detail });
            bHandled = true;
        }>();
    }

    // The lock toggle of a scale row (the Level Editor's Transform/Scale "Lock"): after the row's label, a right-aligned frameless
    // "Link" glyph, accent when locked and dim when not. True when clicked. Every scale-like vec3 property draws this one.
    inline bool ScaleLockToggle(const bool bLocked, const bool bDisabled = false) noexcept
    {
        ImGui::SameLine();
        const char* pIcon = "\xEE\x9C\x9B";                      // the "Link" glyph, the same as xlevel::DependenciesIcon (the Level Tree Dependencies row)
        const float W     = ImGui::CalcTextSize(pIcon).x + ImGui::GetStyle().FramePadding.x * 2.0f;
        ImGui::SetCursorPosX(ImGui::GetCursorPosX() + std::max(0.0f, ImGui::GetContentRegionAvail().x - W));
        // Frameless: transparent button, the glyph colour carries the state.
        ImGui::PushStyleColor(ImGuiCol_Button,        ImVec4(0, 0, 0, 0));
        ImGui::PushStyleColor(ImGuiCol_ButtonHovered, ImVec4(0, 0, 0, 0));
        ImGui::PushStyleColor(ImGuiCol_ButtonActive,  ImVec4(0, 0, 0, 0));
        ImGui::PushStyleColor(ImGuiCol_Text, bLocked ? ImVec4(0.35f, 0.65f, 1.0f, 1.0f) : ImGui::GetStyleColorVec4(ImGuiCol_TextDisabled));
        ImGui::BeginDisabled(bDisabled);
        const bool bClicked = ImGui::SmallButton(pIcon);
        ImGui::EndDisabled();
        ImGui::PopStyleColor(4);
        xproperty::inspector::Tooltip("Lock scale: editing one axis scales all three proportionally");
        return bClicked;
    }

    // Every "<...>/Scale" row whose object has a bool "<...>/EditorLockScale" next to it (see xmath::LockedScaleAxis: the setters
    // that scale proportionally while it is on) gets the lock toggle. A plain field write, like the Level Editor's: not undoable,
    // saved with the object's next save. Every inspector_panel has it (the resource editors' Descriptor panels).
    inline void WireScaleLockToggle(xproperty::inspector& Inspector) noexcept
    {
        Inspector.m_OnLeftColumnAppend.Register<+[](xproperty::inspector& Inspector, const xproperty::type::object& Obj, void* pInstance, std::string_view Path)
        {
            constexpr std::string_view scale_v = "/Scale";
            if (!Path.ends_with(scale_v)) return;

            // The locks of each object, collected once a frame (an object can have many Scale rows: a skeleton's bones)
            static int                                                               s_Frame = -1;
            static std::unordered_map<const void*, std::unordered_map<std::string, bool>> s_Locks;
            if (s_Frame != ImGui::GetFrameCount()) { s_Frame = ImGui::GetFrameCount(); s_Locks.clear(); }
            auto [ItObj, bNew] = s_Locks.try_emplace(pInstance);
            if (bNew)
            {
                xproperty::settings::context Context;
                xproperty::sprop::collector(pInstance, Obj, Context, [&](const char* pName, xproperty::any&& Value, const xproperty::type::members&, bool, const void*) noexcept
                {
                    if (std::string_view(pName).ends_with("/EditorLockScale") && Value.is<bool>()) ItObj->second.emplace(pName, Value.get<bool>());
                }, false
                , [&](const char* pListPath, std::size_t Count, const xproperty::type::members& Member) { return Inspector.getListWalk(pListPath, Count, Member); });  // a folded list has no Scale row shown
            }

            const std::string LockPath = std::string(Path.substr(0, Path.size() - scale_v.size())) + "/EditorLockScale";
            auto It = ItObj->second.find(LockPath);
            if (It == ItObj->second.end()) return;
            if (ScaleLockToggle(It->second))
            {
                std::string                  Error;
                xproperty::settings::context Context;
                xproperty::any               Value;
                Value.set<bool>(!It->second);
                xproperty::sprop::setProperty(Error, pInstance, Obj, xproperty::sprop::container::prop{ LockPath, Value }, Context);
                if (Error.empty()) It->second = !It->second;
            }
        }>();
    }

    // Same inspector chrome the Level Editor Entity Properties panel uses.
    // Row tint off + tight Unity-like spacing - not xresource_editor's ColorVScalar readability multipliers.
    inline void ApplyLevelEditorInspectorTheme(xproperty::inspector& Inspector) noexcept
    {
        Inspector.m_Settings.m_bRenderBackgroundDepth = false;
        Inspector.m_Settings.m_bRenderLeftBackground  = false;
        Inspector.m_Settings.m_bRenderRightBackground = false;
        Inspector.m_Settings.m_FramePadding            = ImVec2(4.0f, 3.0f);
        Inspector.m_Settings.m_ItemSpacing             = ImVec2(1.0f, 1.0f);
        Inspector.m_Settings.m_TableFramePadding       = ImVec2(4.0f, 1.0f);
        BindInspectorHints(Inspector);
    }

    // Mirror Entity Properties: framed headers use ImGuiCol_Header, but LevelEditor_Theme sets that to
    // selection blue. Push the slightly-lighter grey (Inspector Titlebar #3E3E3E) while showing.
    inline void PushLevelEditorInspectorHeaderColors() noexcept
    {
        ImGui::PushStyleColor(ImGuiCol_Header,        ImVec4(0x3E / 255.0f, 0x3E / 255.0f, 0x3E / 255.0f, 1.0f));
        ImGui::PushStyleColor(ImGuiCol_HeaderHovered, ImVec4(0x4A / 255.0f, 0x4A / 255.0f, 0x4A / 255.0f, 1.0f));
        ImGui::PushStyleColor(ImGuiCol_HeaderActive,  ImVec4(0x4A / 255.0f, 0x4A / 255.0f, 0x4A / 255.0f, 1.0f));
    }

    inline void PopLevelEditorInspectorHeaderColors() noexcept
    {
        ImGui::PopStyleColor(3);
    }

    struct inspector_panel
    {
        xproperty::inspector            m_Inspector;
        xproperty::settings::context    m_Context{};

        explicit inspector_panel(const char* Name) noexcept : m_Inspector(Name)
        {
            ApplyLevelEditorInspectorTheme(m_Inspector);
            WireScaleLockToggle(m_Inspector);
        }

        void Clear() noexcept
        {
            m_Inspector.clear();
        }

        void BindObject(const xproperty::type::object& PropObject, void* pBase, void* pUserData = nullptr) noexcept
        {
            m_Inspector.clear();
            m_Inspector.AppendEntity();
            m_Inspector.AppendEntityComponent(PropObject, pBase, pUserData);
        }

        void AppendComponent(const xproperty::type::object& PropObject, void* pBase, void* pUserData = nullptr) noexcept
        {
            m_Inspector.AppendEntityComponent(PropObject, pBase, pUserData);
        }

        template<typename TFn>
        void OnChange(TFn&& Fn) noexcept
        {
            m_Inspector.m_OnChangeEvent.m_Delegates.clear();
            m_Inspector.m_OnChangeEvent.Register<&std::decay_t<TFn>::operator()>(Fn);
        }

        void Show() noexcept
        {
            PushLevelEditorInspectorHeaderColors();
            m_Inspector.ShowEmbedded(m_Context);
            PopLevelEditorInspectorHeaderColors();
        }
    };
}

#endif // XEDITOR_INSPECTOR_H