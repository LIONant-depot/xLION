cmake_minimum_required(VERSION 3.10)
project(xLION LANGUAGES C CXX)
set(TARGET_PROJECT "xLION")
set(COMPONENT_REGISTRY "")

# Mirrors xGPU's own xECSV2 shared-library option (see dependencies/xGPU/CMakeLists.txt) - needed
# for the same reason: the LevelEditor's Game.dll hot-reload system only works when xECSV2 is a
# shared library both xLION and a future Game.dll can link against. The library itself is now built
# by the xLIONCore depot (see dependencies/xLIONCore), which compiles xECSV2 in as a dependency -
# LIONCore.dll, not xECSV2.dll.
option(XECS_BUILD_SHARED_LIBRARY "Build the ECS as its own shared library (LIONCore.dll) instead of compiling it directly into the target" ON)

if(POLICY CMP0169)
  cmake_policy(SET CMP0169 OLD)
endif()

#
# Fetch Common.cmake from xcmake_tools - identical bootstrap to xGPU's own root CMakeLists.txt
#
include(FetchContent)
FetchContent_Declare(
  xcmake_tools
  GIT_REPOSITORY https://github.com/LIONant-depot/xcmake_tools.git
  GIT_TAG main
  GIT_SHALLOW TRUE
  SOURCE_DIR "${CMAKE_BINARY_DIR}/_deps/xcmake_tools"
)
FetchContent_MakeAvailable(xcmake_tools)
include(${CMAKE_BINARY_DIR}/_deps/xcmake_tools/Common.cmake)

# Linux port (clang): applies to every target added below, dependencies included, and never to MSVC.
#  - -fms-extensions/-fdeclspec: accept the MSVC syntax the depots use (__declspec(noinline), ...);
#    dllexport/dllimport are no-ops on ELF, where every symbol is exported by default anyway.
#  - the force-included compat header supplies the MSVC secure-CRT names and the std headers MSVC's STL
#    pulls in transitively (see source/Platform/xlion_platform_compat_linux.h).
if(NOT WIN32)
  add_compile_options(
    "$<$<COMPILE_LANGUAGE:CXX>:-include${CMAKE_SOURCE_DIR}/source/Platform/xlion_platform_compat_linux.h>"
    "$<$<COMPILE_LANGUAGE:CXX>:-fms-extensions>"
    "$<$<COMPILE_LANGUAGE:CXX>:-fdeclspec>"
    -fPIC
    -march=x86-64-v3   # AVX2/FMA/F16C: xmath uses those intrinsics unconditionally (MSVC needs no flag for them)
    -ferror-limit=200
    -Wno-unknown-pragmas -Wno-ignored-attributes -Wno-microsoft-template -Wno-microsoft-cast
    -Wno-unused-value -Wno-switch -Wno-deprecated-declarations -Wno-nonportable-include-path
  )
  # MSVC defines _DEBUG for Debug builds (/MDd); several depots key debug-only members/asserts off it.
  add_compile_definitions($<$<CONFIG:Debug>:_DEBUG>)
  # zstd's x86-64 Huffman fast path lives in a .S file the xcompression component does not list; MSVC
  # builds never use it either, so turn it off and use the C implementation.
  add_compile_definitions(ZSTD_DISABLE_ASM)
endif()

#
# Get and build the sample project (Assets, plugins, and most third-party dependencies live here -
# same mechanism xGPU itself uses, reused verbatim so LevelEditor's plugin editors and asset
# pipeline work identically once ported).
#
# Linux (WSL) port: example.lionprj's Install.bat is Windows-only - on other platforms the tree
# (example.lionprj + its Cache/dependencies and Cache/Plugins clones) must already be in place (see
# documentation/Linux/README_linux_headless.md). Never auto-populate there: FetchContent_Populate of
# example.lionprj into an existing source dir wipes it.
if(NOT WIN32 AND NOT EXISTS "${CMAKE_SOURCE_DIR}/example.lionprj/Cache/dependencies")
    message(FATAL_ERROR "example.lionprj/Cache/dependencies is missing - set the tree up first (see documentation/Linux/README_linux_headless.md)")
endif()
if(WIN32 AND NOT EXISTS "${CMAKE_SOURCE_DIR}/example.lionprj/Cache/Plugins/check_changes.bat")
    FetchContent_Declare(
      xresource_pipeline_example
      GIT_REPOSITORY https://github.com/LIONant-depot/example.lionprj.git
      GIT_TAG main
      GIT_SHALLOW TRUE
      SOURCE_DIR "${CMAKE_SOURCE_DIR}/example.lionprj"
    )
    FetchContent_Populate(xresource_pipeline_example)

    set(XEXAMPLE_PLUGIN_BUILD_DIR "${CMAKE_SOURCE_DIR}/example.lionprj")
    message(STATUS "Running Install.bat in ${XEXAMPLE_PLUGIN_BUILD_DIR}...")
    execute_process(
        COMMAND "${XEXAMPLE_PLUGIN_BUILD_DIR}/Install.bat" "return"
        WORKING_DIRECTORY "${XEXAMPLE_PLUGIN_BUILD_DIR}"
        RESULT_VARIABLE result
    )
    if(result)
        message(FATAL_ERROR "Failed to execute Install.bat: ${result}")
    endif()
endif()

#
# Worm holes to unify all the dependencies/plugins - identical mechanism to xGPU's own
#
if(NOT EXISTS "${CMAKE_SOURCE_DIR}/dependencies")
  file(CREATE_LINK "${CMAKE_SOURCE_DIR}/example.lionprj/Cache/dependencies" "${CMAKE_SOURCE_DIR}/dependencies" SYMBOLIC RESULT result)
  if(result)
    message(FATAL_ERROR "Failed to create symlink: ${result}")
  endif()
endif()

if(NOT EXISTS "${CMAKE_SOURCE_DIR}/plugins")
  file(CREATE_LINK "${CMAKE_SOURCE_DIR}/example.lionprj/Cache/plugins" "${CMAKE_SOURCE_DIR}/plugins" SYMBOLIC RESULT result)
  if(result)
    message(FATAL_ERROR "Failed to create symlink: ${result}")
  endif()
endif()

