# VPS Deployment and Auto-Update

This guide documents the production-style VPS setup for Inebotten using Docker Compose, systemd, and a GitHub webhook.

The intended flow is:

1. GitHub receives a push to `master`.
2. GitHub calls the VPS webhook.
3. The VPS runs `inebotten-update.service`.
4. The update service fetches `origin/master`, hard-resets the checkout, rebuilds Docker, and restarts the container.
5. A 5-minute systemd timer also checks GitHub as a fallback.

## Server Layout

Recommended paths:

```bash
/opt/inebotten-discord          # Git checkout
/opt/inebotten-autoupdate       # Webhook listener
/usr/local/sbin/inebotten-update
/etc/inebotten-webhook.env      # Webhook secret and settings
/var/log/inebotten-autoupdate.log
```

Runtime data should stay outside Git:

```bash
/opt/inebotten-discord/.env
/opt/inebotten-discord/data/
```

## Initial VPS Setup

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-plugin python3 openssl

sudo git clone https://github.com/Reedtrullz/inebotten-discord.git /opt/inebotten-discord
cd /opt/inebotten-discord
sudo cp .env.example .env
sudo nano .env

sudo docker compose up -d --build
```

Verify:

```bash
sudo docker compose ps
sudo docker logs -f inebotten-bot
```

## Install Auto-Update

From the repo checkout on the server:

```bash
cd /opt/inebotten-discord
sudo WEBHOOK_PORT=9000 ./scripts/deploy/install-autoupdate.sh
```

The installer prints:

```text
Webhook URL: http://<server-ip>:9000/github-webhook
Webhook secret: <generated-secret>
```

Keep the secret private. It is stored on the server in `/etc/inebotten-webhook.env`.

## GitHub Webhook

In GitHub:

1. Open `Settings -> Webhooks -> Add webhook`.
2. Set **Payload URL** to `http://<server-ip>:9000/github-webhook`.
3. Set **Content type** to `application/json`.
4. Set **Secret** to the generated secret from the installer.
5. Select **Just the push event**.
6. Enable **Active**.

GitHub should receive `pong` for the ping event. Pushes to `master` should receive `202 update queued`.

## Operations

Check services:

```bash
sudo systemctl status inebotten-webhook.service --no-pager
sudo systemctl status inebotten-update.timer --no-pager
sudo systemctl list-timers inebotten-update.timer --no-pager
```

Run an update manually:

```bash
sudo systemctl start inebotten-update.service
```

Read updater logs:

```bash
sudo tail -f /var/log/inebotten-autoupdate.log
```

Check webhook health:

```bash
curl http://127.0.0.1:9000/health
```

Restart the bot:

```bash
cd /opt/inebotten-discord
sudo docker compose up -d --build
```

## Security Notes

- Do not commit `.env`, Discord tokens, webhook secrets, or `data/`.
- Use the GitHub webhook secret. Unsigned webhook calls are rejected.
- The update service intentionally uses `git reset --hard origin/master`; do not keep manual code edits on the VPS.
- Keep persistent runtime data in `data/`, which is mounted into the Docker container.
- If a firewall is active, open only the webhook port you need, usually `9000/tcp`.

## Troubleshooting

| Problem | Check |
|---------|-------|
| GitHub webhook returns 403 | Secret mismatch or missing `X-Hub-Signature-256` |
| GitHub webhook times out | Firewall, port, or `inebotten-webhook.service` |
| Push does not deploy | `sudo journalctl -u inebotten-webhook.service -n 100 --no-pager` |
| Timer does not run | `sudo systemctl list-timers inebotten-update.timer --no-pager` |
| Docker rebuild fails | `sudo tail -100 /var/log/inebotten-autoupdate.log` |
| Bot starts then exits | `sudo docker logs --tail=200 inebotten-bot` |
