#ifndef LevelEditor_COMMANDS_RESOURCE_EDITORS_H
#define LevelEditor_COMMANDS_RESOURCE_EDITORS_H
#pragma once

// LevelEditor hosts the resource editors of the plugins (Texture, Static Geom, ...): each one is a window with its own document and undo system,
// kept in xeditor::open_resource_editors. Including a plugin's editor header registers its factory. Open editors are also listed in
// xeditor::host, so `list` and Name\Command reach them like the Level; the two commands below are the guid-addressed way in.

#include "Plugins/xtexture.plugin/source/Editor/xtexture_editor.h"
#include "plugins/xgeom_static.plugin/source/Editor/xgeom_static_editor.h"
#include "plugins/xmaterial_instance.plugin/source/Editor/xmaterial_instance_editor.h"
#include "plugins/xmaterial.plugin/source/Editor/xmaterial_editor.h"
#include "plugins/xfont.plugin/source/Editor/xfont_editor.h"
#include "plugins/xanim_package.plugin/source/Editor/xanim_package_editor.h"
#include "plugins/xgeom_skin.plugin/source/Editor/xgeom_skin_editor.h"
#include "plugins/xskeleton.plugin/source/Editor/xskeleton_editor.h"
#include "plugins/xPhysicsMaterial.plugin/source/Editor/xphysics_material_editor.h"
#include "plugins/xscript_module.plugin/source/Editor/xscript_module_editor.h"
#include "plugins/xgame.plugin/source/Editor/xgame_editor.h"
#include "plugins/xlevel.plugin/source/Editor/xlevel_command_context.h"
#include "dependencies/xeditor/include/xeditor/host.h"
#include "source/Editors/LevelEditor/extensions/command_console/LevelEditor_CommandConsolePipe.h"

namespace level_editor
{
    // A picture of the whole window, for whoever drives the editor by commands and wants to see it. The capture happens when the next frame is
    // presented: the app calls BeforeFlip and AfterFlip around the page flip.
    struct window_capture
    {
        bool                        m_bPending   = false;       // a capture was asked for
        bool                        m_bRequested = false;       // the window was told to capture this frame
        std::wstring                m_Path;
        std::vector<std::uint32_t>  m_Pixels;
        int                         m_Width = 0, m_Height = 0;

        void BeforeFlip(xgpu::window& Window) noexcept
        {
            if (m_bPending && !m_bRequested) m_bRequested = Window.Screenshot(m_Pixels, m_Width, m_Height);
        }

        // The file appears complete or not at all: it is written under a temporary name and renamed
        void AfterFlip() noexcept
        {
            if (!m_bRequested) return;
            m_bPending = m_bRequested = false;
            if (m_Width <= 0 || m_Height <= 0 || m_Pixels.size() < static_cast<std::size_t>(m_Width) * m_Height) return;

            // An xbitmap of raw pixels starts with the offset of its first mip: one slot ahead of the pixels. The alpha of a back buffer is
            // whatever the pipeline left there, so it is made opaque.
            std::vector<std::uint32_t> Padded(1 + static_cast<std::size_t>(m_Width) * m_Height);
            Padded[0] = sizeof(xbitmap::mip);
            for (std::size_t i = 0; i < static_cast<std::size_t>(m_Width) * m_Height; ++i) Padded[1 + i] = m_Pixels[i] | 0xFF000000u;

            xbitmap Bitmap;
            Bitmap.setup(m_Width, m_Height, xbitmap::format::B8G8R8A8, static_cast<std::uint64_t>(m_Width) * m_Height * sizeof(std::uint32_t), std::as_writable_bytes(std::span(Padded)), false, 1, 1);

            std::filesystem::path Final(m_Path);
            std::filesystem::path Temp = Final;
            Temp.replace_extension(L".part" + Final.extension().wstring());
            if (xbmp::tools::writers::SaveSTDImage(Temp.wstring(), Bitmap)) return;
            std::error_code Ec;
            std::filesystem::rename(Temp, Final, Ec);
            if (Ec) { std::filesystem::remove(Final, Ec); std::filesystem::rename(Temp, Final, Ec); }
        }
    };