# xscene.plugin, xlevel.plugin, xscript_module.plugin - the Scene/Level editors and the scripting
# core LevelEditor is actually built on - plus xPhysicsMaterial.plugin (its editor). Header-only
# (nothing to compile ahead of time), so - same as xGPU's own root CMakeLists.txt - they're never in
# Install.bat's PLUGINS loop, just cloned straight here and referenced through the plugins/ worm hole above.
foreach(HeaderOnlyPlugin xscene.plugin xlevel.plugin xscript_module.plugin xgame.plugin xPhysicsMaterial.plugin)
    if(NOT EXISTS "${CMAKE_SOURCE_DIR}/example.lionprj/Cache/Plugins/${HeaderOnlyPlugin}/source")
        execute_process(
            COMMAND git clone --depth 1 https://github.com/LIONant-depot/${HeaderOnlyPlugin}.git "${CMAKE_SOURCE_DIR}/example.lionprj/Cache/Plugins/${HeaderOnlyPlugin}"
            RESULT_VARIABLE result
        )
        if(result)
            message(FATAL_ERROR "Failed to clone ${HeaderOnlyPlugin}: ${result}")
        endif()
    endif()
endforeach()

# xscript_module.plugin and xgame.plugin ship the compilers of the ScriptModule and Game resources (Descriptor.txt -> the CMake file of the module; the modules' CMake files ->
# the CMake project of the game). The resource pipeline runs the compilers of every type as exes, and Install.bat only builds the ones it knows, so these are built here when they
# are missing (a developer rebuilds one with its plugin's build/CreateAndBuildProject.bat). A failed build is a warning: the resources then report "compiler not found" when they are
# compiled, and nothing else is affected.
foreach(CompilerPlugin xscript_module xgame)
    set(COMPILER_PLUGIN_DIR "${CMAKE_SOURCE_DIR}/example.lionprj/Cache/Plugins/${CompilerPlugin}.plugin")
    if(WIN32 AND EXISTS "${COMPILER_PLUGIN_DIR}/build/CreateAndBuildProject.bat" AND NOT EXISTS "${COMPILER_PLUGIN_DIR}/build/${CompilerPlugin}_compiler.vs2022/Release/${CompilerPlugin}_compiler.exe")
        if(NOT EXISTS "${COMPILER_PLUGIN_DIR}/dependencies")
            file(CREATE_LINK "${CMAKE_SOURCE_DIR}/example.lionprj/Cache/dependencies" "${COMPILER_PLUGIN_DIR}/dependencies" SYMBOLIC RESULT result)
        endif()
        message(STATUS "Building the ${CompilerPlugin} compiler...")
        execute_process(
            COMMAND "${COMPILER_PLUGIN_DIR}/build/CreateAndBuildProject.bat" "return"
            WORKING_DIRECTORY "${COMPILER_PLUGIN_DIR}/build"
            RESULT_VARIABLE result
        )
        if(result)
            message(WARNING "The ${CompilerPlugin} compiler did not build (${result}): its resources cannot be compiled until it does")
        endif()
    endif()
endforeach()

# Config-only plugins (no source/ folder): they just register a resource type, its name and icon, with
# the Asset Browser - without a clone here the type shows up with no icon and a raw guid for a name.
foreach(ConfigOnlyPlugin xprefab.plugin)
    if(NOT EXISTS "${CMAKE_SOURCE_DIR}/example.lionprj/Cache/Plugins/${ConfigOnlyPlugin}/Plugin.config")
        execute_process(
            COMMAND git clone --depth 1 https://github.com/LIONant-depot/${ConfigOnlyPlugin}.git "${CMAKE_SOURCE_DIR}/example.lionprj/Cache/Plugins/${ConfigOnlyPlugin}"
            RESULT_VARIABLE result
        )
        if(result)
            message(FATAL_ERROR "Failed to clone ${ConfigOnlyPlugin}: ${result}")
        endif()
    endif()
endforeach()

# xmaterial.plugin hardcodes the pre-port path to the Command Console's text-editor widget
# (source/Examples/E19_MaterialEditor/E19_TextEditor.h) - that file now lives at
# source/Tools/Editor/xeditor_text_widget.h (see the port's own file-migration notes). Idempotent
# patch, same technique as the imgui-node-editor patches below.
set(XMATERIAL_EDITOR_H "${CMAKE_SOURCE_DIR}/plugins/xmaterial.plugin/source/Editor/xmaterial_editor.h")
if(EXISTS "${XMATERIAL_EDITOR_H}")
  file(READ "${XMATERIAL_EDITOR_H}" XMATERIAL_EDITOR_CONTENTS)
  string(FIND "${XMATERIAL_EDITOR_CONTENTS}" "source/Examples/E19_MaterialEditor/E19_TextEditor.h" TEXTEDITOR_OLD_PATH_FOUND)
  if(NOT TEXTEDITOR_OLD_PATH_FOUND EQUAL -1)
    string(REPLACE
      "source/Examples/E19_MaterialEditor/E19_TextEditor.h"
      "source/Tools/Editor/xeditor_text_widget.h"
      XMATERIAL_EDITOR_PATCHED "${XMATERIAL_EDITOR_CONTENTS}")
    file(WRITE "${XMATERIAL_EDITOR_H}" "${XMATERIAL_EDITOR_PATCHED}")
  endif()
endif()

# xtexture.plugin's resource-loader .cpp assumes it sits 2 directories below a "tools" sibling
# folder (a layout from whichever repo it was originally vendored inside) - true for wherever
# xGPU's own build reaches it from, not for this one (plugins/xtexture.plugin/source/, symlinked
# in via example.lionprj). Idempotent patch to the real path.
set(XTEXTURE_LOADER_CPP "${CMAKE_SOURCE_DIR}/plugins/xtexture.plugin/source/xtexture_xgpu_rsc_loader.cpp")
if(EXISTS "${XTEXTURE_LOADER_CPP}")
  file(READ "${XTEXTURE_LOADER_CPP}" XTEXTURE_LOADER_CONTENTS)
  string(FIND "${XTEXTURE_LOADER_CONTENTS}" "../../tools/xgpu_xcore_bitmap_helpers.h" XTEXTURE_LOADER_OLD_PATH_FOUND)
  if(NOT XTEXTURE_LOADER_OLD_PATH_FOUND EQUAL -1)
    string(REPLACE
      "../../tools/xgpu_xcore_bitmap_helpers.h"
      "dependencies/xGPU/source/Tools/xgpu_xcore_bitmap_helpers.h"
      XTEXTURE_LOADER_PATCHED "${XTEXTURE_LOADER_CONTENTS}")
    file(WRITE "${XTEXTURE_LOADER_CPP}" "${XTEXTURE_LOADER_PATCHED}")
  endif()
