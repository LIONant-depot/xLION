# Linux port: builds a plugin's asset compiler natively, from the SAME plugin CMakeLists.txt the Windows build uses
# (example.lionprj/Cache/Plugins/<name>.plugin/CMakeLists.txt). The root CMakeLists.txt passes this file as
# -DCMAKE_PROJECT_INCLUDE=... (targets <name>_compiler_linux / xlion_compilers), so it runs right after the plugin's
# project() and adds what the Linux build needs around the unchanged plugin build:
#  - the compile settings of every Linux target (xlion_linux_flags.cmake: compat header, clang flags, <windows.h> shim);
#  - offline configure: FetchContent stays disconnected (the dependencies are the shared clones in Cache/dependencies,
#    reached through the plugin's dependencies -> ../../dependencies link, as the junction does on Windows), and
#    xcmake_tools is copied from the editor build (XLION_XCMAKE_TOOLS_DIR);
#  - at the end of the plugin's CMakeLists: libxlion_pathcompat.so (Windows-style paths at the libc boundary, the same
#    library the editors use: the pipeline hands the compilers backslash paths), threads, dl, libatomic, $ORIGIN rpath.
# Generator "Ninja Multi-Config", binary dir <plugin>/Build/<name>_compiler.linux: the executable lands in
# <plugin>/Build/<name>_compiler.linux/<Config>/<name>_compiler (libxlion_pathcompat.so next to it), the same layout as the
# Windows <name>_compiler.vs2022/<Config>/<name>_compiler.exe the plugin configs name; xresource_pipeline_v2 maps one to
# the other.
if(WIN32)
  return()
endif()
include_guard(GLOBAL)

include("${CMAKE_CURRENT_LIST_DIR}/xlion_linux_flags.cmake")

# The compilers include other plugins as "plugins/<name>.plugin/..." from Cache/ (the plugin CMakeLists add
# ${CMAKE_SOURCE_DIR}/../../); the folder is Cache/Plugins. Windows does not care about the case - here a case alias
# in the build tree, the same way linux_win32_shim_alias/Windows.h is made.
file(MAKE_DIRECTORY "${CMAKE_BINARY_DIR}/linux_case_alias")
if(NOT EXISTS "${CMAKE_BINARY_DIR}/linux_case_alias/plugins")
  file(CREATE_LINK "${CMAKE_SOURCE_DIR}/.." "${CMAKE_BINARY_DIR}/linux_case_alias/plugins" SYMBOLIC)
endif()
include_directories(AFTER "${CMAKE_BINARY_DIR}/linux_case_alias")

set(FETCHCONTENT_FULLY_DISCONNECTED ON CACHE BOOL "Linux asset compilers: dependencies come from Cache/dependencies" FORCE)
if(NOT EXISTS "${CMAKE_BINARY_DIR}/_deps/xcmake_tools/Common.cmake")
  if(NOT XLION_XCMAKE_TOOLS_DIR OR NOT EXISTS "${XLION_XCMAKE_TOOLS_DIR}/Common.cmake")
    message(FATAL_ERROR "XLION_XCMAKE_TOOLS_DIR must name an xcmake_tools checkout (the editor build's _deps/xcmake_tools)")
  endif()
  file(COPY "${XLION_XCMAKE_TOOLS_DIR}/" DESTINATION "${CMAKE_BINARY_DIR}/_deps/xcmake_tools" PATTERN ".git" EXCLUDE)
endif()

function(xlion_linux_asset_compiler_finish)
  if(NOT TARGET_PROJECT OR NOT TARGET ${TARGET_PROJECT})
    message(FATAL_ERROR "xlion_linux_asset_compiler.cmake: the plugin CMakeLists.txt defined no TARGET_PROJECT executable")
  endif()
  find_package(Threads REQUIRED)
  add_library(xlion_pathcompat SHARED "${XLION_ROOT_DIR}/source/Platform/linux_path_compat.cpp")
  target_link_libraries(xlion_pathcompat PRIVATE ${CMAKE_DL_LIBS})
  target_link_libraries(${TARGET_PROJECT} PRIVATE "-Wl,--push-state,--no-as-needed" xlion_pathcompat "-Wl,--pop-state"
                        Threads::Threads ${CMAKE_DL_LIBS} atomic)
  set_target_properties(${TARGET_PROJECT} PROPERTIES BUILD_RPATH "$ORIGIN")
endfunction()
cmake_language(DEFER DIRECTORY "${CMAKE_SOURCE_DIR}" CALL xlion_linux_asset_compiler_finish)
