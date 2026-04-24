# Deployment Scripts

These files install Inebotten's VPS auto-update flow.

Use from a server checkout:

```bash
cd /opt/inebotten-discord
sudo WEBHOOK_PORT=9000 ./scripts/deploy/install-autoupdate.sh
```

Installed components:

- `inebotten-update`: fetches `origin/master`, hard-resets the checkout, rebuilds Docker Compose, and restarts the bot.
- `inebotten-webhook.py`: verifies GitHub webhook signatures and starts the update service on push.
- `inebotten-update.service`: one-shot systemd update job.
- `inebotten-update.timer`: 5-minute fallback polling timer.
- `inebotten-webhook.service`: long-running webhook listener.

See `../../docs/VPS_DEPLOYMENT.md` for the full operational guide.
