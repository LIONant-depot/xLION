#!/usr/bin/env bash
# The shared ccache of the CI machines (see ccache_server.py).
#
#   sudo bash setup_ccache_remote.sh server <this machine's ip> <ip that may use it> [<more ips>...]
#       installs the cache server as a systemd service (user ccache-remote, folder /var/lib/ccache-remote, 8 GB, port 8089) and opens the port to those ips only
#   sudo bash setup_ccache_remote.sh client <server ip>
#       tells ccache of the jenkins-agent user to use that server besides its own folder (xlion-ci/ccache/ccache.conf: remote_storage, and hash_dir = false so the name of the build
#       folder is not part of the key: the three machines compile with the same compiler, flags and paths, so a file compiled on one is a hit on the others)
# Safe to run again.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=8089
mode="${1:?usage: setup_ccache_remote.sh server <my ip> <allowed ip>... | client <server ip>}"
shift

if [ "$mode" = server ]; then
  me="${1:?my ip}"; shift
  id ccache-remote > /dev/null 2>&1 || useradd --system --home-dir /var/lib/ccache-remote --shell /usr/sbin/nologin ccache-remote
  install -d -o ccache-remote -g ccache-remote /var/lib/ccache-remote /opt/ccache-remote
  install -m 0755 "$HERE/ccache_server.py" /opt/ccache-remote/ccache_server.py
  cat > /etc/systemd/system/ccache-remote.service <<EOF
[Unit]
Description=Shared ccache storage of the xLION CI machines
After=network-online.target

[Service]
User=ccache-remote
ExecStart=/usr/bin/python3 /opt/ccache-remote/ccache_server.py --dir /var/lib/ccache-remote --listen $me --port $PORT --max-gb 8
Restart=always
RestartSec=5
Nice=10
ProtectSystem=full
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now ccache-remote
  systemctl restart ccache-remote
  for ip in "$@"; do ufw allow from "$ip" to any port $PORT proto tcp comment "ccache remote" > /dev/null; done
  sleep 2; systemctl is-active ccache-remote; ss -ltn | grep ":$PORT" || true
  exit 0
fi

if [ "$mode" = client ]; then
  server="${1:?server ip}"
  conf=/var/lib/jenkins-agent/xlion-ci/ccache
  install -d -o jenkins-agent -g jenkins-agent /var/lib/jenkins-agent/xlion-ci "$conf"
  # the local folder keeps its own settings (size, compression): only these lines are ours
  touch "$conf/ccache.conf"
  sed -i '/^remote_storage *=/d; /^hash_dir *=/d' "$conf/ccache.conf"
  printf 'remote_storage = http://%s:%s|connect-timeout=2000|operation-timeout=10000\nhash_dir = false\n' "$server" "$PORT" >> "$conf/ccache.conf"
  chown jenkins-agent:jenkins-agent "$conf/ccache.conf"
  cat "$conf/ccache.conf"
  exit 0
fi
echo "unknown mode $mode"; exit 2