    inline window_capture g_WindowCapture;
}

namespace level_editor::commands
{
    inline xeditor::open_resource_editors* FindResourceEditors() noexcept
    {
        auto* pHost = xeditor::host::current();
        return pHost ? pHost->find<xeditor::open_resource_editors>() : nullptr;
    }

    // Shows the file a component or a system is defined in: the module's editor is opened (or brought to the front) and its viewer shows the file; a type of the engine has its file handed
    // to the system. What a click on the module tag of a component header, or "Open ..." of the System Registry's menu, does.
    inline bool OpenTypeSource(const xscene::type_source& Source) noexcept
    {
        if (Source.m_Path.empty()) return false;
        if (Source.m_Module)
            if (auto* pEditors = FindResourceEditors())
            {
                const xresource::full_guid Asset{ xresource::instance_guid{ Source.m_Module }, xscript::module::type_guid_v };
                if (const auto Library = xeditor::open_resource_editors::FindLibraryOf(Asset); !Library.empty()) pEditors->Open(Asset, Library);
            }
        xeditor::OpenRef(xlog::ref{ xlog::ref::type::File, Source.m_Path, 0, 0, 0, 0 });
        return true;
    }
    inline const bool g_TypeSourceOpener = (xscene::g_OpenTypeSource = &OpenTypeSource, true);

    // The same file in the Visual Studio of the active Level's game project (see xlevel_visual_studio.h).
    inline std::string OpenTypeSourceInVisualStudio(const xscene::type_source& Source, bool bDryRun) noexcept
    {
        auto* pLevel = xlevel::FindLevelContext();
        if (!pLevel) return "no Level is open";
        if (Source.m_Path.empty()) return "the type has no file";
        return xlevel::RequestOpenFileInVisualStudio(*pLevel, std::filesystem::path(Source.m_Path), bDryRun);
    }
    inline const bool g_TypeSourceVisualStudioOpener = (xscene::g_OpenTypeSourceInVisualStudio = &OpenTypeSourceInVisualStudio, true);

    // OpenTypeSource -Guid hex16 [-System true]: the same, by the guid of the component (or of the system, with -System true): what the AI and the tests use instead of the mouse.
    struct open_type_source_cmd : xlevel::commands::level_query_command
    {
        open_type_source_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "OpenTypeSource", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Shows the file a component (or, with -System true, a system) is defined in: the module's editor opens at it, or with -In VisualStudio the Visual Studio of the Level's game project (-DryRun true only says what it would do). Usage: OpenTypeSource -Guid hexguid [-System true] [-In Module|VisualStudio] [-DryRun true]"; }
        void RegisterArguments() noexcept override
        {
            m_hGuid   = m_Parser.addOption("Guid",   "The guid of the component or the system, 16 hex digits", true, 1);
            m_hSystem = m_Parser.addOption("System", "true: it is a system", false, 1);
            m_hIn     = m_Parser.addOption("In",     "Module (default): the module's editor; VisualStudio: the Visual Studio of the game project", false, 1);
            m_hDryRun = m_Parser.addOption("DryRun", "true: only say what opening in Visual Studio would do", false, 1);
        }
        std::string Query() noexcept override
        {
            auto GuidArg = m_Parser.getOptionArgAs<std::string>(m_hGuid, 0);
            if (std::holds_alternative<xerr>(GuidArg)) return "OpenTypeSource: bad arguments";
            const std::uint64_t Guid = std::strtoull(std::get<std::string>(GuidArg).c_str(), nullptr, 16);
            auto SystemArg = m_Parser.getOptionArgAs<std::string>(m_hSystem, 0);
            const bool bSystem = !std::holds_alternative<xerr>(SystemArg) && std::get<std::string>(SystemArg) == "true";

            const auto Source = LevelContext().Display().SourceOf(bSystem, Guid);
            if (!Source.m_bKnown)   return "OpenTypeSource: nothing is known about where types come from (is Game.dll loaded, and recent enough?)";
            if (Source.m_bBuiltIn)  return std::format("OpenTypeSource: {:016X} is built in (the engine's or the editor's own): no module defines it", Guid);
            auto InArg = m_Parser.getOptionArgAs<std::string>(m_hIn, 0);
            const std::string In = std::holds_alternative<xerr>(InArg) ? std::string("Module") : std::get<std::string>(InArg);
            if (In == "VisualStudio")
            {
                auto DryArg = m_Parser.getOptionArgAs<std::string>(m_hDryRun, 0);
                const bool bDryRun = !std::holds_alternative<xerr>(DryArg) && (std::get<std::string>(DryArg) == "true" || std::get<std::string>(DryArg) == "1");
                return "OpenTypeSource: " + OpenTypeSourceInVisualStudio(Source, bDryRun);
            }
            if (In != "Module") return "OpenTypeSource: -In is Module or VisualStudio";
            if (!OpenTypeSource(Source)) return "OpenTypeSource: the type has no file";
            return std::format("OpenTypeSource: ok\nModule={}\nFile={}\nPath={}", Source.m_ModuleName, Source.m_File, Source.m_Path);
        }
        xcmdline::parser::handle m_hGuid, m_hSystem, m_hIn, m_hDryRun;
    };

