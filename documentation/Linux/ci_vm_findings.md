# Jenkins build VM: what was found, what was changed, what is fixed in the repo

Purpose: every difference between the VM and the repo, so the repo (and the WSL setup) is fixed once and the VM needs no patches.
VM: `team39@team39.dp-ext8.com` (Ubuntu 24.04, clang 20.1.2, 2 cores, 3 GB RAM). Login `team39` is in group `sudo`; the CI checkout is owned by `jenkins-agent`.

## 1. Already on the VM when I started (not made by me)

CI checkout `/var/lib/jenkins-agent/xLION-inspect-20261008-231132`, at xLION `96b3f18`, with local edits and backups next to them:

| File on the VM | Edit | Why (found / inferred) | Status in the repo |
|---|---|---|---|
| `example.lionprj/Cache/Plugins/xtexture.plugin/CMakeLists.txt` | patch `XLION_CI_CRUNCH_SHIM_OPTOUT`: crunch sources get `XLION_NO_PLATFORM_COMPAT` (backup `.before-crunch-optout`) | crunch has its own `sprintf_s`/`vsprintf_s`; the force-included compat header clashes | **Fixed upstream**, xtexture.plugin `530919f` (`Build/dependency/CMakeLists.txt`) |
| same file | patch `XLION_CI_CRUNCH_LINUX_THREADS`: `crn_threading_win32.cpp` out, `crn_threading_pthreads.cpp` in (backup `.before-linux-threading`) | Win32 threading file does not build on Linux | `530919f` drops the Win32 file (crunch's own Linux makefile does the same); pthreads not added, see open items |
| same file | patch `XLION_CI_CRUNCH_LZMA_LINUX` (Patch 5): `lzma_LzFindMt.cpp`, `lzma_Threads.cpp` out (backup `.before-linux-lzma`) | they use `HANDLE` / `CRITICAL_SECTION` | **Fixed upstream**, `530919f` |
| `source/Platform/xlion_platform_compat_linux.h` | removed `noexcept` from `vsprintf_s(char*,size_t,...)` and `sprintf_s(char*,size_t,...)` (backup `.before-noexcept-fix`) | not in the logs I can read; looks like the same crunch clash (crunch declares them without `noexcept`) | open: with the crunch opt-out in `530919f` it should be unnecessary; confirm on the clean checkout |
| `ci-results/` , `Build/xLION.linux` | logs and build tree | CI output | n/a |

The failure Patch 5 was meant to fix is no longer the last one in `ci-results/build.log`. The build stops later, on compressonator:

* `compressonator/cmp_core/source/core_simd_avx512.cpp`: `always_inline function '_mm512_*' requires target feature 'avx512f'` (46 errors). The file needs `-mavx512f -mavx512dq -mavx512bw -mavx512vl`; the CI patches never added them. **Fixed upstream in `530919f`.**

## 2. Root causes found and fixed in the repo (all in `main`)

Found by building from a **fresh clone** with `Build/CreateProject.sh`; the long-lived WSL tree hid every one of them.

| # | Symptom on a clean checkout | Cause | Fix |
|---|---|---|---|
| 1 | `lzma_LzFindMt.cpp` / `lzma_Threads.h`: unknown `HANDLE`, `CRITICAL_SECTION`; then `core_simd_avx512.cpp` needs `avx512f` | The working fix was an **uncommitted 15-line edit in the WSL clone of xtexture.plugin**; CI re-derived it as patches 1-5 and missed the AVX-512 flags | xtexture.plugin `530919f` |
| 2 | `Cannot find source file plugins/xmaterial.plugin/...` | root CMake made `plugins -> Cache/plugins`, the folder is `Cache/Plugins` (Windows ignores case); the WSL tree had the link made by hand | xLION `b9b87a5` |
| 3 | `xtexture_compiler: Is a directory` at link | every plugin does `add_subdirectory(... ${CMAKE_CURRENT_BINARY_DIR}/<name>_compiler)`, a folder where the executable goes | xLION `68f5a1e`: configure in `_cmake`, executable to `.../Release` |
| 4 | `Could not find shaderc/shaderc.hpp` (xmaterial) | the plugin uses the distribution shaderc; `libshaderc-dev` was not in the package list | `CreateProject.sh` `242bf49` |
| 5 | `msdf-atlas-gen/msdfgen does not contain a CMakeLists.txt` (xfont) | git submodules were not initialised | `CreateProject.sh` `08da4a6` |

Not a bug (looks like one): after `Exit` the headless editor can stay alive for minutes on a fresh checkout. Its main thread is in `xscheduler::Shutdown` joining a worker that is inside `RunCommandLine(xtexture_compiler ...)`; the editor compiles every resource at startup and exit waits for the compile in flight. CI must wait for `CompileStatus` to report `Compiling=0 Waiting=0` before testing and allow a long exit timeout on a cold checkout.

Scan of every other WSL clone: nothing else uncommitted or unpushed in our repos (left alone: `imgui-node-editor`, patched by the root CMake at configure, and the example project's editor-written data).

Rule: a fix is only real once it is pushed to `main`; verify Linux builds from a fresh clone, not from the long-lived WSL tree.

## 3. Changes I made

* **In the repo (main):** xtexture.plugin `530919f`; xLION `b9b87a5`, `68f5a1e`; `Build/CreateProject.sh` `96b3f18`, `242bf49`, `08da4a6`.
* **On the VM**, nothing in `/var/lib/jenkins-agent` (no edits, no ownership or permission changes). Read-only `sudo -u jenkins-agent` was used to read the CI checkout and its logs. What I did change:
  * created `/home/team39/xlion-verify` (a fresh checkout built by `Build/CreateProject.sh`, its logs and three helper scripts);
  * **system changes with sudo:** `apt-get install libshaderc-dev` and `apt-get install gdb`. The Jenkins build account needs `libshaderc-dev` too (it is now in the script's package list);
  * ran and killed my own test processes (`xLION_Headless` under my private socket `~/xlion-verify/editor.sock`).

## 4. Open items

* The CI checkout `/var/lib/jenkins-agent/xLION-inspect-...` still carries patches 1-5 and the `noexcept` edit; with the fixes above it should be recreated from `main` with `Build/CreateProject.sh` (the `noexcept` edit was not needed in the clean build).
* Jenkins job: build with `Build/CreateProject.sh --build`; start the headless editor with its own `XEDITOR_PIPE`; wait for compile idle; run the smoke; `Exit` with a long timeout. The pytest harness (`source/Editors/LevelEditor/smoke`) is Windows-only until `harness.py` gets a socket transport.

## 5. Verification on the VM (fresh clone of main, user team39, 2 cores / 3.8 GB)

* `Build/CreateProject.sh --no-packages`: configure OK.
* `xlion_compilers`: all nine native compilers (texture, material, material_instance, font, game, geom_static, geom_skin, skeleton, anim_package) built as ELF executables.
* `xLION_Headless` + `xeditorcli`: built (`BUILD_EXIT=0`).
* Headless smoke: `ListLevels` (3 levels), `OpenLevel`, `Play`, `Stop`, `Exit` all correct; the game module loaded.

## 6. The pytest suite on Linux (headless editor, VM, fresh clone of main; first full run)

Result: **303 passed, 225 failed, 35 errors, 16 skipped, 4 xfailed, 3 xpassed** in 1 h 00 min (566 tests, 2 cores).

Fixed on the way (all in `main`): the harness had no Linux transport (`harness.py`, `cc12e39`); `ModalState` crashed a headless editor (`xlevel.plugin` `c4efebe`); closing a level that holds prefab instances crashed the editor: **a real double destruction in the ECS pool** that MSVC's self-resetting `std::vector`/`std::string` destructors hid (`xECSV2` `0837fc5`, found with valgrind). `test_entities.py` went from crashing on its second test to 7/7.

What the 260 failures and errors are (grouped, not all analysed yet):

| Group | Count (approx.) | What it is |
|---|---|---|
| "the ScriptModule compiler is not built" (`test_game_compiler`, `test_script_module_compiler`, `test_script_module_editor`) | ~21 | the tests look for the Windows-style plugin build (`xscript_module.plugin/build/CreateAndBuildProject`); there is no Linux target for it in `xlion_compilers` |
| `FileNotFoundError: 'cmd'` | 6 | tests that start `cmd.exe` (Windows only) |
| `'NoneType' object has no attribute 'groups'` | ~20 | a regex over an editor reply that has another shape on Linux (e.g. `test_actions`); to look at |
| Text and layout (`KeyError: 'Quads'/'Lines'/'Bounds'`), `test_modal_position`, `test_keyboard_modifiers` | ~35 | need a real window (UI state, rendering); a headless editor has none |
| **Editor died** (`SimulateModuleCrash`, `CreateAsset`, `LogShow -Query`, connection reset) | ~12 | real Linux crashes still to investigate |
| `xerr_details::chain_pool::Alloc(): Assertion false` | startup of the first launches | the xerr error-chain pool is exhausted; suspected one copy of the pool per shared library (not confirmed) |
| prefab group (`test_prefabs`, `test_prefab_editor`, `test_prefab_*`) | ~75 | not analysed yet; may share causes with the above |

Lessons for the harness and for CI: never run the suite under gdb (a crashed editor stays stopped while gdb resolves symbols and the run stalls: use `XLION_TEST_GDB=1` only on one test); always run with `--timeout` (pytest-timeout); install `valgrind` and `gdb` on the CI box for investigations.