endif()

#
# Get all the dependencies - same list xGPU's own root CMakeLists.txt fetches (duplicated
# deliberately, not extracted into a shared fragment - see the port's own plan notes: touching
# xGPU's own working CMakeLists.txt for this carries more risk than a ~20-line, rarely-changing
# duplicated list is worth. FetchAndPopulate no-ops for anything Install.bat above already placed
# in example.lionprj/Cache/dependencies, so this is mostly a defensive/consistency measure.)
#
FetchAndPopulate("https://github.com/ocornut/imgui.git" "docking")
FetchAndPopulate("https://github.com/LIONant-depot/xresource_mgr.git" "main")
FetchAndPopulate("https://github.com/LIONant-depot/xcontainer.git" "main")
FetchAndPopulate("https://github.com/LIONant-depot/xdelegate.git" "main")
FetchAndPopulate("https://github.com/LIONant-depot/xprim_geom.git" "main")
FetchAndPopulate("https://github.com/LIONant-depot/xproperty.git" "master")
FetchAndPopulate("https://github.com/LIONant-depot/xstrtool.git" "main")
FetchAndPopulate("https://github.com/LIONant-depot/xbmp_tools.git" "main")
FetchAndPopulate("https://github.com/LIONant-depot/xserializer.git" "main")
FetchAndPopulate("https://github.com/LIONant-depot/xscheduler.git" "main")
FetchAndPopulate("https://github.com/LIONant-depot/xECS.git" "Lesson09_Prefabs")
FetchAndPopulate("https://github.com/LIONant-depot/xECSV2.git" "main")
FetchAndPopulate("https://github.com/LIONant-depot/xLIONCore.git" "main")
FetchAndPopulate("https://github.com/LIONant-depot/xLIONRender.git" "main")
FetchAndPopulate("https://github.com/LIONant-depot/xundo.git" "main")
FetchAndPopulate("https://github.com/LIONant-depot/xsource_control.git" "main")
FetchAndPopulate("https://github.com/thedmd/imgui-node-editor.git" "master")
FetchAndPopulate("https://github.com/CedricGuillemet/ImGuizmo.git" "master")

# xproperty's own imgui-inspector example header (xPropertyImGuiInspector.h) falls back to a
# same-directory example "my_properties.h" stub (guard MY_PROPERTIES_H, missing several
# xproperty::inspector members) whenever a consuming file reaches it before including this
# project's real config header (xcore/my_properties.h, guard XCORE_PROPERTIES_H). Every other
# translation unit here reaches the real config first via some other header's own chain;
# xPropertyImGuiInspector.cpp is compiled as its own standalone source (see XLION_EXTRA_SOURCES
# below) with nothing else pulling the real config in ahead of it, so it silently built
# xproperty::inspector 96 bytes smaller than every other TU - a real ODR violation that crashed
# the moment any resource editor's inspector pushed its first entity (access violation writing
# through a garbage vector capacity left over from whatever heap bytes were there). Idempotent
# patch: include the real config first, exactly as this header's own doc comment says every
# source should.
set(XPROPERTY_IMGUI_INSPECTOR_CPP "${CMAKE_SOURCE_DIR}/dependencies/xproperty/source/examples/imgui/xPropertyImGuiInspector.cpp")
if(EXISTS "${XPROPERTY_IMGUI_INSPECTOR_CPP}")
  file(READ "${XPROPERTY_IMGUI_INSPECTOR_CPP}" XPROPERTY_IMGUI_INSPECTOR_CONTENTS)
  string(FIND "${XPROPERTY_IMGUI_INSPECTOR_CONTENTS}" "xcore/my_properties.h" XPROPERTY_REAL_CONFIG_FOUND)
  if(XPROPERTY_REAL_CONFIG_FOUND EQUAL -1)
    string(REPLACE
      "#include \"dependencies/xproperty/source/examples/imgui/xPropertyImGuiInspector.h\""
      "#include \"dependencies/xproperty/source/xcore/my_properties.h\"\n#include \"dependencies/xproperty/source/examples/imgui/xPropertyImGuiInspector.h\""
      XPROPERTY_IMGUI_INSPECTOR_PATCHED "${XPROPERTY_IMGUI_INSPECTOR_CONTENTS}")
    if(XPROPERTY_IMGUI_INSPECTOR_PATCHED STREQUAL XPROPERTY_IMGUI_INSPECTOR_CONTENTS)
      message(FATAL_ERROR "Failed to locate xPropertyImGuiInspector.h's own include in xPropertyImGuiInspector.cpp to patch - upstream may have changed the file's formatting.")
    endif()
    file(WRITE "${XPROPERTY_IMGUI_INSPECTOR_CPP}" "${XPROPERTY_IMGUI_INSPECTOR_PATCHED}")
  endif()
endif()

# Same idempotent upstream patch xGPU's own CMakeLists.txt applies - imgui-node-editor
# (unpatched) calls an ImGui API that no longer exists in the vendored docking-branch ImGui.
set(IMGUI_NODE_EDITOR_INTERNAL_H "${CMAKE_SOURCE_DIR}/dependencies/imgui-node-editor/imgui_node_editor_internal.h")
if(EXISTS "${IMGUI_NODE_EDITOR_INTERNAL_H}")
  file(READ "${IMGUI_NODE_EDITOR_INTERNAL_H}" IMGUI_NODE_EDITOR_INTERNAL_CONTENTS)
  string(FIND "${IMGUI_NODE_EDITOR_INTERNAL_CONTENTS}" "GetKeyIndex(T a)" GETKEYINDEX_SHIM_FOUND)
  if(GETKEYINDEX_SHIM_FOUND EQUAL -1)
    file(APPEND "${IMGUI_NODE_EDITOR_INTERNAL_H}" "\nnamespace ImGui{ template< typename T> T GetKeyIndex(T a) {return a;} }\n")
  endif()
endif()

