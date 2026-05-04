# VPS Deployment (Multi-App Shared VPS)

This guide documents the production deployment of Inebotten on a shared VPS with a central Caddy reverse proxy, using GitHub Actions + GHCR for image publishing.

## Architecture Overview

Inebotten no longer owns public ports 80/443 in production. A central VPS-level Caddy instance handles all domain routing and HTTPS certificates for all apps on the VPS.

- Inebotten runs as an app-only Docker container listening on `127.0.0.1:8080`
- Central Caddy proxies `bot.reidar.tech` to the local Inebotten container
- Public ports 80/443 are owned exclusively by the central Caddy instance

## Prerequisites

- Shared VPS with central Caddy reverse proxy installed
- Docker and Docker Compose installed on the VPS
- Ansible (optional, for automated deployments)
- GitHub Container Registry (GHCR) access for the repo

## Central Caddy Configuration

Add this block to your central Caddy configuration (managed via Ansible or manually):

```caddyfile
bot.reidar.tech {
    reverse_proxy 127.0.0.1:8080

    header {
        X-Frame-Options "DENY"
        X-Content-Type-Options "nosniff"
        Referrer-Policy "strict-origin-when-cross-origin"
    }
}
```

This proxies all traffic for `bot.reidar.tech` to the Inebotten container running on localhost port 8080.

## Recommended Deployment Flow

1. **Code Push**: Push changes to the `master` branch
2. **CI**: GitHub Actions runs tests via the existing `ci.yml` workflow
3. **Image Publish**: On CI success, `docker-publish.yml` workflow builds and pushes the Docker image to `ghcr.io/reedtrullz/inebotten-discord` with tags:
   - Full commit SHA
   - `latest` (for master branch only)
4. **Ansible Deployment**: Ansible updates the VPS deployment:
   - Pulls latest code/config to `/opt/apps/inebotten-discord`
   - Runs `docker compose -f compose.production.yml pull` to fetch the new image
   - Runs `docker compose -f compose.production.yml up -d` to restart the container
5. **HTTPS Serving**: Central Caddy automatically serves the updated app via HTTPS

## Manual Deployment (Without Ansible)

### First-Time Setup

```bash
# Create app directory
sudo mkdir -p /opt/apps/inebotten-discord
sudo chown $USER:$USER /opt/apps/inebotten-discord
cd /opt/apps/inebotten-discord

# Clone the repository
git clone https://github.com/Reedtrullz/inebotten-discord.git .

# Create environment file (fill in your secrets)
cp .env.example .env
nano .env  # Add DISCORD_TOKEN, CONSOLE_API_KEY, etc.

# Pull the latest image from GHCR
docker compose -f compose.production.yml pull

# Start the container
docker compose -f compose.production.yml up -d
```

### Verify Deployment

```bash
# Check container status
docker compose -f compose.production.yml ps

# View logs
docker logs -f inebotten-bot

# Health check (from VPS)
curl http://127.0.0.1:8080/health
```

### Update to Latest Image

```bash
cd /opt/apps/inebotten-discord
docker compose -f compose.production.yml pull
docker compose -f compose.production.yml up -d
```

## Legacy Webhook-Based Deployment (Deprecated)

> ⚠️ **WARNING: This method is deprecated for multi-app VPS setups.**
> 
> The old webhook-based auto-update method is only suitable for single-app VPS deployments. Do not expose the webhook port (9000) publicly unless you are intentionally using this legacy method.

The legacy method uses:
- GitHub webhook → VPS systemd service → `git reset --hard` → Docker rebuild → restart

If you must use this method:
1. Follow the old installation steps below (not recommended for production multi-app setups)
2. Ensure the webhook port (9000) is only accessible from GitHub's IP ranges
3. Use a strong webhook secret

### Legacy First-Time Setup

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-plugin python3 python3-pip openssl

# Clone repo
sudo git clone https://github.com/Reedtrullz/inebotten-discord.git /opt/inebotten-discord
sudo chown -R $USER:$USER /opt/inebotten-discord
cd /opt/inebotten-discord

# Install dependencies
pip install -r requirements.txt

# Run setup wizard
python3 setup.py

# Start with Docker (legacy all-in-one with Caddy)
sudo docker compose -f compose.with-caddy.yml up -d --build
```

### Legacy Webhook Installation

```bash
cd /opt/inebotten-discord
sudo WEBHOOK_PORT=9000 ./scripts/deploy/install-autoupdate.sh
```

### Legacy Manual Update

```bash
cd /opt/inebotten-discord
sudo systemctl start inebotten-update.service
```

## Security Notes

- **Never commit** `.env`, Discord tokens, `data/`, webhook secrets, or Google credentials
- Protect the web console with `CONSOLE_API_KEY` in your `.env` file
- In production, all public access goes through the central Caddy proxy
- Do not expose internal ports (3000, 8080) publicly - they should only be accessible via localhost
- Use a dedicated Discord account if running a selfbot (see `docs/SECURITY.md`)
- Discord selfbots violate Discord Terms of Service - use at your own risk

## Troubleshooting

| Problem | Check |
|---------|-------|
| Container not starting | `docker compose -f compose.production.yml logs inebotten-bot` |
| Console not accessible | Verify Caddy proxy config, check `CONSOLE_HOST=0.0.0.0` in environment |
| Image pull fails | Check GHCR permissions, verify `compose.production.yml` image name |
| Central Caddy error | Check Caddy logs, verify proxy target is `127.0.0.1:8080` |
| Legacy webhook 403 | Webhook secret mismatch, check `/etc/inebotten-webhook.env` |
