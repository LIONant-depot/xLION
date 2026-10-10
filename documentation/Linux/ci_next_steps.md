# CI: what is done and what is left (2026-10-11)

How the CI is laid out is in `jenkins.md`; the findings of the VM work are in `ci_vm_findings.md`. This is the list for the next session.

## Done and running

- **Check-in (`xlion-fast`)**: two legs at the same time, Debug (team38, label `debug`) and Release (team37, label `release`), each builds and runs the fast tests; the PC (`xlion-windows`, label `windows`) does the same with both builds and the tests on Debug. The poll job (team39, label `full`) starts them.
- **Daily**: 08:00 Linux full (team39), 08:30 Windows light, 10:00 Linux Debug sanitizer (team39, label `san`), Sundays 12:00 Windows light also tests Release.
- **Heartbeat and stall watchdog** in every Linux stage (`Build/ci/watch.sh`), a shared ccache served by team38, Netdata of the three VMs in one dashboard, the third party libraries pinned in `Build/third_party.txt`.
- **History of every run** (`Build/ci/history.py`, see below).

## Left, in this order (all are required to call the CI finished)

1. ~~Stall watchdog for the Windows script~~ **done** (`Build/ci/watch_windows.ps1`, started by `ci_run_windows.ps1` as a second process that shares the console): a heartbeat a minute (`[heartbeat] ci mm:ss idle Ns cpu % mem-free top <process>`), and 5 minutes without CPU use in the tree and without file changes in the results folder and `smoke\.logs` prints the process tree and kills what the script started (the stage fails, the run goes on, `results\stalled.txt` says so). Self-check: `powershell -File Build\ci	est_watch_windows.ps1` (a sleeping tree is killed, a computing one is left alone). Not yet seen in a real Jenkins run: check the console of the next Windows run for the heartbeat lines.
1. **Sanitizer jobs**: (a) Windows AddressSanitizer: MSVC `/fsanitize=address` (no UBSan on MSVC), no incremental linking, no `/RTC1`, its own build folder, a nightly Debug and a Sunday Release; (b) Linux Release + sanitizer: `ci_run.sh --sanitize --config Release` already selects `xLION.linux-san-release`, it needs its own Jenkinsfile and agent label (a machine with room: the first build needs one compile at a time and the 7 GB swap); (c) TSan: a `-fsanitize=thread` build (cannot be mixed with ASan), its own build folder and baseline, for `xscheduler` and the lockless containers.
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
