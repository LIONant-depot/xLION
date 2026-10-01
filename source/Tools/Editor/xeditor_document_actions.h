#ifndef XEDITOR_DOCUMENT_ACTIONS_H
#define XEDITOR_DOCUMENT_ACTIONS_H
#pragma once

// The ACTIONS every resource editor has (Save, Undo, Redo, Compile): xproperty function members, so their keys, menu items and
// hints come from the same place as everything else (dependencies/actions.imgui). One object per open editor; it only needs the
// resource_editor interface, so any editor can own one: document_editor does, and the hand-written ones (Texture) can too.
//
// Paths: Editor/Save, Editor/Undo, Editor/Redo, Editor/Compile. They do exactly what the toolbar buttons do.
#include "dependencies/xeditor/include/xeditor/host.h"
#include "source/Tools/Editor/xeditor_resource_editor.h"
#include "source/Tools/Editor/xeditor_inspector.h"
#include "dependencies/actions.imgui/ximgui_actions.h"

namespace xeditor
{
    struct document_actions
    {
        resource_editor* m_pEditor = nullptr;       // xproperty creates objects by default construction, so the editor is a pointer
        document_actions() noexcept = default;
        explicit document_actions(resource_editor& Editor) noexcept : m_pEditor(&Editor) {}

        void        Save()    noexcept;     const char* WhyNoSave()    const noexcept;
        void        Undo()    noexcept;     const char* WhyNoUndo()    const noexcept;
        void        Redo()    noexcept;     const char* WhyNoRedo()    const noexcept;
        void        Compile() noexcept;     const char* WhyNoCompile() const noexcept;
        void        Feedback() noexcept;    const char* WhyNoFeedback() const noexcept;

        bool        m_bOpenFeedback = false;        // raised by Feedback(); the toolbar opens its popup and clears it

        XPROPERTY_DEF
        ( "Editor", document_actions
        , obj_action<"Save", &document_actions::Save
            , member_help<"Saves the descriptor. In every resource editor (Texture, Material, Font, Geometry, Skeleton, ...)">
            , ximgui::actions::member_keys<"Ctrl+S", true>
            , member_dynamic_reason<+[](const document_actions& A) noexcept -> const char* { return A.WhyNoSave(); }> >
        , obj_action<"Undo", &document_actions::Undo
            , member_help<"Undoes the last change. In every resource editor">
            , ximgui::actions::member_keys<"Ctrl+Z">
            , member_dynamic_reason<+[](const document_actions& A) noexcept -> const char* { return A.WhyNoUndo(); }> >
        , obj_action<"Redo", &document_actions::Redo
            , member_help<"Redoes the change that was just undone. In every resource editor">
            , ximgui::actions::member_keys<"Ctrl+Y,Ctrl+Shift+Z">
            , member_dynamic_reason<+[](const document_actions& A) noexcept -> const char* { return A.WhyNoRedo(); }> >
        , obj_action<"Compile", &document_actions::Compile
            , member_help<"Saves the descriptor and compiles the resource. In every resource editor">
            , ximgui::actions::member_keys<"F5", true>
            , member_dynamic_reason<+[](const document_actions& A) noexcept -> const char* { return A.WhyNoCompile(); }> >
        , obj_action<"Feedback", &document_actions::Feedback
            , member_help<"Shows what the last compile said, and any validation errors. In every resource editor">
            , ximgui::actions::member_keys<"F6", true>
            , member_dynamic_reason<+[](const document_actions& A) noexcept -> const char* { return A.WhyNoFeedback(); }> >
        )
    };
    XPROPERTY_REG(document_actions)
    XIMGUI_ACTIONS_OWNER(document_actions)

    inline const char* document_actions::WhyNoSave() const noexcept
    {
        return m_pEditor->getDocument().isDirty() ? nullptr : "no changes to save";
    }
    inline void document_actions::Save() noexcept { (void)m_pEditor->getUndo().Query("Save"); }

    inline const char* document_actions::WhyNoUndo() const noexcept
    {
        return m_pEditor->getUndo().GetUndoIndex() > 0 ? nullptr : "nothing to undo";
    }
    inline void document_actions::Undo() noexcept { m_pEditor->getUndo().Undo(); }

    inline const char* document_actions::WhyNoRedo() const noexcept
    {
        auto& U = m_pEditor->getUndo();
        return U.GetUndoIndex() < static_cast<int>(U.GetHistoryCount()) ? nullptr : "nothing to redo";
    }
    inline void document_actions::Redo() noexcept { m_pEditor->getUndo().Redo(); }

    inline const char* document_actions::WhyNoCompile() const noexcept
    {
        return m_pEditor->isLoaded() ? nullptr : "nothing is loaded";
    }
    inline void document_actions::Compile() noexcept { (void)m_pEditor->getUndo().Query("Compile"); }

    inline const char* document_actions::WhyNoFeedback() const noexcept { return WhyNoCompile(); }
    inline void document_actions::Feedback() noexcept { m_bOpenFeedback = true; }

    // The host's action context, if there is one (the graphical build provides it).
    inline ximgui::actions::context* ActionContext() noexcept
    {
        auto* pHost = host::current();
        return pHost ? pHost->find<ximgui::actions::context>() : nullptr;
    }

    // After a toolbar button: the hint of the action of that name (live key, why not). False when there is no action context.
    inline void HintFor(document_actions& Actions, const char* pAction) noexcept
    {
        auto* pCtx = ActionContext();
        if (!pCtx) return;
        if (const auto* pA = pCtx->Find(*xproperty::getObject(Actions), pAction)) pCtx->Hint(*pA, &Actions);
    }

    // ImGui::Begin for a window of an editor that has actions: those actions are also live while this window has the focus.
    inline bool BeginWithActions(document_actions& Actions, const char* pTitle, bool* pOpen = nullptr, ImGuiWindowFlags Flags = 0) noexcept
    {
        const bool bShown = ImGui::Begin(pTitle, pOpen, Flags);
        if (auto* pCtx = ActionContext()) pCtx->Scope(Actions);
        return bShown;
    }

    // What the mouse does in a 3D preview (listed on the mouse in the F1 view, and in the status line under the cursor). Descriptions only: the
    // preview handles the mouse itself.
    namespace gestures
    {
        using namespace ximgui::actions;
        inline constexpr gesture orbit[] =
        { { 0, mouse_input::Right,  mouse_kind::Drag,   "Look around", "Turns the view around what it looks at." }
        , { 0, mouse_input::Middle, mouse_kind::Drag,   "Pan",         "Slides the view sideways and up / down." }
        , { 0, mouse_input::Wheel,  mouse_kind::Scroll, "Zoom",        "Moves the view toward or away from what it looks at." } };
        inline constexpr gesture orbit_no_pan[] =
        { { 0, mouse_input::Right,  mouse_kind::Drag,   "Look around", "Turns the view around what it looks at." }
        , { 0, mouse_input::Wheel,  mouse_kind::Scroll, "Zoom",        "Moves the view toward or away from what it looks at." } };
    }

    // Call where a 3D preview handles the mouse, inside its window: this window now declares the preview's gestures.
    inline void PreviewGestures(bool bPan = true) noexcept
    {
        if (auto* pCtx = ActionContext()) pCtx->Gestures("Preview", bPan ? std::span<const ximgui::actions::gesture>(gestures::orbit) : std::span<const ximgui::actions::gesture>(gestures::orbit_no_pan));
    }
}

#endif // XEDITOR_DOCUMENT_ACTIONS_H
