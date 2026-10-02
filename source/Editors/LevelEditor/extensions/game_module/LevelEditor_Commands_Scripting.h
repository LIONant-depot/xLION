#ifndef LevelEditor_COMMANDS_SCRIPTING_H
#define LevelEditor_COMMANDS_SCRIPTING_H
#pragma once

// Scripting resource's own "source_db" file management - Phase 1 of the Scripting/Script-module
// resource-type plan (see the standing plan file's own "Scripting/Script-module resource types +
// Project Settings panel" section). Mirrors xecs::scene's own entity_db in spirit (a resource's
// ".desc" folder holds a nested subfolder of individually-tracked files, invisible to
// info_node/library_db - a pure filesystem convention, not a second resource-tracking layer) but
// deliberately simpler: a Scripting resource is never "loaded live" into a running ECS world the
// way a Scene is, so there's no async-safe live-editing manager needed here, just plain add/
// remove/list file operations wrapped as xundo commands (matching CreateAsset/DeleteAsset's own
// command_base shape in xresource_editor_commands_assets.h, since adding/removing a source file is the
// same kind of reversible content operation, not a real external round-trip).
#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_commands_assets.h"
#include <fstream>
#include "plugins/xscript_module.plugin/source/Module/xscript_module_ops.h"

namespace level_editor::commands
{
    // Resolves an asset's own ".desc" folder as a real, absolute filesystem path (info.txt's own
    // path, minus the filename) - same getNodeInfo-based derivation RevertResourceWholeFolder
    // (xresource_editor_commands_source_control.h) already uses, just returning the ABSOLUTE path directly
    // instead of a library-root-relative key, since this is real filesystem I/O, not a git
    // pathspec. Empty return means the asset guid didn't resolve in the given library.
    inline std::wstring ResolveAssetDescFolder(xresource_editor::library::guid LibraryGuid, xresource::full_guid AssetGuid) noexcept
    {
        std::wstring FolderPath;
        // NOT noexcept - getNodeInfo's own function_traits deduction doesn't handle a noexcept
        // lambda's operator() type (xgpu_xcontainer_noexcept_lambda_trait_trap).
        xresource_editor::g_LibMgr.getNodeInfo(LibraryGuid, AssetGuid, [&](const xresource_editor::library_db::info_node& Node)
        {
            const auto SlashPos = Node.m_Path.find_last_of(L'\\');
            FolderPath = (SlashPos == std::wstring::npos) ? Node.m_Path : Node.m_Path.substr(0, SlashPos);
        });
        return FolderPath;
    }

    inline std::wstring ScriptSourceDbFolder(xresource_editor::library::guid LibraryGuid, xresource::full_guid AssetGuid) noexcept
    {
        const auto Desc = ResolveAssetDescFolder(LibraryGuid, AssetGuid);
        return Desc.empty() ? Desc : (Desc + L"\\source_db");
    }

    //================================================================================================
    // The files of a script module (documentation: plugins/xscript_module.plugin/documentation/editor.md). A module's descriptor
    // (Descriptor.txt) lists its files and the disk holds them, and these commands change both together through
    // xscript::module::ops - the layer the module editor's own commands use too. Paths are relative to the module's source_db and may
    // have folders ("Systems/ball_system.h"). Every one is undoable; a change of the file LIST regenerates the game project.
    //================================================================================================
    namespace script_module_cmd
    {
        struct target { std::uint64_t m_Library = 0; std::string m_Asset; };

        inline bool ReadTarget(const xcmdline::parser& Parser, xcmdline::parser::handle hLibrary, xcmdline::parser::handle hAsset, target& Out) noexcept
        {
            auto LibraryArg = Parser.getOptionArgAs<std::string>(hLibrary, 0);
            auto AssetArg   = Parser.getOptionArgAs<std::string>(hAsset, 0);
            if (std::holds_alternative<xerr>(LibraryArg) || std::holds_alternative<xerr>(AssetArg)) return false;
            Out.m_Library = std::strtoull(std::get<std::string>(LibraryArg).c_str(), nullptr, 16);
            Out.m_Asset   = std::get<std::string>(AssetArg);
            return true;
        }
        inline std::string TextArg(const xcmdline::parser& Parser, xcmdline::parser::handle H) noexcept
        {
            auto A = Parser.getOptionArgAs<std::string>(H, 0);
            return std::holds_alternative<xerr>(A) ? std::string() : std::get<std::string>(A);
        }
        inline void WriteTarget(xundo::undo_file& File, const target& T) noexcept { File.Write(T.m_Library); xeditor::WriteString(File, T.m_Asset); }
        inline target ReadTarget(xundo::undo_file& File) noexcept { target T; File.Read(T.m_Library); T.m_Asset = xeditor::ReadString(File); return T; }

