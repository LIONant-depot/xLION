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
#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_compile_view.h"
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
        bool                                                            m_bOrderOpen         = false;   // the resource has a compilation order that is not over: its own compile may be, what it made may not
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
        // Feedback: the drawer on the Compilation tab, with the compile of this editor's asset (its instance guid, m_Subject.m_Id) open there
        void (*m_OnOpenCompilation)(void* pUser, std::uint64_t Instance) = &OpenCompilationFor;

        // Undo / Redo for an editor whose undo needs more than m_pUndo->Undo() (the Level editor checks the write lock and Play first).
        // When set, the buttons call these; m_bUndoRedoEnabled false greys both out.
        void (*m_OnUndo)(void* pUser) = nullptr;
        void (*m_OnRedo)(void* pUser) = nullptr;
        bool   m_bUndoRedoEnabled     = true;

        // Drawn centred between the left buttons and the right (where Compile + Feedback sit): the Level editor's Play / Step.
        void (*m_OnCenter)(void* pUser) = nullptr;

        void (*m_OnSave)(void* pUser)    = nullptr;
        void (*m_OnCompile)(void* pUser) = nullptr;
        void (*m_OnCancel)(void* pUser)  = nullptr;      // the Cancel button (Compile while a compile runs); without it the bar cancels m_Log itself (RequestCancel)
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
            if (ImGui::MenuItem((std::string(save_icon_v) + "  Save").c_str(), "Ctrl+S", false, Model.m_bDirty && Model.m_OnSave != nullptr)) Model.m_OnSave(Model.m_pUser);
            if (ImGui::MenuItem((std::string(save_all_icon_v) + "  Save All").c_str(), "Ctrl+Shift+S")) (void)SaveAllNow();
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
    // The short form of the Compilation tab, shared by every editor's Compile bar: what the compile of the resource is doing or did. The Feedback button opens the full one.
    inline void RenderCompileStatus( const toolbar_model& Model ) noexcept
    {
        namespace ui = xresource_editor::compile_ui;
        using result = xresource_editor::compilation::historical_entry::result;
        const auto V = ui::ReadLog(Model.m_Log);
        ImGui::SameLine(0, 10);

        const bool bFinishing = Model.m_bOrderOpen && !V.m_bRunning && !V.m_bQueued;        // its own compile is over, what it made is not
        if (V.m_bRunning || bFinishing)
        {
            ui::log_view Shown = V;
            if (bFinishing) { Shown.m_Result = result::COMPILING; Shown.m_pParsed = nullptr; }
            const std::string Text = bFinishing ? std::string("Building what it made") : ui::ProgressText(V);
            ui::ProgressBar(Shown, ImVec2(170.0f, ImGui::GetFrameHeight() - 4.0f), Text.c_str());
            if (!bFinishing && V.m_Seconds >= 0.0) { ImGui::SameLine(0, 8); ImGui::TextDisabled("%s", ui::FormatSeconds(V.m_Seconds).c_str()); }
        }
        else if (V.m_bQueued)
        {
            ui::Chip("Queued", ui::ColMuted());
            if (V.m_Seconds >= 0.0) { ImGui::SameLine(0, 8); ImGui::TextDisabled("waiting %s", ui::FormatSeconds(V.m_Seconds).c_str()); }
        }
        // (when it is over there is nothing here: the Feedback button says how it went)
    }

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
            const int nPulse = Model.m_bDirty ? PushSavePulse() : 0;                // unsaved: it breathes towards green
            if (ImGui::Button((std::string(" ") + save_icon_v + " ").c_str()) && Model.m_OnSave)       // the icon of Save, not the word
                Model.m_OnSave(Model.m_pUser);
            if (nPulse) ImGui::PopStyleColor(nPulse);
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
            const bool bBusy = Model.m_bOrderOpen
                            || Results == xresource_editor::compilation::historical_entry::result::QUEUED      // an order that waits for a worker is as open as one that runs
                            || Results == xresource_editor::compilation::historical_entry::result::COMPILING
                            || Results == xresource_editor::compilation::historical_entry::result::COMPILING_WARNINGS;

            // What Feedback says by itself: a soft colour and a small icon (a smile when all went well, a triangle with a count for warnings, a circle for errors).
            // Nothing is there until there is something to say: a resource that was never compiled has no feedback.
            namespace ui = xresource_editor::compile_ui;
            using result = xresource_editor::compilation::historical_entry::result;
            enum class look { neutral, ok, warn, error, muted };
            const auto View = Model.m_Log ? ui::ReadLog(Model.m_Log) : ui::log_view{};
            const bool bHasFeedback = bValidationFail || Model.m_bOrderOpen || View.m_Order != 0;
            look Look = look::neutral;
            int  nIcon = 0;
            if (bValidationFail) { Look = look::error; nIcon = static_cast<int>(Model.m_pValidationErrors->size()); }
            else if (!bBusy && View.m_Order != 0)
            {
                const int nErr  = View.m_pParsed ? View.m_pParsed->m_nErrors   : 0;
                const int nWarn = View.m_pParsed ? View.m_pParsed->m_nWarnings : 0;
                if      (nErr > 0 || View.m_Result == result::FAILURE)                              { Look = look::error; nIcon = std::max(nErr, 1); }
                else if (nWarn > 0 || View.m_Result == result::SUCCESS_WARNINGS)                    { Look = look::warn;  nIcon = std::max(nWarn, 1); }
                else if (View.m_Result == result::CANCELLED)                                        Look = look::muted;
                else                                                                                Look = look::ok;
            }
            const ImU32 LookCol = Look == look::ok ? ui::ColOk() : Look == look::warn ? ui::ColWarn() : Look == look::error ? ui::ColError() : Look == look::muted ? ui::ColMuted() : 0u;
            const std::string IconText = (Look == look::warn || Look == look::error) ? std::format("{}", nIcon) : std::string{};
            const float IconW = Look == look::ok ? 20.0f : (Look == look::warn || Look == look::error) ? 22.0f + ImGui::CalcTextSize(IconText.c_str()).x : 0.0f;
            const float FeedbackW = bHasFeedback ? ImGui::CalcTextSize("Feedback:").x + ImGui::GetStyle().FramePadding.x * 2.0f + IconW : 0.0f;
            // Default for all editors: center Compile + Feedback like LevelEditor Play/Stop
            // (SameLine((windowWidth - groupW) * 0.5f)).
            const float CompileW  = ImGui::CalcTextSize("\xEF\x96\xB0 Compile ").x + ImGui::GetStyle().FramePadding.x * 2.0f;
            const float Gap       = 4.0f;
            const float GroupW    = CompileW + (bHasFeedback ? Gap + FeedbackW : 0.0f);
            // SetCursorPosX avoids SameLine wrap when left controls already pass center
            // (wrap made Compile/Feedback look like a second, taller toolbar row).
            {
                const float CenterX = (ImGui::GetWindowWidth() - GroupW) * 0.5f;
                const float Y = ImGui::GetCursorPosY();
                ImGui::SetCursorPos(ImVec2(ImMax(CenterX, ImGui::GetCursorPosX() + 8.0f), Y));
            }

            // While a compile runs Compile is Cancel: it ends the compiler's process tree and marks the compile cancelled (compilation::RequestCancel)
            if (bBusy && Model.m_Log)
            {
                if (ImGui::Button("\xEE\x9C\x91 Cancel##Compile", ImVec2(CompileW, 0)))
                {
                    if (Model.m_OnCancel) Model.m_OnCancel(Model.m_pUser);
                    else                  xresource_editor::compilation::RequestCancel(*Model.m_Log);
                }
                if (ImGui::IsItemHovered()) xeditor::hint::Text("Stop the compile: the compiler and what it started end, the resource is marked cancelled");
            }
            else
            {
                if (bBusy || bValidationFail) ImGui::BeginDisabled();
                if (ImGui::Button("\xEF\x96\xB0 Compile ") && Model.m_OnCompile)
                    Model.m_OnCompile(Model.m_pUser);
                if (bBusy || bValidationFail) ImGui::EndDisabled();
                if (Model.m_OnHint) Model.m_OnHint(Model.m_pUser, "Compile"); else if (ImGui::IsItemHovered()) xeditor::hint::Text("Save the descriptor and trigger compilation");
            }

            int nFeedbackColors = 0, nFeedbackVars = 0;
            bool bOpenFeedback = false;
            if (bHasFeedback)
            {
                ImGui::SameLine(0, 4);
                if (LookCol)
                {
                    ImGui::PushStyleColor(ImGuiCol_Text,          ImGui::ColorConvertU32ToFloat4(LookCol));
                    ImGui::PushStyleColor(ImGuiCol_Button,        ImGui::ColorConvertU32ToFloat4(ui::Fade(LookCol, 24)));
                    ImGui::PushStyleColor(ImGuiCol_ButtonHovered, ImGui::ColorConvertU32ToFloat4(ui::Fade(LookCol, 56)));
                    ImGui::PushStyleColor(ImGuiCol_ButtonActive,  ImGui::ColorConvertU32ToFloat4(ui::Fade(LookCol, 84)));
                    nFeedbackColors = 4;
                }
                ImGui::PushStyleVar(ImGuiStyleVar_ButtonTextAlign, ImVec2(1.0f, 0.5f));      // the text at the right: the icon has the left
                nFeedbackVars = 1;
                bOpenFeedback = ImGui::Button("Feedback:", ImVec2(FeedbackW, 0.0f));
                if (Model.m_OnHint) Model.m_OnHint(Model.m_pUser, "Feedback"); else if (ImGui::IsItemHovered()) xeditor::hint::Text("Compilation / validation feedback");

                // the icon, inside the button
                const ImVec2 Min = ImGui::GetItemRectMin();
                const float  H   = ImGui::GetItemRectSize().y;
                auto* pList = ImGui::GetWindowDrawList();
                const ImVec2 C(Min.x + ImGui::GetStyle().FramePadding.x + 8.0f, Min.y + H * 0.5f);
                if (Look == look::ok) ui::DrawSmile(pList, C, LookCol);
                else if (Look == look::warn || Look == look::error)
                {
                    ui::DrawGlyph(pList, C, Look == look::error);
                    pList->AddText(ImVec2(C.x + 11.0f, Min.y + (H - ImGui::GetTextLineHeight()) * 0.5f), LookCol, IconText.c_str());
                }
            }
            if (Model.m_pOpenFeedback && *Model.m_pOpenFeedback) { *Model.m_pOpenFeedback = false; bOpenFeedback = true; }
            // Feedback goes to the Compilation tab: the drawer opens there with the compile of this asset open (its state, the problems, the compiler's
            // output). Only the descriptor's own validation errors, which are not build events, keep a small popup of their own. A bar with no asset to
            // name (no subject) still goes to the Logs.
            if (bOpenFeedback && !bValidationFail && Model.m_OnOpenCompilation && Model.m_Subject.m_Id != 0)
            {
                Model.m_OnOpenCompilation(Model.m_pUser, Model.m_Subject.m_Id);
                bOpenFeedback = false;
            }
            else if (bOpenFeedback && !bValidationFail && Model.m_OnOpenLogs && xlog::hub::current())
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
            if (nFeedbackColors) ImGui::PopStyleColor(nFeedbackColors);
            if (nFeedbackVars)   ImGui::PopStyleVar(nFeedbackVars);

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

            // How it is going, next to the button: a bar with what the compiler is doing while it runs, a state with its warnings and errors when it is over
            if (Model.m_Log && !bValidationFail) RenderCompileStatus(Model);
        }

        ImGui::PopStyleVar();
        ImGui::EndMenuBar();
    }
}

#endif // XEDITOR_TOOLBAR_H
