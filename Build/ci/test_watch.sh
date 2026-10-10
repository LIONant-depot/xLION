#!/usr/bin/env bash
# Self-check of watch.sh (a few seconds): a hang is killed, a busy command and a talking command are not, the exit status comes through.
#   bash Build/ci/test_watch.sh
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/watch.sh"
export WATCH_INTERVAL=2
fail=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: got $2, wanted $3"; fail=1; fi; }

watched 6 hang bash -c 'sleep 600' > /dev/null 2>&1;                                         check "a command that sleeps is stalled" $? 124
watched 6 busy bash -c 'end=$((SECONDS + 9)); while [ $SECONDS -lt $end ]; do :; done' > /dev/null 2>&1; check "a command that computes is left alone" $? 0
watched 6 talk bash -c 'for i in 1 2 3 4 5 6; do echo line $i; sleep 2; done' > /dev/null 2>&1;   check "a command that prints is left alone" $? 0
watched 6 fails bash -c 'echo x; exit 7' > /dev/null 2>&1;                                  check "the exit status comes through" $? 7
sleep 1; check "the hung process is gone" "$(pgrep -f 'sleep 600' | wc -l)" 0
exit $fail