        // The module's folder (the .desc folder), "" when the asset does not resolve.
        inline std::filesystem::path FolderOf(const target& T) noexcept
        {
            const auto Library = xresource_editor::commands::ParseLibraryGuid(std::format("{:016X}", T.m_Library));
            return ResolveAssetDescFolder(Library, xresource_editor::commands::ParseAssetGuid(T.m_Asset));
        }
        inline void Regenerate() noexcept { if (xlevel::g_pGamePlugin) xlevel::RegenerateGameModuleSources(xlevel::g_pGamePlugin->m_Paths); }

        // Load, change, save: the shape of every command below. Fn gets the descriptor and the folder and returns an error text.
        template<class T_FN>
        inline std::string Edit(const target& T, bool bRegenerate, T_FN&& Fn) noexcept
        {
            const auto Folder = FolderOf(T);
            if (Folder.empty()) return "asset not found";
            auto Loaded = xscript::module::LoadOrMigrate(Folder, /*bWriteMigration*/ true);
            if (!Loaded.m_Error.empty()) return "Descriptor.txt cannot be read: " + Loaded.m_Error;
            if (auto Err = Fn(Loaded.m_Descriptor, Folder); !Err.empty()) return Err;
            std::string WriteError;
            if (!xscript::module::Write(Folder, Loaded.m_Descriptor, &WriteError)) return "Descriptor.txt could not be written: " + WriteError;
            if (bRegenerate) Regenerate();
            return {};
        }
    }

    // AddScriptSourceFile: a new file (from a template) or a file that is already in source_db and not yet listed.
    struct add_script_source_file_cmd : xlevel::commands::level_command
    {
        add_script_source_file_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_command(System, "AddScriptSourceFile", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Adds a file to a script module (undoable): created from a template, or an existing file of its source_db that was not listed. Usage: AddScriptSourceFile -Library hexguid -Asset assetguid -FileName \"Systems/Foo.h\" [-Template header|source|empty]"; }
        void RegisterArguments() noexcept override
        {
            m_hLibrary  = m_Parser.addOption("Library",  "Library instance guid, 16 hex digits", true, 1);
            m_hAsset    = m_Parser.addOption("Asset",    "Scripting asset guid, 32 hex digits",  true, 1);
            m_hFileName = m_Parser.addOption("FileName", "Path inside the module's source_db, e.g. \"Systems/Foo.h\"", true, 1);
            m_hTemplate = m_Parser.addOption("Template", "header (#pragma once), source (includes its own header) or empty; default by the extension", false, 1);
        }
        static xscript::module::file_template TemplateOf(const std::string& Name, const std::string& Path) noexcept
        {
            if (Name == "empty")  return xscript::module::file_template::Empty;
            if (Name == "header") return xscript::module::file_template::Header;
            if (Name == "source") return xscript::module::file_template::Source;
            return xscript::module::IsPchHeader(Path) ? xscript::module::file_template::Header : xscript::module::KindOf(Path) == xscript::module::file_kind::Compiled ? xscript::module::file_template::Source : xscript::module::file_template::Empty;
        }
        std::string Redo() noexcept override
        {
            script_module_cmd::target T;
            if (!script_module_cmd::ReadTarget(m_Parser, m_hLibrary, m_hAsset, T)) return "AddScriptSourceFile: bad arguments";
            const auto Path = script_module_cmd::TextArg(m_Parser, m_hFileName);
            const auto Template = TemplateOf(script_module_cmd::TextArg(m_Parser, m_hTemplate), xscript::module::NormalizeRelative(Path));
            auto Err = script_module_cmd::Edit(T, true, [&](xscript::module::descriptor& D, const std::filesystem::path& Folder) noexcept
            {
                xscript::module::ops::added Added;
                return xscript::module::ops::AddFile(D, Folder, Path, Template, Added);
            });
            return Err.empty() ? Err : "AddScriptSourceFile: " + Err;
        }
        void BackupCurrenState(xundo::undo_file& File) noexcept override
        {
            script_module_cmd::target T; script_module_cmd::ReadTarget(m_Parser, m_hLibrary, m_hAsset, T);
            script_module_cmd::WriteTarget(File, T);
            const auto Path = xscript::module::NormalizeRelative(script_module_cmd::TextArg(m_Parser, m_hFileName));
            std::error_code Ec;
            const auto Folder = script_module_cmd::FolderOf(T);
            const std::uint8_t bExisted = !Folder.empty() && !Path.empty() && std::filesystem::exists(xscript::module::Absolute(Folder, Path), Ec);   // a file that was already there is not deleted by the undo
            File.Write(bExisted);
            xeditor::WriteString(File, Path);
        }
        void Undo(xundo::undo_file& File) noexcept override
        {
            const auto T = script_module_cmd::ReadTarget(File);
            std::uint8_t bExisted = 0; File.Read(bExisted);
            const auto Path = xeditor::ReadString(File);
            script_module_cmd::Edit(T, true, [&](xscript::module::descriptor& D, const std::filesystem::path& Folder) noexcept
            {
                return xscript::module::ops::UndoAdd(D, Folder, { Path, bExisted == 0 });
            });
        }
        xcmdline::parser::handle m_hLibrary, m_hAsset, m_hFileName, m_hTemplate;
    };

