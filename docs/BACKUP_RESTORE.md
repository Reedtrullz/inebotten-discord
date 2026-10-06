# Private data backup and reviewed restore

The local CLI supports the versioned owned stores `calendar.json`,
`reminders.json`, `user_memory.json`, `polls.json` and `reminder_log.json`.
Calendar outboxes, local undo records, memory sharing/retention policy and
reminder delivery uncertainty remain inside those store documents. No field
is silently stripped from an included document. Configuration, credentials,
OAuth files, console sessions/stats, raw logs, member exports and older unowned
feature stores are excluded. The manifest lists the exact included stores:
a subset bundle is not a complete application installation or credential backup.
Bundles contain private calendar and memory data. Keep them locally in private
storage; no offsite/upload provider or backup-retention deletion policy is selected.

`create_bundle(registry, destination)` is async. A `StoreRegistry` receives the
actual initialized `DocumentOwner` objects, takes their async locks and thread
mutexes in sorted filename order, claims their cooperating process ownership,
and captures bounded immutable documents while writes are frozen. Related
multi-store mutations must use the same `registry.freeze()` lock ordering if
they require a transaction-wide cut. Ordinary independent store commits retain
their independent revisions. The UUID generation identifies one frozen capture,
not equal revision numbers or a global business transaction. File capture/output
runs on the existing cancellation-drained worker path; cancelled capture retains
the freeze until its actual file worker terminates. Output occurs after release.

Each source must be regular, single-link and unchanged from its owner's committed
fingerprint. Legacy documents are normalized only in the bundle; live bytes stay
unchanged. Calendar and reminder snapshots use schema 2, polls use schema 3, memory uses schema 4,
and delivery-log stores use schema 1. Version 1 polls and memory remain readable. Version 1 calendar/reminder bundles remain readable and restore
their original bytes. Exporting a readable older store upgrades only its bundle
copy, without changing live files or consuming migration backups. Domain validators,
per-file revision, byte count and SHA-256
are recorded. Each store is limited to 8 MiB, the manifest to 32 KiB and the archive
to 48 MiB. ZIP members are stored without compression; encrypted members,
duplicate names, links, directories, unlisted paths, unsupported schemas and
checksum/domain mismatches are refused before any extraction. Validation writes
only individually checked files into an exclusively created 0700 stage, with
0600 files. The archive is exclusively created 0600; an existing path is preserved.

## CLI workflow

There is no implicit personal-data default. Stop the bot, console, scheduler and
all readers before CLI backup or restore. `--services-stopped` is your assertion
that this operational step was completed; it is not a service-manager query.
Writer locks additionally refuse an active cooperating owner. The current
always-on launchd service is not stopped by this tool.

```sh
python scripts/inebotten_backup.py create \
  --data-dir /explicit/profile/discord/data \
  --archive /private/backups/reviewed.zip --services-stopped
python scripts/inebotten_backup.py preview \
  --archive /private/backups/reviewed.zip \
  --staging /private/backups/new-stage \
  --destination /explicit/restored-data
```

Review the printed generation, exact destination, included schema/checksums,
warnings and `review_token`. The stage's private `review.json` binds that reviewed
manifest, directory identity and destination inventory. The token is a content
binding, not a cryptographic signature or authorization system. Then use the
printed literal values:

```sh
python scripts/inebotten_backup.py restore \
  --staging /private/backups/new-stage \
  --destination /explicit/restored-data \
  --generation PRINTED_GENERATION --review-token PRINTED_REVIEW_TOKEN \
  --services-stopped
```

Restore revalidates every stage checksum/domain/schema, stage identity and the
exact destination contents/inodes, acquires the parent restore coordinator plus
all cooperating writer locks, then rechecks the destination. New destination
creation is exclusive, including the final creation race. A pre-existing directory
may contain only the allowlisted data files and their regular ownership locks;
a directory containing sessions, credentials, logs or other files is refused.
Use a new dedicated data directory for a normal profile restore and reconnect
configuration explicitly. Existing older-code-incompatible stores are refused.

Before replacement, the previous directory is preserved privately under
`DESTINATION.before-UUID`. The new destination is created privately, locked,
filled with exclusive files and every byte/checksum is reverified. No previous
generation is deleted. Restoring a subset intentionally installs only its listed
stores; the previous directory retains other included-store generations. The
successful receipt records the previous path and every restored checksum.
Replay is refused because the destination inventory has changed.

A failure after preservation or during new output leaves the previous directory,
partial destination and validated stage intact. Keep services stopped. Inspect the
printed content-free failure code, the `before-UUID` directory and stage; use a new
explicit destination and a fresh preview for recovery. Do not automatically
replace a raced directory or delete partial evidence. This is a quiescent restore,
not an atomic directory swap visible to concurrent readers. Cooperative advisory
locks do not defeat uncooperative writers. File fsync and checksum verification
are not a cross-platform power-loss certification or directory-fsync guarantee.

## Verification

Synthetic tests demonstrate a naive mixed-generation copy and a frozen consistent
cut; cancellation, excluded credentials, stage/destination races, stale previews,
newer schema, corrupt/truncated/duplicate/path/link archives, lock symlinks and
failed replacement preservation are covered. A separate CLI subprocess rehearsal
creates, previews, restores and stages a rollback using generated data. No personal
store, actual service, live Discord/Google account or offsite backup was used.
