#!/usr/bin/env bash
# MANUAL sanitizer run on the CI machine (a tree built by hand with Build/CreateProject.sh --sanitize --build in ~/xlion-san/tree): compile wait, the fast tier, the report. The Jenkins job (Build/ci/ci_run.sh --sanitize) does the same, with the lock.
set -u
BASE=$HOME/xlion-san
TREE=$BASE/tree
RES=$BASE/results
BIN=$TREE/Build/xLION.linux-san
PROJECT=$TREE/example.lionprj
PIPE=$BASE/pipe-san.sock
rm -rf "$RES"; mkdir -p "$RES/sanitizer"
export ASAN_OPTIONS="detect_leaks=0:halt_on_error=0:abort_on_error=0:symbolize=1:handle_segv=0:log_path=$RES/sanitizer/asan"
export UBSAN_OPTIONS="print_stacktrace=1:halt_on_error=0:symbolize=1:log_path=$RES/sanitizer/ubsan"
export XEDITOR_PIPE="$PIPE" XEDITOR_NO_ASSERT_DIALOG=1

[ -x "$BASE/venv/bin/python" ] || python3 -m venv "$BASE/venv"
"$BASE/venv/bin/python" -c "import pytest, pytest_timeout" 2>/dev/null || "$BASE/venv/bin/pip" install -q pytest pytest-timeout

echo "== resources compile $(date +%T)"
rm -f "$PIPE"
"$BIN/xLION_Headless" "$PROJECT" > "$RES/compile_editor.log" 2>&1 &
ed=$!
for i in $(seq 1 600); do [ -S "$PIPE" ] && break; kill -0 $ed 2>/dev/null || { echo "the editor exited at startup"; tail -5 "$RES/compile_editor.log"; break; }; sleep 1; done
idle=0; start=$(date +%s)
while [ $(( $(date +%s) - start )) -lt 5400 ]; do
  s=$(timeout 120 "$BIN/xeditorcli" CompileStatus 2>&1 | head -1)
  echo "$(date +%T) $s" | cut -c1-160 >> "$RES/compile_wait.log"
  if echo "$s" | grep -q "^Compiling=0 Waiting=0"; then idle=$((idle + 1)); else idle=0; fi
  [ $idle -ge 3 ] && break
  sleep 15
done
timeout 120 "$BIN/xeditorcli" Exit > /dev/null 2>&1
for i in $(seq 1 120); do kill -0 $ed 2>/dev/null || break; sleep 1; done; kill -9 $ed 2>/dev/null
echo "compile done after $(( $(date +%s) - start )) s"

echo "== tests $(date +%T)"
files=(); while read -r line; do line="${line%%#*}"; line="$(echo "$line" | xargs)"; [ -n "$line" ] && files+=("$line"); done < "$TREE/Build/ci/fast_files.txt"
desel=(); while read -r line; do line="${line%%#*}"; line="$(echo "$line" | xargs)"; [ -n "$line" ] && desel+=(--deselect "$line"); done < "$TREE/Build/ci/fast_deselect.txt"
cd "$TREE/source/Editors/LevelEditor/smoke" && rm -rf .logs
XLION_PROJECT="$PROJECT" timeout 5400 "$BASE/venv/bin/python" -m pytest "${files[@]}" "${desel[@]}" -p no:cacheprovider --exe "$BIN/xLION_Headless" --timeout=600 --timeout-method=thread -q --tb=no -rfE -o junit_family=xunit2 --junitxml="$RES/suite.xml" > "$RES/pytest.log" 2>&1
tail -3 "$RES/pytest.log"
python3 "$TREE/Build/ci/sanitize_report.py" --logs "$RES/sanitizer" --out "$RES" --baseline "$TREE/Build/ci/sanitizer_baseline.txt"
echo "== done $(date +%T)"