    // RemoveScriptSourceFile: the file leaves the module and the disk; Undo puts it back as it was (content and place in the list).
    struct remove_script_source_file_cmd : xlevel::commands::level_command
    {
        remove_script_source_file_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_command(System, "RemoveScriptSourceFile", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Removes a file from a script module and deletes it (undoable - restores its exact content and place). Usage: RemoveScriptSourceFile -Library hexguid -Asset assetguid -FileName \"Systems/Foo.h\""; }
        void RegisterArguments() noexcept override
        {
            m_hLibrary  = m_Parser.addOption("Library",  "Library instance guid, 16 hex digits", true, 1);
            m_hAsset    = m_Parser.addOption("Asset",    "Scripting asset guid, 32 hex digits",  true, 1);
            m_hFileName = m_Parser.addOption("FileName", "Path inside the module's source_db",   true, 1);
        }
        std::string Redo() noexcept override
        {
            script_module_cmd::target T;
            if (!script_module_cmd::ReadTarget(m_Parser, m_hLibrary, m_hAsset, T)) return "RemoveScriptSourceFile: bad arguments";
            const auto Path = script_module_cmd::TextArg(m_Parser, m_hFileName);
            auto Err = script_module_cmd::Edit(T, true, [&](xscript::module::descriptor& D, const std::filesystem::path& Folder) noexcept
            {
                xscript::module::ops::removed Removed;
                return xscript::module::ops::RemoveFile(D, Folder, Path, Removed);
            });
            return Err.empty() ? Err : "RemoveScriptSourceFile: " + Err;
        }
        void BackupCurrenState(xundo::undo_file& File) noexcept override
        {
            script_module_cmd::target T; script_module_cmd::ReadTarget(m_Parser, m_hLibrary, m_hAsset, T);
            script_module_cmd::WriteTarget(File, T);
            xscript::module::ops::removed R;
            if (const auto Folder = script_module_cmd::FolderOf(T); !Folder.empty())
                xscript::module::ops::CaptureFile(xscript::module::LoadOrMigrate(Folder, false).m_Descriptor, Folder, script_module_cmd::TextArg(m_Parser, m_hFileName), R);
            xeditor::WriteString(File, R.m_Path); xeditor::WriteString(File, R.m_Content);
            const std::uint64_t Index = R.m_Index; File.Write(Index);
            const std::uint8_t Flags = static_cast<std::uint8_t>((R.m_bExclude ? 1 : 0) | (R.m_bWasListed ? 2 : 0) | (R.m_bHadFile ? 4 : 0)); File.Write(Flags);
        }
        void Undo(xundo::undo_file& File) noexcept override
        {
            const auto T = script_module_cmd::ReadTarget(File);
            xscript::module::ops::removed R;
            R.m_Path = xeditor::ReadString(File); R.m_Content = xeditor::ReadString(File);
            std::uint64_t Index = 0; File.Read(Index); R.m_Index = static_cast<std::size_t>(Index);
            std::uint8_t Flags = 0; File.Read(Flags); R.m_bExclude = Flags & 1; R.m_bWasListed = Flags & 2; R.m_bHadFile = Flags & 4;
            script_module_cmd::Edit(T, true, [&](xscript::module::descriptor& D, const std::filesystem::path& Folder) noexcept { return xscript::module::ops::RestoreFile(D, Folder, R); });
        }
        xcmdline::parser::handle m_hLibrary, m_hAsset, m_hFileName;
    };

    // ListScriptSourceFiles: what the descriptor lists and what the folder holds, with how they agree.
    struct list_script_source_files_query_cmd : xlevel::commands::level_query_command
    {
        list_script_source_files_query_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "ListScriptSourceFiles", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Lists the files of a script module: path, kind, excluded and state (ok, missing: listed but not on disk, unlisted: on disk but not in the descriptor, so not built). Usage: ListScriptSourceFiles -Library hexguid -Asset assetguid"; }
        void RegisterArguments() noexcept override
        {
            m_hLibrary = m_Parser.addOption("Library", "Library instance guid, 16 hex digits", true, 1);
            m_hAsset   = m_Parser.addOption("Asset",   "Scripting asset guid, 32 hex digits",  true, 1);
        }
        std::string Query() noexcept override
        {
            script_module_cmd::target T;
            if (!script_module_cmd::ReadTarget(m_Parser, m_hLibrary, m_hAsset, T)) return "ListScriptSourceFiles: bad arguments";
            const auto Folder = script_module_cmd::FolderOf(T);
            if (Folder.empty()) return "ListScriptSourceFiles: asset not found";
            const auto Module = xscript::module::Resolve(Folder, /*bWriteMigration*/ false);
            if (!Module.m_Error.empty()) return "ListScriptSourceFiles: Descriptor.txt cannot be read: " + Module.m_Error;
            std::string Out = std::format("ListScriptSourceFiles: ok\nFiles={}  Unlisted={}  Descriptor={}\n\nPath\tKind\tExcluded\tState\n", Module.m_Descriptor.m_Files.size(), Module.m_Unlisted.size(), Module.m_bMigrated ? "none (the folder is listed)" : "Descriptor.txt");
            std::error_code Ec;
            for (const auto& F : Module.m_Descriptor.m_Files)
            {
                const auto Kind = xscript::module::KindOf(F.m_Path);
                Out += std::format("{}\t{}\t{}\t{}\n", F.m_Path, Kind == xscript::module::file_kind::Compiled ? "source" : Kind == xscript::module::file_kind::Header ? "header" : "other"
                    , F.m_bExclude, std::filesystem::is_regular_file(xscript::module::Absolute(Folder, F.m_Path), Ec) ? "ok" : "missing");
            }
            for (const auto& Path : Module.m_Unlisted) Out += std::format("{}\t{}\tfalse\tunlisted\n", Path, xscript::module::KindOf(Path) == xscript::module::file_kind::Compiled ? "source" : "header");
            return Out;
        }
        xcmdline::parser::handle m_hLibrary, m_hAsset;
    };