    struct open_resource_editor_cmd : xlevel::commands::level_query_command
    {
        open_resource_editor_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "OpenResourceEditor", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Opens the editor of a resource (Texture, GeomStatic, ...) in its own dock-isolated window, or focuses it when it is already open. Usage: OpenResourceEditor -Asset assetguid [-Library hexguid]"; }
        void RegisterArguments() noexcept override
        {
            m_hLibrary = m_Parser.addOption("Library", "Library instance guid, 16 hex digits (default: the library that has the resource)", false, 1);
            m_hAsset   = m_Parser.addOption("Asset",   "Resource guid, 32 hex digits",                                                       true,  1);
        }
        std::string Query() noexcept override
        {
            auto AssetArg = m_Parser.getOptionArgAs<std::string>(m_hAsset, 0);
            if (std::holds_alternative<xerr>(AssetArg)) return "OpenResourceEditor: bad arguments";

            auto* pEditors = FindResourceEditors();
            if (!pEditors) return "OpenResourceEditor: no editor host";

            const auto AssetGuid = xresource_editor::commands::ParseAssetGuid(std::get<std::string>(AssetArg));
            if (!xeditor::open_resource_editors::HasEditorFor(AssetGuid.m_Type)) return "OpenResourceEditor: this resource type has no editor";

            auto LibraryGuid = xeditor::open_resource_editors::FindLibraryOf(AssetGuid);
            if (m_Parser.hasOption(m_hLibrary))
            {
                auto LibraryArg = m_Parser.getOptionArgAs<std::string>(m_hLibrary, 0);
                if (std::holds_alternative<xerr>(LibraryArg)) return "OpenResourceEditor: bad arguments";
                LibraryGuid = xresource_editor::commands::ParseLibraryGuid(std::get<std::string>(LibraryArg));
            }
            if (LibraryGuid.empty()) return "OpenResourceEditor: no open library has that resource";

            auto* pEditor = pEditors->Open(AssetGuid, LibraryGuid);
            return pEditor && pEditor->isLoaded() ? "" : "OpenResourceEditor: failed to load the descriptor";
        }
        xcmdline::parser::handle m_hLibrary, m_hAsset;
    };