# Second idempotent upstream patch, same rationale: imgui-node-editor's imgui_extra_math.inl
# unconditionally defines operator*(float, ImVec2) as a "missing from imgui.h" fallback - true
# for xGPU's own older pinned imgui.h, but the docking-branch imgui.h xLION fetches fresh (~11
# months newer) has since added that exact overload itself (upstream imgui commit, unrelated to
# this project), so with IMGUI_DEFINE_MATH_OPERATORS active both definitions now collide
# (C2084 "already has a body"). Guard imgui-node-editor's copy behind the same
# IMGUI_DEFINE_MATH_OPERATORS_IMPLEMENTED flag imgui.h itself sets when its own operators are
# active, so whichever one runs first wins and the other is skipped.
set(IMGUI_EXTRA_MATH_INL "${CMAKE_SOURCE_DIR}/dependencies/imgui-node-editor/imgui_extra_math.inl")
if(EXISTS "${IMGUI_EXTRA_MATH_INL}")
  file(READ "${IMGUI_EXTRA_MATH_INL}" IMGUI_EXTRA_MATH_CONTENTS)
  string(FIND "${IMGUI_EXTRA_MATH_CONTENTS}" "IMGUI_DEFINE_MATH_OPERATORS_IMPLEMENTED" FLOAT_VEC2_SHIM_FOUND)
  if(FLOAT_VEC2_SHIM_FOUND EQUAL -1)
    string(REPLACE
      "inline ImVec2 operator*(const float lhs, const ImVec2& rhs)\n{\n    return ImVec2(lhs * rhs.x, lhs * rhs.y);\n}"
      "#ifndef IMGUI_DEFINE_MATH_OPERATORS_IMPLEMENTED\ninline ImVec2 operator*(const float lhs, const ImVec2& rhs)\n{\n    return ImVec2(lhs * rhs.x, lhs * rhs.y);\n}\n#endif"
      IMGUI_EXTRA_MATH_PATCHED "${IMGUI_EXTRA_MATH_CONTENTS}")
    if(IMGUI_EXTRA_MATH_PATCHED STREQUAL IMGUI_EXTRA_MATH_CONTENTS)
      message(FATAL_ERROR "Failed to locate operator*(float, ImVec2) in imgui_extra_math.inl to patch - upstream may have changed the file's formatting.")
    endif()
    file(WRITE "${IMGUI_EXTRA_MATH_INL}" "${IMGUI_EXTRA_MATH_PATCHED}")
  endif()
endif()

FetchAndPopulate("https://github.com/LIONant-depot/toolbar.imgui.git" "main")
FetchAndPopulate("https://github.com/LIONant-depot/Actions.imgui.git" "main")
FetchAndPopulate("https://github.com/LIONant-depot/xlog.git" "main")
FetchAndPopulate("https://github.com/LIONant-depot/xeditor.git" "main")

#
# xGPU itself, as a dependency. Its own build/dependency/CMakeLists.txt registers the "xGPU"
# component (source/xGPU.cpp + public headers) via DefineInterfaceComponent, and FetchAndPopulate
# auto-add_subdirectory's that file since it exists - so xGPU's own component (and its own xmath
# fetch) is pulled in automatically, no extra step needed here.
#
FetchAndPopulate("https://github.com/LIONant-depot/xGPU.git" "main")

#
# Shared 3D editor-viewport scaffolding (orbit+fly camera, ground grid/shadow map) - its own
# Build/dependency/CMakeLists.txt registers the "xeditor_tools" component the same way xbmp_tools does
# (one umbrella .cpp, no static lib), auto-add_subdirectory'd by FetchAndPopulate.
#
FetchAndPopulate("https://github.com/LIONant-depot/xeditor_tools.git" "main")

#
# Add ImGui files directly - identical component definition to xGPU's own
#
# The Win32 platform backend only exists on Windows (headless on other platforms never creates a window).
if(WIN32)
  set(XLION_IMGUI_PLATFORM_BACKEND "backends/imgui_impl_win32.h" "backends/imgui_impl_win32.cpp")
else()
  set(XLION_IMGUI_PLATFORM_BACKEND)
endif()
DefineInterfaceComponent(imgui "dependencies"
  "imconfig.h"
  "imgui.cpp"
  "imgui.h"
  "imgui_demo.cpp"
  "imgui_draw.cpp"
  "imgui_internal.h"
  "imgui_tables.cpp"
  "imgui_widgets.cpp"
  "imstb_rectpack.h"
  "imstb_textedit.h"
  "imstb_truetype.h"
  ${XLION_IMGUI_PLATFORM_BACKEND}
)

DefineInterfaceComponent(imgui-node-editor "dependencies"
  "crude_json.cpp"
  "crude_json.h"
  "imgui_bezier_math.h"
  "imgui_canvas.cpp"
  "imgui_canvas.h"
  "imgui_extra_math.h"
  "imgui_node_editor.cpp"
  "imgui_node_editor.h"
  "imgui_node_editor_api.cpp"
  "imgui_node_editor_internal.h"
)

DefineInterfaceComponent(ImGuizmo "dependencies"
  "src/ImGuizmo.h"
  "src/ImGuizmo.cpp"
)

#
# Shaders - only the subset LevelEditor's own plugin editors (static geom, skinned geom, skeleton,
# font) and its own mesh-preview widget actually need, plus xGPU's own core draw/imgui shaders
# (which live in xGPU's own repo now, fetched to dependencies/xGPU).
#
if(WIN32)
  set(GLSLC_CANDIDATE "${CMAKE_SOURCE_DIR}/dependencies/Shaderc/bin/glslc.exe")
else()
  # Linux: the distro's glslc (Ubuntu package "glslc")
  find_program(GLSLC_CANDIDATE glslc REQUIRED)
endif()
if(NOT EXISTS "${GLSLC_CANDIDATE}")
  message(FATAL_ERROR "glslc.exe not found at ${GLSLC_CANDIDATE} - expected example.lionprj's Install.bat to have provided a Shaderc install alongside xGPU's own dependencies.")
endif()
set(GLSLC "${GLSLC_CANDIDATE}")

file(MAKE_DIRECTORY "${CMAKE_BINARY_DIR}/sprv_shaders_h")

