# VPS-oppsett og auto-oppdatering

Denne guiden dokumenterer VPS-oppsettet for Inebotten med Docker Compose, systemd og en GitHub-webhook.

Flyten er slik:

1. GitHub mottar en push til `master`.
2. GitHub kaller webhooken på VPS-en.
3. VPS-en kjører `inebotten-update.service`.
4. Oppdateringstjenesten henter `origin/master`, hard-resetter checkouten, bygger Docker på nytt og starter containeren på nytt.
5. En systemd-timer på 5 minutter sjekker også GitHub som fallback.

## Serveroppsett

Anbefalte stier:

```bash
/opt/inebotten-discord          # Git-checkout
/opt/inebotten-autoupdate       # Webhook-lytter
/usr/local/sbin/inebotten-update
/etc/inebotten-webhook.env      # Webhook-secret og innstillinger
/var/log/inebotten-autoupdate.log
```

Kjøringsdata skal ligge utenfor Git:

```bash
/opt/inebotten-discord/.env
/opt/inebotten-discord/data/
```

## Første Oppsett

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-plugin python3 python3-pip python3-full openssl

# Sett opp eierskap (viktig for setup.py)
sudo git clone https://github.com/Reedtrullz/inebotten-discord.git /opt/inebotten-discord
sudo chown -R $USER:$USER /opt/inebotten-discord
cd /opt/inebotten-discord

# Installer avhengigheter (bruk --break-system-packages hvis ikke i venv)
pip install --break-system-packages -r requirements.txt

# Kjør setup wizard
python3 setup.py

# Start med Docker
sudo docker compose up -d --build
```

Verifiser:

```bash
sudo docker compose ps
sudo docker logs -f inebotten-bot
```

Web console er tilgjengelig på det konfigurerte domenet (f.eks. `https://bot.reidar.tech`). API-nøkkelen skrives til Docker-loggen ved oppstart.

## Installer Auto-Update

Fra repo-checkoutet på serveren:

```bash
cd /opt/inebotten-discord
sudo WEBHOOK_PORT=9000 ./scripts/deploy/install-autoupdate.sh
```

Installasjonsskriptet skriver ut:

```text
Webhook URL: http://<server-ip>:9000/github-webhook
Webhook secret: <generated-secret>
```

Hold secreten privat. Den lagres på serveren i `/etc/inebotten-webhook.env`.

## GitHub-webhook

I GitHub:

1. Åpne `Settings -> Webhooks -> Add webhook`.
2. Sett **Payload URL** til `http://<server-ip>:9000/github-webhook`.
3. Sett **Content type** til `application/json`.
4. Sett **Secret** til hemmeligheten fra installasjonsskriptet.
5. Velg **Just the push event**.
6. Slå på **Active**.

GitHub skal få `pong` for ping-eventen. Push til `master` skal få `202 update queued`.

## Drift

Sjekk tjenester:

```bash
sudo systemctl status inebotten-webhook.service --no-pager
sudo systemctl status inebotten-update.timer --no-pager
sudo systemctl list-timers inebotten-update.timer --no-pager
```

Kjør en oppdatering manuelt:

```bash
sudo systemctl start inebotten-update.service
```

Les oppdateringsloggen:

```bash
sudo tail -f /var/log/inebotten-autoupdate.log
```

Sjekk webhook-helsen:

```bash
curl http://127.0.0.1:9000/health
```

Start botten på nytt:

```bash
cd /opt/inebotten-discord
sudo docker compose up -d --build
```

## Sikkerhetsnotater

- Ikke commit `.env`, Discord-tokens, webhook-secrets eller `data/`.
- Bruk GitHub-webhook-secret. Usignerte webhook-kall blir avvist.
- Oppdateringstjenesten bruker med vilje `git reset --hard origin/master`; ikke behold manuelle kodeendringer på VPS-en.
- Behold varige kjøringsdata i `data/`, som mountes inn i Docker-containeren.
- Hvis en brannmur er aktiv, åpne bare webhook-porten du trenger, vanligvis `9000/tcp`.

## Feilsøking

| Problem | Sjekk |
|---------|-------|
| GitHub-webhooken returnerer 403 | Secret matcher ikke, eller `X-Hub-Signature-256` mangler |
| GitHub-webhooken timeouter | Brannmur, port eller `inebotten-webhook.service` |
| Push deployer ikke | `sudo journalctl -u inebotten-webhook.service -n 100 --no-pager` |
| Timeren kjører ikke | `sudo systemctl list-timers inebotten-update.timer --no-pager` |
| Docker-bygg feiler | `sudo tail -100 /var/log/inebotten-autoupdate.log` |
| Botten starter og avslutter | `sudo docker logs --tail=200 inebotten-bot` |