    // SetScriptSourceFileContent: the whole content of a file that is in the module. The only command-line way to write code into a module.
    struct set_script_source_file_content_cmd : xlevel::commands::level_command
    {
        set_script_source_file_content_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_command(System, "SetScriptSourceFileContent", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Overwrites the content of a file of a script module (undoable - restores the previous content). Usage: SetScriptSourceFileContent -Library hexguid -Asset assetguid -FileName \"Foo.cpp\" -Content \"text\""; }
        void RegisterArguments() noexcept override
        {
            m_hLibrary  = m_Parser.addOption("Library",  "Library instance guid, 16 hex digits", true, 1);
            m_hAsset    = m_Parser.addOption("Asset",    "Scripting asset guid, 32 hex digits",  true, 1);
            m_hFileName = m_Parser.addOption("FileName", "Path inside the module's source_db",   true, 1);
            m_hContent  = m_Parser.addOption("Content",  "New file content",                     true, 1);
        }
        std::string Redo() noexcept override
        {
            script_module_cmd::target T;
            if (!script_module_cmd::ReadTarget(m_Parser, m_hLibrary, m_hAsset, T)) return "SetScriptSourceFileContent: bad arguments";
            const auto Folder = script_module_cmd::FolderOf(T);
            if (Folder.empty()) return "SetScriptSourceFileContent: asset not found";
            std::string Previous;
            auto Err = xscript::module::ops::SetContent(Folder, script_module_cmd::TextArg(m_Parser, m_hFileName), script_module_cmd::TextArg(m_Parser, m_hContent), Previous);
            return Err.empty() ? Err : "SetScriptSourceFileContent: " + Err;           // the file list did not change: no reconfigure; MSBuild sees the new time by itself
        }
        void BackupCurrenState(xundo::undo_file& File) noexcept override
        {
            script_module_cmd::target T; script_module_cmd::ReadTarget(m_Parser, m_hLibrary, m_hAsset, T);
            script_module_cmd::WriteTarget(File, T);
            const auto Path = xscript::module::NormalizeRelative(script_module_cmd::TextArg(m_Parser, m_hFileName));
            std::string Previous;
            if (const auto Folder = script_module_cmd::FolderOf(T); !Folder.empty() && !Path.empty()) xscript::module::ReadAll(xscript::module::Absolute(Folder, Path), Previous);
            xeditor::WriteString(File, Path); xeditor::WriteString(File, Previous);
        }
        void Undo(xundo::undo_file& File) noexcept override
        {
            const auto T = script_module_cmd::ReadTarget(File);
            const auto Path = xeditor::ReadString(File); const auto Previous = xeditor::ReadString(File);
            if (const auto Folder = script_module_cmd::FolderOf(T); !Folder.empty() && !Path.empty()) xscript::module::WriteAll(xscript::module::Absolute(Folder, Path), Previous);
        }
        xcmdline::parser::handle m_hLibrary, m_hAsset, m_hFileName, m_hContent;
    };