    struct capture_window_cmd : xlevel::commands::level_query_command
    {
        capture_window_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "CaptureWindow", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Saves a picture of the whole editor window (png, bmp, tga or jpg by the extension). The file appears when the next frame is presented. Usage: CaptureWindow -File path"; }
        void RegisterArguments() noexcept override { m_hFile = m_Parser.addOption("File", "Where to write the picture", true, 1); }
        std::string Query() noexcept override
        {
            auto FileArg = m_Parser.getOptionArgAs<std::string>(m_hFile, 0);
            if (std::holds_alternative<xerr>(FileArg)) return "CaptureWindow: bad arguments";
            const std::filesystem::path Path = xstrtool::To(std::get<std::string>(FileArg));
            if (Path.extension().empty()) return "CaptureWindow: the file needs an extension (png, bmp, tga or jpg)";
            if (g_WindowCapture.m_bPending) return "CaptureWindow: a capture is already waiting for the next frame";
            std::error_code Ec;
            if (Path.has_parent_path()) std::filesystem::create_directories(Path.parent_path(), Ec);
            std::filesystem::remove(Path, Ec);
            g_WindowCapture.m_Path     = Path.wstring();
            g_WindowCapture.m_bPending = true;
            return "CaptureWindow: queued, the file appears when the next frame is presented";
        }
        xcmdline::parser::handle m_hFile;
    };

    // CloseResourceEditor: the editor menu's Close. Without -Save it closes the editor and drops what was not saved (what a script wants); with -Save it does what a person is offered:
    //   -Save true     saves the changes, then closes (an editor that cannot save stays open and says why)
    //   -Save false    closes and drops them
    //   -Save ask      what the menu's Close does: closes at once when nothing is pending, otherwise opens the question (Save / Don't Save / Cancel) and leaves the editor open
    //   -Save cancel   answers that question with Cancel
    struct close_resource_editor_cmd : xlevel::commands::level_query_command
    {
        close_resource_editor_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "CloseResourceEditor", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Closes the editor of a resource, like the editor menu's Close. Without -Save the changes that are not saved are dropped; -Save true saves them first, false drops them, ask opens the question a person is asked, cancel answers it with Cancel. Usage: CloseResourceEditor -Asset assetguid [-Save true|false|ask|cancel]"; }
        void RegisterArguments() noexcept override
        {
            m_hAsset = m_Parser.addOption("Asset", "Resource guid, 32 hex digits", true, 1);
            m_hSave  = m_Parser.addOption("Save", "true: save first, false: drop the changes, ask: ask as the menu does, cancel: answer the question with Cancel", false, 1);
        }
        std::string Query() noexcept override
        {
            auto AssetArg = m_Parser.getOptionArgAs<std::string>(m_hAsset, 0);
            if (std::holds_alternative<xerr>(AssetArg)) return "CloseResourceEditor: bad arguments";
            auto* pEditors = FindResourceEditors();
            auto* pEditor  = pEditors ? pEditors->Find(xresource_editor::commands::ParseAssetGuid(std::get<std::string>(AssetArg))) : nullptr;
            if (!pEditor) return "CloseResourceEditor: no open editor for that resource";

            std::string Save;
            if (auto SaveArg = m_Parser.getOptionArgAs<std::string>(m_hSave, 0); !std::holds_alternative<xerr>(SaveArg)) Save = std::get<std::string>(SaveArg);

            if (Save.empty() || Save == "false") { pEditor->m_bAskClose = false; pEditor->m_bOpen = false; return ""; }      // the host drops it at the start of the next frame
            if (Save == "true")
            {
                if (pEditor->HasPendingChanges()) pEditor->SaveChanges();
                if (pEditor->HasPendingChanges()) return "CloseResourceEditor: the changes could not be saved: the editor stays open";
                pEditor->m_bAskClose = false; pEditor->m_bOpen = false;
                return "";
            }
            if (Save == "ask")
            {
                if (!pEditor->HasPendingChanges()) { pEditor->m_bOpen = false; return ""; }
                if (pEditor->m_bAskClose) return "CloseResourceEditor: the question is already open";
                pEditor->RequestClose();
                return std::format("CloseResourceEditor: asking whether to save the changes of {}", pEditor->DisplayName());
            }
            if (Save == "cancel")
            {
                const bool bAsking = pEditor->m_bAskClose;
                pEditor->m_bAskClose = false;
                return bAsking ? "CloseResourceEditor: cancelled: the editor stays open" : "CloseResourceEditor: there was no question to cancel";
            }
            return "CloseResourceEditor: -Save is true, false, ask or cancel";
        }
        xcmdline::parser::handle m_hAsset, m_hSave;
    };

