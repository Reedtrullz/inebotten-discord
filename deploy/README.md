# Ansible deployment profile

This playbook defines `compose-host-caddy` on a provisioned checkout at
`/opt/apps/inebotten-discord`, with diagnostic access at `127.0.0.1:8081`.
The definition does not establish which service currently runs on the VPS.
See [the deployment contract](../docs/VPS_DEPLOYMENT.md) for preflight, immutable
image receipts, readiness, code rollback and the separate data-restore gate.

The playbook refuses dirty source before synchronization, preserves WIP (`force:
false`), and stops on source failure. It neither deletes unrelated old containers,
rotates `.env`, recursively chowns data, nor prunes images. Existing config and a
reviewed data root owned by UID 10001 are required. It calls the shared Python
3.12 deployment tool with `--build --apply`; candidate failure remains a failed
Ansible run even after successful code rollback. `first_install` defaults false.

Before running this playbook, verify current service, port inventory, backup
health and old image evidence on the target. Existing images without full
revision/schema metadata need a separately reviewed transition; they are refused.
Use the verified `Racknerd-Deploy` SSH alias (deploy user, `id_ed25519_racknerd`,
`IdentitiesOnly=yes`, `IdentityAgent=none`). Resolve the actual inventory and
credentials locally; do not print vault or token values.

The host proxy and any Cloudflare Access settings are provisioned separately.
The tool uses an explicit Compose file pair and its profile mapping, so an
unrelated `docker-compose.override.yml` is not silently loaded. Review existing
overrides before adopting the profile.
