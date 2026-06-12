#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${INEBOTTEN_WEBHOOK_ENV:-/etc/inebotten-webhook.env}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root, for example: sudo $0" >&2
  exit 1
fi

existing_env_value() {
  local key="$1"
  if [ -f "$ENV_FILE" ]; then
    grep -E "^${key}=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- || true
  fi
}

REPO="${INEBOTTEN_REPO:-$(existing_env_value INEBOTTEN_REPO)}"
REPO="${REPO:-/opt/inebotten-discord}"
BRANCH="${INEBOTTEN_BRANCH:-$(existing_env_value INEBOTTEN_BRANCH)}"
BRANCH="${BRANCH:-master}"
PORT="${WEBHOOK_PORT:-$(existing_env_value WEBHOOK_PORT)}"
PORT="${PORT:-9000}"
SECRET="${WEBHOOK_SECRET:-$(existing_env_value WEBHOOK_SECRET)}"
SECRET="${SECRET:-$(openssl rand -hex 32)}"

install -d /opt/inebotten-autoupdate
install -m 0755 "$SCRIPT_DIR/inebotten-update" /usr/local/sbin/inebotten-update
install -m 0755 "$SCRIPT_DIR/inebotten-webhook.py" /opt/inebotten-autoupdate/webhook.py

cat >"$ENV_FILE" <<EOF
WEBHOOK_SECRET=$SECRET
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=$PORT
WEBHOOK_BRANCH=refs/heads/$BRANCH
UPDATE_SERVICE=inebotten-update.service
INEBOTTEN_REPO=$REPO
INEBOTTEN_BRANCH=$BRANCH
EOF
chmod 600 "$ENV_FILE"

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
systemctl restart inebotten-webhook.service
systemctl restart inebotten-update.timer

if command -v ufw >/dev/null && ufw status | grep -q '^Status: active'; then
  ufw allow "$PORT/tcp"
fi

echo "Auto-update installed."
echo "Webhook URL: http://<server-ip>:$PORT/github-webhook"
echo "Webhook secret: $SECRET"
