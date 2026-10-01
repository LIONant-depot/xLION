#pragma once

// The Assets tab's file keys as actions (see files_actions in LevelEditor_App.h): what the tab did on F2 / Ctrl+X / Ctrl+C / Ctrl+V / Delete
// when it read those keys itself (xresource_editor_asset_browser_files_tab.h; it still does when m_bFileKeysByHost is off). Included after the tab
// header, because the bodies need the tab's members.
namespace level_editor
{
    namespace details
    {
        inline xresource_editor::files_tab* Tab(const files_actions& A) noexcept { return static_cast<xresource_editor::files_tab*>(A.m_pTab); }

        inline const char* WhyNoFileOp(const files_actions& A) noexcept
        {
            auto* pTab = Tab(A);
            if (!pTab)                    return "the Assets tab is not showing";
            if (pTab->m_bBrowsingTrash)   return "not in the trash";
            return nullptr;
        }
    }

    inline const char* files_actions::WhyNoRename() const noexcept
    {
        if (auto* Why = details::WhyNoFileOp(*this)) return Why;
        auto* pTab = details::Tab(*this);
        return (pTab->m_MultiSelected.size() == 1 && !pTab->m_SelectedFile.empty()) ? nullptr : "select one file";
    }
    inline void files_actions::Rename() noexcept
    {
        auto* pTab = details::Tab(*this);
        pTab->StartRename(pTab->m_SelectedLibrary, pTab->m_SelectedFolder / pTab->m_SelectedFile);
    }

    inline const char* files_actions::WhyNoCut() const noexcept
    {
        if (auto* Why = details::WhyNoFileOp(*this)) return Why;
        return details::Tab(*this)->m_MultiSelected.empty() ? "nothing selected" : nullptr;
    }
    inline const char* files_actions::WhyNoCopy()   const noexcept { return WhyNoCut(); }
    inline const char* files_actions::WhyNoDelete() const noexcept { return WhyNoCut(); }
    inline void files_actions::Cut()    noexcept { details::Tab(*this)->CutSelection(); }
    inline void files_actions::Copy()   noexcept { details::Tab(*this)->CopySelection(); }
    inline void files_actions::Delete() noexcept { details::Tab(*this)->DeleteSelectionToTrash(); }

    inline const char* files_actions::WhyNoPaste() const noexcept
    {
        if (auto* Why = details::WhyNoFileOp(*this)) return Why;
        return details::Tab(*this)->m_Clipboard.empty() ? "nothing to paste" : nullptr;
    }
    inline void files_actions::Paste() noexcept { details::Tab(*this)->PasteClipboard(); }

    // The Project Settings inspector (the asset browser's plugin tab) is a library's: its property help becomes the editors' hint window, like every
    // other inspector. Done once, when the tab exists.
    inline void app::BindProjectSettingsHints()
    {
        if (m_bProjectSettingsHints) return;
        if (auto* pPlugin = AssetBrowser.FindTab<xresource_editor::plugin_tab>()) { xeditor::BindInspectorHints(*pPlugin); m_bProjectSettingsHints = true; }
    }

    // "Show in keymap" on a pinned card: the drawer open on its Project Settings tab (7), at the Keymap section.
    inline void app::WireKeymapNavigation()
    {
        Actions.m_OnShowInKeymap = [this](const std::string&)
        {
            EditorHost.open_drawer_tab(ImGui::GetMainViewport(), 7);
            if (auto* pPlugin = AssetBrowser.FindTab<xresource_editor::plugin_tab>())
                for (int i = 0; i < static_cast<int>(AssetBrowser.m_ExtraPluginTabSections.size()); ++i)
                    if (AssetBrowser.m_ExtraPluginTabSections[i].m_Label == "Keymap") pPlugin->m_SelectedExtraIndex = i;
        };
    }

    // Called every frame the Assets tab of the drawer is drawn: its files_tab, and the actions live while that window has the focus.
    inline void app::BindFilesActions()
    {
        FilesActions.m_pTab = AssetBrowser.FindTab<xresource_editor::files_tab>();
        Actions.Scope(FilesActions);
    }
}