    // SaveAll: Save All of the menus and of Ctrl+Shift+S. Fires the editor's Save All event: everything that has unsaved work saves it - the open editors (the Levels among them) and the asset database
    // (the renames and moves of the resource view) - and whatever else subscribed. (The command Save is the local one: the Level's.)
    struct save_all_cmd : xlevel::commands::level_query_command
    {
        save_all_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "SaveAll", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Saves everything in the editor that has unsaved work, whoever owns it: the open editors and the changes of the resource view (renames, moves). Usage: SaveAll"; }
        void RegisterArguments() noexcept override {}
        std::string Query() noexcept override
        {
            const auto Report = xeditor::SaveAllNow();
            if (Report.empty()) return "SaveAll: nothing was pending";
            auto Join = [](const std::vector<std::string>& L) { std::string S; for (const auto& N : L) S += (S.empty() ? "" : ", ") + N; return S; };
            std::string Out = std::format("SaveAll: saved {}: {}", Report.m_Saved.size(), Join(Report.m_Saved));
            if (!Report.m_Failed.empty()) Out += std::format("; failed {}: {}", Report.m_Failed.size(), Join(Report.m_Failed));
            return Out;
        }
    };

    // Unsaved: what has unsaved work, without saving it - what Save All would save, and what the Save buttons of the editors pulse for. For whoever cannot see the button (a command line, an AI that
    // drives the editor).
    struct unsaved_cmd : xlevel::commands::level_query_command
    {
        unsaved_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "Unsaved", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Lists what has unsaved work, without saving it: the open editors with changes that are not saved, and the resource database (renames, moves). What SaveAll would save. Usage: Unsaved"; }
        void RegisterArguments() noexcept override {}
        std::string Query() noexcept override
        {
            std::vector<std::string> Names;
            if (auto* pEditors = FindResourceEditors())
                for (auto& E : pEditors->m_List)
                    if (E && E->m_bOpen && E->isLoaded() && E->HasPendingChanges()) Names.push_back(E->DisplayName());
            if (xresource_editor::g_LibMgr.isReadyToSave()) Names.push_back("Resource database");
            if (Names.empty()) return "Unsaved: nothing";
            std::string Joined;
            for (const auto& N : Names) Joined += (Joined.empty() ? "" : ", ") + N;
            return std::format("Unsaved: {}: {}", Names.size(), Joined);
        }
    };

    // LocateResource: the "find in the resource browser" button of a resource reference. The Resources tab of the drawer shows the resource (its folder is current, what hid it is cleared) and
    // the drawer is open on it.
    struct locate_resource_cmd : xlevel::commands::level_query_command
    {
        locate_resource_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "LocateResource", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Finds a resource in the resource browser of the drawer, as the button of a resource reference does: its folder is shown, the search and the type filter that hid it are cleared, it is selected, and the drawer is open on the Resources tab. Usage: LocateResource -Asset assetguid"; }
        void RegisterArguments() noexcept override { m_hAsset = m_Parser.addOption("Asset", "Resource guid, 32 hex digits", true, 1); }
        std::string Query() noexcept override
        {
            auto AssetArg = m_Parser.getOptionArgAs<std::string>(m_hAsset, 0);
            if (std::holds_alternative<xerr>(AssetArg)) return "LocateResource: bad arguments";
            const auto Guid = xresource_editor::commands::ParseAssetGuid(std::get<std::string>(AssetArg));
            if (Guid.empty()) return "LocateResource: not a resource guid";
            auto& Reference = xresource_editor::g_ReferenceHost;
            if (!Reference.m_Locate || !Reference.m_Locate(Guid)) return "LocateResource: the resource is not in the browser (it is in the trash, or in no open library)";
            return "LocateResource: ok";
        }
        xcmdline::parser::handle m_hAsset;
    };

