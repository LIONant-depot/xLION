# CI: what is done and what is left (2026-10-11)

How the CI is laid out is in `jenkins.md`; the findings of the VM work are in `ci_vm_findings.md`. This is the list for the next session.

## Done and running

- **Check-in (`xlion-fast`)**: two legs at the same time, Debug (team38, label `debug`) and Release (team37, label `release`), each builds and runs the fast tests; the PC (`xlion-windows`, label `windows`) does the same with both builds and the tests on Debug. The poll job (team39, label `full`) starts them.
- **Daily**: 08:00 Linux full (team39), 08:30 Windows light, 10:00 Linux Debug sanitizer (team39, label `san`), Sundays 12:00 Windows light also tests Release.
- **Heartbeat and stall watchdog** in every Linux stage (`Build/ci/watch.sh`), a shared ccache served by team38, Netdata of the three VMs in one dashboard, the third party libraries pinned in `Build/third_party.txt`.
- **History of every run** (`Build/ci/history.py`, see below).

## Left, in this order (all are required to call the CI finished)

1. ~~Stall watchdog for the Windows script~~ **done** (`Build/ci/watch_windows.ps1`, started by `ci_run_windows.ps1` as a second process that shares the console): a heartbeat a minute (`[heartbeat] ci mm:ss idle Ns cpu % mem-free top <process>`), and 5 minutes without CPU use in the tree and without file changes in the results folder and `smoke\.logs` prints the process tree and kills what the script started (the stage fails, the run goes on, `results\stalled.txt` says so). Self-check: `powershell -File Build\ci	est_watch_windows.ps1` (a sleeping tree is killed, a computing one is left alone). Not yet seen in a real Jenkins run: check the console of the next Windows run for the heartbeat lines.
1. **Sanitizer jobs** (2026-10-12, uncommitted batch; none counts as done before its Jenkins run):
   - (b) Linux Release + ASan/UBSan: `Build/jenkins/Jenkinsfile.sanitize_release` (Sundays 12:00, label `heavy`, tree `tree-san-release`, `ci_run.sh --sanitize --config Release --baseline Build/ci/sanitizer_baseline_release.txt`). Sanitizer builds compile with `-j1`. **Hand-run done on team37, awaiting Jenkins job** `xlion-sanitize-release`: 10 findings (520 reports), seeded into `sanitizer_baseline_release.txt` (the run was cut by the old 1500 s test cap; a second hand-run with line tables, `-gline-tables-only`, is under way and may change the fingerprints).
   - (c) TSan: `XLION_SANITIZE_MODE=thread`, `CreateProject.sh --tsan` (`Build/xLION.linux-tsan`), `ci_run.sh --tsan` (`Build/ci/tsan_suppressions.txt`, baseline `sanitizer_baseline_tsan.txt`), `Build/jenkins/Jenkinsfile.tsan` (Saturdays 12:00, `heavy && san2` = team37, which has `vm.mmap_rnd_bits=28` in `/etc/sysctl.d/99-tsan.conf`). **Hand-run queued on team37**. Expected blocker: `xlevel_engine_copies.h` drops RTLD_DEEPBIND only for ASan, not TSan (engine change awaiting approval).
   - (a) Windows MSVC ASan: `ci_run_windows.ps1 -Sanitize [-Config]` (`Build\xLION.vs2022-asan`, `Build/ci/msvc_asan.cmake`, runtime DLLs copied), `Build/jenkins/Jenkinsfile.windows_sanitize` (nightly 02:00 Debug, Sundays 04:00 Release). Hand-run on LION-HEAVY: the editor first died at start on an ASan heap-buffer-overflow in xGPU (texture upload size counted the xbitmap mip table), fixed in xGPU; after it the editor starts and the tests run (3 findings left in `sanitizer_baseline_windows.txt`: new-delete-type-mismatch in `xlioncore::game::DestroyWorld` x2, container-overflow in `xscene::system_usage::EventGroups`). **Hand-run done, awaiting Jenkins job** `xlion-windows-sanitize`.
   - Daily `xlion-sanitize` #1 (team39): UNSTABLE, 4 real findings (ASan new-delete-type-mismatch in `xecs::event::mgr::~mgr`, x465; UBSan misaligned `std::byte*` in `xserializer::stream::LoadObject`; misaligned `settings::data_memory` in `xproperty`). Its test failures were the sanitizer run starving team39 (Jenkins + editor + a 1.2 GB llvm-symbolizer on 3.8 GB): every 60 s compile poll timed out and the 1500 s tier cap cut the tests. Fixed in the batch: `symbolize=0` + offline symbolization in `sanitize_report.py`, sanitizer caps 5400 s / 180 s polls, label `heavy`. Baseline not seeded (run not clean).
