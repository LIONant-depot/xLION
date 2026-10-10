# Linux port (clang): the compile settings every Linux target of xLION uses - the editors and engine libraries (the root
# CMakeLists.txt includes this file) and the plugins' asset compilers (source/Platform/xlion_linux_asset_compiler.cmake).
# Never used by MSVC builds.
#  - -fms-extensions/-fdeclspec: accept the MSVC syntax the depots use (__declspec(noinline), ...);
#    dllexport/dllimport are no-ops on ELF, where every symbol is exported by default anyway.
#  - the force-included compat header supplies the MSVC secure-CRT names and the std headers MSVC's STL
#    pulls in transitively (see source/Platform/xlion_platform_compat_linux.h).
if(WIN32)
  return()
endif()
get_filename_component(XLION_ROOT_DIR "${CMAKE_CURRENT_LIST_DIR}/../.." ABSOLUTE)
add_compile_options(
  "$<$<COMPILE_LANGUAGE:CXX>:-include${XLION_ROOT_DIR}/source/Platform/xlion_platform_compat_linux.h>"
  "$<$<COMPILE_LANGUAGE:CXX>:-fms-extensions>"
  "$<$<COMPILE_LANGUAGE:CXX>:-fdeclspec>"
  -fPIC
  -march=x86-64-v3   # AVX2/FMA/F16C: xmath uses those intrinsics unconditionally (MSVC needs no flag for them)
  -ferror-limit=200
  -Wno-unknown-pragmas -Wno-ignored-attributes -Wno-microsoft-template -Wno-microsoft-cast
  -Wno-unused-value -Wno-switch -Wno-deprecated-declarations -Wno-nonportable-include-path -Wno-invalid-constexpr -fbracket-depth=2048
)
# Debug info is most of a Debug build (an object file of xecs.cpp: 10 MB, 6 MB compressed), and the CI machine has a small disk: compress it (zlib sections; gdb, valgrind and addr2line read them).
# -DXLION_COMPRESS_DEBUG=OFF for a build that must not.
option(XLION_COMPRESS_DEBUG "Compress the debug info of Linux builds" ON)
if(XLION_COMPRESS_DEBUG)
  add_compile_options(-gz)
  add_link_options(-Wl,--compress-debug-sections=zlib)
endif()
# The sanitizer build (the nightly job of Build/jenkins/Jenkinsfile.sanitize, or Build/CreateProject.sh --sanitize): AddressSanitizer and UndefinedBehaviorSanitizer. What it leaves out on
# purpose, to keep the findings ours and few:
#  - third-party code (Build/ci/sanitizer_ignorelist.txt: not instrumented at all, so it costs nothing and reports nothing);
#  - vptr and function checks: the engine copies (xlevel_engine_copies.h) rename shared objects and load them side by side, so two copies of one type have two typeinfos on purpose;
#  - leak detection (an editor that is stopped is not asked to free everything: ASAN_OPTIONS=detect_leaks=0 in the CI run).
# The asset compilers (the plugins' own ExternalProjects) do not inherit these flags: they stay ordinary builds.
option(XLION_SANITIZE "Build the editors with AddressSanitizer and UndefinedBehaviorSanitizer" OFF)
if(XLION_SANITIZE)
  # -fsanitize-recover=address: AddressSanitizer reports and GOES ON (ASAN_OPTIONS halt_on_error=0 in the CI run), so one run lists every finding instead of one per run
  add_compile_options(-fsanitize=address,undefined -fsanitize-recover=address -fno-sanitize=vptr,function -fno-omit-frame-pointer
                      "-fsanitize-ignorelist=${XLION_ROOT_DIR}/Build/ci/sanitizer_ignorelist.txt")
  add_link_options(-fsanitize=address,undefined)
endif()
# MSVC defines _DEBUG for Debug builds (/MDd); several depots key debug-only members/asserts off it.
add_compile_definitions($<$<CONFIG:Debug>:_DEBUG>)
# zstd's x86-64 Huffman fast path lives in a .S file the xcompression component does not list; MSVC
# builds never use it either, so turn it off and use the C implementation.
add_compile_definitions(ZSTD_DISABLE_ASM)
# Linux port: stub <windows.h> for UI-only Win32 calls (never on the MSVC include path)
include_directories(AFTER "${XLION_ROOT_DIR}/source/Platform/linux_win32_shim")
# Code includes both <windows.h> and <Windows.h>. The repo only holds windows.h (two names differing only in case cannot
# be checked out on Windows/NTFS), so the case alias is generated into the build tree here.
file(CONFIGURE OUTPUT "${CMAKE_BINARY_DIR}/linux_win32_shim_alias/Windows.h" @ONLY CONTENT "#pragma once\n#include \"${XLION_ROOT_DIR}/source/Platform/linux_win32_shim/windows.h\"\n")
include_directories(AFTER "${CMAKE_BINARY_DIR}/linux_win32_shim_alias")
# MSVC also searches the directories of all open includers; clang does not.
include_directories(AFTER "${XLION_ROOT_DIR}/dependencies/xGPU/source")
