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

        // "Scripting" section in the merged Plugins/Project Settings tab (xresource_editor::plugin_tab,
        // xresource_editor_asset_browser_plugin_tab.h) - the project's Script-Module build-membership list
        // (Project.config\Script.config.txt, xlevel::g_ScriptConfig.m_ModuleRefs), rendered as a normal
        // xproperty::inspector array field. Reuses plugin_tab's OWN inherited xproperty::inspector (passed in by
        // RightPanel()) rather than carrying a second, redundant instance.
        AssetBrowser.m_ExtraPluginTabSections.push_back(
        {
            "Scripting",
            [](xproperty::inspector& Inspector)
            {
                static bool bWired = false;
                if (!bWired) { xresource_editor::WireResourcePickerCallbacks(Inspector); bWired = true; }

                // Rebuild ONLY when the data actually changed (never unconditionally - see
                // xgpu_imgui_per_frame_rebuild_activeid_bug), whether from this same UI or an external CLI command.
                static std::vector<xresource::full_guid> s_BuiltWith;
                if (xlevel::g_ScriptConfig.m_ModuleRefs != s_BuiltWith)
                {
                    Inspector.clear();
                    Inspector.AppendEntity();
                    Inspector.AppendEntityComponent(*xproperty::getObjectByType<xlevel::script_config>(), &xlevel::g_ScriptConfig);
                }

                // Separate, frame-local snapshot - did THIS ShowEmbedded call itself edit the array?
                const auto BeforeThisRender = xlevel::g_ScriptConfig.m_ModuleRefs;

                xproperty::settings::context Context;
                Inspector.ShowEmbedded(Context);

                if (xlevel::g_ScriptConfig.m_ModuleRefs != BeforeThisRender)
                {
                    if (auto Err = xlevel::SaveScriptConfig(xresource_editor::g_LibMgr.m_ProjectPath, xlevel::g_ScriptConfig); Err)
                        xeditor::NotifyError(std::format("Failed to save Script.config.txt: {}", Err.getMessage()));
                    if (xlevel::g_pGamePlugin) xlevel::RegenerateGameModuleSources(xlevel::g_pGamePlugin->m_Paths);
                }
                s_BuiltWith = xlevel::g_ScriptConfig.m_ModuleRefs;
            }
        });

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
