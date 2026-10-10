#!/usr/bin/env bash
# watch.sh: run a command with a heartbeat and a stall watchdog (sourced by ci_run.sh; test_watch.sh checks it).
#
#   watched <stall_seconds> <name> <command...>     returns the command's status, or 124 when it stalled (and was killed)
#
# A line every minute: stage, elapsed, seconds without activity, load, free memory and swap, the biggest process, and the last line of $WATCH_TAIL (a log file, when set).
# ACTIVITY is any of: the command (or a child of it) wrote a line, the command's process tree used CPU (>= 1 s in the interval), a file named in $WATCH_FILES changed in the interval.
# No activity for <stall_seconds> (CI: 300) = a stall: the process tree, and where each process is waiting, is printed, the tree is killed and "STALLED" is reported.
# $WATCH_INTERVAL (seconds, default 60) exists so the self-check does not take minutes.

tree_pids() { local c; echo "$1"; for c in $(pgrep -P "$1" 2>/dev/null); do tree_pids "$c"; done; }

# CPU ticks used by a process tree: every live process once (its own time plus the time of the children it already waited for)
tree_cpu() {
  local total=0 p s
  for p in $(tree_pids "$1"); do
    s=$(awk '{ print $14 + $15 + $16 + $17 }' "/proc/$p/stat" 2>/dev/null) || continue
    total=$((total + ${s:-0}))
  done
  echo "$total"
}

heartbeat_line() {            # heartbeat_line <name> <elapsed s> <idle s> <root pid>
  local load mem swap top tail=""
  load=$(cut -d' ' -f1 /proc/loadavg)
  mem=$(awk '/MemAvailable/ { printf "%d", $2 / 1024 }' /proc/meminfo)
  swap=$(awk '/SwapTotal/ { t = $2 } /SwapFree/ { f = $2 } END { if (t > 0) printf "%d", (t - f) * 100 / t; else print 0 }' /proc/meminfo)
  top=$(ps -eo rss=,comm= --sort=-rss 2>/dev/null | head -1 | awk '{ printf "%s %dMB", $2, $1 / 1024 }')
  [ -n "${WATCH_TAIL:-}" ] && [ -f "$WATCH_TAIL" ] && tail=" | $(tail -n 1 "$WATCH_TAIL" | cut -c1-110)"
  printf '%s [heartbeat] %s %02d:%02d idle %ds load %s mem-free %sMB swap %s%% top %s%s\n' "$(date +%T)" "$1" $(($2 / 60)) $(($2 % 60)) "$3" "$load" "$mem" "$swap" "$top" "$tail"
}

stall_report() {              # what was hanging, for the person reading the log
  local p
  echo "=== STALLED: no output and no CPU use; the process tree:"
  ps -o pid,ppid,etime,pcpu,rss,stat,wchan:20,args -p "$(tree_pids "$1" | paste -sd, -)" 2>/dev/null | cut -c1-200
  if command -v gdb > /dev/null; then          # where the busiest-looking leaf is: its stack (a hang is usually a lock or a wait)
    for p in $(tree_pids "$1" | tail -n 3); do echo "--- stack of $p"; timeout 30 gdb -p "$p" -batch -ex "thread apply all bt 12" 2>/dev/null | grep -E "^#|^Thread" | head -40; done
  fi
}

watched() {
  local stall="$1" name="$2"; shift 2
  local interval="${WATCH_INTERVAL:-60}"
  local act rcf mark; act=$(mktemp); rcf=$(mktemp); mark=$(mktemp)
  local start; start=$(date +%s)
  { "$@" 2>&1 | while IFS= read -r line; do printf '%s\n' "$line"; : > "$act"; done; echo "${PIPESTATUS[0]}" > "$rcf"; } &
  local pid=$! cpu0 cpu1 last_active=$start now idle=0 stalled=0
  cpu0=$(tree_cpu "$pid")
  while kill -0 "$pid" 2>/dev/null; do
    local i=0; while [ $i -lt "$interval" ] && kill -0 "$pid" 2>/dev/null; do sleep 1; i=$((i + 1)); done
    kill -0 "$pid" 2>/dev/null || break
    now=$(date +%s)
    cpu1=$(tree_cpu "$pid")
    if [ $((cpu1 - cpu0)) -ge 100 ]; then last_active=$now; fi                                   # 100 ticks = 1 s of CPU
    cpu0=$cpu1
    if [ "$act" -nt "$mark" ]; then last_active=$now; fi                                          # a line was written
    if [ -n "${WATCH_FILES:-}" ] && [ -n "$(find $WATCH_FILES -newer "$mark" 2>/dev/null | head -1)" ]; then last_active=$now; fi
    : > "$mark"
    idle=$((now - last_active))
    heartbeat_line "$name" $((now - start)) "$idle" "$pid" >&2
    if [ "$idle" -ge "$stall" ]; then
      stalled=1
      stall_report "$pid" >&2
      local p; for p in $(tree_pids "$pid" | tac); do kill -9 "$p" 2>/dev/null; done
      break
    fi
  done
  wait "$pid" 2>/dev/null
  local rc=0; [ -s "$rcf" ] && rc=$(cat "$rcf")
  rm -f "$act" "$rcf" "$mark"
  if [ "$stalled" = 1 ]; then echo "=== $name STALLED after ${idle}s without output or CPU: killed" >&2; return 124; fi
  return "$rc"
}
