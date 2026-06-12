# Inebotten Deployment

Inebotten is deployed to a shared VPS (198.23.137.16) where its source is
checked out at `/opt/apps/inebotten-discord` and brought up via
`docker compose`. This `deploy/` directory contains the Ansible playbook,
inventory, and encrypted secrets used to run that deploy from a developer
workstation.

## Prerequisites

On the workstation:
- Ansible (Homebrew: `brew install ansible`)
- SSH key at `~/.ssh/id_rsa_racknerd` (deploy user on the VPS)
- Vault password at `~/.vault_pass.txt` (gitignored)

On the VPS (already configured, here for reference):
- Docker + Docker Compose v2
- A user `deploy` with SSH access and Docker group membership
- A repo checkout at `/opt/apps/inebotten-discord`
- A `.env` file at `/opt/apps/inebotten-discord/.env` containing
  `DISCORD_USER_TOKEN` (per-user, not in vault)
- A host-level Caddy serving `bot.reidar.tech` → `127.0.0.1:8081`

## Deploy

```bash
cd /path/to/inebotten-discord
ansible-playbook -i deploy/inventory/hosts.yml deploy/ansible-playbook.yml \
  --vault-password-file ~/.vault_pass.txt
```

What the playbook does:

1. **Removes any leftover standalone container** named `inebotten` from
   older deploys.
2. **Updates source from `origin/master`** on the VPS and records the checked-out
   commit for Docker build metadata.
3. **Idempotently writes a managed block to `.env`**:
   ```
   AI_PROVIDER=openrouter
   OPENROUTER_API_KEY={{ vault_openrouter_api_key }}
   OPENROUTER_MODEL=google/gemma-4-31b-it:free
   ```
   The block is delimited by `# === managed by ansible (inebotten-discord
   deploy) BEGIN/END ===`. Hand-edits between those markers are overwritten
   on every run; lines outside the block (`DISCORD_USER_TOKEN`,
   `CONSOLE_HOST`, …) are preserved.
4. **Drops a `docker-compose.override.yml`** that:
   - remaps the bot's web console to `127.0.0.1:8081` (host Caddy reverse-proxies there)
   - disables the bundled compose `caddy` service (host Caddy already owns 80/443)
5. **`docker compose up --build`** for the `inebotten` service only.
6. **Polls `http://127.0.0.1:8081/health`** until it responds.
7. **Verifies `/app/commit_hash.txt` inside the running container** matches the
   checked-out commit, so stale containers fail the deploy instead of looking
   successful.

## Secrets

| Secret | Where it lives |
|---|---|
| `OPENROUTER_API_KEY` | `deploy/group_vars/vps/vault.yml` (encrypted, `vault_openrouter_api_key`) |
| `DISCORD_USER_TOKEN` | `/opt/apps/inebotten-discord/.env` on the VPS, outside the managed block |

Edit the vault:
```bash
ansible-vault edit deploy/group_vars/vps/vault.yml \
  --vault-password-file ~/.vault_pass.txt
```

To rotate `DISCORD_USER_TOKEN`, ssh to the VPS and edit `.env` directly —
the playbook does not touch it.

## Verify

```bash
ssh deploy@198.23.137.16 "docker ps --filter name=inebotten-bot"
ssh deploy@198.23.137.16 "docker exec inebotten-bot cat /app/commit_hash.txt"
ssh deploy@198.23.137.16 "docker logs --tail 20 inebotten-bot | grep -iE 'openrouter|fallback|logged in'"
curl -s -o /dev/null -w "%{http_code}\n" https://bot.reidar.tech/
```

Expected log lines after a successful deploy:

```
[CONFIG] Using OpenRouter API (model: google/gemma-4-31b-it:free)
  AI Provider: OpenRouter (model: google/gemma-4-31b-it:free)
  ✓ AI Connector: API reachable (using model: google/gemma-4-31b-it:free)
[BOT] Logged in as inebotten (ID: ...)
```

If you see `[BRIDGE] Using local fallback response` instead, the AI
provider is unreachable. Check `AI_PROVIDER`, `OPENROUTER_API_KEY`, and
`OPENROUTER_MODEL` in `/opt/apps/inebotten-discord/.env`, then re-run
the playbook to re-inject them from vault.

## Don't

- Don't bring up the bundled compose `caddy` service. The host's system
  Caddy already terminates TLS for `bot.reidar.tech`; another Caddy on
  ports 80/443 will conflict.
- Don't drop `force_source: yes` from any docker-image pull task you
  add later. Without it, Ansible silently skips the pull when `:latest`
  already exists locally.
- Don't put `DISCORD_USER_TOKEN` in vault. It's per-user, not deployment
  config, and binding it to a vault makes account rotation painful.