set(FRAG_SHADER_SOURCES
  "dependencies/xGPU/bin/draw_frag.glsl"
  "plugins/xgeom_static.plugin/source/runtime/GeomStaticShadowMapCreation_frag.glsl"
  "plugins/xgeom_static.plugin/source/runtime/GeomStaticBasicShader_frag.glsl"
  "plugins/xgeom_skin.plugin/source/runtime/GeomSkinShadowMapCreation_frag.glsl"
  "plugins/xgeom_skin.plugin/source/runtime/GeomSkinBasicShader_frag.glsl"
  "dependencies/xeditor_tools/src/shaders/xeditor_tools_grid_frag.glsl"
  "plugins/xgeom_static.plugin/source/Editor/shaders/xgeom_static_wireframe_frag.glsl"
  "plugins/xgeom_static.plugin/source/Editor/shaders/xgeom_static_debug_normal_frag.glsl"
  "plugins/xskeleton.plugin/source/Editor/shaders/xskeleton_wedge_fill_frag.glsl"
  "plugins/xskeleton.plugin/source/Editor/shaders/xskeleton_shadow_generation_frag.glsl"
  "plugins/xfont.plugin/source/Editor/shaders/xfont_msdf_frag.glsl"
  "plugins/xfont.plugin/source/Editor/shaders/xfont_wire_frag.glsl"
  "dependencies/xGPU/source/Examples/E10_TextureResourcePipeline/e10_2d_frag.glsl"
  "dependencies/xGPU/source/Examples/E10_TextureResourcePipeline/e10_3d_frag.glsl"
  "dependencies/xGPU/source/Examples/E10_TextureResourcePipeline/e10_2d_cube_frag.glsl"
  "dependencies/xGPU/source/Examples/E10_TextureResourcePipeline/e10_3d_cube_frag.glsl"
)

set(VERT_SHADER_SOURCES
  "dependencies/xGPU/bin/draw_vert.glsl"
  "dependencies/xGPU/bin/imgui_vert.glsl"
  "plugins/xgeom_static.plugin/source/runtime/GeomStaticShadowMapCreation_vert.glsl"
  "plugins/xgeom_static.plugin/source/runtime/GeomStaticBasicShader_vert.glsl"
  "plugins/xgeom_skin.plugin/source/runtime/GeomSkinShadowMapCreation_vert.glsl"
  "plugins/xgeom_skin.plugin/source/runtime/GeomSkinBasicShader_vert.glsl"
  "dependencies/xeditor_tools/src/shaders/xeditor_tools_grid_vert.glsl"
  "plugins/xgeom_static.plugin/source/Editor/shaders/xgeom_static_wireframe_vert.glsl"
  "plugins/xgeom_static.plugin/source/Editor/shaders/xgeom_static_debug_normal_vert.glsl"
  "plugins/xskeleton.plugin/source/Editor/shaders/xskeleton_wedge_fill_vert.glsl"
  "plugins/xskeleton.plugin/source/Editor/shaders/xskeleton_shadow_generation_vert.glsl"
  "plugins/xfont.plugin/source/Editor/shaders/xfont_msdf_vert.glsl"
  "plugins/xfont.plugin/source/Editor/shaders/xfont_wire_vert.glsl"
  "source/Tools/Editor/shaders/xeditor_mesh_preview_full_vert.glsl"
  "dependencies/xGPU/source/Examples/E10_TextureResourcePipeline/e10_2d_vert.glsl"
  "dependencies/xGPU/source/Examples/E10_TextureResourcePipeline/e10_3d_vert.glsl"
  "dependencies/xGPU/source/Examples/E10_TextureResourcePipeline/e10_2d_cube_vert.glsl"
  "dependencies/xGPU/source/Examples/E10_TextureResourcePipeline/e10_3d_cube_vert.glsl"
)

set(GEOM_SHADER_SOURCES
  "plugins/xgeom_static.plugin/source/Editor/shaders/xgeom_static_wireframe_geom.glsl"
  "plugins/xgeom_static.plugin/source/Editor/shaders/xgeom_static_debug_normal_geom.glsl"
)

set(GENERATED_HEADERS)
foreach(SHADER ${FRAG_SHADER_SOURCES})
    get_filename_component(FILENAME ${SHADER} NAME_WE)
    set(OUTPUT_FILE "${CMAKE_BINARY_DIR}/sprv_shaders_h/${FILENAME}.h")
    add_custom_command(
        OUTPUT ${OUTPUT_FILE}
        COMMAND ${GLSLC} -fshader-stage=frag "${CMAKE_CURRENT_SOURCE_DIR}/${SHADER}" -mfmt=num -o ${OUTPUT_FILE}
        DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/${SHADER}"
        COMMENT "Compiling fragment shader ${SHADER}"
    )
    list(APPEND GENERATED_HEADERS ${OUTPUT_FILE})
endforeach()

foreach(SHADER ${VERT_SHADER_SOURCES})
    get_filename_component(FILENAME ${SHADER} NAME_WE)
    set(OUTPUT_FILE "${CMAKE_BINARY_DIR}/sprv_shaders_h/${FILENAME}.h")
    add_custom_command(
        OUTPUT ${OUTPUT_FILE}
        COMMAND ${GLSLC} -fshader-stage=vert "${CMAKE_CURRENT_SOURCE_DIR}/${SHADER}" -mfmt=num -o ${OUTPUT_FILE}
        DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/${SHADER}"
        COMMENT "Compiling vertex shader ${SHADER}"
    )
    list(APPEND GENERATED_HEADERS ${OUTPUT_FILE})
endforeach()

foreach(SHADER ${GEOM_SHADER_SOURCES})
    get_filename_component(FILENAME ${SHADER} NAME_WE)
    set(OUTPUT_FILE "${CMAKE_BINARY_DIR}/sprv_shaders_h/${FILENAME}.h")
    add_custom_command(
        OUTPUT ${OUTPUT_FILE}
        COMMAND ${GLSLC} -fshader-stage=geom "${CMAKE_CURRENT_SOURCE_DIR}/${SHADER}" -mfmt=num -o ${OUTPUT_FILE}
        DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/${SHADER}"
        COMMENT "Compiling geometry shader ${SHADER}"
    )
    list(APPEND GENERATED_HEADERS ${OUTPUT_FILE})
endforeach()

include_directories("${CMAKE_BINARY_DIR}/sprv_shaders_h")

#
# xLION's own sources - shared between the graphical and headless targets; only the main_*.cpp
# entry point differs (see source/main_graphical.cpp / source/main_headless.cpp).
#
# xtextfile.cpp/my_properties.cpp/xPropertyImGuiInspector.cpp: xGPU's own CMakeLists.txt gets
# these compiled in as a side effect of including unrelated examples (E20/E04) that happen to
# #include them - not needed here (those examples aren't part of the port), so they're listed
# directly instead. Each binary that needs them (this target AND LIONCore.dll, built by the
# xLIONCore depot - see the XECS_BUILD_SHARED_LIBRARY block below) compiles its own private copy -
# not a name clash, two separate binaries. Kept out of XLION_COMMON_SOURCES (below) since they
# don't live under source/ - source_group(TREE ...) requires every file it's given to share that root.
set(XLION_EXTRA_SOURCES
  "dependencies/xtextfile/source/xtextfile.cpp"
  "dependencies/xproperty/source/xcore/my_properties.cpp"
  "dependencies/xproperty/source/examples/imgui/xPropertyImGuiInspector.cpp"

  "plugins/xmaterial.plugin/source/Graph/xmaterial_graph.cpp"
  "plugins/xmaterial.plugin/source/Graph/xmaterial_graph.h"
  "plugins/xmaterial.plugin/source/Graph/xmaterial_graph_node.cpp"
  "plugins/xmaterial.plugin/source/Graph/xmaterial_graph_node.h"
  "plugins/xmaterial.plugin/source/Graph/xmaterial_graph_node_guid.h"

  "plugins/xtexture.plugin/source/xtexture_xgpu_rsc_loader.h"
)

