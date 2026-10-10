# xLION on Jenkins (Linux)

Two jobs test xLION on the CI VM (headless editor, Linux), plus one tiny job that starts the fast one:

| job | script | when | what |
|---|---|---|---|
| `xlion-full` | `Build/jenkins/Jenkinsfile.full` | every day 08:00 Singapore time (and by hand) | update, build, let the resources compile, the whole smoke suite (about an hour) |
| `xlion-fast` | `Build/jenkins/Jenkinsfile.fast` | started by `xlion-poll` when any repo has a new commit (and by hand) | the same, but only the files of `Build/ci/fast_files.txt` (reliable, broad: about 6 minutes of tests) |
| `xlion-sanitize` | `Build/jenkins/Jenkinsfile.sanitize` | every day 10:00 Singapore time (and by hand) | the same fast files on a build with the sanitizers; reports the NEW findings (below) |
| `xlion-poll` | `Build/jenkins/Jenkinsfile.poll` | every 5 minutes | compares the newest commit of every repo on GitHub with the CI tree (15 seconds, nothing cloned) and starts `xlion-fast` if anything is new. Delete it when the GitHub organization webhook starts `xlion-fast` directly |

All three run on an **agent** with the label `linux`, not on the Jenkins server's own (built-in) node: a build runs project scripts, and on the built-in node that
is the same account, files and credentials as Jenkins itself (Jenkins warns about this on its management page). The agent is a service of the low-privilege user
`jenkins-agent` on the same VM; set it up with `Build/jenkins/agent/install_agent.sh` (the steps are at the top of that file), then give the built-in node 0 executors.
Until then, giving the built-in node the label `linux` makes the jobs run (on the less safe node). All three share one persistent checkout and build,
`~/xlion-ci/tree` of the agent's user (updated with `Build/CreateProject.sh --update`, so a run only rebuilds what changed). They take a lock on it: when the full run
is going, a fast run waits its turn. Before every run the example project is put back exactly as GitHub has it (the tests leave files behind when a run is killed).
The full job starts from nothing on Sundays (or with `SCRATCH`).

## The sanitizer job (`xlion-sanitize`)

Every day at 10:00 Singapore time (after the 08:00 full run; the tree lock keeps them apart) the editor is built with AddressSanitizer and UndefinedBehaviorSanitizer in its own tree (`~/xlion-ci/tree-san`, build dir `Build/xLION.linux-san`, made by `Build/CreateProject.sh --sanitize`) and the fast tier runs on it (`Build/ci/ci_run.sh --tier fast --sanitize`). Third-party code is not instrumented (`Build/ci/sanitizer_ignorelist.txt`), the asset compilers stay ordinary builds, vptr/function checks and leak detection are off.

The verdict is the findings, not the tests: every finding gets a fingerprint (its kind and the top three frames of our code) and `Build/ci/sanitize_report.py` compares them with `Build/ci/sanitizer_baseline.txt`. The build name is `SAN-GREEN`, `SAN-KNOWN` (only known ones) or `SAN-NEW` (yellow: something new; the description counts them). Read `sanitizer.md` in the artifacts: the new findings with three frames each, the known ones counted. To accept a finding copy its line from `sanitizer_all.txt` into the baseline; delete a line when it is fixed. Locally: `bash Build/CreateProject.sh --sanitize --build`, then run the editor or a test from `Build/xLION.linux-san`.

## Disk and build time (the CI machine has a 38 GB disk)

- **Swap: the CI machine needs 6 GB of it, never less** (RAM is 3.8 GB, 2 cores). `/swapfile` 2 GB + `/swapfile2` 4 GB, both in `/etc/fstab`. A sanitized clang peaks at about 3 GB and two can run side by side: with only 2 GB of swap the build was OOM-killed. Do not remove them to get the disk back.

