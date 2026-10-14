#ifndef XEDITOR_RESOURCE_UPDATES_H
#define XEDITOR_RESOURCE_UPDATES_H
#pragma once

// A resource compiled again (successfully) is new data for xresource::g_Mgr: MarkUpdated, so every reference still holding the old data
// moves to the new one on its next getResource (a running editor shows a material recompiled after a change of a shader it includes,
// without a restart). Compiles finish on the compile thread and the manager is the main thread's: the GUIDs are queued here and applied
// by Apply, once a frame on the main thread (LevelEditor_AppFrame, before the frame ends). A host service: whoever holds resources of its own (a
// Level's copy of the engine core has its own resource manager) registers on m_OnUpdated and passes them on.
#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_asset_mgr.h"
#include <mutex>
#include <vector>

namespace xeditor
{
    class resource_updates
    {
    public:
        resource_updates() noexcept  { xresource_editor::g_LibMgr.m_OnCompilationState.Register<&resource_updates::OnState>(*this); }
        ~resource_updates() noexcept { xresource_editor::g_LibMgr.m_OnCompilationState.RemoveDelegates(this); }
        resource_updates(const resource_updates&) = delete;
        resource_updates& operator=(const resource_updates&) = delete;

        xdelegate::thread_unsafe<xresource::full_guid>  m_OnUpdated;      // the main thread, per resource compiled again

        // The main thread, once a frame
        void Apply() noexcept
        {
            std::vector<xresource::full_guid> Updated;
            {
                std::lock_guard Lock(m_Mutex);
                if (m_Updated.empty()) return;
                Updated.swap(m_Updated);
            }
            for (const auto& G : Updated)
            {
                xresource::g_Mgr.MarkUpdated(G);            // the editor's own (the resource editors' previews)
                m_OnUpdated.NotifyAll(G);                   // the others' (each Level's copy of the engine core)
            }
        }

    private:
        using log_t  = xresource_editor::compilation::historical_entry::log;
        using result = xresource_editor::compilation::historical_entry::result;

        void OnState(xresource_editor::library_mgr&, xresource_editor::library::guid, xresource::full_guid Guid, std::shared_ptr<log_t>& Log) noexcept
        {
            if (!Log) return;
            result R;
            {
                xcontainer::lock::scope Lock(*Log);
                R = Log->get().m_Result;
            }
            if (R != result::SUCCESS && R != result::SUCCESS_WARNINGS) return;
            std::lock_guard Lock(m_Mutex);
            m_Updated.push_back(Guid);
        }

        std::mutex                          m_Mutex;
        std::vector<xresource::full_guid>   m_Updated;
    };
}
#endif
