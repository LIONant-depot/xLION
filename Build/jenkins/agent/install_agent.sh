#!/usr/bin/env bash
# Runs the Jenkins agent of the CI VM as a systemd service under the low-privilege user "jenkins-agent", so that builds do not run on the Jenkins server's own
# (built-in) node: a build runs project scripts, and on the built-in node that is the same account, files and credentials as Jenkins itself.
#
# 1. In Jenkins (an administrator): Manage Jenkins > Nodes > New Node, name "linux-vm", type Permanent Agent. Number of executors 1 (the two jobs share one tree),
#    Remote root directory /var/lib/jenkins-agent/agent, Labels "linux", Usage "Only build jobs with label expressions matching this node",
#    Launch method "Launch agent by connecting it to the controller" (with WebSocket). Save; the node page shows the secret.
# 2. Here, as root:   sudo bash Build/jenkins/agent/install_agent.sh linux-vm <secret> [jenkins url] [tcp]
#    By default the agent connects over WebSocket (the node's page has "Use WebSocket" ticked). When the node form has no such option, use "tcp" as the last
#    argument: the agent then connects to the controller's TCP port for inbound agents, which is off until you set it: Manage Jenkins > Security > Agents >
#    TCP port for inbound agents > Fixed, 50000 (the firewall of the VM denies incoming traffic by default, so that port is only reachable from this machine).
# 3. In Jenkins: Manage Jenkins > Nodes > Built-In Node > Configure: Number of executors 0 (nothing builds on the server any more).
#
# The secret is kept in /etc/xlion-jenkins-agent.secret (root and jenkins-agent only). The agent connects out to the controller on the same machine; no port is opened.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }
NAME="${1:?usage: install_agent.sh <node name> <secret> [jenkins url] [tcp]}"
SECRET="${2:?usage: install_agent.sh <node name> <secret> [jenkins url] [tcp]}"
URL="${3:-http://127.0.0.1:8080/jenkin/}"
WS="-webSocket"; [ "${4:-}" = tcp ] && WS=""
USER_=jenkins-agent
HOME_=$(getent passwd "$USER_" | cut -d: -f6)
[ -n "$HOME_" ] || { echo "no user $USER_ on this machine"; exit 1; }
DIR="$HOME_/agent"

install -d -o "$USER_" -g "$USER_" "$DIR"
curl -fsS -o "$DIR/agent.jar" "${URL%/}/jnlpJars/agent.jar"
chown "$USER_:$USER_" "$DIR/agent.jar"

umask 077
printf '%s' "$SECRET" > /etc/xlion-jenkins-agent.secret
chown root:"$USER_" /etc/xlion-jenkins-agent.secret
chmod 0640 /etc/xlion-jenkins-agent.secret

cat > /etc/systemd/system/xlion-jenkins-agent.service <<EOF
[Unit]
Description=Jenkins agent "$NAME" for the xLION CI (runs as $USER_)
After=network-online.target jenkins.service
Wants=network-online.target

[Service]
User=$USER_
WorkingDirectory=$DIR
ExecStart=/usr/bin/java -jar $DIR/agent.jar -url $URL -name $NAME -secret @/etc/xlion-jenkins-agent.secret -workDir $DIR $WS
Restart=always
RestartSec=10
# nothing here may write outside the agent's own home
ProtectSystem=full
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now xlion-jenkins-agent
sleep 5
systemctl --no-pager --lines=5 status xlion-jenkins-agent || true
echo "Done. In Jenkins the node '$NAME' should show as connected; then set the executors of the Built-In Node to 0."