    // RenameScriptSourceFile: a new path for a file, which may be in another folder (a move). The descriptor follows.
    struct rename_script_source_file_cmd : xlevel::commands::level_command
    {
        rename_script_source_file_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_command(System, "RenameScriptSourceFile", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Renames or moves a file of a script module (undoable); the descriptor follows. Usage: RenameScriptSourceFile -Library hexguid -Asset assetguid -OldFileName \"Foo.h\" -NewFileName \"Systems/Foo.h\""; }
        void RegisterArguments() noexcept override
        {
            m_hLibrary     = m_Parser.addOption("Library",     "Library instance guid, 16 hex digits", true, 1);
            m_hAsset       = m_Parser.addOption("Asset",       "Scripting asset guid, 32 hex digits",  true, 1);
            m_hOldFileName = m_Parser.addOption("OldFileName", "Current path inside source_db",        true, 1);
            m_hNewFileName = m_Parser.addOption("NewFileName", "New path inside source_db",            true, 1);
        }
        std::string Redo() noexcept override
        {
            script_module_cmd::target T;
            if (!script_module_cmd::ReadTarget(m_Parser, m_hLibrary, m_hAsset, T)) return "RenameScriptSourceFile: bad arguments";
            const auto Old = script_module_cmd::TextArg(m_Parser, m_hOldFileName), New = script_module_cmd::TextArg(m_Parser, m_hNewFileName);
            auto Err = script_module_cmd::Edit(T, true, [&](xscript::module::descriptor& D, const std::filesystem::path& Folder) noexcept { return xscript::module::ops::RenameFile(D, Folder, Old, New); });
            return Err.empty() ? Err : "RenameScriptSourceFile: " + Err;
        }
        void BackupCurrenState(xundo::undo_file& File) noexcept override
        {
            script_module_cmd::target T; script_module_cmd::ReadTarget(m_Parser, m_hLibrary, m_hAsset, T);
            script_module_cmd::WriteTarget(File, T);
            xeditor::WriteString(File, script_module_cmd::TextArg(m_Parser, m_hOldFileName)); xeditor::WriteString(File, script_module_cmd::TextArg(m_Parser, m_hNewFileName));
        }
        void Undo(xundo::undo_file& File) noexcept override
        {
            const auto T = script_module_cmd::ReadTarget(File);
            const auto Old = xeditor::ReadString(File), New = xeditor::ReadString(File);
            script_module_cmd::Edit(T, true, [&](xscript::module::descriptor& D, const std::filesystem::path& Folder) noexcept { return xscript::module::ops::RenameFile(D, Folder, New, Old); });
        }
        xcmdline::parser::handle m_hLibrary, m_hAsset, m_hOldFileName, m_hNewFileName;
    };

    // RescanScriptModule: lists the files that are in the folder and not in the descriptor (and, with -RemoveMissing, drops the listed ones that are gone).
    struct rescan_script_module_cmd : xlevel::commands::level_command
    {
        rescan_script_module_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_command(System, "RescanScriptModule", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Adds the files that are in a script module's source_db and not in its descriptor, and with -RemoveMissing drops the listed files that are gone (undoable). Usage: RescanScriptModule -Library hexguid -Asset assetguid [-RemoveMissing true]"; }
        void RegisterArguments() noexcept override
        {
            m_hLibrary = m_Parser.addOption("Library", "Library instance guid, 16 hex digits", true, 1);
            m_hAsset   = m_Parser.addOption("Asset",   "Scripting asset guid, 32 hex digits",  true, 1);
            m_hRemove  = m_Parser.addOption("RemoveMissing", "true: also drop the listed files that are not on disk", false, 1);
        }
        std::string Redo() noexcept override
        {
            script_module_cmd::target T;
            if (!script_module_cmd::ReadTarget(m_Parser, m_hLibrary, m_hAsset, T)) return "RescanScriptModule: bad arguments";
            const bool bRemove = script_module_cmd::TextArg(m_Parser, m_hRemove) == "true";
            auto Err = script_module_cmd::Edit(T, true, [&](xscript::module::descriptor& D, const std::filesystem::path& Folder) noexcept { xscript::module::Sync(D, Folder, bRemove); return std::string(); });
            return Err.empty() ? Err : "RescanScriptModule: " + Err;
        }
        void BackupCurrenState(xundo::undo_file& File) noexcept override
        {
            script_module_cmd::target T; script_module_cmd::ReadTarget(m_Parser, m_hLibrary, m_hAsset, T);
            script_module_cmd::WriteTarget(File, T);
            std::string Before;                                                   // the descriptor as it was, whole: "" when there was none
            if (const auto Folder = script_module_cmd::FolderOf(T); !Folder.empty()) xscript::module::ReadAll(xscript::module::DescriptorFile(Folder), Before);
            xeditor::WriteString(File, Before);
        }
        void Undo(xundo::undo_file& File) noexcept override
        {
            const auto T = script_module_cmd::ReadTarget(File);
            const auto Before = xeditor::ReadString(File);
            if (const auto Folder = script_module_cmd::FolderOf(T); !Folder.empty())
            {
                if (Before.empty()) { std::error_code Ec; std::filesystem::remove(xscript::module::DescriptorFile(Folder), Ec); }
                else xscript::module::WriteAll(xscript::module::DescriptorFile(Folder), Before);
                script_module_cmd::Regenerate();
            }
        }
        xcmdline::parser::handle m_hLibrary, m_hAsset, m_hRemove;
    };
    //================================================================================================
    // AddProjectModuleReference / RemoveProjectModuleReference - the project's own build-membership
    // list (Project.config\Script.config.txt's ModuleRefs, see LevelEditor_ProjectScriptConfig.h). Persisted
    // immediately on every Redo/Undo, same convention AddLibraryDependency/RemoveLibraryDependency
    // already use (LevelEditor_Commands_LibraryDependency.h) - no separate "Save" step. No cycle/orphan
    // checks here (unlike library dependencies) - this is a flat membership list, not a graph edge; a
    // module-to-module dependency graph (if/when that's built) is a separate, later concern.
    //================================================================================================
    struct add_project_module_reference_cmd : xlevel::commands::level_command
    {
        add_project_module_reference_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_command(System, "AddProjectModuleReference", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Adds a Script-Module resource to the project's build membership list (undoable, persisted immediately). Usage: AddProjectModuleReference -Module assetguid"; }
        void RegisterArguments() noexcept override
        {
            m_hModule = m_Parser.addOption("Module", "Script-Module asset guid, 32 hex digits", true, 1);
        }

        std::string Redo() noexcept override
        {
            auto ModuleArg = m_Parser.getOptionArgAs<std::string>(m_hModule, 0);
            if (std::holds_alternative<xerr>(ModuleArg)) return "AddProjectModuleReference: bad arguments";

            const auto ModuleGuid = xresource_editor::commands::ParseAssetGuid(std::get<std::string>(ModuleArg));
            auto& Refs = xlevel::g_ScriptConfig.m_ModuleRefs;
            if (std::find(Refs.begin(), Refs.end(), ModuleGuid) != Refs.end()) return {};

            Refs.push_back(ModuleGuid);
            if (auto Err = xlevel::SaveScriptConfig(xresource_editor::g_LibMgr.m_ProjectPath, xlevel::g_ScriptConfig); Err)
                return std::format("AddProjectModuleReference: {}", Err.getMessage());
            xlevel::RegenerateGameModuleSources(xlevel::g_pGamePlugin->m_Paths);
            return {};
        }

        void BackupCurrenState(xundo::undo_file& File) noexcept override
        {
            auto ModuleArg = m_Parser.getOptionArgAs<std::string>(m_hModule, 0);
            xeditor::WriteString(File, std::holds_alternative<xerr>(ModuleArg) ? std::string(32, '0') : std::get<std::string>(ModuleArg));
        }

        void Undo(xundo::undo_file& File) noexcept override
        {
            const auto ModuleGuid = xresource_editor::commands::ParseAssetGuid(xeditor::ReadString(File));
            auto& Refs = xlevel::g_ScriptConfig.m_ModuleRefs;
            if (auto It = std::find(Refs.begin(), Refs.end(), ModuleGuid); It != Refs.end())
                Refs.erase(It);
            xlevel::SaveScriptConfig(xresource_editor::g_LibMgr.m_ProjectPath, xlevel::g_ScriptConfig);
            xlevel::RegenerateGameModuleSources(xlevel::g_pGamePlugin->m_Paths);
        }

        xcmdline::parser::handle m_hModule;
    };

