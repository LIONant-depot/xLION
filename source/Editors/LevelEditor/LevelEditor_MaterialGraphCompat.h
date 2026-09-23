#pragma once

#include "dependencies/xresource_pipeline_v2/source/editor/E10_InspectorPickers.h"

// plugins/xmaterial.plugin's xmaterial_graph.cpp forward-declares RemapGUIDToString/
// ResourceBrowserPopup at global scope, expecting whichever example is compiled alongside it to
// supply a matching definition - this codebase's own convention (see E19/E20/E21/E24's near-
// identical per-example copies, each with its own private g_AssetBrowserPopup) is normally
// satisfied that way. LevelEditor doesn't compile any of those examples, so provide thin global-
// scope forwards to the shared e10:: versions instead of duplicating their implementation - same
// underlying e10::g_AssetBrowserPopup instance LevelEditor's own code already uses (LevelEditor_Kit.h),
// so there's still only one popup, not a second disconnected one.
//
// Deliberately NOT `inline`: only ever defined here, in this one TU (LevelEditor_Main.cpp) - and
// crucially, neither function is actually CALLED from within that TU itself, only forward-declared
// and called from xmaterial_graph.cpp's own separate TU. An `inline` definition that's never
// ODR-used locally gets silently stripped from the object file under /Zc:inline (MSVC's default
// for C++20) - "remove unreferenced COMDAT data" - which is exactly this case, and is why the
// linker couldn't find them the first time around.
void RemapGUIDToString(std::string& Name, const xresource::full_guid& PreFullGuid)
{
    e10::RemapGUIDToString(Name, PreFullGuid);
}

void ResourceBrowserPopup(const void* pUID, bool& Open, xresource::full_guid& Output, std::span<const xresource::type_guid> Filters)
{
    e10::ResourceBrowserPopup(pUID, Open, Output, Filters);
}
