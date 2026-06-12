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

Hvis Discord-statusen viser en gammel commit selv om repoet er oppdatert, kan
den installerte `/usr/local/sbin/inebotten-update` være gammel eller en tidligere
Docker-rebuild kan ha feilet etter `git reset`. Oppdater installert updater og
start jobben manuelt:

```bash
cd /opt/inebotten-discord
git fetch origin master
git reset --hard origin/master
sudo install -m 0755 scripts/deploy/inebotten-update /usr/local/sbin/inebotten-update
sudo systemctl start inebotten-update.service
sudo tail -100 /var/log/inebotten-autoupdate.log
```
