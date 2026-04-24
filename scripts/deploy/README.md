# Deploy-skript

Disse filene installerer VPS-flyten for Inebotten med auto-oppdatering.

Bruk fra et checkout på serveren:

```bash
cd /opt/inebotten-discord
sudo WEBHOOK_PORT=9000 ./scripts/deploy/install-autoupdate.sh
```

Installerte komponenter:

- `inebotten-update`: henter `origin/master`, hard-resetter checkouten, bygger Docker Compose på nytt og starter botten på nytt.
- `inebotten-webhook.py`: verifiserer GitHub-webhook-signaturer og starter oppdateringstjenesten ved push.
- `inebotten-update.service`: engangs systemd-jobb for oppdatering.
- `inebotten-update.timer`: fallback-timer som sjekker hvert 5. minutt.
- `inebotten-webhook.service`: langkjørende webhook-lytter.

Se `../../docs/VPS_DEPLOYMENT.md` for hele driftsguiden.
