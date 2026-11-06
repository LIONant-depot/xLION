// The editor knows the TYPES of the engine's components (their reflection, to inspect them) but never registers them: the copy of the core it talks to does (xECSEditor::RegisterHostComponents).
// Without this, a header that says XSCRIPT_REGISTER_COMPONENT would make this binary run xECS registration code of its own (see xscript_registration.h, documentation/Editors/ecs_link_gate.md).
#define XSCRIPT_IMPORT_ONLY

// Folded in directly (not a separate CMake source) - see the port's own CMakeLists.txt comment
// at the removed xgpu_imgui_breach target for why: it reproducibly fails to compile as its own
// independent MSBuild-invoked translation unit ("xgpu::device/window not a member of xgpu"), for
// reasons never root-caused, despite an exhaustive manual cl.exe reproduction never failing once.
// Compiling it as part of THIS TU, in THIS position (first), is the specific combination that's
// been verified working - moving it after LevelEditor's own includes reintroduced the same
// failure, so whatever the real cause is, it's sensitive to more than just "is xGPU.h already
// visible" - not fully understood, just empirically pinned down.
#include "dependencies/xLIONRender/src/xlionrender_env.h"      // (the environment switches: one answer to MSVC's C4996, header only)
#include "dependencies/xGPU/source/Tools/xgpu_imgui_breach.cpp"
#if defined(XLION_LINUX_GUI)
    #include "source/Platform/xlion_linux_gui.h"      // Linux graphical editor: X11 clipboard, cursors, desktop dialogs
#endif

// This executable's new/delete counted - bytes and blocks, nothing else (the profiler's memory page and Profiler -Memory: app::Frame
// publishes them; each DLL keeps its own heap and is not counted here). Two atomic adds per allocation; the block's real size from the CRT.
// ponytail: memory new'd here and deleted in a DLL (or the reverse: one CRT heap) moves the count off - per-module counts if it drifts
#include <atomic>
#include <new>
#include <cstdlib>
#if defined(_WIN32)
    #include <malloc.h>
    #define XLION_BLOCK_SIZE(P) _msize(P)
#else
    #include <malloc.h>
    #define XLION_BLOCK_SIZE(P) malloc_usable_size(P)
#endif
namespace level_editor { inline std::atomic<std::int64_t> g_HeapBytes{ 0 }, g_HeapBlocks{ 0 }; }
static void* CountedAlloc(std::size_t n) noexcept
{
    void* p = std::malloc(n ? n : 1);
    if (!p) std::abort();                   // (out of memory: the editor stops - no exceptions)
    level_editor::g_HeapBytes.fetch_add(static_cast<std::int64_t>(XLION_BLOCK_SIZE(p)), std::memory_order_relaxed);
    level_editor::g_HeapBlocks.fetch_add(1, std::memory_order_relaxed);
    return p;
}
static void CountedFree(void* p) noexcept
{
    if (!p) return;
    level_editor::g_HeapBytes.fetch_sub(static_cast<std::int64_t>(XLION_BLOCK_SIZE(p)), std::memory_order_relaxed);
    level_editor::g_HeapBlocks.fetch_sub(1, std::memory_order_relaxed);
    std::free(p);
}
void* operator new  (std::size_t n)                         { return CountedAlloc(n); }
void* operator new[](std::size_t n)                         { return CountedAlloc(n); }
void* operator new  (std::size_t n, const std::nothrow_t&) noexcept { return CountedAlloc(n); }
void* operator new[](std::size_t n, const std::nothrow_t&) noexcept { return CountedAlloc(n); }
void  operator delete  (void* p) noexcept                   { CountedFree(p); }
void  operator delete[](void* p) noexcept                   { CountedFree(p); }
void  operator delete  (void* p, std::size_t) noexcept      { CountedFree(p); }
void  operator delete[](void* p, std::size_t) noexcept      { CountedFree(p); }

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
#include "source/Editors/LevelEditor/LevelEditor_FilesActions.h"

//-----------------------------------------------------------------------------------
// What the editor's renderer runs by default (Tomas, 2026-11-03: approved, a menu later): the voxel GI, the material tile pass, the contact shadows. A value already set wins; XLION_CLASSIC=1: none of
// them (the surfels, the raster). They are environment switches the renderer reads once: before anything starts
static void SetRendererDefaults() noexcept
{
    if (xlionrender::Env("XLION_CLASSIC")) return;
    const auto Default = [](const char* pName, const char* pValue)
    {
        if (xlionrender::Env(pName)) return;
#if _WIN32
        _putenv_s(pName, pValue);
#else
        setenv(pName, pValue, 0);
#endif
    };
    Default("XLION_GI_PROBES_ONLY", "1"); Default("XLION_GI_NO_PROBES", "1"); Default("XLION_GI_VOX_HITS", "1"); Default("XLION_GI_VOX", "0.5 2 16384");
    // (Tomas, 2026-11-03: the base image first, one feature at a time. Contact shadows: XLION_CONTACT="0.35 8 0.15 30 1")
    Default("XLION_TILE", "1");
    // (2026-11-06: the reflections' coarse directional store, 16 x 16 directions at the 4 m level, read by the receivers from .15 to .4 (rays below): 13.05 to 10.27 ms on Bistro, better against the path tracer at .15 to .4. XLION_VOX_DIRS=-1: off)
    Default("XLION_VOX_DIRS", "3,16"); Default("XLION_VOX_DIRS_TRACE", "0.1,0.4");      // (2026-11-06: rays below .1, was .15: the half size's trace 2.1 to 0.2 ms, the frame -1.4 ms at tomas; lit against the path tracer 24.8 to 25.8 % off, noise the same)
    // (2026-11-06: contact readers feed and read records of their own - the leak at pots, hedges, wall bases: GI light 33.0 to 30.1 % off against the path tracer, +.26 ms in the gather. XLION_VOX_AO_BUCKET=0: off)
    Default("XLION_VOX_AO_BUCKET", "0.85");
    Default("XLION_CONTACT", "0.35 8 0.15 30 1");      // (contact shadows, the sun's: on again - Tomas, 2026-11-06)
}

// LevelEditor - Level + Scene editor. The editor itself is level_editor::app (LevelEditor_App.h).
// Called by source/main_graphical.cpp / source/main_headless.cpp.
//-----------------------------------------------------------------------------------
int RunLevelEditorGraphical()
{
    SetRendererDefaults();
    level_editor::app App;
    if (const int Err = App.Init(/*bHeadlessMode*/ false)) return Err;
    App.Run();
    App.Shutdown();
    return 0;
}

int RunLevelEditorHeadless()
{
    SetRendererDefaults();
    level_editor::app App;
    if (const int Err = App.Init(/*bHeadlessMode*/ true)) return Err;
    App.RunHeadless();
    App.Shutdown();
    return 0;
}