- **Compressed debug info** (`-gz`, and `--compress-debug-sections` at link): on by default in every Linux build (`XLION_COMPRESS_DEBUG`, `source/Platform/xlion_linux_flags.cmake`); an object file of `xecs.cpp` went from 10.2 MB to 6.2 MB.
- **ccache**: used by `Build/CreateProject.sh` when it is installed (`XLION_CCACHE=0` turns it off), for the editors and the asset compilers. It keys on the compiler, the flags and the preprocessed source, compresses its entries (zstd) and is capped at 4 GB (`CCACHE_MAXSIZE`); `ci_run.sh` keeps it in `xlion-ci/ccache`. The build from scratch of the first week of a month runs with the cache off (`CCACHE_DISABLE`), so a cold, honest build is made every month.

## Creating the jobs (a Jenkins administrator does this once)

For each of the three: **New Item**, name as in the table, type **Pipeline**; **Pipeline > Definition: Pipeline script from SCM**, SCM **Git**, Repository URL
`https://github.com/LIONant-depot/xLION.git`, Branch `*/main`, Script Path as in the table, **Lightweight checkout** on. Save. Run `xlion-poll` once (it creates the
tree with a first full build, about an hour on a 2 core machine, then the fast job starts). If Jenkins refuses a script step, approve it under
*Manage Jenkins > In-process Script Approval*.

`Build/ci/fast_deselect.txt` lists tests of the fast files that are left out of the fast tier for now (with the reason).

Needs on the machine (already installed on the CI VM): `Build/CreateProject.sh` packages (clang-20, cmake, ninja, libvulkan-dev, glslc, libshaderc-dev, libx11-dev),
python3-venv. The tests make their own Python environment (`~/xlion-ci/venv`: pytest and pytest-timeout).

## Reading a run without opening a log

* **Build name**: `#42 GREEN` all tests passed; `#42 KNOWN` (yellow) only failures that are already in `Build/ci/known_failures_linux.txt`;
  `#42 NEW` (red) a test failed that is not in that list; `#42 FAILED` (red) the update or the build did not finish (see the build log artifact).
* **Description**: the counts (passed, failed, new, skipped, minutes), the number of known failures that now pass, and the repos that have a new commit since the last run.
* **Test Result** (the build's page > *Test Result*): every test with its time and message; for a failed test also *the tail of the editor's log* and whether the
  editor was still running or how it died. The trend graph on the job page follows pass/fail over runs.
* **Artifacts** (`results/`):
  * `summary.md`: the report (also printed at the end of the console log): verdict, what changed, where the time went per stage, NEW failures, FIXED tests,
    failures grouped by reason, failing files, slowest tests and files.
  * `timing.log`: a START and an END line for every test with the time and the setup/call/teardown split; a START without an END is the test that hung.
    `timing.tsv` is the same as a table.
  * `manifest.txt`: the commit of every repo the build was made from. `changed.txt`: the repos that moved since the last run and their newest commit message.
  * `stages.tsv`, `build.log`, `compile_wait.log` (the resource compile queue, polled), `suite.xml` (JUnit), `smoke_logs.tgz` (the editor logs of every launch).
  * `new_failures.txt`, `fixed.txt`, `failed_now.txt`.

## The known failures

A fresh Linux headless run still has failures that are understood but not fixed (see `documentation/Linux/ci_vm_findings.md`, section 6). They are listed in
`Build/ci/known_failures_linux.txt`; a run is red only for a failure that is not in the list, and the report says which listed tests now pass. When you fix a group:
delete those lines (the report names the tests that passed); to start a new list from a run, copy its `failed_now.txt`.

## The fast list

`Build/ci/fast_files.txt` holds the test files the check-in job runs: files that passed every test on Linux, none slow, ranked by how many source areas they cover
per second (`python Build/ci/pick_fast.py <JUnit xml of a full run>` prints the ranking). A file that is broad but still fails is left out until it is fixed; the
full job keeps running it.

## By hand

    bash Build/ci/ci_run.sh --tier fast --tree ~/xlion-ci/tree --results ~/xlion-ci/results      # or --tier full; --scratch; --force
    bash Build/ci/ci_run.sh --tier fast --tree ~/xlion-ci/tree --results /tmp/r --detect-only     # prints "CHANGED <n>" or "NOTREE"

Times: the VM is on Singapore time (`timedatectl`); the Jenkins web page shows UTC until Jenkins is restarted once (the schedules name `TZ=Asia/Singapore`
explicitly, so they run at the right time either way).
