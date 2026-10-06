# Private console diagnostics

ConsoleStore defaults to an 8 MiB total budget across four fixed JSONL segments
and a seven-day diagnostic retention window. Constructor arguments
`max_log_bytes` (16 KiB–128 MiB) and `log_retention_days` (1–90) configure these
limits. Cooperating writers use one held OS lock. Read-only queries do not claim
ownership. Symlinks and multiply linked files are refused. Files are private
and the console directory is restricted to its owner.

`read_log_page(cursor, max_bytes, filters)` reads backwards within an actual
1–256 KiB byte budget and returns `records`, `bytes_read`, `next_cursor` and
`truncated`. It reads only the four fixed diagnostic paths. Newest records come
first; the compatibility `logs` strings are presented chronologically within
the returned page. `lines` is a compatibility byte-budget hint, not a promise
to scan arbitrarily many records. Filters match exact level, component, outcome
or opaque request ID. Missing metadata in legacy lines has an explicit default.
Malformed or oversized records are skipped within the budget.

Cursors are authenticated, bound to filters and file identities, and contain
no log text or pathname. Each live segment also has a process-local generation nonce,
forgotten on owned deletion/replacement so an immediately recycled inode cannot
revive an older cursor. The generation registry retains only the four live segments;
it changes no persisted log format. Moving a still-live segment during rotation
keeps its identity. Appending does not repeat a snapshot's rows. Rotation,
maintenance replacement or truncation can invalidate a cursor (HTTP 409);
process restart invalidates its ephemeral authentication key (HTTP 400). Fetch
the latest page again. No historical snapshot is retained just to serve a cursor.

Age-expired rows are excluded from all returned pages. Physical cleanup happens
on writes, at most once per minute, reading at most one segment's tail per file;
with no writes old rows remain on disk until the next owned write. Oversized
legacy files are reduced to their bounded valid tail on that write. No migration
or cleanup of the real user's stores was run for this implementation.

Structured logging records carry aware UTC time, level, component, optional
opaque request ID and outcome. Credentials and known legacy prompt/member debug
messages are removed before live buffering and persistence. Content-bearing AI
request traces were removed at source. Never log prompts, responses, member
lists or arbitrary account metadata: pattern redaction cannot certify arbitrary
free-form text as private. Existing legacy diagnostic tails are filtered on read
and sanitized during bounded maintenance; this does not erase backups or remote
copies. stdout capture also bounds an incomplete line to 16 KiB.

The authenticated API retains `Cache-Control: no-store`. Console controls filter
exact metadata, pause/follow with the existing owned polling controller, fetch
one older page, copy visible text or download only the visible page as plain
text. Dynamic content uses text nodes. Downloads contain private diagnostics;
the caller chooses where the browser saves them.

Audit retention is independent and no audit file is included or modified. The
existing rotating application log remains on its separate 10 MiB/five-backup
policy. Diagnostic limits do not cap those files, service logs, backups or
application data.

Generated-file tests compare a greater-than-2-MiB whole-file tail with an
independently instrumented 8-KiB reader. Rotation, age cleanup, private modes,
writer refusal, bad cursors, malformed rows and text-safe browser controls are
checked with synthetic data. No live Discord/account log was read.