# xGPU's own ImGui integration layer (xgpu::tools::imgui::CreateInstance/BeginRendering/Render/
# Shutdown/getFont/ConsumeWindowFocusGained) - not part of the "xGPU" component (that's just
# source/xGPU.h + Details/xgpu_*_inline.h), a separate Tools/ file every windowed example needs.
# NOT registered as its own CMake source: compiled as an independent translation unit (its own
# add_library(OBJECT) target, or a plain entry in XLION_EXTRA_SOURCES), xgpu_imgui_breach.cpp
# reproducibly fails to compile under MSBuild specifically - xgpu::device/window/texture come back
# "not a member of xgpu" (C2039/C2065 cascade from xgpu_imgui_breach.h) - despite an exhaustive,
# byte-for-byte matched manual cl.exe reproduction (same flags, same include dirs in the same
# order, same working directory, same output paths, with and without /MP, with and without a rich
# %INCLUDE%/%LIB%) succeeding every single time. Root cause not found. Instead, its .cpp is
# #include'd directly into LevelEditor_Main.cpp (see there) - the same "fold a dependency's .cpp
# into an already-known-good TU" trick this port already uses for my_properties.cpp/xtextfile.cpp/
# xPropertyImGuiInspector.cpp being pulled in via unrelated xGPU examples upstream - which sidesteps
# whatever is specific to compiling this file as its own independent MSBuild-invoked TU.

set(XLION_COMMON_SOURCES
  "source/Editors/LevelEditor/LevelEditor_MaterialGraphCompat.h"
  "source/Editors/LevelEditor/LevelEditor_App.h"
  "source/Editors/LevelEditor/LevelEditor_AppFrame.h"
  "source/Editors/LevelEditor/LevelEditor_AppFrameHeadless.h"
  "source/Editors/LevelEditor/LevelEditor_AppInit.h"
  "source/Editors/LevelEditor/LevelEditor_AppToolbars.h"
  "source/Editors/LevelEditor/LevelEditor_EditorTabs.h"
  "source/Editors/LevelEditor/LevelEditor_Kit.h"
  "source/Editors/LevelEditor/LevelEditor_Main.cpp"
  "source/Editors/LevelEditor/LevelEditor_Theme.h"
  "source/Editors/LevelEditor/commands/LevelEditor_CommandSet.h"
  "source/Editors/LevelEditor/extensions/asset_browser/LevelEditor_AppAssetBrowser.h"
  "source/Editors/LevelEditor/extensions/asset_browser/LevelEditor_Commands_ResourceEditors.h"
  "source/Editors/LevelEditor/extensions/command_console/LevelEditor_CommandConsolePipe.h"
  "source/Editors/LevelEditor/extensions/command_console/LevelEditor_Commands_Chat.h"
  "source/Editors/LevelEditor/extensions/command_console/LevelEditor_Panel_CommandConsole.h"

  "source/Tools/Editor/xeditor_camera.h"
  "source/Tools/Editor/xeditor_descriptor_editor.h"
  "source/Tools/Editor/xeditor_dock_isolation.h"
  "source/Tools/Editor/xeditor_document_editor.h"
  "source/Tools/Editor/xeditor_inspector.h"
  "source/Tools/Editor/xeditor_mesh_preview.h"
  "source/Tools/Editor/xeditor_registry.h"
  "source/Tools/Editor/xeditor_resource_editor.h"
  "source/Tools/Editor/xeditor_resource_tab.h"
  "source/Tools/Editor/xeditor_text_widget.h"
  "source/Tools/Editor/xeditor_text_widget.cpp"
  "source/Tools/Editor/xeditor_thumbnail.h"
  "source/Tools/Editor/xeditor_thumbnail_cache.h"
  "source/Tools/Editor/xeditor_toolbar.h"
  "source/Tools/Editor/xeditor_types.h"
)

set(XLION_SOURCES ${XLION_COMMON_SOURCES} ${XLION_EXTRA_SOURCES} ${GENERATED_HEADERS} "source/main_graphical.cpp")
set(XLION_HEADLESS_SOURCES ${XLION_COMMON_SOURCES} ${XLION_EXTRA_SOURCES} ${GENERATED_HEADERS} "source/main_headless.cpp")

set(XLION_PLUGIN_INCLUDES
  "${CMAKE_SOURCE_DIR}/dependencies/toolbar.imgui"
  "${CMAKE_SOURCE_DIR}/dependencies/actions.imgui"
  "${CMAKE_SOURCE_DIR}/dependencies/xcmdline/source"
  "${CMAKE_SOURCE_DIR}/plugins/xgeom_static.plugin"
  "${CMAKE_SOURCE_DIR}/plugins/xgeom_skin.plugin"
  "${CMAKE_SOURCE_DIR}/plugins/xtexture.plugin"
  "${CMAKE_SOURCE_DIR}/plugins/xmaterial.plugin"
  "${CMAKE_SOURCE_DIR}/plugins/xmaterial_instance.plugin"
  "${CMAKE_SOURCE_DIR}/plugins/xskeleton.plugin"
  "${CMAKE_SOURCE_DIR}/plugins/xfont.plugin"
  "${CMAKE_SOURCE_DIR}/plugins/xanim_package.plugin"
)

