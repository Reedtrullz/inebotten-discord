# Recurring calendar items

Calendar events and reminders store a recurring series separately from its
occurrences. A series has a stable `series_id`, an immutable schedule anchor,
an interval rule, and an optional inclusive end date or occurrence count.
Occurrence IDs are deterministic within a series and use the logical occurrence
index, so moving an occurrence or splitting the future schedule does not change
the selected occurrence's identity.

The local rule set is daily, weekly, every other week, monthly, and yearly.
Monthly and yearly dates are calculated from the original anchor each time: a
January 31 series yields February 28 (or 29) and returns to March 31; a February
29 yearly series returns to February 29 in leap years. An end count includes the
anchor occurrence. An end date includes occurrences on that date.

An occurrence can be planned, completed, or skipped. A moved occurrence keeps
its original scheduled start and ID, with the new date/time and other changed
fields stored as an override. Completed and skipped instances remain in the
series record. On restart, the next index and these exceptions determine the
next notification, and notification delivery keys use the occurrence ID and
delivery stage.

Legacy recurring records that stored only a moving “next date” cannot recover
their earlier schedule. Migration anchors the new series at the stored date and
records `recurrence_migration.status=legacy_collapsed`,
`anchor_source=stored_current_date`, and `recovered_before_anchor=false`. It does
not invent missed occurrences. The normal storage migration keeps the original
file in its verified `.legacy-v0.bak` backup. Calendar and reminder envelopes
now use data schema 2. A version 1 envelope is read without changing its bytes;
the first successful write saves its original bytes in `.schema-v1.bak` before
writing version 2. Calendar setup migrates legacy recurrence records; reminders
migrate when changed. Older schema 1 readers refuse version 2 rather than
misinterpreting occurrence history. Deployment rollback checks this boundary.

Reminder create, complete, edit, delete, and cleanup operations resolve records
inside the bucket selected by the current request and its `AccessPolicy`. A
missing actor cannot write to a configured private or approved-group scope.
Legacy shared reminder files keep their existing guild/channel buckets and
unscoped records remain readable through the legacy shared policy; no automatic
move into a newly configured private or group scope is inferred.

Snoozes for recurring reminders store the same deterministic occurrence ID used
by the scheduler. The scheduler reprojects that current occurrence after
restart; completed, exhausted, read-only, or malformed series cannot fall back
to snoozing the raw series record. Delivery receipts older than 48 hours are
pruned only after their outcome is resolved. `pending` and `unknown` receipts
remain durable across restart, including when they keep the receipt cap full.

Recurring edits require a scope in the command: `bare denne` edits the current
occurrence; `denne og fremtidige` or `herfra og ut` starts the revised schedule
at the current occurrence while preserving earlier occurrence records; `hele
serien` applies the change to the active series. A preview names the exact
occurrence before confirmation. `hopp over` skips the selected occurrence; the
usual completion command completes it. Ordinary one-off item edits keep their
existing behavior.

Google Calendar imports request expanded events and deleted exceptions, then
fetch the master event for each recurring series. The master RRULE and each
instance's `originalStartTime` are used to reconstruct supported series and
persist moved or canceled exceptions. The supported Google RRULE subset is
DAILY, WEEKLY (one weekday matching the DTSTART weekday), every-other-week
WEEKLY, MONTHLY anchored on days 1–28, and YEARLY except February 29, with a
positive COUNT or UNTIL. Google follows RFC 5545 and skips invalid dates;
the local monthly/yearly rules clamp them. Rules whose results differ therefore
remain raw and read-only. Timed DTSTART requires a UTC date-time UNTIL;
all-day DTSTART requires a DATE UNTIL. UTC UNTIL values
are compared with the local scheduled start before choosing the inclusive end
date. Parts such as BYSETPOS, multiple weekdays, RDATE, EXDATE, EXRULE, and
multiple rules remain as their raw Google rule and a readable diagnostic;
they are never converted into a guessed local schedule. If Google supplies
expanded instances but its master cannot be read, the instances are retained
as opaque evidence and that series is read-only locally. Subsequent pulls retain
opaque instance evidence and pending local edits. A changed Google schedule
with existing local occurrence history is held for review with the incoming
schedule recorded separately; it does not silently remap or erase exceptions.

Google's API defines `originalStartTime` as the identity of an instance even
when its actual start moves. “This and following” edits require separate remote
operations and can reset later exceptions. The local proposal flow therefore
keeps recurrence occurrence edits local and marks the Google scope as requiring
remote review; local persistence does not claim that Google accepted the
change. A live test-calendar round trip remains a separate acceptance gate.