    struct remove_project_module_reference_cmd : xlevel::commands::level_command
    {
        remove_project_module_reference_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_command(System, "RemoveProjectModuleReference", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Removes a Script-Module resource from the project's build membership list (undoable, persisted immediately). Usage: RemoveProjectModuleReference -Module assetguid"; }
        void RegisterArguments() noexcept override
        {
            m_hModule = m_Parser.addOption("Module", "Script-Module asset guid, 32 hex digits", true, 1);
        }

        std::string Redo() noexcept override
        {
            auto ModuleArg = m_Parser.getOptionArgAs<std::string>(m_hModule, 0);
            if (std::holds_alternative<xerr>(ModuleArg)) return "RemoveProjectModuleReference: bad arguments";

            const auto ModuleGuid = xresource_editor::commands::ParseAssetGuid(std::get<std::string>(ModuleArg));
            auto& Refs = xlevel::g_ScriptConfig.m_ModuleRefs;
            auto It = std::find(Refs.begin(), Refs.end(), ModuleGuid);
            if (It == Refs.end()) return "RemoveProjectModuleReference: not a project module reference";
            // Captured as an INDEX, not kept as an iterator - Refs.erase(It) below invalidates It
            // itself (a stale iterator used later for a revert-insert would be undefined behavior).
            const auto OriginalIndex = static_cast<std::size_t>(std::distance(Refs.begin(), It));

            // Component-registry compatibility plan, Phase 5 - RESTORED to its originally-designed
            // strength (2026-09-19): a real trial rebuild-and-probe, reverting the removal on a
            // genuine mismatch. An earlier version of this session descoped it to a static warning
            // after live testing surfaced what looked like a CMake/MSBuild incremental-build
            // reliability gap - since root-caused and fixed (BuildGamePluginIfStale now touches
            // cmake_pch.cxx before every build - see that function's own comment for the full isolated
            // repro/fix), so the trial rebuild this needs is trustworthy again. Verified live: 4
            // consecutive module add/remove cycles through the real Play/reload path all correctly
            // reflected the change afterward.
            std::vector<xecs::scene::component_dependency> PluginOwnedBefore;
            if (xlevel::g_pGamePlugin && xlevel::g_pGamePlugin->m_hModule)
            {
                xlevel::game_plugin_candidate CurrentView{ xlevel::g_pGamePlugin->m_hModule, {} };
                PluginOwnedBefore = xlevel::ProbeCandidateComponents(CurrentView);
            }

            std::vector<xecs::scene::component_dependency> RequiredFromOpenScenes;
            std::unordered_set<std::uint64_t> PluginOwnedGuids;
            for (auto& D : PluginOwnedBefore) PluginOwnedGuids.insert(D.m_Guid.m_Value);

            for (auto& SceneGuid : State().m_OpenScenes)
                for (auto& Dep : xecs::scene::LoadSceneComponentDependencies(xresource_editor::g_LibMgr.m_ProjectPath, SceneGuid))
                    if (PluginOwnedGuids.contains(Dep.m_Guid.m_Value))
                        RequiredFromOpenScenes.push_back(Dep);

            Refs.erase(It);
            if (auto Err = xlevel::SaveScriptConfig(xresource_editor::g_LibMgr.m_ProjectPath, xlevel::g_ScriptConfig); Err)
            {
                Refs.insert(Refs.begin() + static_cast<std::ptrdiff_t>(OriginalIndex), ModuleGuid); // restore in-memory state to match what's still on disk
                return std::format("RemoveProjectModuleReference: {}", Err.getMessage());
            }
            xlevel::RegenerateGameModuleSources(xlevel::g_pGamePlugin->m_Paths);

            // Only worth a real trial compile if removing this module could plausibly affect anything
            // currently open - skip it entirely (the common case) rather than pay a compile for a
            // guaranteed-safe removal.
            if (!RequiredFromOpenScenes.empty() && xlevel::g_pGamePlugin)
            {
                // Wait for any in-flight ASYNC build already started elsewhere (window-focus-regain
                // fires automatically - see StartGameReload's own comment) to finish first - a real
                // race found live earlier this session: two concurrent `cmake --build` invocations
                // against the same output DLL raced, and whichever finished last won regardless of
                // which fragment it was building from. Safe to .wait() without .get()'ing it, since
                // PollGameReload (the only other consumer) runs on this same main thread.
                if (xlevel::g_pGamePlugin->m_bBuilding) xlevel::g_pGamePlugin->m_BuildFuture.wait();

                const auto BuildResult = xlevel::BuildGamePluginIfStale(*xlevel::g_pGamePlugin, xlevel::GetLatestModuleSourceWriteTime(xlevel::g_pGamePlugin->m_Paths));
                if (BuildResult == xlevel::build_result::Rebuilt)
                {
                    const std::uint32_t TrialGeneration = xlevel::g_pGamePlugin->m_Token.m_Generation + 1000000; // scratch-only, never Commit'ed
                    auto Candidate = xlevel::PrepareGamePluginCandidate(xlevel::g_pGamePlugin->m_Paths, TrialGeneration);
                    if (Candidate.m_hModule)
                    {
                        const auto NewManifest = xlevel::ProbeCandidateComponents(Candidate);
                        std::unordered_set<std::uint64_t> Available;
                        for (auto& D : NewManifest) Available.insert(D.m_Guid.m_Value);

                        auto Missing = xlevel::CheckComponentCompatibility(RequiredFromOpenScenes, [&](xecs::component::type::guid Guid) noexcept
                        {
                            return Available.contains(Guid.m_Value);
                        });
                        xlevel::DiscardGamePluginCandidate(Candidate);

                        if (!Missing.empty())
                        {
                            // Revert - put the reference back exactly as it was, re-persist, re-
                            // regenerate the fragment so a LATER real reload rebuilds WITH the module
                            // again (not the trial DLL this command just discarded).
                            Refs.insert(Refs.begin() + static_cast<std::ptrdiff_t>(OriginalIndex), ModuleGuid);
                            xlevel::SaveScriptConfig(xresource_editor::g_LibMgr.m_ProjectPath, xlevel::g_ScriptConfig);
                            xlevel::RegenerateGameModuleSources(xlevel::g_pGamePlugin->m_Paths);

                            std::string Names;
                            for (auto& Dep : Missing) Names += (Names.empty() ? "" : ", ") + Dep.m_Name;
                            return std::format("RemoveProjectModuleReference: refused - {} currently-open component(s) would break: {}", Missing.size(), Names);
                        }
                    }
                }
                // A build failure here (bad code elsewhere, unrelated to this removal) isn't this
                // command's problem to solve - the removal already committed, same as it would have
                // without this check at all; the existing reload machinery will surface the failure
                // through its own normal path next time it runs.
            }

            return {};
        }

        void BackupCurrenState(xundo::undo_file& File) noexcept override
        {
            auto ModuleArg = m_Parser.getOptionArgAs<std::string>(m_hModule, 0);
            std::uint32_t Index = 0;
            if (!std::holds_alternative<xerr>(ModuleArg))
            {
                const auto ModuleGuid = xresource_editor::commands::ParseAssetGuid(std::get<std::string>(ModuleArg));
                auto& Refs = xlevel::g_ScriptConfig.m_ModuleRefs;
                if (auto It = std::find(Refs.begin(), Refs.end(), ModuleGuid); It != Refs.end())
                    Index = static_cast<std::uint32_t>(std::distance(Refs.begin(), It));
            }
            xeditor::WriteString(File, std::holds_alternative<xerr>(ModuleArg) ? std::string(32, '0') : std::get<std::string>(ModuleArg));
            File.Write(Index);
        }

        void Undo(xundo::undo_file& File) noexcept override
        {
            const auto ModuleGuid = xresource_editor::commands::ParseAssetGuid(xeditor::ReadString(File));
            std::uint32_t Index = 0; File.Read(Index);

            auto& Refs = xlevel::g_ScriptConfig.m_ModuleRefs;
            if (std::find(Refs.begin(), Refs.end(), ModuleGuid) == Refs.end())
            {
                const auto Idx = std::min<std::size_t>(Index, Refs.size());
                Refs.insert(Refs.begin() + static_cast<std::ptrdiff_t>(Idx), ModuleGuid);
            }
            xlevel::SaveScriptConfig(xresource_editor::g_LibMgr.m_ProjectPath, xlevel::g_ScriptConfig);
            xlevel::RegenerateGameModuleSources(xlevel::g_pGamePlugin->m_Paths);
        }

        xcmdline::parser::handle m_hModule;
    };

