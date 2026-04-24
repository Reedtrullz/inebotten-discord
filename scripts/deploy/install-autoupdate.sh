#!/usr/bin/env bash
set -euo pipefail

REPO="${INEBOTTEN_REPO:-/opt/inebotten-discord}"
BRANCH="${INEBOTTEN_BRANCH:-master}"
PORT="${WEBHOOK_PORT:-9000}"
SECRET="${WEBHOOK_SECRET:-$(openssl rand -hex 32)}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root, for example: sudo $0" >&2
  exit 1
fi

install -d /opt/inebotten-autoupdate
install -m 0755 "$SCRIPT_DIR/inebotten-update" /usr/local/sbin/inebotten-update
install -m 0755 "$SCRIPT_DIR/inebotten-webhook.py" /opt/inebotten-autoupdate/webhook.py

cat >/etc/inebotten-webhook.env <<EOF
WEBHOOK_SECRET=$SECRET
WEBHOOK_PORT=$PORT
WEBHOOK_BRANCH=refs/heads/$BRANCH
UPDATE_SERVICE=inebotten-update.service
INEBOTTEN_REPO=$REPO
INEBOTTEN_BRANCH=$BRANCH
EOF
chmod 600 /etc/inebotten-webhook.env

install -m 0644 "$SCRIPT_DIR/inebotten-update.service" /etc/systemd/system/inebotten-update.service
install -m 0644 "$SCRIPT_DIR/inebotten-update.timer" /etc/systemd/system/inebotten-update.timer
install -m 0644 "$SCRIPT_DIR/inebotten-webhook.service" /etc/systemd/system/inebotten-webhook.service

systemctl daemon-reload
systemd-analyze verify \
  /etc/systemd/system/inebotten-update.service \
  /etc/systemd/system/inebotten-update.timer \
  /etc/systemd/system/inebotten-webhook.service
systemctl enable --now inebotten-webhook.service
systemctl enable --now inebotten-update.timer

if command -v ufw >/dev/null && ufw status | grep -q '^Status: active'; then
  ufw allow "$PORT/tcp"
fi

echo "Auto-update installed."
echo "Webhook URL: http://<server-ip>:$PORT/github-webhook"
echo "Webhook secret: $SECRET"
