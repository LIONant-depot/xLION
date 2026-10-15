#ifndef XEDITOR_VIRTUAL_RESOURCES_H
#define XEDITOR_VIRTUAL_RESOURCES_H
#pragma once

// The editor half of the virtual resources an owner's compiler makes (documentation/Editors/virtual_resources_plan.md): the command and the button that
// take away the ones the compiler no longer makes. They stay on disk with their edits when an import is turned off or the model loses a material (the
// editor does not compile them); this is the way to get rid of them.
//
//      RemoveUnusedImportedResources       removes the unused virtual resources of this resource (undoable: the files and the library entries come back)
#include "source/Tools/Editor/xeditor_descriptor_editor.h"
#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_commands_assets.h"

#include <cstdio>
#include <filesystem>
#include <fstream>

namespace xeditor::virtual_resources
{
    struct remove_unused_cmd : xundo::command_base
    {
        xeditor::file_document& m_Doc;

        remove_unused_cmd(xundo::system& System, xeditor::file_document& Doc) noexcept
            : command_base(System, "RemoveUnusedImportedResources", nullptr), m_Doc(Doc) { RegisterArguments(); }

        const char* getCommandHelp() const noexcept override { return "Removes the imported resources (Material Instances, Textures, Skeleton, Animations, atlases) that this resource no longer makes, with their edits (undoable). Usage: RemoveUnusedImportedResources"; }
        void RegisterArguments() noexcept override {}

        std::string Redo() noexcept override
        {
            const auto Unused = xresource_editor::g_LibMgr.UnusedVirtualsOf(m_Doc.m_LibraryGuid, m_Doc.m_Guid);
            if (Unused.empty()) return "RemoveUnusedImportedResources: nothing is unused";
            for (auto It = Unused.rbegin(); It != Unused.rend(); ++It) xresource_editor::g_LibMgr.RemoveVirtualResource(m_Doc.m_LibraryGuid, *It);
            return {};
        }

        // What comes back on an undo: for each resource its guid, its folder and the files in it
        void BackupCurrenState(xundo::undo_file& File) noexcept override
        {
            const auto Unused = xresource_editor::g_LibMgr.UnusedVirtualsOf(m_Doc.m_LibraryGuid, m_Doc.m_Guid);
            xeditor::WriteString(File, std::to_string(Unused.size()));
            for (auto& Guid : Unused)
            {
                std::wstring InfoPath;
                xresource_editor::g_LibMgr.getNodeInfo(m_Doc.m_LibraryGuid, Guid, [&](xresource_editor::library_db::info_node& Node) { InfoPath = Node.m_Path; });
                const auto Folder = std::filesystem::path(InfoPath).parent_path();

                std::vector<std::filesystem::path> Files;
                std::error_code Ec;
                if (!InfoPath.empty()) for (auto It = std::filesystem::directory_iterator(Folder, Ec); !Ec && It != std::filesystem::directory_iterator(); It.increment(Ec)) if (It->is_regular_file(Ec)) Files.push_back(It->path());

                xeditor::WriteString(File, std::format("{:X} {:X}", Guid.m_Instance.m_Value, Guid.m_Type.m_Value));
                xeditor::WriteString(File, xstrtool::To(Folder.wstring()));
                xeditor::WriteString(File, std::to_string(Files.size()));
                for (auto& F : Files)
                {
                    std::ifstream In(F, std::ios::binary);
                    xeditor::WriteString(File, xstrtool::To(F.filename().wstring()));
                    xeditor::WriteString(File, std::string(std::istreambuf_iterator<char>(In), {}));
                }
            }
        }

        void Undo(xundo::undo_file& File) noexcept override
        {
            const int Count = std::atoi(xeditor::ReadString(File).c_str());
            std::vector<xresource::full_guid> Restored;
            for (int i = 0; i < Count; ++i)
            {
                std::uint64_t Instance = 0, Type = 0;
                const auto Ids = xeditor::ReadString(File);
                std::sscanf(Ids.c_str(), "%llx %llx", reinterpret_cast<unsigned long long*>(&Instance), reinterpret_cast<unsigned long long*>(&Type));
                const auto Folder = std::filesystem::path(xstrtool::To(xeditor::ReadString(File)));
                const int  nFiles = std::atoi(xeditor::ReadString(File).c_str());

                std::error_code Ec;
                std::filesystem::create_directories(Folder, Ec);
                for (int f = 0; f < nFiles; ++f)
                {
                    const auto Name    = xeditor::ReadString(File);
                    const auto Content = xeditor::ReadString(File);
                    std::ofstream Out(Folder / std::filesystem::path(xstrtool::To(Name)), std::ios::binary | std::ios::trunc);
                    Out.write(Content.data(), static_cast<std::streamsize>(Content.size()));
                }
                Restored.push_back({ xresource::instance_guid{ Instance }, xresource::type_guid{ Type } });
            }
            // The parents first: they were backed up shallowest first, so the links to a parent find it
            for (auto& G : Restored) xresource_editor::g_LibMgr.LoadVirtualDescriptor(m_Doc.m_LibraryGuid, G);
        }
    };

    //--------------------------------------------------------------------------------------------
    // The button of an editor panel: how many are unused, and a confirmation before the command runs (they may hold the user's edits)
    //--------------------------------------------------------------------------------------------
    struct unused_button
    {
        int     m_Count     = 0;
        double  m_NextCheck = 0;

        void Draw(xundo::system& Undo, xeditor::file_document& Doc) noexcept
        {
            if (ImGui::GetTime() >= m_NextCheck)
            {
                m_NextCheck = ImGui::GetTime() + 1.0;
                m_Count     = static_cast<int>(xresource_editor::g_LibMgr.UnusedVirtualsOf(Doc.m_LibraryGuid, Doc.m_Guid).size());
            }
            if (m_Count == 0) return;

            if (ImGui::Button(std::format("Remove {} unused imported resources###RemoveUnusedImported", m_Count).c_str())) ImGui::OpenPopup("Remove unused imported resources?###RemoveUnusedImportedPopup");
            if (ImGui::IsItemHovered()) ImGui::SetTooltip("The model no longer makes them (a material left it, an import is off). They stay with your edits until you remove them");

            if (ImGui::BeginPopupModal("Remove unused imported resources?###RemoveUnusedImportedPopup", nullptr, ImGuiWindowFlags_AlwaysAutoResize))
            {
                ImGui::Text("%d imported resources are not made by this resource any more.", m_Count);
                ImGui::TextUnformatted("They may hold edits of yours. Removing them can be undone.");
                if (ImGui::Button("Remove")) { xeditor::Run(Undo, "RemoveUnusedImportedResources"); m_NextCheck = 0; ImGui::CloseCurrentPopup(); }
                ImGui::SameLine();
                if (ImGui::Button("Cancel")) ImGui::CloseCurrentPopup();
                ImGui::EndPopup();
            }
        }
    };
}

#endif