    //================================================================================================
    // ListProjectModuleReferences - the project's current build-membership list, one guid per line.
    // Discovery command, same "never need to read a raw file by hand" reasoning every other list
    // command in this system was built for.
    //================================================================================================
    struct list_project_module_references_query_cmd : xlevel::commands::level_query_command
    {
        list_project_module_references_query_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "ListProjectModuleReferences", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Lists the project's current Script-Module build-membership list. Usage: ListProjectModuleReferences"; }
        void RegisterArguments() noexcept override {}

        std::string Query() noexcept override
        {
            if (xlevel::g_ScriptConfig.m_ModuleRefs.empty()) return "(empty)";
            std::string Out;
            for (auto& G : xlevel::g_ScriptConfig.m_ModuleRefs)
                Out += xresource_editor::commands::FormatAssetGuid(G) + "\n";
            return Out;
        }
    };

    //================================================================================================
    // RegenerateProjectModuleSources - force-regenerates the generated script project (Cache\Script\CMakeLists.txt) from the
    // CURRENT build-membership list, on demand. Every mutating command in this file already triggers
    // this as a side effect - this exists for recovery/debugging (e.g. after a raw file edit made
    // outside the command bus) rather than any normal workflow needing to call it directly.
    //================================================================================================
    struct regenerate_project_module_sources_query_cmd : xlevel::commands::level_query_command
    {
        regenerate_project_module_sources_query_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "RegenerateProjectModuleSources", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Force-regenerates the CMake module-sources fragment from the current build-membership list. Usage: RegenerateProjectModuleSources"; }
        void RegisterArguments() noexcept override {}

