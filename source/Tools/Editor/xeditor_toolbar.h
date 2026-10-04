#ifndef XEDITOR_TOOLBAR_H
#define XEDITOR_TOOLBAR_H
#pragma once

// Per-editor top bar for the shared editor framework — Undo/Redo, Save, Compile + Feedback.
// Drawn via ImGui::BeginMenuBar() so it picks up ImGuiCol_MenuBarBg — the same App Toolbar
// color LevelEditor's Level Editor menu bar uses (official editor theme). Host windows must pass
// ImGuiWindowFlags_MenuBar to ImGui::Begin. Hosts must also PushStyleVar(WindowPadding, 0) around Begin/End like LevelEditor's Level Editor, or a hairline gap appears under the menu bar.
// Feedback colors/layout follow xresource_editor's Compile + Feedback strip.
#include "dependencies/xundo/source/xundo_system.h"
#include "dependencies/xeditor/include/xeditor/hint.h"
#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_asset_mgr.h"
#include "dependencies/xstrtool/source/xstrtool.h"
#include "source/Tools/Editor/xeditor_compile_logs.h"
#include "source/Tools/Editor/xeditor_resource_editor.h"
#include "dependencies/xlog/editor/xlog_diagnostics.h"
#include "dependencies/xeditor/include/xeditor/open_ref.h"
#include "imgui.h"
#include <memory>
#include <vector>
#include <string>
#include <format>

namespace xeditor
{
    struct toolbar_model
    {
        xundo::system*                                                  m_pUndo              = nullptr;
        bool                                                            m_bDirty             = false;
        bool                                                            m_bCanCompile        = true;
        std::shared_ptr<xresource_editor::compilation::historical_entry::log>        m_Log;
        std::vector<std::string>*                                       m_pValidationErrors  = nullptr;

        // The hint of a button, when the host has actions: called right after the button with the action's name (Undo / Redo / Save /
        // Compile). Without it the button keeps its plain tooltip.
        void (*m_OnHint)(void* pUser, const char* pAction) = nullptr;

        // The Feedback action (F6) raises this; the toolbar opens the Feedback popup and clears it.
        bool* m_pOpenFeedback = nullptr;

        // What the Feedback popup reads from the Logs (the xlog diagnostics view): the asset this editor edits, and "Open in Logs" (given the operation id, 0 = none yet).
        xlog::ref m_Subject;
        void (*m_OnOpenLogs)(void* pUser, std::uint64_t Operation) = &OpenLogsForOperation;

        // Undo / Redo for an editor whose undo needs more than m_pUndo->Undo() (the Level editor checks the write lock and Play first).
        // When set, the buttons call these; m_bUndoRedoEnabled false greys both out.
        void (*m_OnUndo)(void* pUser) = nullptr;
        void (*m_OnRedo)(void* pUser) = nullptr;
        bool   m_bUndoRedoEnabled     = true;

        // Drawn centred between the left buttons and the right (where Compile + Feedback sit): the Level editor's Play / Step.
        void (*m_OnCenter)(void* pUser) = nullptr;

        void (*m_OnSave)(void* pUser)    = nullptr;
        void (*m_OnCompile)(void* pUser) = nullptr;
        void* m_pUser                    = nullptr;

        // The editor the bar belongs to: with it the bar starts with the editor menu (the icon of the resource's type and a down arrow, one button) that has Save, Save All and Close.
        resource_editor* m_pEditor       = nullptr;
        xgpu::device*    m_pDevice       = nullptr;     // for the icon
        xresource::type_guid m_IconType  = {};          // the type whose icon it is, when the document does not say (the Level editor)
    };

