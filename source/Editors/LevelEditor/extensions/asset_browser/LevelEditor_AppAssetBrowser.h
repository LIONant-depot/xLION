#pragma once

// level_editor::app: wiring between the Asset Browser and the editor.
namespace level_editor
{
    // Everything the Asset Browser needs from the editor: command-routed mutations, source-control badges and locks,
    // open-asset routing (Level / Texture), and the extra Project Settings sections.
    inline void app::WireAssetBrowser()
    {
        xresource_editor::RegisterAssetBrowserCallbacks(AssetBrowser, EditorHost.m_Workspace, IdleLevel ? IdleLevel->m_Undo : EditorHost.m_Workspace, MainWindow);
        xresource_editor::RegisterSourceControlCallbacks(AssetBrowser, EditorHost.m_Workspace);

        // "Keymap" section: every action's keys as an xproperty inspector (dependencies/actions.imgui), saved in this person's own
        // Project.config\Keymaps\<user>.keymap.txt. It has its own inspector; the tab's is shared with the other sections.
        AssetBrowser.m_ExtraPluginTabSections.push_back(
        {
            "Keymap",
            [this](xproperty::inspector& Tab) { ximgui::actions::DrawKeymapPage(Actions, Tab); }
        });

        // Double-click: a resource type with a registered editor (Level, Texture, Static Geom, ...) opens in its own window,
        // and every other type keeps today's inert setSelection-only default. A Level is queued rather than opened right
        // here: a new Level editor builds a world, which waits for a clean point of the frame (PumpLevels).
        AssetBrowser.m_OnOpenAsset = [this](xresource_editor::library::guid LibraryGuid, xresource::full_guid AssetGuid)
            {
                if (AssetGuid.m_Type == xecs::level::type_guid_v || AssetGuid.m_Type == xecs::prefab::type_guid_v || AssetGuid.m_Type == xecs::scene::type_guid_v)        // a Level, or a Prefab in its own editor (a Prefab Editor), or a Scene (a Scene Editor)
                {
                    xlevel::QueueOpenLevel(AssetGuid);
                    return;
                }
                ResourceEditors.Open(AssetGuid, LibraryGuid);
            };

        // The Save All of the resource view's menu: the editor's Save All (what the other resource editors' menus do too).
        AssetBrowser.m_OnSaveAll = [] { (void)xeditor::SaveAllNow(); };

        // Per-resource thumbnails (Texture today; any other type that registers a xeditor::thumbnail_renderer
        // going forward) - same dependency-inversion shape as m_OnOpenAsset just above.
        xeditor::g_ThumbnailCache.Init(MainWindow);
        AssetBrowser.m_OnRequestThumbnail = [this](xresource::full_guid AssetGuid) -> xresource_editor::plugin_icon_ref
            {
                if (!ResourceEditors.m_pDevice) return {};
                return xeditor::g_ThumbnailCache.RequestThumbnail(*ResourceEditors.m_pDevice, AssetGuid);
            };

        // The resource reference of every inspector (xresource_editor::RenderResourceReference) asks the application for the picture of the resource, its editor, and its place in the resource
        // browser. Opening is what a double click in the browser does; finding it makes the Resources tab of the drawer show it (and opens the drawer on that tab: it stays open).
        auto& Reference = xresource_editor::g_ReferenceHost;
        Reference.m_Thumbnail = AssetBrowser.m_OnRequestThumbnail;
        Reference.m_HasEditor = [](xresource::type_guid Type) { return Type == xecs::level::type_guid_v || xeditor::open_resource_editors::HasEditorFor(Type); };
        Reference.m_OpenEditor = [this](xresource::full_guid Guid)
            {
                if (const auto Library = xeditor::open_resource_editors::FindLibraryOf(Guid); !Library.empty()) AssetBrowser.m_OnOpenAsset(Library, Guid);
            };
        Reference.m_Locate = [this](xresource::full_guid Guid)
            {
                if (!AssetBrowser.RevealResource(Guid)) return false;
                xeditor::drawer& Drawer = EditorHost.drawer_for(xeditor::FocusedDrawerViewport()->ID);
                Drawer.m_bOpen = true;
                Drawer.m_ActiveTab = Drawer.m_RequestTab = 0;                       // Resources
                return true;
            };

        // The asset reference (the source file of a descriptor, xresource_editor::RenderAssetReference) is the twin of that one: opening is what a double click on the file in the Assets tab does
        // (lock-before-edit included); finding it makes the Assets tab of the drawer show it, and opens the drawer on that tab.
        auto& AssetReference = xresource_editor::g_AssetReferenceHost;
        AssetReference.m_Open   = [this](const std::wstring& Path) { return AssetBrowser.OpenAssetFile(Path); };
        AssetReference.m_Locate = [this](const std::wstring& Path)
            {
                if (!AssetBrowser.RevealAssetFile(Path)) return false;
                xeditor::drawer& Drawer = EditorHost.drawer_for(xeditor::FocusedDrawerViewport()->ID);
                Drawer.m_bOpen = true;
                Drawer.m_ActiveTab = Drawer.m_RequestTab = 1;                       // Assets
                return true;
            };
        xresource_editor::InstallAssetFileWidget();
    }
}