        std::string Query() noexcept override
        {
            xlevel::RegenerateGameModuleSources(xlevel::g_pGamePlugin->m_Paths);
            return "RegenerateProjectModuleSources: regenerated";
        }
    };

    //================================================================================================
    // SerializeRoundtrip - write+read the same binary SerializeGameState path mid-play reload uses
    // (Vn bridge). Forces the DLL/host BitID landmine without waiting for a Game.dll rebuild.
    //================================================================================================
    struct serialize_roundtrip_query_cmd : xlevel::commands::level_query_command
    {
        serialize_roundtrip_query_cmd(xundo::system& System, void* pDataBase) noexcept
            : xlevel::commands::level_query_command(System, "SerializeRoundtrip", pDataBase) { RegisterArguments(); }
        void RegisterArguments() noexcept override {}
        const char* getCommandHelp() const noexcept override
        {
            return "Writes then reads game_mgr SerializeGameState (binary) via the reload-bridge path. Usage: SerializeRoundtrip";
        }
        std::string Query() noexcept override
        {
            auto& State = get<xlevel::level_context>().State();
            if (State.m_CurrentLevel.empty() && State.m_OpenScenes.empty())
                return "SerializeRoundtrip: nothing open (open a Level first)";

            const auto Path = xlevel::GetReloadBridgeSnapshotPath();
            if (!xlevel::SaveSnapshot(World(), Path))
                return "SerializeRoundtrip: SaveSnapshot failed (see Game.dll log)";
            if (!xlevel::LoadSnapshot(World(), Path))
                return "SerializeRoundtrip: LoadSnapshot failed (see Game.dll log)";
            return std::format("SerializeRoundtrip: ok ({})", std::filesystem::path(Path).string());
        }
    };
}

#endif // LevelEditor_COMMANDS_SCRIPTING_H
