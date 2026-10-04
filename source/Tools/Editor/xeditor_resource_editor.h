#ifndef XEDITOR_RESOURCE_EDITOR_H
#define XEDITOR_RESOURCE_EDITOR_H
#pragma once

// A resource editor opened from the asset browser: one open resource, its undo system and its window. A resource type
// registers a factory; the host keeps the open editors (open_resource_editors), renders them and lists them in
// xeditor::host so the command console reaches each one as Name\Command.
#include "dependencies/xeditor/include/xeditor/host.h"
#include "dependencies/xeditor/include/xeditor/popup.h"
#include "source/Tools/Editor/xeditor_resource_tab.h"
#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_asset_mgr.h"

#include <algorithm>
#include <format>
#include <functional>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace xeditor
{
    // Hand GPU objects (textures, pipelines, instances, render passes) to the device to be destroyed a couple of frames later, when the GPU is done with them.
    // An object simply dropped goes to the same queue with its device link already cut, and crashes when the queue is emptied. (A buffer is the exception: dropping it is right, it queues itself.)
    template<typename... T_OBJECTS>
    void DestroyGpu(xgpu::device* pDevice, T_OBJECTS&... Objects) noexcept
    {
        if (pDevice) ((Objects.m_Private ? pDevice->Destroy(std::move(Objects)) : void()), ...);
    }

    struct resource_editor
    {
        virtual                     ~resource_editor()          = default;
        virtual IDocument&          getDocument()               noexcept = 0;
        virtual xundo::system&      getUndo()                   noexcept = 0;
        virtual void                Render()                    noexcept = 0;
        virtual bool                isLoaded()            const noexcept { return true; }       // the resource's data could be read

        void Focus() noexcept { m_bOpen = true; m_bRequestFocus = true; }

        // What is not saved yet, and how to save it: what the editor menu's Save / Save All and the question of Close use. An editor that keeps its changes in another way overrides them.
        virtual bool HasPendingChanges()      noexcept { return getDocument().isDirty(); }
        virtual std::string DisplayName()     noexcept { return ResolveResourceDisplayName(getDocument().getGuid(), nullptr); }
        virtual void SaveChanges()            noexcept { (void)getUndo().Query("Save"); }

        // Close, as the editor menu's Close and the window's close button do it: with nothing pending the editor closes, otherwise the host asks (Save / Don't Save / Cancel) before it does.
        // An editor that already has a question of its own for this (the Level editor) overrides it.
        virtual void RequestClose()           noexcept { m_bAskClose = true; }

        bool m_bOpen         = true;         // the window's close button clears it; the host then drops the editor (a button with something pending asks first: see open_resource_editors::RenderAll)
        bool m_bRequestFocus = false;
        bool m_bAskClose     = false;        // the question "save the changes?" is being asked
    };

    using resource_editor_factory = std::function<std::unique_ptr<resource_editor>(xresource::full_guid, xresource_editor::library::guid, xgpu::device*)>;

    inline std::unordered_map<xresource::type_guid, resource_editor_factory>& ResourceEditorFactories() noexcept
    {
        static std::unordered_map<xresource::type_guid, resource_editor_factory> s_Map;
        return s_Map;
    }

    // A resource type's editor header declares one of these at namespace scope: `inline const xeditor::auto_register_resource_editor g_Registration{ type, factory };`
    struct auto_register_resource_editor
    {
        auto_register_resource_editor(xresource::type_guid Type, resource_editor_factory Factory) noexcept { ResourceEditorFactories()[Type] = std::move(Factory); }
    };

    // The editors a host has open. Provided to the host as a service so commands and the asset browser reach it.
    struct open_resource_editors
    {
        std::vector<std::unique_ptr<resource_editor>> m_List;
        xgpu::device*                                 m_pDevice = nullptr;     // handed to every editor for its GPU work (null: no preview)

        resource_editor* Find(xresource::full_guid Guid) noexcept
        {
            for (auto& E : m_List) if (E && E->getDocument().getGuid() == Guid) return E.get();
            return nullptr;
        }

        // The library a resource lives in (empty when no open library has it).
        static xresource_editor::library::guid FindLibraryOf(xresource::full_guid Guid) noexcept
        {
            for (auto& Lib : xresource_editor::g_LibMgr.m_mLibraryDB)
            {
                bool bFound = false;
                Lib.second->m_InfoByTypeDataBase.FindAsReadOnly(Guid.m_Type, [&](const std::unique_ptr<xresource_editor::library_db::info_db>& InfoDB)
                {
                    InfoDB->m_InfoDataBase.FindAsReadOnly(Guid.m_Instance, [&](const xresource_editor::library_db::info_node&) { bFound = true; });
                });
                if (bFound) return Lib.first;
            }
            return {};
        }

        static bool HasEditorFor(xresource::type_guid Type) noexcept { return ResourceEditorFactories().contains(Type); }

        // Focuses the editor already open for this resource, or opens one. Null when the type has no editor.
        resource_editor* Open(xresource::full_guid Guid, xresource_editor::library::guid LibraryGuid) noexcept
        {
            if (auto* pOpen = Find(Guid)) { pOpen->Focus(); return pOpen; }
            auto It = ResourceEditorFactories().find(Guid.m_Type);
            if (It == ResourceEditorFactories().end()) return nullptr;
            m_List.push_back(It->second(Guid, LibraryGuid, m_pDevice));
            return m_List.back().get();
        }

        // Lists the open editors in the host's sessions (document and undo borrowed) so Name\Command and `list` reach them. Only open
        // editors are listed: a closed one is dropped by RenderAll next frame and must not stay borrowed.
        void SyncToHost(host& Host) noexcept
        {
            std::erase_if(Host.m_Sessions, [&](std::unique_ptr<session>& U) noexcept
            {
                if (!U || !U->is_borrowed()) return false;
                for (auto& E : m_List)
                    if (E && E->m_bOpen && U->m_pBorrowedUndo == &E->getUndo()) return false;
                std::erase_if(Host.m_WriteLocks, [&](const host::write_lock& L) noexcept { return L.pWriter == U.get(); });   // a closed editor holds no write locks
                return true;
            });

            for (auto& E : m_List)
            {
                if (!E || !E->m_bOpen) continue;
                session* pHit = nullptr;
                for (auto& U : Host.m_Sessions)
                    if (U && U->m_pBorrowedUndo == &E->getUndo()) { pHit = U.get(); break; }
                if (!pHit)
                {
                    Host.m_Sessions.push_back(std::make_unique<session>());
                    pHit = Host.m_Sessions.back().get();
                }
                pHit->m_pBorrowedDocument = &E->getDocument();
                pHit->m_pBorrowedUndo     = &E->getUndo();
            }
        }

        // Saves every open editor that has something pending, and then the changes of the asset database that no editor owns (a rename, a move: the SaveAssets command). Returns the
        // names of the editors it saved (empty: no editor had anything pending).
        std::vector<std::string> SaveAll() noexcept
        {
            std::vector<std::string> Saved;
            for (auto& E : m_List)
            {
                if (!E || !E->m_bOpen || !E->isLoaded() || !E->HasPendingChanges()) continue;
                E->SaveChanges();
                Saved.push_back(E->DisplayName());
            }
            xproperty::settings::context Context;
            xresource_editor::g_LibMgr.Save(Context);
            return Saved;
        }

        bool AnyPending() noexcept
        {
            for (auto& E : m_List) if (E && E->m_bOpen && E->isLoaded() && E->HasPendingChanges()) return true;
            return false;
        }

        // The question of a Close that has something to lose: one editor at a time, in the middle of that editor. Save saves and closes (an editor that could not save stays open),
        // Don't Save drops what was changed, Cancel leaves everything as it was.
        void RenderCloseQuestions() noexcept
        {
            for (auto& E : m_List)
            {
                if (!E || !E->m_bAskClose) continue;
                if (!E->HasPendingChanges()) { E->m_bAskClose = false; E->m_bOpen = false; continue; }

                const std::string Name  = E->DisplayName();
                const std::string Title = std::format("Save changes?###CloseQuestion{:p}", static_cast<const void*>(E.get()));
                if (!ImGui::IsPopupOpen(Title.c_str())) ImGui::OpenPopup(Title.c_str());
                if (BeginModal(Title.c_str()))
                {
                    ImGui::Text("%s has changes that are not saved.", Name.c_str());
                    ImGui::Spacing();
                    if (ImGui::Button("Save"))       { E->SaveChanges(); E->m_bAskClose = false; if (!E->HasPendingChanges()) E->m_bOpen = false; ImGui::CloseCurrentPopup(); }
                    ImGui::SameLine();
                    if (ImGui::Button("Don't Save")) { E->m_bAskClose = false; E->m_bOpen = false; ImGui::CloseCurrentPopup(); }
                    ImGui::SameLine();
                    if (ImGui::Button("Cancel"))     { E->m_bAskClose = false; ImGui::CloseCurrentPopup(); }
                    ImGui::EndPopup();
                }
                break;
            }
        }

        // Drops the editors that closed themselves. Never while one of them is being rendered.
        void DropClosed() noexcept
        {
            std::erase_if(m_List, [](auto& E) noexcept { return !E || !E->m_bOpen; });
        }

        // Once a frame: drops the closed editors and renders the rest.
        void RenderAll() noexcept
        {
            if (auto* pHost = host::current()) SyncToHost(*pHost);
            DropClosed();
            for (auto& E : m_List)
            {
                const bool bWasOpen = E->m_bOpen;
                E->Render();
                if (bWasOpen && !E->m_bOpen && E->HasPendingChanges()) { E->m_bOpen = true; E->RequestClose(); }          // the window's close button: not before the question
            }
            RenderCloseQuestions();
        }
    };
}

#endif // XEDITOR_RESOURCE_EDITOR_H