    // The editor menu: one button, the icon of the resource type and a down arrow. Save saves this editor, Save All saves every open editor that has something pending, Close closes this one
    // (asking first when it has changes that are not saved).
    inline void RenderEditorMenu(toolbar_model& Model) noexcept
    {
        const auto& Style     = ImGui::GetStyle();
        constexpr const char* Arrow = "\xEE\x9C\x8D";                                      // Segoe MDL2 ChevronDown
        const float  IconSize = ImGui::GetFrameHeight() - 2.0f;                            // as big as the button allows: a pixel of the button around it
        const float  Gap      = 4.0f;
        const ImVec2 Size(Style.FramePadding.x + IconSize + Gap + ImGui::CalcTextSize(Arrow).x + Style.FramePadding.x, 0.0f);

        const bool bPressed = ImGui::Button("###EditorMenu", Size);
        const ImVec2 Min = ImGui::GetItemRectMin(), Max = ImGui::GetItemRectMax();
        if (Model.m_pDevice)
        {
            xresource_editor::EnsureIconAtlasTexture(xresource_editor::g_LibMgr.m_AssetPluginsDB, *Model.m_pDevice);
            const auto Icon = xresource_editor::g_LibMgr.m_AssetPluginsDB.getIconRef(Model.m_IconType.m_Value ? Model.m_IconType : Model.m_pEditor->getDocument().getGuid().m_Type, 0);
            if (Icon.isValid())
            {
                const ImVec2 At(Min.x + Style.FramePadding.x, Min.y + (Max.y - Min.y - IconSize) * 0.5f);
                ImGui::GetWindowDrawList()->AddImage((ImTextureRef)(void*)Icon.m_pTexture, At, ImVec2(At.x + IconSize, At.y + IconSize), ImVec2(Icon.m_U0, Icon.m_V0), ImVec2(Icon.m_U1, Icon.m_V1));
            }
        }
        ImGui::GetWindowDrawList()->AddText(ImVec2(Min.x + Style.FramePadding.x + IconSize + Gap, Min.y + Style.FramePadding.y), ImGui::GetColorU32(ImGuiCol_Text), Arrow);
        if (ImGui::IsItemHovered()) xeditor::hint::Text("The editor's menu: Save, Save All, Close");

        if (bPressed)
        {
            ImGui::SetNextWindowPos(ImVec2(Min.x, Max.y));
            ImGui::OpenPopup("###EditorMenuPopup");
        }
        if (ImGui::BeginPopup("###EditorMenuPopup"))
        {
            auto* pEditors = host::current() ? host::current()->find<open_resource_editors>() : nullptr;
            if (ImGui::MenuItem("Save", nullptr, false, Model.m_bDirty && Model.m_OnSave != nullptr)) Model.m_OnSave(Model.m_pUser);
            if (ImGui::MenuItem("Save All", nullptr, false, pEditors != nullptr)) pEditors->SaveAll();
            ImGui::Separator();
            if (ImGui::MenuItem("Close")) Model.m_pEditor->RequestClose();
            ImGui::EndPopup();
        }
        ImGui::SameLine(0, 8);
        ImGui::SeparatorEx(ImGuiSeparatorFlags_Vertical);
        ImGui::SameLine(0, 8);
    }

