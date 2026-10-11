# The Windows AddressSanitizer build (Build\xLION.vs2022-asan: Build\ci\ci_run_windows.ps1 -Sanitize, the job Build/jenkins/Jenkinsfile.windows_sanitize). The script gives this file to the
# configure as CMAKE_PROJECT_xLION_INCLUDE, so it runs right after project(xLION) and applies to every target added below it (the dependencies included); the normal build never sees it.
#  - /fsanitize=address: MSVC AddressSanitizer (no UBSan on MSVC); /Zi: the PDBs it symbolizes the reports with (Release too);
#  - no /RTC1: the run-time checks cannot be mixed with /fsanitize=address;
#  - /INCREMENTAL:NO: incremental linking cannot be mixed with it either; /DEBUG so Release has PDBs.
# The runtime DLLs (clang_rt.asan[_dbg]_dynamic-x86_64.dll) are copied next to the exes by the script after the build.
if(NOT MSVC)
  return()
endif()
foreach(v CMAKE_C_FLAGS_DEBUG CMAKE_CXX_FLAGS_DEBUG CMAKE_C_FLAGS_RELEASE CMAKE_CXX_FLAGS_RELEASE)
  string(REGEX REPLACE "[/-]RTC[1csu]+" "" ${v} "${${v}}")
  string(REGEX REPLACE "[/-]ZI" "/Zi" ${v} "${${v}}")
endforeach()
foreach(t EXE SHARED MODULE)
  foreach(c DEBUG RELEASE)
    string(REGEX REPLACE "[/-]INCREMENTAL(:YES)?( |$)" "" CMAKE_${t}_LINKER_FLAGS_${c} "${CMAKE_${t}_LINKER_FLAGS_${c}}")
  endforeach()
endforeach()
add_compile_options(/fsanitize=address /Zi)
add_link_options(/INCREMENTAL:NO /DEBUG)
message(STATUS "xLION: MSVC AddressSanitizer build (Build/ci/msvc_asan.cmake)")