add_executable(${TARGET_PROJECT} ${XLION_SOURCES})
target_include_directories(${TARGET_PROJECT} PRIVATE "${CMAKE_SOURCE_DIR}" ${XLION_PLUGIN_INCLUDES})
# Target-wide (not per-file): imgui-node-editor's own internal headers try to enable this
# themselves before their own <imgui.h> include, but that didn't reliably activate imgui.h's
# operators for every TU that needed them here - defining it target-wide plus the
# imgui_extra_math.inl patch above (for the one overload that now collides) is the combination
# that actually works. NOMINMAX: xgpu_imgui_breach.cpp (folded into LevelEditor_Main.cpp, see
# there) #includes <windows.h> without it, whose min/max macros otherwise break every later
# std::...::max()/min() call in the SAME translation unit (e.g. xbitmap's xcolor_inline.h).
# XLION_EDITOR/XLION_GAME: the real axis this engine cares about is Editor-vs-Game, independent of
# Headless-vs-graphical (both xLION and xLION_Headless below are Editor builds - Headless is just
# "the editor without ImGui", still has Play/Stop/a loaded-but-not-running state; a shipped Game
# target, whenever one exists, would define XLION_GAME instead here - load-time and about-to-run
# are the same moment there, unlike in the editor). Not to be confused with the unrelated bare
# EDITOR macro below (imgui-node-editor's own internal requirement, coincidentally same name).
target_compile_definitions(${TARGET_PROJECT} PRIVATE EDITOR XLION_EDITOR IMGUI_DEFINE_MATH_OPERATORS NOMINMAX)

# xLION_Headless - no window/device/ImGui at runtime (see LevelEditor_App::Init's bHeadless
# branch), driven entirely by the same command system over the Command Console pipe. Still links
# the same components as the graphical target (xGPU/imgui) since there's no separate "core"
# library to link against yet - see the port's own plan notes on why that split is deferred.
# Still an Editor build (see XLION_EDITOR/XLION_GAME comment above) - Headless is orthogonal.
add_executable(xLION_Headless ${XLION_HEADLESS_SOURCES})
target_include_directories(xLION_Headless PRIVATE "${CMAKE_SOURCE_DIR}" ${XLION_PLUGIN_INCLUDES})
target_compile_definitions(xLION_Headless PRIVATE EDITOR XLION_EDITOR IMGUI_DEFINE_MATH_OPERATORS NOMINMAX)

if(XECS_BUILD_SHARED_LIBRARY)
  # The shared library itself (LIONCore.dll) is now built by the xLIONCore depot (fetched above),
  # which compiles xECSV2 in as a dependency - see dependencies/xLIONCore/Build/dependency/CMakeLists.txt
  # for the add_library block this used to be here directly. xLIONCore builds to its own natural
  # per-target output folder (it doesn't know or care where any given consumer's exe lands); each
  # executable that links it is responsible for copying it next to itself, conditionally
  # (copy_if_different - a no-op once the DLL is already up to date) - a plain POST_BUILD step, not a
  # RUNTIME_OUTPUT_DIRECTORY override on the dependency itself.
  target_link_libraries(${TARGET_PROJECT} PRIVATE xLIONCore)
  target_compile_definitions(${TARGET_PROJECT} PRIVATE XECS_BUILD_SHARED XLIONCORE_BUILD_SHARED)
  add_custom_command(TARGET ${TARGET_PROJECT} POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different "$<TARGET_FILE:xLIONCore>" "$<TARGET_FILE_DIR:${TARGET_PROJECT}>"
  )

  target_link_libraries(xLION_Headless PRIVATE xLIONCore)
  target_compile_definitions(xLION_Headless PRIVATE XECS_BUILD_SHARED XLIONCORE_BUILD_SHARED)
  add_custom_command(TARGET xLION_Headless POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different "$<TARGET_FILE:xLIONCore>" "$<TARGET_FILE_DIR:xLION_Headless>"
  )

  # LIONRender.dll - linked into BOTH targets, since xlevel_session.h (shared source) references
  # xlionrender::Init/Draw either way and needs to link successfully. But its render SYSTEM is only
  # ever registered when m_pDevice is non-null (xlevel_session.h's own RegisterHostSystems) - headless
  # has no window/device to draw with, so it never runs there. Its component (Primitive) IS registered
  # unconditionally in both, so headless scenes still carry the data - just never rendered. xLION.exe/
  # xLION_Headless link it directly (ordinary import-lib linking, for the two always-present Init/Draw
  # calls in xlionrender_api.h) as well as resolving its self-registration entry points at runtime via
  # xlevel_plugin_dlls.h - the two are independent: direct linking for the fixed host-facing API,
  # GetProcAddress for the ECS types.
  target_link_libraries(${TARGET_PROJECT} PRIVATE xLIONRender)
  target_compile_definitions(${TARGET_PROJECT} PRIVATE XLIONRENDER_BUILD_SHARED)
  add_custom_command(TARGET ${TARGET_PROJECT} POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different "$<TARGET_FILE:xLIONRender>" "$<TARGET_FILE_DIR:${TARGET_PROJECT}>"
  )

  target_link_libraries(xLION_Headless PRIVATE xLIONRender)
  target_compile_definitions(xLION_Headless PRIVATE XLIONRENDER_BUILD_SHARED)
  add_custom_command(TARGET xLION_Headless POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different "$<TARGET_FILE:xLIONRender>" "$<TARGET_FILE_DIR:xLION_Headless>"
  )
endif()

# Plugin editor sources (xlevel_session.h, xscene_editor.h, every xscene/xlevel/xskeleton/...
# command and panel file, etc.) live entirely under plugins/*.plugin/source/ and are reached only
# through #include chains starting at LevelEditor_Main.cpp plus the XLION_PLUGIN_INCLUDES search
# path above - never listed as an explicit CMake source. Visual Studio's Solution Explorer only
# shows files MSBuild knows about, so none of this was ever browsable there (direct user report:
# "I should be able to find all the important headers in the visual studio solution without having
# to open explorer"). GLOB_RECURSE here is a deliberate exception to XLION_COMMON_SOURCES's own
# hand-maintained-list convention above: this is IDE browsability only, never build correctness, so
# a new plugin header just needs one reconfigure to appear instead of also requiring a
# CMakeLists.txt edit to stay visible - CONFIGURE_DEPENDS re-globs automatically when the plugin
# tree changes, without needing a manual "touch CMakeLists.txt".
file(GLOB_RECURSE XLION_PLUGIN_HEADERS CONFIGURE_DEPENDS
  "${CMAKE_SOURCE_DIR}/plugins/*.plugin/source/*.h"
  "${CMAKE_SOURCE_DIR}/plugins/*.plugin/source/*.hpp"
  "${CMAKE_SOURCE_DIR}/plugins/*.plugin/source/*.inl"
)
file(GLOB_RECURSE XLION_PLUGIN_CPPS CONFIGURE_DEPENDS
  "${CMAKE_SOURCE_DIR}/plugins/*.plugin/source/*.cpp"
)
# Every plugin .cpp except the two already compiled directly into xLION.exe (XLION_EXTRA_SOURCES,
# above) is an asset compiler's main()/implementation or a runtime resource loader - each built by
# that plugin's own separate CMakeLists.txt (plugins/*.plugin/build/...), not this target. Listed
# here as HEADER_FILE_ONLY so they're browsable in this solution too without compiling them a
# second time (a duplicate-symbol link error) or pulling them out of whatever actually builds them.
set(XLION_PLUGIN_CPPS_COMPILED_ELSEWHERE
  "${CMAKE_SOURCE_DIR}/plugins/xmaterial.plugin/source/Graph/xmaterial_graph.cpp"
  "${CMAKE_SOURCE_DIR}/plugins/xmaterial.plugin/source/Graph/xmaterial_graph_node.cpp"
)
list(REMOVE_ITEM XLION_PLUGIN_CPPS ${XLION_PLUGIN_CPPS_COMPILED_ELSEWHERE})
set_source_files_properties(${XLION_PLUGIN_CPPS} PROPERTIES HEADER_FILE_ONLY TRUE)

