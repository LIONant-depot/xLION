#!/usr/bin/env bash
# One CI run of xLION on Linux: update, build, let the resources compile, run the smoke tests, summarize. Used by the two Jenkins jobs
# (Build/jenkins/Jenkinsfile.full and Jenkinsfile.fast) and runnable by hand with the same arguments.
#
#   bash Build/ci/ci_run.sh --tier fast|full --tree DIR --results DIR [--scratch] [--detect-only] [--force]
#
#   --tier       fast: the files of Build/ci/fast_files.txt.  full: the whole suite.
#   --tree       the persistent xLION checkout and build (created on first use). Next to it: .lock (one run at a time), venv/ (pytest), and the sockets.
#   --results    where everything a person wants goes (the Jenkins job archives it): summary.md, description.txt, status.txt, suite.xml (JUnit), timing.log/.tsv,
#                manifest.txt, changed.txt, stages.tsv, build.log, compile_wait.log, new_failures.txt, fixed.txt, failed_now.txt, smoke_logs.tgz
#   --scratch    delete the tree first: a clean checkout, a clean build, a clean resource cache
#   --detect-only  only compare the repos with GitHub: writes changed.txt, prints "CHANGED <n>" (or "NOTREE"), builds nothing
#   --force      (with the fast job) run even when nothing changed
#   --sanitize   the sanitizer build (AddressSanitizer + UndefinedBehaviorSanitizer, Build/xLION.linux-san) and its tests: the verdict is the NEW sanitizer findings
#                (Build/ci/sanitize_report.py), not the tests, which are slower and are only the way to exercise the code
#
# The tests run against the headless editor with a private socket, so it never meets another editor on the machine. Exit status is 0 unless the run itself could
# not be made (build failure, no result); failing tests are reported in status.txt (GREEN, KNOWN failures only, NEW failures), not by the exit status.
set -uo pipefail

TIER=full; TREE=; RESULTS=; SCRATCH=0; DETECT=0; FORCE=0; SAN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --tier) TIER="$2"; shift 2 ;; --tree) TREE="$2"; shift 2 ;; --results) RESULTS="$2"; shift 2 ;;
    --scratch) SCRATCH=1; shift ;; --detect-only) DETECT=1; shift ;; --sanitize) SAN=1; shift ;; --force) FORCE=1; shift ;;
    *) echo "unknown argument $1"; exit 2 ;;
  esac
