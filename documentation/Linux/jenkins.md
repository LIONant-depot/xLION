# xLION on Jenkins (Linux)

Two jobs test xLION on the CI VM (headless editor, Linux), plus one tiny job that starts the fast one:

| job | script | when | what |
|---|---|---|---|
| `xlion-full` | `Build/jenkins/Jenkinsfile.full` | every day 08:00 Singapore time (and by hand) | update, build, let the resources compile, the whole smoke suite (about an hour) |
| `xlion-fast` | `Build/jenkins/Jenkinsfile.fast` | started by `xlion-poll` when any repo has a new commit (and by hand) | the same, but only the files of `Build/ci/fast_files.txt` (reliable, broad: about 6 minutes of tests) |
| `xlion-poll` | `Build/jenkins/Jenkinsfile.poll` | every 5 minutes | compares the newest commit of every repo on GitHub with the CI tree (15 seconds, nothing cloned) and starts `xlion-fast` if anything is new. Delete it when the GitHub organization webhook starts `xlion-fast` directly |

All three run on the Jenkins server itself (label `built-in`) and share one persistent checkout and build, `/var/lib/jenkins/xlion-ci/tree` (updated with
`Build/CreateProject.sh --update`, so a run only rebuilds what changed). They take a lock on it: when the full run is going, a fast run waits its turn.
The full job starts from nothing on Sundays (or with `SCRATCH`).

## Creating the jobs (a Jenkins administrator does this once)

For each of the three: **New Item**, name as in the table, type **Pipeline**; **Pipeline > Definition: Pipeline script from SCM**, SCM **Git**, Repository URL
`https://github.com/LIONant-depot/xLION.git`, Branch `*/main`, Script Path as in the table, **Lightweight checkout** on. Save. Run `xlion-poll` once (it creates the
tree with a first full build, about an hour on a 2 core machine, then the fast job starts). If Jenkins refuses a script step, approve it under
*Manage Jenkins > In-process Script Approval*.

Needs on the machine (already installed on the CI VM): `Build/CreateProject.sh` packages (clang-20, cmake, ninja, libvulkan-dev, glslc, libshaderc-dev, libx11-dev),
python3-venv. The tests make their own Python environment (`/var/lib/jenkins/xlion-ci/venv`: pytest and pytest-timeout).

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
