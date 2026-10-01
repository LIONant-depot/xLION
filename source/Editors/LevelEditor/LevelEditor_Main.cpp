// Folded in directly (not a separate CMake source) - see the port's own CMakeLists.txt comment
// at the removed xgpu_imgui_breach target for why: it reproducibly fails to compile as its own
// independent MSBuild-invoked translation unit ("xgpu::device/window not a member of xgpu"), for
// reasons never root-caused, despite an exhaustive manual cl.exe reproduction never failing once.
// Compiling it as part of THIS TU, in THIS position (first), is the specific combination that's
// been verified working - moving it after LevelEditor's own includes reintroduced the same
// failure, so whatever the real cause is, it's sensitive to more than just "is xGPU.h already
// visible" - not fully understood, just empirically pinned down.
#include "dependencies/xGPU/source/Tools/xgpu_imgui_breach.cpp"

#include "source/Editors/LevelEditor/LevelEditor_MaterialGraphCompat.h"
#include "source/Editors/LevelEditor/LevelEditor_App.h"
#include "source/Editors/LevelEditor/LevelEditor_AppInit.h"
#include "source/Editors/LevelEditor/LevelEditor_AppFrame.h"
#include "source/Editors/LevelEditor/LevelEditor_AppFrameHeadless.h"
#include "source/Editors/LevelEditor/LevelEditor_AppToolbars.h"
#include "source/Editors/LevelEditor/extensions/asset_browser/LevelEditor_AppAssetBrowser.h"

// xtexture.plugin's own resource-loader .cpp - same "must be folded into a known-good TU, not an
// independent CMake source" situation as xgpu_imgui_breach.cpp above, but this one instead needs
// to come AFTER LevelEditor's own includes: it assumes several things some xGPU example normally
// brings in first (resource_mgr_user_data, xresource_pipeline::, xrsc::texture_type_guid_v,
// my_properties.h), all of which LevelEditor_App.h's own chain already provides by this point.
#include "plugins/xtexture.plugin/source/xtexture_xgpu_rsc_loader.h"
#include "plugins/xtexture.plugin/source/xtexture_rsc_descriptor.h"
#include "plugins/xtexture.plugin/source/xtexture_xgpu_rsc_loader.cpp"

// Asset Browser's own sub-tabs ("Resources", "Assets", "Compilation", ...) self-register into a
// global linked list (browser_registration_base::g_pHead) via a namespace-scope `inline` object at
// the bottom of each file - nothing calls into them directly, so if the header itself is never
// #include'd by anything actually linked into the binary, the registration constructor never runs
// and xresource_editor::asset_browser::m_Tabs stays empty ("No browser tab matching ..." for every tab). In
// xGPU's own build these come along for free via E10_TextureResourcePipeline.cpp (not part of this
// port), so they need the same explicit fold-in here.
#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_asset_browser_virtual_tree_tab.h"
#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_asset_browser_search_tab.h"
#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_asset_browser_compiler_tab.h"
#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_asset_browser_plugin_tab.h"
#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_asset_browser_files_tab.h"

//-----------------------------------------------------------------------------------
// LevelEditor - Level + Scene editor. The editor itself is level_editor::app (LevelEditor_App.h).
// Called by source/main_graphical.cpp / source/main_headless.cpp.
//-----------------------------------------------------------------------------------
int RunLevelEditorGraphical()
{
    level_editor::app App;
    if (const int Err = App.Init(/*bHeadlessMode*/ false)) return Err;
    App.Run();
    App.Shutdown();
    return 0;
}

int RunLevelEditorHeadless()
{
    level_editor::app App;
    if (const int Err = App.Init(/*bHeadlessMode*/ true)) return Err;
    App.RunHeadless();
    App.Shutdown();
    return 0;
}
