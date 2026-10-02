#ifndef XEDITOR_COMPILE_LOGS_H
#define XEDITOR_COMPILE_LOGS_H
#pragma once

// Every asset compile as an operation of the Logs (documentation/Editors/DESIGN_logs.md, 6.10) - one listener on the library manager, not one hook per
// resource editor: Texture, Material, Font and the generic document editors all get the same Feedback view because the compile is recorded where it
// happens, whether or not an editor is open for that asset (the background compile of a project that fails at startup is in the Logs too).
//
//      asset.compile   subject = the asset (typed ref), channel asset.compile.<type>, outcome = what the compiler said
//        [Warning]/[Error] lines of the compiler's output   -> diagnostics (problems), by the pipeline adapter
//        everything else                                    -> log events, the progress bars as debug-level progress
//
// The library manager notifies from the compile worker threads (once when a compile starts, once or more when it ends: the dependents of a compiled
// asset are told too, with the same log). The bridge starts the operation on the start notification and ends it on the first final one for that log;
// a final notification for a log it already finished is ignored (it is the cascade, not a second compile).
#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_asset_mgr.h"
#include "dependencies/xlog/source/xlog_pipeline.h"
#include "dependencies/xeditor/include/xeditor/host.h"

#include <deque>
#include <memory>
#include <mutex>
#include <unordered_map>

namespace xeditor
{
    // The asset as the Logs name things: a typed reference. The id is the instance guid, so the same asset is the same subject in every view.
    inline xlog::ref AssetRef(xresource::full_guid Guid) noexcept
    {
        xlog::ref R;
        R.m_Type = xlog::ref::type::Asset;
        R.m_Id   = Guid.m_Instance.m_Value;
        return R;
    }

    // "Open in Logs" of an editor's Feedback view: the drawer on the Logs tab, filtered to the operation.
    inline void OpenLogsForOperation(void*, std::uint64_t Operation) noexcept
    {
        if (auto* pHost = host::current()) pHost->show_logs(Operation ? std::format("op:{}", Operation) : std::string("channel:asset.compile"));
    }

    class compile_log_bridge
    {
    public:
        compile_log_bridge() noexcept  { xresource_editor::g_LibMgr.m_OnCompilationState.Register<&compile_log_bridge::OnState>(*this); }
        ~compile_log_bridge() noexcept { xresource_editor::g_LibMgr.m_OnCompilationState.RemoveDelegates(this); }
        compile_log_bridge(const compile_log_bridge&) = delete;
        compile_log_bridge& operator=(const compile_log_bridge&) = delete;

    private:
        using log_t  = xresource_editor::compilation::historical_entry::log;
        using result = xresource_editor::compilation::historical_entry::result;

        struct open_compile
        {
            xlog::op_handle m_Op;
            std::uint64_t   m_Asset = 0;              // the asset's instance guid
            std::string     m_TypeName;
            xlog::ref       m_Subject;
        };

        static constexpr std::size_t finished_remembered_v = 64;

        void OnState(xresource_editor::library_mgr& LibMgr, xresource_editor::library::guid Library, xresource::full_guid Guid, std::shared_ptr<log_t>& Log) noexcept
        {
            auto* pHub = xlog::hub::current();
            if (!pHub || !Log) return;

            result Result;
            std::string Output;
            {
                xcontainer::lock::scope Lock(*Log);
                Result = Log->get().m_Result;
                if (Result != result::COMPILING && Result != result::COMPILING_WARNINGS) Output = Log->get().m_Log;
            }
            const bool bRunning = Result == result::COMPILING || Result == result::COMPILING_WARNINGS;

            std::lock_guard Lock(m_Mutex);
            auto It = m_Open.find(Log.get());
            if (It == m_Open.end())
            {
                if (!bRunning && WasFinished(Log)) return;                // the cascade telling a dependent about a compile that is already recorded

                // A compile we did not see start: either it is starting now (the normal case), or it failed before it could start (no compiler for the
                // type) and this is the only word there will be. The name is looked up only for a start: the cascade calls from inside the library's locks.
                open_compile Fresh;
                Fresh.m_Asset = Guid.m_Instance.m_Value;
                Fresh.m_Subject = AssetRef(Guid);
                if (auto pPlugin = LibMgr.m_AssetPluginsDB.find(Guid.m_Type); pPlugin) Fresh.m_TypeName = pPlugin->m_TypeName;
                std::string Name;
                if (bRunning) LibMgr.getNodeInfo(Library, Guid, [&](xresource_editor::library_db::info_node& Node) { Name = Node.m_Info.m_Name; });
                Fresh.m_Subject.m_Path = Name;
                for (auto Old = m_Open.begin(); Old != m_Open.end(); ) Old = Old->second.m_Asset == Fresh.m_Asset ? m_Open.erase(Old) : std::next(Old);      // an unfinished one of the same asset is abandoned
                Fresh.m_Op = pHub->Begin("asset.compile", { xlog::origin::type::System, "asset pipeline", 0 }, Fresh.m_Subject
                    , std::format("Compile {}", Name.empty() ? Fresh.m_TypeName : Name));
                It = m_Open.emplace(Log.get(), std::move(Fresh)).first;
            }
            if (bRunning) return;

            open_compile& C = It->second;
            std::string Channel = "asset.compile";
            if (!C.m_TypeName.empty()) { Channel += '.'; for (char c : C.m_TypeName) Channel += static_cast<char>(std::tolower(static_cast<unsigned char>(c))); }
            xlog::pipeline_output_adapter Adapter(*pHub, C.m_Op, C.m_Subject, std::move(Channel));
            xlog::FeedPipelineOutput(Adapter, Output);
            Result == result::FAILURE ? C.m_Op.Fail() : C.m_Op.Succeed();

            m_Finished.push_back(Log);
            if (m_Finished.size() > finished_remembered_v) m_Finished.pop_front();
            m_Open.erase(It);
        }

        bool WasFinished(const std::shared_ptr<log_t>& Log) const noexcept
        {
            for (const auto& W : m_Finished) if (W.lock().get() == Log.get()) return true;
            return false;
        }

        std::mutex                                          m_Mutex;
        std::unordered_map<const void*, open_compile>       m_Open;             // by the compile's log: what a start and its end have in common
        std::deque<std::weak_ptr<log_t>>                    m_Finished;         // the logs already recorded, to tell a cascade from a new compile
    };
}

#endif // XEDITOR_COMPILE_LOGS_H
