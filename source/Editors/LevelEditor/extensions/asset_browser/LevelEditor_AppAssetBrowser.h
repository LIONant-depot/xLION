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
                if (AssetGuid.m_Type == xecs::level::type_guid_v)
                {
                    xlevel::QueueOpenLevel(AssetGuid);
                    return;
                }
                ResourceEditors.Open(AssetGuid, LibraryGuid);
            };

        // Per-resource thumbnails (Texture today; any other type that registers a xeditor::thumbnail_renderer
        // going forward) - same dependency-inversion shape as m_OnOpenAsset just above.
        xeditor::g_ThumbnailCache.Init(MainWindow);
        AssetBrowser.m_OnRequestThumbnail = [this](xresource::full_guid AssetGuid) -> xresource_editor::plugin_icon_ref
            {
                if (!ResourceEditors.m_pDevice) return {};
                return xeditor::g_ThumbnailCache.RequestThumbnail(*ResourceEditors.m_pDevice, AssetGuid);
            };
    }
}
