# Resource ownership and shutdown

MessageMonitor owns its background and admitted message tasks, outbound sender,
calendar/reminder/poll store handles, Google provider slot, crypto/aurora clients,
forecast service and search manager. Each created resource is registered once.
Its forecast service owns the weather client and borrows the monitor's aurora
client. The AI connector, console store, process-wide user memory and default
console forecast service belong to the process composition, not the monitor.

`OwnedResources.close(deadline)` uses an absolute monotonic deadline and reverse
registration order. One cleanup driver survives caller cancellation. A cleanup
operation already running at the deadline remains referenced with a pending
receipt; it is not silently abandoned or certified closed. Errors stop dependent
cleanup. A later close can drain that same operation or retry a failed operation,
while successful closers are not repeated. Receipts include pending/unclosed
names and exception types, not private exception messages.

Monitor shutdown blocks new message admission, cancels/drains owned work, flushes
final counter deltas, and then releases owned managers/stores. Final and periodic
flushes share a lock. File writes run off-loop. If cancellation arrives during a
successful write, its snapshot is acknowledged before cancellation propagates;
the next flush does not add the batch again. A failed flush preserves the pending
intent/rate delta and leaves shutdown incomplete for retry. The stats store stays
with the process owner until dependent cleanup succeeds.

The client stops console admission/connections, stops the reminder checker and
drains its tasks, then closes the monitor/checker store and Discord transport.
Idle HTTP connections are closed before waiting for the asyncio server, so its
wait cannot depend on the original request timeout. Cancelled startup candidates
are retained for cleanup and are not published. READY retry does not replace a
candidate while its cleanup remains incomplete. Existing reconnect ownership is
retained.

The runner cleans up even when startup never reached `running=True`. It owns the
connector, shared memory/default forecast and capture/store lifecycle after the
client. Capture is stopped before the shared console lock is released. AI
admission drains cancellation-resistant operations before its HTTP session is
closed. Closed network managers reject session recreation. A normal run with an
incomplete cleanup receipt returns exit status 2.

Python cannot safely terminate a native provider thread. The deadline bounds the
cleanup call, not an OS process/executor join. A live thread keeps its resource
and an incomplete receipt; the process must remain quiescent and finish/retry
cleanup. Underlying provider network deadlines remain required. I30 supplies
bounded search-provider workers; this change does not certify the old search
executor path as bounded. No live service shutdown, account call or process kill
was used for these tests.

Synthetic receipts cover final delta exactly once, concurrent/repeated close,
cancel-after-write acknowledgement, failed flush/retry, borrowed clients,
cancel-resistant background and AI work, real monitor composition, partial
startup, cancelled READY and idle loopback HTTP connections. Actual desktop
process termination and platform-specific service acceptance remain separate.