    // Requires the host window to have been begun with ImGuiWindowFlags_MenuBar.
    // Undo/Redo/Save stay left; Compile + Feedback are centered by default (LevelEditor Play/Stop pattern).
    inline void RenderEditorToolbar(toolbar_model& Model) noexcept
    {
        if (!ImGui::BeginMenuBar())
            return;

        ImGui::PushStyleVar(ImGuiStyleVar_ItemSpacing, ImVec2(4, 2));

        if (Model.m_pEditor) RenderEditorMenu(Model);

        if (Model.m_pUndo)
        {
            const bool bCanUndo = Model.m_bUndoRedoEnabled && Model.m_pUndo->GetUndoIndex() > 0;
            const bool bCanRedo = Model.m_bUndoRedoEnabled && Model.m_pUndo->GetUndoIndex() < static_cast<int>(Model.m_pUndo->GetHistoryCount());

            if (!bCanUndo) ImGui::BeginDisabled();
            if (ImGui::Button(" \xEE\x9E\xA7 "))
                { if (Model.m_OnUndo) Model.m_OnUndo(Model.m_pUser); else Model.m_pUndo->Undo(); }
            if (!bCanUndo) ImGui::EndDisabled();
            if (Model.m_OnHint) Model.m_OnHint(Model.m_pUser, "Undo"); else if (ImGui::IsItemHovered()) xeditor::hint::Text("Undo the last change");

            ImGui::SameLine(0, 4);

            if (!bCanRedo) ImGui::BeginDisabled();
            if (ImGui::Button(" \xEE\x9E\xA6 "))
                { if (Model.m_OnRedo) Model.m_OnRedo(Model.m_pUser); else Model.m_pUndo->Redo(); }
            if (!bCanRedo) ImGui::EndDisabled();
            if (Model.m_OnHint) Model.m_OnHint(Model.m_pUser, "Redo"); else if (ImGui::IsItemHovered()) xeditor::hint::Text("Redo the last change");

            ImGui::SameLine(0, 8);
            ImGui::SeparatorEx(ImGuiSeparatorFlags_Vertical);
            ImGui::SameLine(0, 8);
        }

        {
            if (!Model.m_bDirty) ImGui::BeginDisabled();
            if (ImGui::Button(" Save ") && Model.m_OnSave)
                Model.m_OnSave(Model.m_pUser);
            if (!Model.m_bDirty) ImGui::EndDisabled();
            if (Model.m_OnHint) Model.m_OnHint(Model.m_pUser, "Save"); else if (ImGui::IsItemHovered()) xeditor::hint::Text("Save the descriptor");
        }

        if (Model.m_OnCenter) Model.m_OnCenter(Model.m_pUser);

        if (Model.m_bCanCompile)
        {
            xresource_editor::compilation::historical_entry::result Results = xresource_editor::compilation::historical_entry::result::SUCCESS;
            if (Model.m_Log)
            {
                xcontainer::lock::scope lk(*Model.m_Log);
                Results = Model.m_Log->get().m_Result;
            }

            const bool bValidationFail = Model.m_pValidationErrors && !Model.m_pValidationErrors->empty();
            const bool bBusy = Results == xresource_editor::compilation::historical_entry::result::COMPILING
                            || Results == xresource_editor::compilation::historical_entry::result::COMPILING_WARNINGS;

            // Default for all editors: center Compile + Feedback like LevelEditor Play/Stop
            // (SameLine((windowWidth - groupW) * 0.5f)).
            const float CompileW  = ImGui::CalcTextSize("\xEF\x96\xB0 Compile ").x + ImGui::GetStyle().FramePadding.x * 2.0f;
            const float FeedbackW = ImGui::CalcTextSize("Feedback:\xee\xa5\xb2").x + ImGui::GetStyle().FramePadding.x * 2.0f;
            const float Gap       = 4.0f;
            const float GroupW    = CompileW + Gap + FeedbackW;
            // SetCursorPosX avoids SameLine wrap when left controls already pass center
            // (wrap made Compile/Feedback look like a second, taller toolbar row).
            {
                const float CenterX = (ImGui::GetWindowWidth() - GroupW) * 0.5f;
                const float Y = ImGui::GetCursorPosY();
                ImGui::SetCursorPos(ImVec2(ImMax(CenterX, ImGui::GetCursorPosX() + 8.0f), Y));
            }

            if (bBusy || bValidationFail) ImGui::BeginDisabled();
            if (ImGui::Button("\xEF\x96\xB0 Compile ") && Model.m_OnCompile)
                Model.m_OnCompile(Model.m_pUser);
            if (bBusy || bValidationFail) ImGui::EndDisabled();
            if (Model.m_OnHint) Model.m_OnHint(Model.m_pUser, "Compile"); else if (ImGui::IsItemHovered()) xeditor::hint::Text("Save the descriptor and trigger compilation");

            ImGui::SameLine(0, 4);

            std::uint32_t Color = IM_COL32(255, 255, 255, 255);
            if (bValidationFail)
                Color = IM_COL32(255, 170, 140, 255);
            else
            {
                switch (Results)
                {
                case xresource_editor::compilation::historical_entry::result::COMPILING_WARNINGS: Color = IM_COL32(255, 255, 0, 255); break;
                case xresource_editor::compilation::historical_entry::result::COMPILING:          Color = IM_COL32(0, 255, 0, 255);   break;
                case xresource_editor::compilation::historical_entry::result::FAILURE:            Color = IM_COL32(255, 170, 140, 255); break;
                case xresource_editor::compilation::historical_entry::result::SUCCESS_WARNINGS:   Color = IM_COL32(255, 255, 0, 255); break;
                case xresource_editor::compilation::historical_entry::result::SUCCESS:            Color = IM_COL32(255, 255, 255, 255); break;
                }
            }

            ImGui::PushStyleColor(ImGuiCol_Text, Color);
            bool bOpenFeedback = ImGui::Button("Feedback:\xee\xa5\xb2");
            if (Model.m_OnHint) Model.m_OnHint(Model.m_pUser, "Feedback"); else if (ImGui::IsItemHovered()) xeditor::hint::Text("Compilation / validation feedback");
            if (Model.m_pOpenFeedback && *Model.m_pOpenFeedback) { *Model.m_pOpenFeedback = false; bOpenFeedback = true; }
            // Feedback goes to the Logs: the drawer opens on the Logs tab, filtered to this asset's last compile (the whole build situation: its state, the
            // compiler's output, the problems). Only the descriptor's own validation errors, which are not build events, keep a small popup of their own.
            if (bOpenFeedback && !bValidationFail && Model.m_OnOpenLogs && xlog::hub::current())
            {
                const xlog::operation* pLast = xlog::FindLatestOperation(*xlog::hub::current(), "asset.compile", Model.m_Subject);
                Model.m_OnOpenLogs(Model.m_pUser, pLast ? pLast->m_Id : 0);
                bOpenFeedback = false;
            }
            if (bOpenFeedback)
            {
                const ImVec2 ButtonPos  = ImGui::GetItemRectMin();
                const ImVec2 ButtonSize = ImGui::GetItemRectSize();
                ImGui::SetNextWindowPos(ImVec2(ButtonPos.x, ButtonPos.y + ButtonSize.y));
                ImGui::OpenPopup("###EditorToolbarFeedback");
            }
            ImGui::PopStyleColor();

            if (ImGui::BeginPopup("###EditorToolbarFeedback"))
            {
                const float PopupW = std::min(640.0f, ImGui::GetMainViewport()->Size.x - 40.0f);
                ImGui::BeginChild("###EditorToolbarFeedback-Child", ImVec2(PopupW, 340));
                // What the compile and the descriptor said, in one generic view (the Logs' diagnostics): state first, errors before warnings, the rest of an event
                // under its row. The compiler's own text stays below, raw, for anything the view did not parse.
                if (auto* pLogs = xlog::hub::current())
                {
                    xlog::diagnostics_options Options;
                    Options.m_Subject = Model.m_Subject;
                    Options.m_pLiveErrors = Model.m_pValidationErrors;
                    Options.m_OnOpen = [](const xlog::ref& R) { xeditor::OpenRef(R); };
                    if (Model.m_OnOpenLogs) Options.m_OnOpenInLogs = [&Model](std::uint64_t Op) { Model.m_OnOpenLogs(Model.m_pUser, Op); };
                    xlog::RenderDiagnostics(*pLogs, Options);
                }
                else if (bValidationFail)
                    for (const auto& E : *Model.m_pValidationErrors) ImGui::TextWrapped("ERROR: %s", E.c_str());
                if (Model.m_Log)
                {
                    xcontainer::lock::scope lk(*Model.m_Log);
                    auto& Log = Model.m_Log->get();
                    if (!Log.m_Log.empty() && ImGui::CollapsingHeader("Compiler output (raw)"))
                    {
                        ImGui::PushTextWrapPos(0.0f);
                        ImGui::TextUnformatted(Log.m_Log.c_str());
                        ImGui::PopTextWrapPos();
                    }
                }
                ImGui::EndChild();
                ImGui::EndPopup();
            }

            if (Model.m_Log)
            {
                xcontainer::lock::scope lk(*Model.m_Log);
                auto& Log = Model.m_Log->get();
                if (!Log.m_Log.empty())
                {
                    ImGui::SameLine(0, 8);
                    ImGui::TextUnformatted(std::format("{}", xstrtool::getLastLine(Log.m_Log)).c_str());
                }
            }
        }

        ImGui::PopStyleVar();
        ImGui::EndMenuBar();
    }
}

#endif // XEDITOR_TOOLBAR_H
