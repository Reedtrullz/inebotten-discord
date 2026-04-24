# Deploy-skript

Denne mappen inneholder skript for drift på VPS.

## Auto-oppdatering

`install-autoupdate.sh` installerer:

- systemd-service for GitHub-webhook.
- systemd-timer som fallback hvis webhook feiler.
- loggfil for oppdateringer.

Kjør fra repoet på serveren:

```bash
sudo WEBHOOK_PORT=9000 ./scripts/deploy/install-autoupdate.sh
```

Se [docs/VPS_DEPLOYMENT.md](../../docs/VPS_DEPLOYMENT.md) for komplett oppsett.
