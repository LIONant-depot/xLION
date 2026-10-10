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

## 7. Netdata monitor (installed 2026-10-09)

* `apt-get install netdata` (Ubuntu package 1.43.2, free/open source; Netdata Cloud is not connected). `/etc/netdata/netdata.conf` is ours (previous file kept as `netdata.conf.before-xlion`): listens on `127.0.0.1:19999` only, machine learning off, 2 s samples, anonymous statistics opted out.
* Published by Caddy at `https://team39.dp-ext8.com/monitor/` behind basic auth (user `monitor`; the password is kept by the team, not in this repository). The block is in `/etc/caddy/Caddyfile` (backup `Caddyfile.backup-20261009-130227`, restore with `sudo cp` and `sudo systemctl reload caddy`). To change the password: `caddy hash-password`, replace the hash in the `/monitor` block, reload.
* Also installed with sudo while investigating: `libshaderc-dev`, `gdb`, `valgrind`.

## 8. TODO for the VM

- [x] **GeomSkin on the Windows PC (reported 2026-10-10): cause found and fixed on this PC the same day.** The Visual Studio solution had been generated on 10-08 and was not regenerated after `c6de339`, so its rule for `GeomSkinBasicShader_vert.h` still depended only on the main `.glsl`: the old SPIR-V stayed (headers dated 10-08) next to the new C++ vertex layout of `7380d7b`. Fix: `cmake -S . -B Build/xLION.vs2022` (regenerates the rules) and rebuild; the headers were rebuilt at once. Anyone whose build was made before 10-09 needs the same once. Original note: the skin mesh does not come out right there, probably because the PC is on older code than the Linux work. What changed on 2026-10-09 (all on `main`): `xgeom_skin` `7380d7b` (the preview's vertex formats, and the two included files `xgeom_skin_mb_input_full.vert` / `_position.vert`, changed together: position as SINT16_4D, the packed skin bytes as R16_UINT + R16G16_UINT), `xserializer` `7272017` (writer pads an array to its type's alignment, up to 16: files made before it still load, so it alone should not break old data, but it changes the bytes a new compiler writes) and root `CMakeLists.txt` `c6de339` (a shader's SPIR-V header now depends on the other shader files of its folder: before it, an edit to an included `.vert` did NOT regenerate the header, so the PC can hold old SPIR-V next to new C++). On the PC: pull every repo (`Build/CreateProject.bat` update), re-run CMake and rebuild xLION (the shader headers then regenerate), rebuild `xgeom_skin_compiler` (`plugins/xgeom_skin.plugin/build/CreateAndBuildProject.bat`) and start the editor: since `c0cd5f4` the asset manager recompiles every resource whose compiler is newer than it. If it is still wrong, send the editor log lines for the skin asset (`asset.compile` operation in the Logs).
- [ ] **Window editor on WSL (Mesa Dozen), intermittent, found 2026-10-10 while testing the resource card**: now and then the window editor aborts in `xgpu::tools::imgui::share_resources::setTexture` (`xgpu_imgui_breach.cpp:589`, `Assertion false`), right after Vulkan validation errors `VUID-vkCmdCopyBufferToImage-imageOffset-07738` (the thumbnail atlas uploads a cell at an offset the driver does not accept). Not a regression of the card (no hover is involved); probably the thumbnails being redrawn. Headless CI is not affected. Also fixed that day: `xeditor_tools::camera::m_Angles` was uninitialized (NaN in `LookAt`, intermittent abort in the 3D viewports).
- [ ] **Netdata Jenkins integration** (waiting for a go-ahead and a time with no running build). Needs: (1) Netdata's official apt package instead of Ubuntu's (Ubuntu's has no Go plugin, where the Jenkins collector lives); (2) the *Prometheus metrics* plugin installed in Jenkins 2.580.1 and a Jenkins restart when no build is running; (3) a read-only `netdata` Jenkins user with an API token (created by a Jenkins admin), and the collector config `/etc/netdata/go.d/jenkins.conf` pointing at `http://127.0.0.1:8080/jenkin/prometheus`.
- [ ] Recreate the Jenkins workspace from `main` with `Build/CreateProject.sh --update` (the old `xLION-inspect-...` checkout still carries CI patches 1-5); keep `/var/lib/jenkins-agent` untouched until agreed.
- [ ] Jenkinsfile in the repo: update (`--update` + manifest), build, wait for `CompileStatus` idle, smoke, pytest, archive logs; nightly scratch build with `ccache`.
- [ ] Trigger: GitHub organization webhook for push events (needs Jenkins reachable from the internet) or a poller on `git ls-remote` of every repo's `main`.
- [ ] Linux build target for the ScriptModule compiler (about 21 tests need it) and skip markers for GUI-only and Windows-only tests (see section 6).
- [ ] Remaining Linux crashes and the `xerr` pool assertion (section 6).
- [ ] **Windows build agent: needs a dedicated PC** (the VM is Linux only; the working PC is already fully used by people and AIs). Spec: 8+ cores, 32 GB RAM, 500 GB+ NVMe SSD, any GPU with a Vulkan driver (the window-only tests need a real editor window). It must keep an interactive desktop session (auto-login; a disconnected remote-desktop session locks the screen and breaks the window tests), so the agent runs from the user session, not as a service, under its own low-privilege Windows account, in a CI folder (not a dev tree). Install: Visual Studio 2022 Build Tools (v143, Windows SDK), CMake, Git, Java 17+, Python + pytest, Vulkan SDK. It connects outward to Jenkins with `-webSocket` through `/jenkin/` (no port opened on the PC); the node (label `windows`) is created by a Jenkins admin. Prepare in advance: the agent setup script and the Windows job (build, smoke, upload `timing.log`).
- [ ] SSH hardening (section 9) and the broken Caddy apt source.
- [ ] **Jenkins agent instead of the built-in node** (Jenkins' own warning): a Jenkins administrator creates the node `linux-vm` (label `linux`) and runs `Build/jenkins/agent/install_agent.sh` here with its secret; then the Built-In Node gets 0 executors. The jobs already ask for the label `linux`.
- [ ] Create the three Jenkins jobs (`xlion-full`, `xlion-fast`, `xlion-poll`: documentation/Linux/jenkins.md). The full job runs at 08:00 Singapore time.
- [ ] Restart Jenkins once (with the Prometheus plugin restart when that is done) so its pages use Singapore time: the schedules name `TZ=Asia/Singapore`, but the page still shows UTC.
- [ ] Jenkins housekeeping from its management page: Content Security Policy (enable in report-only mode if offered, check the Test Result pages, then enforce); Java 21 reaches end of support on or after 2027-09-30 (plan the move to a newer Java before then).
- [ ] Understand `test_play_more.py::test_transform_edit_during_play_survives_every_kind_of_frame[fast_...]`: fails every time on Linux when its file runs alone (the edited entity drifts up to 0.14 after the edit at 3x game speed), passed inside the first full run (see `Build/ci/fast_deselect.txt`).

## 9. Removed and found (2026-10-09)

* **Tailscale removed** (no longer used; one network entry point less): logged out of the tailnet, `tailscaled` disabled, `tailscale` and its keyring purged, the apt source moved to `/root/tailscale.list.removed-20261009`. Public SSH, `ufw` and everything else were not touched. If the node `team39` still shows in the tailnet's admin console, its owner can delete it there.
* **SSH is open to the internet with passwords enabled.** The journal shows password-guessing bots all day (about 60 to 120 failed attempts per address; the only successful logins are `team39` from the team's address). Options, least to most disruptive: `fail2ban` (bans repeat offenders, changes no login settings), then `PasswordAuthentication no` (keys only; needs every person to have a key first), then limiting port 22 to known addresses. Nothing was changed.
* **Caddy's apt repository is broken** (`dl.cloudsmith.io/public/caddy/stable` answers `402 Payment Required` and "no longer signed"): the public web server does not get updates through apt until that source is replaced.
