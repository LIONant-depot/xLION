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
    // have folders ("Systems/ball_system.h"). Every one is undoable; a change of the file LIST compiles the module again (the resource pipeline), which makes the game project again.
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
        // Load, change, save: the shape of every command below. Fn gets the descriptor and the folder and returns an error text.
        template<class T_FN>
        inline std::string Edit(const target& T, T_FN&& Fn) noexcept
        {
            const auto Folder = FolderOf(T);
            if (Folder.empty()) return "asset not found";
            auto Loaded = xscript::module::LoadOrMigrate(Folder, /*bWriteMigration*/ true);
            if (!Loaded.m_Error.empty()) return "Descriptor.txt cannot be read: " + Loaded.m_Error;
            if (auto Err = Fn(Loaded.m_Descriptor, Folder); !Err.empty()) return Err;
            std::string WriteError;
            if (!xscript::module::Write(Folder, Loaded.m_Descriptor, &WriteError)) return "Descriptor.txt could not be written: " + WriteError;
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
                std::string Redo() noexcept override
        {
            script_module_cmd::target T;
            if (!script_module_cmd::ReadTarget(m_Parser, m_hLibrary, m_hAsset, T)) return "AddScriptSourceFile: bad arguments";
            const auto Path = script_module_cmd::TextArg(m_Parser, m_hFileName);
            const auto Template = xscript::module::ops::TemplateFor(script_module_cmd::TextArg(m_Parser, m_hTemplate), xscript::module::NormalizeRelative(Path));
            auto Err = script_module_cmd::Edit(T, [&](xscript::module::descriptor& D, const std::filesystem::path& Folder) noexcept
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
            script_module_cmd::Edit(T, [&](xscript::module::descriptor& D, const std::filesystem::path& Folder) noexcept
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
            auto Err = script_module_cmd::Edit(T, [&](xscript::module::descriptor& D, const std::filesystem::path& Folder) noexcept
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
            script_module_cmd::Edit(T, [&](xscript::module::descriptor& D, const std::filesystem::path& Folder) noexcept { return xscript::module::ops::RestoreFile(D, Folder, R); });
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
            auto Err = script_module_cmd::Edit(T, [&](xscript::module::descriptor& D, const std::filesystem::path& Folder) noexcept { return xscript::module::ops::RenameFile(D, Folder, Old, New); });
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
            script_module_cmd::Edit(T, [&](xscript::module::descriptor& D, const std::filesystem::path& Folder) noexcept { return xscript::module::ops::RenameFile(D, Folder, New, Old); });
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
            auto Err = script_module_cmd::Edit(T, [&](xscript::module::descriptor& D, const std::filesystem::path& Folder) noexcept { xscript::module::Sync(D, Folder, bRemove); return std::string(); });
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
            }
        }
        xcmdline::parser::handle m_hLibrary, m_hAsset, m_hRemove;
    };
    //================================================================================================
    // AddProjectModuleReference / RemoveProjectModuleReference / ListProjectModuleReferences / RegenerateProjectModuleSources -
    // the script modules a Game is made of. They live in the Game resource (xgame.plugin: its Descriptor.txt, see LevelEditor_ProjectGame.h); the resource
    // pipeline makes the CMake project of the game from it. The project has no Game of its own: every command says which Game it works on (-Game), and a Level
    // names the Game it runs under. Add and Remove are undoable and persist at once - no separate "Save" step. No cycle/orphan checks: this is a flat list, not a graph.
    //================================================================================================
    namespace game_arg
    {
        // -Game assetguid: the Game resource a command works on (none given: 0, no Game). Returns "" or what is wrong with the argument.
        inline std::string Read(const xcmdline::parser& Parser, xcmdline::parser::handle H, std::uint64_t& Game) noexcept
        {
            Game = 0;
            auto Arg = Parser.getOptionArgAs<std::string>(H, 0);
            if (std::holds_alternative<xerr>(Arg)) return {};
            const auto Guid = xresource_editor::commands::ParseAssetGuid(std::get<std::string>(Arg));
            if (Guid.m_Type != xgame::type_guid_v || Guid.m_Instance.empty()) return "not a Game asset guid";
            if (xgame::FindGameFolder(xlevel::ProjectRoot(), xgame::game_ref{ Guid.m_Instance }).empty()) return "the Game is not in the project";
            Game = Guid.m_Instance.m_Value;
            return {};
        }

        // The module commands work on one Game and the project has no Game of its own: -Game is required.
        inline std::string ReadRequired(const xcmdline::parser& Parser, xcmdline::parser::handle H, std::uint64_t& Game) noexcept
        {
            if (auto Bad = Read(Parser, H, Game); !Bad.empty()) return Bad;
            return Game ? std::string() : std::string("give the Game it works on: -Game <Game asset guid>");
        }
    }

    struct add_project_module_reference_cmd : xlevel::commands::level_command
    {
        add_project_module_reference_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_command(System, "AddProjectModuleReference", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Adds a Script-Module resource to a Game (undoable, persisted immediately). Usage: AddProjectModuleReference -Module assetguid [-Game assetguid]"; }
        void RegisterArguments() noexcept override
        {
            m_hModule = m_Parser.addOption("Module", "Script-Module asset guid, 32 hex digits", true, 1);
            m_hGame   = m_Parser.addOption("Game",   "Game asset guid, 32 hex digits", true, 1);
        }

        std::string Redo() noexcept override
        {
            auto ModuleArg = m_Parser.getOptionArgAs<std::string>(m_hModule, 0);
            if (std::holds_alternative<xerr>(ModuleArg)) return "AddProjectModuleReference: bad arguments";

            const auto Guid = xresource_editor::commands::ParseAssetGuid(std::get<std::string>(ModuleArg));
            if (Guid.m_Type != xscript::module::type_guid_v || Guid.m_Instance.empty()) return "AddProjectModuleReference: not a Script-Module asset guid";
            std::uint64_t Game = 0;
            if (auto Bad = game_arg::ReadRequired(m_Parser, m_hGame, Game); !Bad.empty()) return "AddProjectModuleReference: " + Bad;
            const xscript::module::module_ref Module{ Guid.m_Instance };
            auto Why = xlevel::EditGame(Game, [&](xgame::descriptor& D) -> std::string
            {
                if (std::find(D.m_Modules.begin(), D.m_Modules.end(), Module) == D.m_Modules.end()) D.m_Modules.push_back(Module);
                return {};
            });
            return Why.empty() ? Why : "AddProjectModuleReference: " + Why;
        }

        void BackupCurrenState(xundo::undo_file& File) noexcept override
        {
            auto ModuleArg = m_Parser.getOptionArgAs<std::string>(m_hModule, 0);
            xeditor::WriteString(File, std::holds_alternative<xerr>(ModuleArg) ? std::string(32, '0') : std::get<std::string>(ModuleArg));
            // whether the module was there before: Redo of an already listed module changes nothing, and its undo must not remove it
            std::uint64_t Game = 0;
            game_arg::Read(m_Parser, m_hGame, Game);
            std::uint8_t bWas = 0;
            if (!std::holds_alternative<xerr>(ModuleArg))
            {
                const auto Guid = xresource_editor::commands::ParseAssetGuid(std::get<std::string>(ModuleArg));
                const auto Modules = xlevel::ReadGame(Game).m_Modules;
                bWas = std::find(Modules.begin(), Modules.end(), xscript::module::module_ref{ Guid.m_Instance }) != Modules.end();
            }
            File.Write(bWas);
            File.Write(Game);
        }

        void Undo(xundo::undo_file& File) noexcept override
        {
            const auto Guid = xresource_editor::commands::ParseAssetGuid(xeditor::ReadString(File));
            std::uint8_t bWas = 0; File.Read(bWas);
            std::uint64_t Game = 0; File.Read(Game);
            if (bWas) return;
            const xscript::module::module_ref Module{ Guid.m_Instance };
            xlevel::EditGame(Game, [&](xgame::descriptor& D) -> std::string
            {
                if (auto It = std::find(D.m_Modules.begin(), D.m_Modules.end(), Module); It != D.m_Modules.end()) D.m_Modules.erase(It);
                return {};
            });
        }

        xcmdline::parser::handle m_hModule, m_hGame;
    };

    struct remove_project_module_reference_cmd : xlevel::commands::level_command
    {
        remove_project_module_reference_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_command(System, "RemoveProjectModuleReference", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Removes a Script-Module resource from a Game (undoable, persisted immediately). Usage: RemoveProjectModuleReference -Module assetguid [-Game assetguid]"; }
        void RegisterArguments() noexcept override
        {
            m_hModule = m_Parser.addOption("Module", "Script-Module asset guid, 32 hex digits", true, 1);
            m_hGame   = m_Parser.addOption("Game",   "Game asset guid, 32 hex digits", true, 1);
        }

        std::string Redo() noexcept override
        {
            auto ModuleArg = m_Parser.getOptionArgAs<std::string>(m_hModule, 0);
            if (std::holds_alternative<xerr>(ModuleArg)) return "RemoveProjectModuleReference: bad arguments";

            const auto Guid = xresource_editor::commands::ParseAssetGuid(std::get<std::string>(ModuleArg));
            const xscript::module::module_ref Module{ Guid.m_Instance };
            std::uint64_t Game = 0;
            if (auto Bad = game_arg::ReadRequired(m_Parser, m_hGame, Game); !Bad.empty()) return "RemoveProjectModuleReference: " + Bad;
            const auto Modules = xlevel::ReadGame(Game).m_Modules;
            if (std::find(Modules.begin(), Modules.end(), Module) == Modules.end()) return "RemoveProjectModuleReference: not a module reference of that Game";

            // Refused when a scene that is OPEN uses components of this module: its live entities say so, no rebuild needed (this used to build the game without the module, on this thread, and
            // look at what the new DLL still registered: minutes of a frozen editor for a question the data answers). The scenes of other, closed Levels are not in the way - they are checked
            // against the Game that runs them when they are opened - but the person is told how many there are.
            const auto ModuleValue = Module.m_Instance.m_Value;
            std::vector<std::string> InUse;
            const bool bRunsHere = Game != 0 && Game == xlevel::GameOfLevel(State().m_CurrentLevel.m_Instance.m_Value);         // the open scenes run under their Level's Game: another Game's list is not in their way
            if (bRunsHere)
            for (auto& SceneGuid : State().m_OpenScenes)
                for (const auto& Dep : xlioncore::Ecs(World()).CollectSceneComponentDependencies(SceneGuid))
                    if (Dep.m_Module == ModuleValue && std::find(InUse.begin(), InUse.end(), Dep.m_Name) == InUse.end()) InUse.push_back(Dep.m_Name);
            if (!InUse.empty())
            {
                std::string Names;
                for (const auto& Name : InUse) Names += (Names.empty() ? "" : ", ") + Name;
                return std::format("RemoveProjectModuleReference: refused - the open scene(s) use {} component(s) of this module: {}. Remove those components, or close the level, first", InUse.size(), Names);
            }

            if (auto Why = xlevel::EditGame(Game, [&](xgame::descriptor& D) -> std::string
                {
                    if (auto Found = std::find(D.m_Modules.begin(), D.m_Modules.end(), Module); Found != D.m_Modules.end()) D.m_Modules.erase(Found);
                    return {};
                }); !Why.empty())
                return "RemoveProjectModuleReference: " + Why;

            if (const auto Saved = xlevel::ScenesUsingModule(xlevel::ProjectRoot().wstring(), ModuleValue); !Saved.empty())
                xeditor::NotifyToast(std::format("The module was removed from the Game, but {} saved scene(s) still use its components (ListScenesUsingModule says which): they will not load them until the module is back", Saved.size()));

            return {};
        }

        void BackupCurrenState(xundo::undo_file& File) noexcept override
        {
            auto ModuleArg = m_Parser.getOptionArgAs<std::string>(m_hModule, 0);
            std::uint32_t Index = 0;
            std::uint64_t Game = 0;
            game_arg::Read(m_Parser, m_hGame, Game);
            if (!std::holds_alternative<xerr>(ModuleArg))
            {
                const auto Guid = xresource_editor::commands::ParseAssetGuid(std::get<std::string>(ModuleArg));
                const auto Modules = xlevel::ReadGame(Game).m_Modules;
                if (auto It = std::find(Modules.begin(), Modules.end(), xscript::module::module_ref{ Guid.m_Instance }); It != Modules.end())
                    Index = static_cast<std::uint32_t>(std::distance(Modules.begin(), It));
            }
            xeditor::WriteString(File, std::holds_alternative<xerr>(ModuleArg) ? std::string(32, '0') : std::get<std::string>(ModuleArg));
            File.Write(Index);
            File.Write(Game);
        }

        void Undo(xundo::undo_file& File) noexcept override
        {
            const auto Guid = xresource_editor::commands::ParseAssetGuid(xeditor::ReadString(File));
            std::uint32_t Index = 0; File.Read(Index);
            std::uint64_t Game = 0; File.Read(Game);
            const xscript::module::module_ref Module{ Guid.m_Instance };
            xlevel::EditGame(Game, [&](xgame::descriptor& D) -> std::string
            {
                if (std::find(D.m_Modules.begin(), D.m_Modules.end(), Module) == D.m_Modules.end())
                    D.m_Modules.insert(D.m_Modules.begin() + static_cast<std::ptrdiff_t>(std::min<std::size_t>(Index, D.m_Modules.size())), Module);
                return {};
            });
        }

        xcmdline::parser::handle m_hModule, m_hGame;
    };

    //================================================================================================
    // ListProjectModuleReferences - the project's Game resource and its modules, one guid per line (the Game first). Discovery command, same
    // "never need to read a raw file by hand" reasoning every other list command in this system was built for.
    //================================================================================================
    struct list_project_module_references_query_cmd : xlevel::commands::level_query_command
    {
        list_project_module_references_query_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "ListProjectModuleReferences", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Lists a Game resource and the Script-Modules it is made of. Usage: ListProjectModuleReferences -Game assetguid"; }
        void RegisterArguments() noexcept override
        {
            m_hGame = m_Parser.addOption("Game", "Game asset guid, 32 hex digits", true, 1);
        }

        std::string Query() noexcept override
        {
            std::uint64_t GameValue = 0;
            if (auto Bad = game_arg::ReadRequired(m_Parser, m_hGame, GameValue); !Bad.empty()) return "ListProjectModuleReferences: " + Bad;
            const auto Game = xlevel::ReadGame(GameValue);
            if (!Game.HasGame()) return "Game: (none)\n(empty)";
            std::string Out = "Game: " + xresource_editor::commands::FormatAssetGuid(xresource::full_guid{ xresource::instance_guid{ GameValue }, xgame::type_guid_v }) + "\n";
            if (Game.m_Modules.empty()) return Out + "(empty)";
            for (auto& M : Game.m_Modules)
                Out += xresource_editor::commands::FormatAssetGuid(xresource::full_guid{ M.m_Instance, xscript::module::type_guid_v }) + "\n";
            return Out;
        }
        xcmdline::parser::handle m_hGame;
    };

    //================================================================================================
    // RegenerateProjectModuleSources - compiles a Game resource again (every Game of the project when none is given), on demand (the resource pipeline makes the CMake project of the game:
    // Cache\Script\<Game>\CMakeLists.txt). Every command that changes what a Game is made of already causes this through the descriptor it writes - this exists for
    // recovery/debugging (e.g. after a raw file edit made outside the command bus) rather than any normal workflow needing to call it directly.
    //================================================================================================
    struct regenerate_project_module_sources_query_cmd : xlevel::commands::level_query_command
    {
        regenerate_project_module_sources_query_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "RegenerateProjectModuleSources", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Compiles a Game resource again (every Game of the project when none is given): the resource pipeline makes the CMake project of the game from its modules. Usage: RegenerateProjectModuleSources [-Game assetguid]"; }
        void RegisterArguments() noexcept override
        {
            m_hGame = m_Parser.addOption("Game", "Game asset guid, 32 hex digits (default: every Game of the project)", false, 1);
        }

        std::string Query() noexcept override
        {
            std::vector<std::uint64_t> Games;
            if (!std::holds_alternative<xerr>(m_Parser.getOptionArgAs<std::string>(m_hGame, 0)))
            {
                std::uint64_t Game = 0;
                if (auto Bad = game_arg::Read(m_Parser, m_hGame, Game); !Bad.empty()) return "RegenerateProjectModuleSources: " + Bad;
                Games.push_back(Game);
            }
            else for (const auto& [Game, Name] : xlevel::commands::BuildAssetNameMap(xgame::type_guid_v)) Games.push_back(Game);
            if (Games.empty()) return "RegenerateProjectModuleSources: the project has no Game resource";
            for (const auto Game : Games)
                xresource_editor::g_LibMgr.RecompileResource(xresource_editor::g_LibMgr.m_ProjectGUID, xresource::full_guid{ xresource::instance_guid{ Game }, xgame::type_guid_v });
            return std::format("RegenerateProjectModuleSources: {} Game(s) are queued to compile", Games.size());
        }
        xcmdline::parser::handle m_hGame;
    };

    //================================================================================================
    // ListModuleRegistrations - the components and systems of the loaded Game.dll and the script module that defines each one (the editor finds the module from the file the type is
    // defined in: see xscript_registration.h). One line each: kind, guid, name, module (asset guid, "-" for none), file (relative to the module's source_db). A component that is not listed
    // is the engine's or the editor's own. -Module keeps one module's.
    //================================================================================================
    struct list_module_registrations_query_cmd : xlevel::commands::level_query_command
    {
        list_module_registrations_query_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "ListModuleRegistrations", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Lists the components and systems of the loaded Game.dll and the script module that defines each one. Usage: ListModuleRegistrations [-Module assetguid]"; }
        void RegisterArguments() noexcept override
        {
            m_hModule = m_Parser.addOption("Module", "Script-Module asset guid, 32 hex digits: only that module's types", false, 1);
        }

        static std::string RelativeToSourceDb(const std::string& File) noexcept
        {
            std::string Text = File;
            std::ranges::replace(Text, '\\', '/');
            const auto Lowered = xscript::module::Lower(Text);
            const auto At = Lowered.rfind("/source_db/");
            return At == std::string::npos ? Text : Text.substr(At + 11);
        }

        std::string Query() noexcept override
        {
            const auto* pPlugin = xlevel::g_pGamePlugin;
            if (!pPlugin || !pPlugin->isLoaded()) return "ListModuleRegistrations: Game.dll is not loaded";
            if (!pPlugin->m_bHasRegistrations)    return "ListModuleRegistrations: the loaded Game.dll was built before modules were tracked: rebuild it";

            std::uint64_t Only = 0;
            if (auto Arg = m_Parser.getOptionArgAs<std::string>(m_hModule, 0); !std::holds_alternative<xerr>(Arg))
            {
                const auto Guid = xresource_editor::commands::ParseAssetGuid(std::get<std::string>(Arg));
                if (Guid.m_Type != xscript::module::type_guid_v || Guid.m_Instance.empty()) return "ListModuleRegistrations: not a Script-Module asset guid";
                Only = Guid.m_Instance.m_Value;
            }

            const auto Names = xlevel::commands::BuildAssetNameMap(xscript::module::type_guid_v);
            std::string Out = "ListModuleRegistrations: ok\nKind\tGuid\tName\tModule\tFile\n";
            for (const auto& R : pPlugin->m_Registrations)
            {
                if (Only && R.m_Module != Only) continue;
                std::string Module = "-";
                if (R.m_Module) Module = xresource_editor::commands::FormatAssetGuid(xresource::full_guid{ xresource::instance_guid{ R.m_Module }, xscript::module::type_guid_v });
                Out += std::format("{}\t{:016X}\t{}\t{}\t{}\n", R.m_Kind == 0 ? "component" : "system", R.m_Guid, R.m_Name, Module, R.m_Module ? RelativeToSourceDb(R.m_File) : R.m_File);
            }
            return Out;
        }

        xcmdline::parser::handle m_hModule;
    };

    //================================================================================================
    // Scenes, modules and Games (the data-only check, see LevelEditor_ComponentCompatibility.h): ListSceneModules, CheckGameCompatibility, ListScenesUsingModule. They read the files the
    // editor writes (ComponentDeps.txt of each scene, the Game's Descriptor.txt), so they answer before anything is built; a scene that is open with changes that are not saved is read as it
    // was last saved.
    //================================================================================================
    namespace module_dependencies
    {
        inline std::uint64_t HexArg(const xcmdline::parser& Parser, xcmdline::parser::handle H, bool& bGiven) noexcept
        {
            auto Arg = Parser.getOptionArgAs<std::string>(H, 0);
            bGiven = !std::holds_alternative<xerr>(Arg);
            return bGiven ? std::strtoull(std::get<std::string>(Arg).c_str(), nullptr, 16) : 0;
        }

        inline std::string Label(const std::unordered_map<std::uint64_t, std::string>& Names, std::uint64_t Instance) noexcept
        {
            const auto It = Names.find(Instance);
            return It == Names.end() ? std::format("{:X}", Instance) : It->second;
        }

        inline std::string Join(const std::vector<std::string>& Items) noexcept
        {
            std::string Out;
            for (const auto& I : Items) Out += (Out.empty() ? "" : ", ") + I;
            return Out;
        }

        inline std::string ModuleAsset(std::uint64_t Module) noexcept
        {
            return xresource_editor::commands::FormatAssetGuid(xresource::full_guid{ xresource::instance_guid{ Module }, xscript::module::type_guid_v });
        }
        inline std::string GameAsset(std::uint64_t Game) noexcept
        {
            return xresource_editor::commands::FormatAssetGuid(xresource::full_guid{ xresource::instance_guid{ Game }, xgame::type_guid_v });
        }
    }

    // ListSceneModules -Scene hex16 [-Own true]: the modules a scene needs, with the components it uses from each. With -Own true: only the scene itself (by default the scenes it depends on count).
    struct list_scene_modules_query_cmd : xlevel::commands::level_query_command
    {
        list_scene_modules_query_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "ListSceneModules", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Lists the script modules a scene needs and the components it uses from each (read from its ComponentDeps.txt; the scenes it depends on count unless -Own true). Usage: ListSceneModules -Scene hexguid [-Own true]"; }
        void RegisterArguments() noexcept override
        {
            m_hScene = m_Parser.addOption("Scene", "Scene instance guid, 16 hex digits", true, 1);
            m_hOwn   = m_Parser.addOption("Own",   "true: only the scene itself, not the scenes it depends on", false, 1);
        }
        std::string Query() noexcept override
        {
            bool bGiven = false;
            const auto Scene = module_dependencies::HexArg(m_Parser, m_hScene, bGiven);
            if (!bGiven || !Scene) return "ListSceneModules: bad arguments";
            auto OwnArg = m_Parser.getOptionArgAs<std::string>(m_hOwn, 0);
            const bool bTransitive = std::holds_alternative<xerr>(OwnArg) || std::get<std::string>(OwnArg) != "true";

            const std::wstring Project = xlevel::ProjectRoot().wstring();
            xlevel::scene_module_needs Needs;
            xlevel::AddSceneModuleNeeds(Needs, Project, Scene, bTransitive);
            const auto Modules = xlevel::commands::BuildAssetNameMap(xscript::module::type_guid_v);
            std::string Out = std::format("ListSceneModules: ok\nScene={:016X}  Scenes read={}\nModule\tName\tComponents\n", Scene, Needs.m_Visited.size());
            for (const auto& [Module, Need] : Needs.m_Modules)
                Out += std::format("{}\t{}\t{}\n", module_dependencies::ModuleAsset(Module), module_dependencies::Label(Modules, Module), module_dependencies::Join(Need.m_Components));
            if (!Needs.m_Unknown.m_Components.empty())
                Out += std::format("unknown\t\t{}\n", module_dependencies::Join(Needs.m_Unknown.m_Components));
            return Out;
        }
        xcmdline::parser::handle m_hScene, m_hOwn;
    };

    // CheckGameCompatibility (-Scene hex16 | -Level hex16) [-Game assetguid]: can a Game run the scene (or all the scenes of the Level)? Without -Game, every Game resource of the project answers.
    struct check_game_compatibility_query_cmd : xlevel::commands::level_query_command
    {
        check_game_compatibility_query_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "CheckGameCompatibility", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Says whether a Game lists every script module that a scene (or all the scenes of a Level) needs; without -Game, for every Game of the project. Usage: CheckGameCompatibility (-Scene hexguid | -Level hexguid) [-Game assetguid]"; }
        void RegisterArguments() noexcept override
        {
            m_hScene = m_Parser.addOption("Scene", "Scene instance guid, 16 hex digits", false, 1);
            m_hLevel = m_Parser.addOption("Level", "Level instance guid, 16 hex digits", false, 1);
            m_hGame  = m_Parser.addOption("Game",  "Game asset guid, 32 hex digits (default: every Game of the project)", false, 1);
        }
        std::string Query() noexcept override
        {
            bool bScene = false, bLevel = false;
            const auto Scene = module_dependencies::HexArg(m_Parser, m_hScene, bScene);
            const auto Level = module_dependencies::HexArg(m_Parser, m_hLevel, bLevel);
            if (bScene == bLevel) return "CheckGameCompatibility: give -Scene or -Level (one of them)";

            const std::wstring Project = xlevel::ProjectRoot().wstring();
            xlevel::scene_module_needs Needs;
            std::vector<std::uint64_t> Scenes;
            if (bScene) Scenes.push_back(Scene); else Scenes = xlevel::ReadLevelScenes(Project, Level);
            if (bLevel && Scenes.empty()) return std::format("CheckGameCompatibility: Level {:016X} was not found (or has no scenes)", Level);
            for (const auto S : Scenes) xlevel::AddSceneModuleNeeds(Needs, Project, S, /*bTransitive*/ true);

            const auto GameNames = xlevel::commands::BuildAssetNameMap(xgame::type_guid_v);
            const auto Modules   = xlevel::commands::BuildAssetNameMap(xscript::module::type_guid_v);
            const auto SceneNames = xlevel::commands::BuildAssetNameMap(xecs::scene::type_guid_v);

            std::vector<std::uint64_t> Games;
            if (auto Arg = m_Parser.getOptionArgAs<std::string>(m_hGame, 0); !std::holds_alternative<xerr>(Arg))
            {
                const auto Guid = xresource_editor::commands::ParseAssetGuid(std::get<std::string>(Arg));
                if (Guid.m_Type != xgame::type_guid_v || Guid.m_Instance.empty()) return "CheckGameCompatibility: not a Game asset guid";
                Games.push_back(Guid.m_Instance.m_Value);
            }
            else for (const auto& [Instance, Name] : GameNames) Games.push_back(Instance);
            std::ranges::sort(Games);

            std::string Out = bScene ? std::format("CheckGameCompatibility: ok\nScene={:016X}  Scenes read={}\n", Scene, Needs.m_Visited.size())
                                     : std::format("CheckGameCompatibility: ok\nLevel={:016X}  Scenes read={}\n", Level, Needs.m_Visited.size());
            for (const auto Game : Games)
            {
                std::vector<xscript::module::module_ref> GameModules;
                if (!xlevel::ReadGameModules(Game, GameModules)) { Out += std::format("Game {} '{}'\tnot in the project\n", module_dependencies::GameAsset(Game), module_dependencies::Label(GameNames, Game)); continue; }
                const auto Missing = xlevel::MissingModules(Needs, GameModules);
                const std::string Header = std::format("Game {} '{}'", module_dependencies::GameAsset(Game), module_dependencies::Label(GameNames, Game));
                if (Missing.empty())
                {
                    Out += Header + "\tcompatible";
                    if (!Needs.m_Unknown.m_Components.empty())
                        Out += std::format(" ({} component(s) of unknown module: {} - save their scenes with the Game loaded)", Needs.m_Unknown.m_Components.size(), module_dependencies::Join(Needs.m_Unknown.m_Components));
                    Out += "\n";
                    continue;
                }
                Out += Header + "\tincompatible\n" + xlevel::DescribeMissingModules(Missing);
            }
            return Out;
        }
        xcmdline::parser::handle m_hScene, m_hLevel, m_hGame;
    };

    // ListScenesUsingModule -Module assetguid: the scenes whose ComponentDeps.txt names a component of that module (the scene itself, not the scenes it depends on).
    struct list_scenes_using_module_query_cmd : xlevel::commands::level_query_command
    {
        list_scenes_using_module_query_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "ListScenesUsingModule", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Lists the scenes that use components of a script module (from their ComponentDeps.txt). Usage: ListScenesUsingModule -Module assetguid"; }
        void RegisterArguments() noexcept override
        {
            m_hModule = m_Parser.addOption("Module", "Script-Module asset guid, 32 hex digits", true, 1);
        }
        std::string Query() noexcept override
        {
            auto Arg = m_Parser.getOptionArgAs<std::string>(m_hModule, 0);
            if (std::holds_alternative<xerr>(Arg)) return "ListScenesUsingModule: bad arguments";
            const auto Guid = xresource_editor::commands::ParseAssetGuid(std::get<std::string>(Arg));
            if (Guid.m_Type != xscript::module::type_guid_v || Guid.m_Instance.empty()) return "ListScenesUsingModule: not a Script-Module asset guid";

            const auto SceneNames = xlevel::commands::BuildAssetNameMap(xecs::scene::type_guid_v);
            const auto Found = xlevel::ScenesUsingModule(xlevel::ProjectRoot().wstring(), Guid.m_Instance.m_Value);
            std::string Out = "ListScenesUsingModule: ok\nScene\tName\tComponents\n";
            for (const auto& [Instance, Components] : Found) Out += std::format("{:016X}\t{}\t{}\n", Instance, module_dependencies::Label(SceneNames, Instance), module_dependencies::Join(Components));
            return Out;
        }
        xcmdline::parser::handle m_hModule;
    };

    //================================================================================================
    // SetLevelGame / GetLevelGame - the Game a Level runs under (the Level's descriptor: `Game`). Empty is the project's Game. A Game that does not list a module that one of the Level's scenes
    // needs is refused, with the modules (the data-only check: ListSceneModules / CheckGameCompatibility say the same). Persisted at once, undoable.
    //================================================================================================
    namespace level_game
    {
        inline std::filesystem::path LevelFolder(std::uint64_t Level) noexcept
        {
            return xlevel::ProjectRoot() / "Descriptors" / "Level" / std::format("{:02X}", Level & 0xFF) / std::format("{:02X}", (Level >> 8) & 0xFF) / std::format("{:X}.desc", Level);
        }

        // Writes the Level's Descriptor.txt with another Game (the scenes stay as they are on disk), and the live Level of every open editor with it, so that a later Save keeps it.
        inline std::string Write(std::uint64_t Level, std::uint64_t Game) noexcept
        {
            const auto Folder = LevelFolder(Level);
            std::error_code Ec;
            if (!std::filesystem::is_directory(Folder, Ec)) return "the Level is not in the project";
            xecs::level::descriptor D;
            xproperty::settings::context Context{};
            const auto File = (Folder / "Descriptor.txt").wstring();
            if (std::filesystem::exists(File, Ec)) D.Serialize(true, File, Context);        // a Level that was never saved has none: it starts empty
            D.m_Game = xecs::level::game_ref{ xresource::instance_guid{ Game } };
            std::string Why;
            const bool bWritten = xscript::module::Retry([&]
            {
                xproperty::settings::context WriteContext{};
                if (auto Err = D.Serialize(false, File, WriteContext); Err) { Why = std::string(Err.getMessage()); return false; }
                return true;
            });
            if (!bWritten) return "the Level could not be saved: " + Why;
            for (auto* pContext : xlevel::g_LevelContexts)
                if (auto* pLevel = pContext->World().m_LevelMgr.Find(xecs::level::guid{ xresource::instance_guid{ Level } })) pLevel->m_Game = D.m_Game;
            return {};
        }
    }

    struct set_level_game_cmd : xlevel::commands::level_command
    {
        set_level_game_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_command(System, "SetLevelGame", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Sets the Game a Level runs under (undoable, persisted immediately); without -Game the Level names no Game: no scripts, components or systems of any module. A Game that lacks a module the Level's scenes need is refused (so is none). Usage: SetLevelGame -Level hexguid [-Game assetguid]"; }
        void RegisterArguments() noexcept override
        {
            m_hLevel = m_Parser.addOption("Level", "Level instance guid, 16 hex digits", true, 1);
            m_hGame  = m_Parser.addOption("Game",  "Game asset guid, 32 hex digits (default: none, the Level runs under the project's Game)", false, 1);
        }

        std::string Redo() noexcept override
        {
            bool bGiven = false;
            const auto Level = module_dependencies::HexArg(m_Parser, m_hLevel, bGiven);
            if (!bGiven || !Level) return "SetLevelGame: bad arguments";
            std::uint64_t Game = 0;
            if (auto Bad = game_arg::Read(m_Parser, m_hGame, Game); !Bad.empty()) return "SetLevelGame: " + Bad;

            // What the Level's scenes need must be in the Game that is to run them (the project's Game when none is named)
            const std::wstring Project = xlevel::ProjectRoot().wstring();
            xlevel::scene_module_needs Needs;
            for (const auto Scene : xlevel::ReadLevelScenes(Project, Level)) xlevel::AddSceneModuleNeeds(Needs, Project, Scene, /*bTransitive*/ true);
            const auto Target = Game ? xlevel::ReadGame(Game) : xlevel::project_game{};      // no Game: no module, so a Level whose scenes need one cannot go without
            if (!Game || Target.HasGame())
                if (const auto Missing = xlevel::MissingModules(Needs, Target.m_Modules); !Missing.empty())
                    return "SetLevelGame: refused - the Game does not list what the Level needs:\n" + xlevel::DescribeMissingModules(Missing);

            if (auto Why = level_game::Write(Level, Game); !Why.empty()) return "SetLevelGame: " + Why;
            return {};
        }

        void BackupCurrenState(xundo::undo_file& File) noexcept override
        {
            bool bGiven = false;
            const auto Level = module_dependencies::HexArg(m_Parser, m_hLevel, bGiven);
            File.Write(Level);
            File.Write(bGiven ? xlevel::ReadLevelGame(xlevel::ProjectRoot().wstring(), Level) : std::uint64_t{ 0 });
        }

        void Undo(xundo::undo_file& File) noexcept override
        {
            std::uint64_t Level = 0, Before = 0;
            File.Read(Level); File.Read(Before);
            if (Level) level_game::Write(Level, Before);
        }

        xcmdline::parser::handle m_hLevel, m_hGame;
    };

    struct get_level_game_query_cmd : xlevel::commands::level_query_command
    {
        get_level_game_query_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "GetLevelGame", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Says the Game a Level names (none: the Level has no scripts, components or systems of any module). Usage: GetLevelGame -Level hexguid"; }
        void RegisterArguments() noexcept override
        {
            m_hLevel = m_Parser.addOption("Level", "Level instance guid, 16 hex digits", true, 1);
        }
        std::string Query() noexcept override
        {
            bool bGiven = false;
            const auto Level = module_dependencies::HexArg(m_Parser, m_hLevel, bGiven);
            if (!bGiven || !Level) return "GetLevelGame: bad arguments";
            std::error_code Ec;
            if (!std::filesystem::is_directory(level_game::LevelFolder(Level), Ec)) return std::format("GetLevelGame: Level {:016X} is not in the project", Level);
            const auto Named = xlevel::GameOfLevel(Level);
            const auto Names = xlevel::commands::BuildAssetNameMap(xgame::type_guid_v);
            return std::format("GetLevelGame: ok\nGame={}\nSource={}\nName={}", Named ? module_dependencies::GameAsset(Named) : std::string("(none)"), Named ? "set" : "none"
                , Named ? module_dependencies::Label(Names, Named) : std::string());
        }
        xcmdline::parser::handle m_hLevel;
    };

    // DescribeLevel: what the Inspector shows when the Level is selected in the Level Tree (SelectLevel): the Level, its Game (and whether it can run the scenes), the Game's modules, and what each open scene needs.
    struct describe_level_query_cmd : xlevel::commands::level_query_command
    {
        describe_level_query_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "DescribeLevel", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Describes the open Level the way the Inspector does when the Level is selected: its Game, the Game's modules and what each scene needs. Usage: DescribeLevel"; }
        void RegisterArguments() noexcept override {}
        std::string Query() noexcept override
        {
            auto& State = get<xlevel::level_context>().State();
            if (State.m_CurrentLevel.empty()) return "DescribeLevel: no Level is open";
            return xlevel::DescribeLevelView(xlevel::BuildLevelView(State)) + std::format("Selected={}\n", State.m_bRootSelected ? "true" : "false");
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

    // ProbeEngineSet: makes a set of copies of the engine DLLs the way a Level that opens does (xlevel_engine_copies.h), shows that the copy of the core is a registry of its own (registering in it does not
    // touch the one this Level runs on) and that the render copy is bound to it, then frees the set again. What the independence of the Levels stands on, as a command.
    struct probe_engine_set_query_cmd : xlevel::commands::level_query_command
    {
        probe_engine_set_query_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "ProbeEngineSet", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Makes a set of renamed copies of the core and render DLLs, checks that the copy of the core has a registry of its own and that the render copy imports it, then frees the set. Usage: ProbeEngineSet"; }
        void RegisterArguments() noexcept override {}
        std::string Query() noexcept override
        {
            std::string Why;
            auto pSet = xlevel::Services().Engines.Make(Why);
            if (!pSet) return "ProbeEngineSet: failed: " + Why;

            auto pEcs = xlevel::CreateEcsEditor(pSet->m_Core.c_str());
            if (!pEcs) return "ProbeEngineSet: failed: the core copy has no editor interface";

            auto& Mine = xlioncore::Ecs(World());
            std::vector<const xecs::component::type::info*> Types;
            Mine.ListComponentTypes(Types);
            const auto MineBefore = Types.size();
            pEcs->ListComponentTypes(Types);
            const auto CopyBefore = Types.size();

            auto& CopyWorld = pEcs->CreateWorld();
            pEcs->RegisterHostComponents();
            pEcs->RegisterHostSystems();                    // locks the component types: the registry is complete after it
            pEcs->ListComponentTypes(Types);
            const auto CopyAfter = Types.size();
            Mine.ListComponentTypes(Types);
            const auto MineAfter = Types.size();
            const bool bIndependent = CopyAfter > CopyBefore && MineAfter == MineBefore && &CopyWorld != &World() && pEcs->Native() == &CopyWorld;

            std::string RenderImport = "none";
            bool bRender = false, bChecksum = true;
            if (!pSet->m_Render.empty())
            {
                const auto Imports = xlevel::engine::ImportsOf(xlevel::engine::ReadFile(pSet->m_RenderPath));
                RenderImport = Imports.empty() ? std::string("?") : Imports.front();
                auto pRender = xlevel::CreateRenderEditor(pSet->m_Render.c_str());
                bRender = pRender != nullptr;
                bChecksum = xlevel::engine::ChecksumIsRight(pSet->m_RenderPath);
            }

            const auto Out = std::format("ProbeEngineSet: ok\nCore={}\nRender={}\nRenderImportsCore={}\nRenderEditor={}\nChecksum={}\nRegistry: copy {} -> {} types, this Level {} -> {} types\nIndependent={}"
                , pSet->CoreName(), pSet->m_Render.empty() ? std::string("none") : std::filesystem::path(pSet->m_Render).string(), RenderImport, bRender ? "ok" : "none", bChecksum ? "ok" : "wrong"
                , CopyBefore, CopyAfter, MineBefore, MineAfter, bIndependent ? "yes" : "no");
            pEcs->DestroyWorld();
            return Out;
        }
    };
}

#endif // LevelEditor_COMMANDS_SCRIPTING_H