2. **Create in Jenkins**: the job `xlion-windows-full` (script path `Build/jenkins/Jenkinsfile.windows_full`).

## Verify against the next runs

- The Debug leg of `xlion-fast` after the `box3d` fix (`f550e54`): its first run is a cold build of about an hour.
- The 08:00 full run: whether `test_engine_copies`, `test_system_constraints` and `test_undo_redo` pass now (the failures of the first run were the memory thrash); then regenerate `Build/ci/known_failures_linux.txt` from a clean run.
- The 10:00 sanitizer: its first real report seeds `Build/ci/sanitizer_baseline.txt`; it also checks the `xbitmap` (`delete[]`) and `RTLD_DEEPBIND` fixes.
- Release-only failures: `Build/ci/known_failures_linux_release.txt` is empty; whatever the Release legs report that is not a bug goes there with a reason.

## The history of the runs (for binary search)

`Build/ci/history.py` keeps, for good, one record per leg of every run: the outcome of every test and the commit of every repo (the `manifest.txt` of the run). A timer on team39 (`xlion-ci-history.timer`, every 10 minutes) ingests what Jenkins archived into `/var/lib/xlion-ci-history/records.jsonl` (about 1 MB for 80 runs). On team39:

    sudo python3 /opt/xlion-ci-history/history.py runs
    sudo python3 /opt/xlion-ci-history/history.py timeline <part of a test name> --job xlion-fast --leg Release
    sudo python3 /opt/xlion-ci-history/history.py bisect <test> --job xlion-windows      # last pass, first failure after it, and the repos that differ between them (with the git log command for each)

The Windows runs have the commits of their repos from the run after `de50c5e` on. Back the folder up with the rest of team39.

## Open bugs

- **Window editor on WSL, intermittent abort in `xgpu::tools::imgui::share_resources::setTexture`** (`xgpu_imgui_breach.cpp`, `assert(false)` after `m_Device.Create(PipelineInstance, ...)` fails), after Vulkan validation errors on `vkCmdCopyBufferToImage` (the thumbnail atlas). Not reproduced on 2026-10-11 with the validation layer on (`VK_INSTANCE_LAYERS=VK_LAYER_KHRONOS_validation`), the windowed `xLION` of a fresh build, the Assets drawer open (`LocateAsset -Path Assets/SheKnewMe.tga`) and 25 rounds of `SetBrowserSearch` and `LocateAsset` through `xeditorcli` (no validation message, no abort). Next: a longer run with real scrolling and folder changes (virtual input: `MouseWheel`, `MouseMove`), and read the exact `VUID` text when it comes; the failing `Create` should be made to report why instead of asserting.
- The macro system: `macro_system_design.md` is the first design; a clean revision (`macro_system_design_v2.md`) is being written by a separate review.
- The `xGPU` standalone CMake still lists `xECS` (to go with the `xGPU` clean-up). The dev PC's `xcmake_tools` copy (`Build\xLION.vs2022\_deps\xcmake_tools`) needs a `git pull` to use the pins.