target_sources(${TARGET_PROJECT} PRIVATE ${XLION_PLUGIN_HEADERS} ${XLION_PLUGIN_CPPS})
target_sources(xLION_Headless PRIVATE ${XLION_PLUGIN_HEADERS} ${XLION_PLUGIN_CPPS})

source_group("Shaders" FILES ${GENERATED_HEADERS})
source_group(TREE "${CMAKE_SOURCE_DIR}/source" PREFIX "source" FILES ${XLION_COMMON_SOURCES})
source_group(TREE "${CMAKE_SOURCE_DIR}/plugins" PREFIX "plugins" FILES ${XLION_PLUGIN_HEADERS} ${XLION_PLUGIN_CPPS})

find_package(OpenMP REQUIRED)
target_link_libraries(${TARGET_PROJECT} PRIVATE OpenMP::OpenMP_CXX)
target_link_libraries(xLION_Headless PRIVATE OpenMP::OpenMP_CXX)

# Linux port: only the headless editor is supported off Windows - the graphical target still configures
# (shared CMake below references it) but is never part of "all". Headless still compiles xGPU's Vulkan
# backend in (never initialized there), so it links the Vulkan loader; dlopen/threads for the platform layer.
if(NOT WIN32)
  set_target_properties(${TARGET_PROJECT} PROPERTIES EXCLUDE_FROM_ALL TRUE)
  find_package(Vulkan REQUIRED)
  find_package(Threads REQUIRED)
  target_link_libraries(xLION_Headless PRIVATE Vulkan::Vulkan Threads::Threads ${CMAKE_DL_LIBS})
  # $ORIGIN rpath: LIONCore.so/LIONRender.so are copied next to the executable, same as the .dlls on Windows.
  set_target_properties(xLION_Headless PROPERTIES BUILD_RPATH "$ORIGIN" INSTALL_RPATH "$ORIGIN")
endif()

# Shared 3D editor-viewport scaffolding (camera + grid) - the graphical target only; headless renders nothing.
target_link_libraries(${TARGET_PROJECT} PRIVATE xeditor_tools)

if(WIN32)
  target_link_libraries(${TARGET_PROJECT} PRIVATE Advapi32.lib)
  target_link_libraries(xLION_Headless PRIVATE Advapi32.lib)
endif()

if(MSVC)
  target_compile_options(${TARGET_PROJECT} PRIVATE /bigobj)
  target_compile_options(xLION_Headless PRIVATE /bigobj)
endif()

# xeditorcli - the client both xLION executables' Command Console pipe server accepts commands
# from. Zero dependency on Vulkan/ImGui/xproperty/etc, so it stays its own fast-building tool.
add_executable(xeditorcli "source/Tools/Editor/xeditorcli.cpp")
set_target_properties(xeditorcli PROPERTIES CXX_STANDARD 20 CXX_STANDARD_REQUIRED ON)

# The ECS link gate (see documentation/Editors/ecs_link_gate.md): the headless editor built exactly like
# xLION_Headless but linked WITHOUT LIONCore.dll and LIONRender.dll. The headers still say dllimport
# (XECS_BUILD_SHARED, ...), so everything the editor still takes from the engine through the exe's own
# import of it - the registry, bit ids, Run/SerializeGameState, the render calls - is an unresolved external
# here. That list is the measured to-do of moving the editor behind the xECSEditor interface (each
# renamed copy of the core can then be used without the exe silently reaching the original one).
# Never part of a normal build: EXCLUDE_FROM_ALL, and it is EXPECTED to fail to link until the list is empty
# (tools/ecs_gate/check_link_gate.py compares it to the saved baseline: it may only shrink).
option(XLION_ECS_LINK_GATE "Add the xLION_ecs_gate target (not built by default)" OFF)
if(XLION_ECS_LINK_GATE)
  add_executable(xLION_ecs_gate EXCLUDE_FROM_ALL ${XLION_HEADLESS_SOURCES})
  target_include_directories(xLION_ecs_gate PRIVATE "${CMAKE_SOURCE_DIR}" ${XLION_PLUGIN_INCLUDES})
  target_compile_definitions(xLION_ecs_gate PRIVATE EDITOR XLION_EDITOR IMGUI_DEFINE_MATH_OPERATORS NOMINMAX
                             XECS_BUILD_SHARED XLIONCORE_BUILD_SHARED XLIONRENDER_BUILD_SHARED)
  target_link_libraries(xLION_ecs_gate PRIVATE OpenMP::OpenMP_CXX)
  if(WIN32)
    target_link_libraries(xLION_ecs_gate PRIVATE Advapi32.lib)
  endif()
  if(MSVC)
    target_compile_options(xLION_ecs_gate PRIVATE /bigobj)
  endif()
endif()

# Pulls in xGPU's own "xGPU" component registration (source/xGPU.cpp + public headers) and the
# imgui/imgui-node-editor components above, via their build/dependency/CMakeLists.txt files -
# applied to BOTH targets in turn (ProcessComponents applies the whole registry to whichever
# target TARGET names).
ProcessComponents(TARGET ${TARGET_PROJECT})
ProcessComponents(TARGET xLION_Headless)
if(XLION_ECS_LINK_GATE)
  ProcessComponents(TARGET xLION_ecs_gate)
endif()
