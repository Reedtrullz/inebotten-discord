# Legacy webhook and systemd entry points

These files describe an optional older installation, not current server truth.
The updater retains its flock/log/timer interface and delegates activation to
`scripts/inebotten_deploy.py`. Python 3.12+, Docker and Compose 2.24.4+ are required.
See [deployment profiles and rollback](../../docs/VPS_DEPLOYMENT.md).

`INEBOTTEN_REPO`, `INEBOTTEN_BRANCH`, `INEBOTTEN_PYTHON` and
`INEBOTTEN_DEPLOY_PROFILE` select the provisioned checkout, branch, interpreter
and explicit Compose profile (`compose` or `compose-host-caddy`). The default
branch is `master`. Configured repository paths and webhook authentication must
remain operator controlled.

Dirty source and fetch/non-fast-forward failures return failure before invoking
Docker. The deployer builds only tracked source, retains previous immutable code,
checks full revision and required readiness, and rolls code back only when stored
schemas remain compatible. The updater never hard-resets WIP, prunes images,
restores data, or reports a failed candidate as a verified update.

Installing/restarting the webhook or timer remains a separate explicit operator
operation. Do not assume installing these definitions is a safe migration from a
running launchd/Compose/standalone installation. Inspect active services, backup
health and port allocation first; retain the current service until the transition
is reviewed. Keep the webhook secret private and authenticated; do not place
secret values in documentation or diagnostic receipts.
