#!/usr/bin/env bash
# Makes a fresh Ubuntu VM a CI node like team39: the build tools, 6 GB of swap, the low-privilege user "jenkins-agent", and the Jenkins agent as a systemd service.
#
# 1. In Jenkins (an administrator): Manage Jenkins > Nodes > New Node: a name (team38, team37, ...), Permanent Agent, executors 1 (a sanitized build needs ~3 GB per compile: 1 per 4 GB of RAM),
#    Remote root directory /var/lib/jenkins-agent/agent, Labels "linux" (and "big-ram" on a machine with 8 GB or more), Usage "Only build jobs with label expressions matching this node",
#    Launch method "Launch agent by connecting it to the controller". Save: the node page shows the secret.
# 2. On the new VM, as root (put the secret in a file so it does not show in the command line):
#       printf '%s' '<secret>' > /root/node.secret
#       sudo bash setup_ci_node.sh <node name> @/root/node.secret [jenkins url]
#    The default url is the public one (https://team39.dp-ext8.com/jenkin/); the agent connects over WebSocket. If that is refused (the proxy in front of Jenkins must pass WebSockets),
#    add "tcp" as the last argument and open the controller's TCP port for inbound agents (Manage Jenkins > Security > Agents > fixed 50000, firewall allowing it from this VM).
#    With "-" as the secret only the machine is prepared (tools, swap, user) and no agent is installed; run again with the real secret when the node exists in Jenkins.
# 3. The node should show as connected. Nothing else is needed: the jobs build in the agent's own home, $HOME/xlion-ci.
#
# Safe to run again (every step checks what is already there).
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }
NAME="${1:?usage: setup_ci_node.sh <node name> <secret or @file> [jenkins url] [tcp]}"
SECRET="${2:?usage: setup_ci_node.sh <node name> <secret or @file> [jenkins url] [tcp]}"
URL="${3:-https://team39.dp-ext8.com/jenkin/}"
MODE="${4:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SWAP_GB="${SWAP_GB:-6}"

echo "== packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
# the list of Build/CreateProject.sh (PACKAGES), plus what the CI itself uses: Java for the agent, ccache, a Python with venv for pytest, gdb for the stack dumps of the stall watchdog
apt-get install -y -q build-essential git cmake ninja-build pkg-config python3 python3-venv clang-20 lld-20 libomp-20-dev libvulkan-dev glslc libshaderc-dev \
  libx11-dev libxrandr2 libxcursor1 zenity xdg-utils openjdk-21-jre-headless ccache gdb curl ca-certificates

echo "== swap (a sanitized compile needs about 3 GB; at least ${SWAP_GB} GB in total)"
have_kb=$(awk '/SwapTotal/ { print $2 }' /proc/meminfo)
need_kb=$((SWAP_GB * 1024 * 1024))
if [ "$have_kb" -lt "$need_kb" ]; then
  add_gb=$(( (need_kb - have_kb + 1024 * 1024 - 1) / (1024 * 1024) ))
  f=/swapfile-ci
  if [ ! -e "$f" ]; then
    fallocate -l "${add_gb}G" "$f" 2>/dev/null || dd if=/dev/zero of="$f" bs=1M count=$((add_gb * 1024)) status=none
    chmod 600 "$f"; mkswap "$f" > /dev/null
  fi
  swapon "$f" 2>/dev/null || true
  grep -q "^$f " /etc/fstab || echo "$f none swap sw 0 0" >> /etc/fstab
fi
swapon --show

echo "== the user jenkins-agent (no sudo, no password)"
id jenkins-agent > /dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/jenkins-agent --shell /bin/bash jenkins-agent
install -d -o jenkins-agent -g jenkins-agent /var/lib/jenkins-agent/xlion-ci

echo "== the agent service"
if [ "$SECRET" = "-" ]; then echo "(no secret given: the machine is prepared, the agent is not installed)"; else bash "$HERE/install_agent.sh" "$NAME" "$SECRET" "$URL" $([ "$MODE" = tcp ] && echo tcp); fi

echo
echo "Done: $(nproc) cores, $(awk '/MemTotal/ { printf "%d", $2 / 1024 }' /proc/meminfo) MB RAM, $(df -h --output=avail / | tail -1 | tr -d ' ') free."
echo "In Jenkins the node '$NAME' should show as connected. Labels and executors are set on its page (see the top of this file)."