    // GetBrowserState: where the resource browser is and what the drawer shows. SetBrowserSearch types in its search box.
    struct get_browser_state_cmd : xlevel::commands::level_query_command
    {
        get_browser_state_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "GetBrowserState", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Says where the resource browser is (folder, selection, history, search and type filter) and whether the drawer is open on it. Usage: GetBrowserState"; }
        void RegisterArguments() noexcept override {}
        std::string Query() noexcept override
        {
            auto* pHost    = xeditor::host::current();
            auto* pBrowser = pHost ? pHost->find<xresource_editor::asset_browser>() : nullptr;
            if (!pBrowser) return "GetBrowserState: no browser";
            const auto& Drawer = pHost->drawer_for(xeditor::FocusedDrawerViewport()->ID);
            return std::format("GetBrowserState: ok\nDrawer={}\nDrawerTab={}\n{}", Drawer.m_bOpen ? "open" : "closed", Drawer.m_ActiveTab, pBrowser->DescribeBrowser());
        }
    };

    struct set_browser_search_cmd : xlevel::commands::level_query_command
    {
        set_browser_search_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "SetBrowserSearch", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Types a text into the search box of the resource browser (an empty text clears it). Usage: SetBrowserSearch [-Text name]"; }
        void RegisterArguments() noexcept override { m_hText = m_Parser.addOption("Text", "The text to search for", false, 1); }
        std::string Query() noexcept override
        {
            auto* pHost    = xeditor::host::current();
            auto* pBrowser = pHost ? pHost->find<xresource_editor::asset_browser>() : nullptr;
            if (!pBrowser) return "SetBrowserSearch: no browser";
            auto TextArg = m_Parser.getOptionArgAs<std::string>(m_hText, 0);
            pBrowser->m_SearchString = std::holds_alternative<xerr>(TextArg) ? std::string() : std::get<std::string>(TextArg);
            return "SetBrowserSearch: ok";
        }
        xcmdline::parser::handle m_hText;
    };

    // The guid-addressed way to reach an open editor's own commands (the friendlier way is Name\Command from `list`).
    struct resource_editor_command_cmd : xlevel::commands::level_query_command
    {
        resource_editor_command_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "ResourceEditorCommand", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Runs a command of an open resource editor, addressed by resource guid. Usage: ResourceEditorCommand -Asset assetguid -Cmd \"SetProperty ...\""; }
        void RegisterArguments() noexcept override
        {
            m_hAsset = m_Parser.addOption("Asset", "Resource guid, 32 hex digits", true, 1);
            m_hCmd   = m_Parser.addOption("Cmd",   "Inner command string",  true, 1);
        }
        std::string Query() noexcept override
        {
            auto AssetArg = m_Parser.getOptionArgAs<std::string>(m_hAsset, 0);
            auto CmdArg   = m_Parser.getOptionArgAs<std::string>(m_hCmd, 0);
            if (std::holds_alternative<xerr>(AssetArg) || std::holds_alternative<xerr>(CmdArg))
                return "ResourceEditorCommand: bad arguments";

            auto* pEditors = FindResourceEditors();
            auto* pEditor  = pEditors ? pEditors->Find(xresource_editor::commands::ParseAssetGuid(std::get<std::string>(AssetArg))) : nullptr;
            if (!pEditor) return "ResourceEditorCommand: no open editor for that resource";
            return xeditor::host::current()->run_on(pEditor->getUndo(), std::get<std::string>(CmdArg));
        }
        xcmdline::parser::handle m_hAsset, m_hCmd;
    };
}

#endif // LevelEditor_COMMANDS_RESOURCE_EDITORS_H