done
[ -n "$TREE" ] && [ -n "$RESULTS" ] || { echo "usage: ci_run.sh --tier fast|full --tree DIR --results DIR [--scratch] [--detect-only] [--force]"; exit 2; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BSUB="xLION.linux"; [ "$SAN" = 1 ] && BSUB="xLION.linux-san"
# ccache (see Build/CreateProject.sh): one cache next to the trees, capped; the build from scratch of the FIRST week of a month runs with the cache off, so a cold, honest build is
# made every month (the cache cannot hide a build that no longer works from nothing)
export CCACHE_DIR="${CCACHE_DIR:-$(dirname "$TREE")/ccache}" CCACHE_MAXSIZE="${CCACHE_MAXSIZE:-4G}"
[ "$SCRATCH" = 1 ] && [ "$(date +%d | sed s/^0//)" -le 7 ] && export CCACHE_DISABLE=1
BASE="$(dirname "$TREE")"
GIT_BASE="${GIT_BASE:-https://github.com/LIONant-depot}"
mkdir -p "$RESULTS" "$BASE"
STAGES="$RESULTS/stages.tsv"

# ------------------------------------------------------------------------------------------------------------------------------------------------------
# which repos moved
# ------------------------------------------------------------------------------------------------------------------------------------------------------
if [ "$DETECT" = 1 ]; then
  bash "$HERE/changed_repos.sh" "$TREE" > "$RESULTS/changed_raw.txt"; rc=$?
  if [ $rc = 2 ]; then echo "NOTREE"; exit 0; fi
  echo "CHANGED $(wc -l < "$RESULTS/changed_raw.txt")"
  exit 0
fi

# ------------------------------------------------------------------------------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------------------------------------------------------------------------------
: > "$STAGES"
stage_run() {                                   # stage_run <name> <command...>: runs it, records the time and the result in stages.tsv
  local name="$1"; shift
  local t0; t0=$(date +%s)
  echo; echo "=================== $name ($(date '+%F %T %z')) ==================="
  "$@"; local rc=$?
  local t1; t1=$(date +%s)
  printf "%s\t%d\t%s\n" "$name" $((t1 - t0)) "$([ $rc = 0 ] && echo ok || echo "FAILED($rc)")" >> "$STAGES"
  return $rc
}
finish() {                                      # always: the summary, whatever happened
  local junit="$RESULTS/suite.xml"
  python3 "$HERE/summarize.py" --junit "$junit" --out "$RESULTS" --tier "$TIER" --known "$HERE/known_failures_linux.txt" \
    --timing "$RESULTS/timing.tsv" --changed "$RESULTS/changed.txt" --stages "$STAGES" --title "xLION $TIER run $(date '+%F %T %z')" > /dev/null 2>&1 || true
  clean_project 2>/dev/null || true
  if [ "$SAN" = 1 ]; then          # the verdict of a sanitizer run is its findings
    python3 "$HERE/sanitize_report.py" --logs "$RESULTS/sanitizer" --out "$RESULTS" --baseline "$HERE/sanitizer_baseline.txt" || true
    [ -f "$RESULTS/sanitizer_status.txt" ] && { cp "$RESULTS/sanitizer_status.txt" "$RESULTS/status.txt"; head -3 "$RESULTS/sanitizer.md" | tail -1 > "$RESULTS/description.txt"; cp "$RESULTS/sanitizer.md" "$RESULTS/summary.md"; }
    tar -czf "$RESULTS/sanitizer_logs.tgz" -C "$RESULTS" sanitizer 2>/dev/null || true
  fi
  [ -d "$TREE/source/Editors/LevelEditor/smoke/.logs" ] && tar -czf "$RESULTS/smoke_logs.tgz" -C "$TREE/source/Editors/LevelEditor/smoke" .logs 2>/dev/null || true
  [ -f "$TREE/Build/xLION.linux/manifest.txt" ] && cp "$TREE/Build/xLION.linux/manifest.txt" "$RESULTS/manifest.txt" || true
  echo; echo "status: $(cat "$RESULTS/status.txt" 2>/dev/null || echo unknown)"
  cat "$RESULTS/summary.md" 2>/dev/null || true
}
trap finish EXIT

# ------------------------------------------------------------------------------------------------------------------------------------------------------
# one run at a time on this tree (the fast and the full job share it)
# ------------------------------------------------------------------------------------------------------------------------------------------------------
exec 9> "$BASE/.lock"
echo "waiting for the tree lock ($BASE/.lock) ..."
flock -w 7200 9 || { echo "the tree was busy for 2 hours"; echo "FAILED" > "$RESULTS/status.txt"; exit 1; }
echo "lock taken"

# what changed since the last run (before the update moves the repos)
if [ -d "$TREE/.git" ]; then bash "$HERE/changed_repos.sh" "$TREE" > "$RESULTS/changed_raw.txt" 2>/dev/null || true; else : > "$RESULTS/changed_raw.txt"; fi

# ------------------------------------------------------------------------------------------------------------------------------------------------------
# update
# ------------------------------------------------------------------------------------------------------------------------------------------------------
# The tests drive a real editor against the example project and it is shared by every run: a run that crashed or was killed leaves entities, scenes and
# descriptors behind (the test tool only puts the project back when it ends normally), and the next run then sees a different project (extra bodies in the Physics
# scene changed what a test picked). So the project is put back exactly as GitHub has it before every run and after it. Cache/ (the plugins, the dependencies and
# the compiled resources) is never touched.
clean_project() {
  local p="$TREE/example.lionprj"
  [ -d "$p/.git" ] || return 0
  git -C "$p" reset -q --hard
  git -C "$p" clean -fdq -- Descriptors Project.config Assets
  return 0
}
update_tree() {
  if [ "$SCRATCH" = 1 ] && [ -d "$TREE" ]; then echo "scratch build: removing $TREE"; rm -rf "$TREE"; fi
  if [ ! -d "$TREE/.git" ]; then
    git clone -q --depth 1 --branch main "$GIT_BASE/xLION.git" "$TREE" || return 1
  else
    git -C "$TREE" fetch -q --depth 1 origin main && git -C "$TREE" reset -q --hard origin/main || return 1
  fi
  ( cd "$TREE" && bash Build/CreateProject.sh --no-packages --update $([ "$SAN" = 1 ] && echo --sanitize) ) || return 1
  clean_project
}
if ! stage_run "update repos" update_tree; then echo "FAILED" > "$RESULTS/status.txt"; exit 1; fi

# the repos that changed, with what the newest commit says
: > "$RESULTS/changed.txt"
while read -r name old new; do
  [ -n "${name:-}" ] || continue
  d=""; for c in "$TREE" "$TREE/example.lionprj" "$TREE/example.lionprj/Cache/dependencies/$name" "$TREE/example.lionprj/Cache/Plugins/$name"; do [ "$(basename "$c")" = "$name" ] && [ -d "$c/.git" ] && d="$c" && break; done
  subj=""; [ -n "$d" ] && subj=$(git -C "$d" log -1 --format='%s' 2>/dev/null)
  echo "$name ${new:0:9} $subj" >> "$RESULTS/changed.txt"
done < "$RESULTS/changed_raw.txt"
echo "repos changed since the last run: $(wc -l < "$RESULTS/changed.txt")"; head -20 "$RESULTS/changed.txt"

# ------------------------------------------------------------------------------------------------------------------------------------------------------
# build
# ------------------------------------------------------------------------------------------------------------------------------------------------------
build_all() {
  cmake --build "$TREE/Build/$BSUB" --target xlion_compilers xLION_Headless xeditorcli -- -j"$(nproc)" > "$RESULTS/build.log" 2>&1 &
  local pid=$! n=0
  while kill -0 $pid 2>/dev/null; do                 # a line a minute, so the console shows it is alive (the full output is build.log)
    sleep 5; n=$((n + 5)); [ $((n % 60)) = 0 ] || continue
    echo "$(date +%T) build: $(grep -E '^\[[0-9]+/[0-9]+\]' "$RESULTS/build.log" | tail -1 | cut -c1-150)"
  done
  wait $pid; local rc=$?; tail -5 "$RESULTS/build.log"; return $rc
}
if ! stage_run "build" build_all; then
  echo "FAILED" > "$RESULTS/status.txt"
  grep -n -E "error:|FAILED:|Error " "$RESULTS/build.log" | head -20
  exit 1
fi

# ------------------------------------------------------------------------------------------------------------------------------------------------------
# python for the tests
# ------------------------------------------------------------------------------------------------------------------------------------------------------
make_venv() {
  [ -x "$BASE/venv/bin/python" ] || python3 -m venv "$BASE/venv" || return 1
  "$BASE/venv/bin/python" -c "import pytest, pytest_timeout" 2>/dev/null || "$BASE/venv/bin/pip" install -q pytest pytest-timeout || return 1
}
stage_run "python (pytest)" make_venv || { echo "FAILED" > "$RESULTS/status.txt"; exit 1; }

# ------------------------------------------------------------------------------------------------------------------------------------------------------
# let the resources compile: an editor on the project until the compile queue is empty, so the tests do not fight over it
# (a cold cache is the long case: every resource is compiled; a warm one is seconds)
# ------------------------------------------------------------------------------------------------------------------------------------------------------
PROJECT="$TREE/example.lionprj"
if [ "$SAN" = 1 ]; then
  mkdir -p "$RESULTS/sanitizer"; rm -f "$RESULTS/sanitizer"/*
  # one log file per process; the editor stops at the first AddressSanitizer error (that is the finding), UndefinedBehaviorSanitizer reports and goes on; no leak report: an editor that is
  # stopped is not asked to free everything
  export ASAN_OPTIONS="detect_leaks=0:halt_on_error=1:abort_on_error=0:symbolize=1:handle_segv=0:log_path=$RESULTS/sanitizer/asan"
  export UBSAN_OPTIONS="print_stacktrace=1:halt_on_error=0:symbolize=1:log_path=$RESULTS/sanitizer/ubsan"
fi
BIN="$TREE/Build/$BSUB"
PIPE="$BASE/pipe-$TIER.sock"
wait_compiles() {
  local log="$RESULTS/compile_wait.log"
  export XEDITOR_PIPE="$PIPE" XEDITOR_NO_ASSERT_DIALOG=1
  rm -f "$PIPE"
  "$BIN/xLION_Headless" "$PROJECT" > "$RESULTS/compile_editor.log" 2>&1 &
  local ed=$!
  local i
  for i in $(seq 1 180); do [ -S "$PIPE" ] && break; kill -0 $ed 2>/dev/null || { echo "the editor exited at startup" | tee -a "$log"; return 1; }; sleep 1; done
  local idle=0 polls=0 start; start=$(date +%s)
  while [ $(( $(date +%s) - start )) -lt 2700 ]; do          # at most 45 minutes
    local s; s=$(timeout 60 "$BIN/xeditorcli" CompileStatus 2>&1 | head -1)
    polls=$((polls + 1)); echo "$(date +%T) $s" | cut -c1-200 >> "$log"
    [ $((polls % 6)) = 1 ] && echo "$(date +%T) resources: $s" | cut -c1-200      # a line a minute on the console too
    if echo "$s" | grep -q "^Compiling=0 Waiting=0"; then idle=$((idle + 1)); else idle=0; fi
    [ $idle -ge 3 ] && break
    sleep 10
  done
  echo "compile queue idle after $(( $(date +%s) - start )) s ($polls polls)" | tee -a "$log"
  timeout 60 "$BIN/xeditorcli" Exit > /dev/null 2>&1
  for i in $(seq 1 120); do kill -0 $ed 2>/dev/null || break; sleep 1; done
  kill -9 $ed 2>/dev/null
  [ $idle -ge 3 ]
}
stage_run "resources compile" wait_compiles || echo "(the queue did not settle: the tests run anyway)"

# ------------------------------------------------------------------------------------------------------------------------------------------------------
# the tests
# ------------------------------------------------------------------------------------------------------------------------------------------------------
run_tests() {
  local smoke="$TREE/source/Editors/LevelEditor/smoke" files=() cap
  local desel=()
  if [ "$TIER" = fast ]; then
    while read -r line; do line="${line%%#*}"; line="$(echo "$line" | xargs)"; [ -n "$line" ] && files+=("$line"); done < "$HERE/fast_files.txt"
    # tests left out of the fast tier for now (a failure nobody has explained yet): one node id per line, '#' comments
    while read -r line; do line="${line%%#*}"; line="$(echo "$line" | xargs)"; [ -n "$line" ] && desel+=(--deselect "$line"); done < "$HERE/fast_deselect.txt"
    cap=1500
  else
    files=(.)           # the whole folder, named: pytest with no argument does not find this folder's pytest.ini and conftest.py ("unrecognized arguments: --exe")
    cap=7200
  fi
  rm -rf "$smoke/.logs"
  ( cd "$smoke" && \
    XEDITOR_PIPE="$PIPE" XLION_PROJECT="$PROJECT" XEDITOR_NO_ASSERT_DIALOG=1 XLION_TEST_TIMING_LOG="$RESULTS/timing.log" \
    timeout "$cap" "$BASE/venv/bin/python" -m pytest "${files[@]}" "${desel[@]}" -p no:cacheprovider --exe "$BIN/xLION_Headless" \
      --timeout=300 --timeout-method=thread -o junit_family=xunit2 -o junit_logging=all -o junit_log_passed_tests=false \
      --junitxml="$RESULTS/suite.xml" -rfE --tb=short -v )
  local rc=$?
  [ -f "$RESULTS/timing.tsv" ] || true
  return 0                                      # failing tests are the summary's business, not the run's
}
stage_run "tests ($TIER)" run_tests
exit 0
