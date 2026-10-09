#!/usr/bin/env bash
# Which repos of a CI tree have a newer commit on GitHub than the one checked out.
#
#   bash Build/ci/changed_repos.sh <tree>      prints one line per changed repo: "<name> <local sha> <remote sha>"
#
# <tree> is the xLION checkout that Build/CreateProject.sh built. Every repo in it that follows a branch (our own repos: main) is compared with
# `git ls-remote` (no clone, about 15 seconds for all of them, run 8 at a time); the third party repos sit on a pinned commit (detached HEAD) and are skipped.
# Exit status: 0 = compared (the list may be empty), 2 = there is no tree yet (a build is needed).
set -u
TREE="${1:?usage: changed_repos.sh <tree>}"
[ -d "$TREE/.git" ] || exit 2

check_one() {
  d="$1"
  [ -L "${d%/}" ] && return 0
  [ -d "$d/.git" ] || return 0
  branch=$(git -C "$d" symbolic-ref -q --short HEAD) || return 0       # detached: pinned, not followed
  remote=$(timeout 40 git -C "$d" ls-remote origin "refs/heads/$branch" 2>/dev/null | cut -f1)
  [ -n "$remote" ] || return 0                                          # network trouble: say nothing rather than a false change
  local_sha=$(git -C "$d" rev-parse HEAD 2>/dev/null)
  [ "$local_sha" = "$remote" ] || echo "$(basename "${d%/}") $local_sha $remote"
}
export -f check_one

{
  echo "$TREE"
  echo "$TREE/example.lionprj"
  ls -d "$TREE"/example.lionprj/Cache/dependencies/*/ "$TREE"/example.lionprj/Cache/Plugins/*/ 2>/dev/null
} | xargs -P 8 -I{} bash -c 'check_one "{}"' | sort
exit 0
