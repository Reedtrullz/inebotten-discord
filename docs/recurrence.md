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
file in its verified `.legacy-v0.bak` backup.

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
WEEKLY, MONTHLY, and YEARLY, with a positive COUNT or UNTIL. UTC UNTIL values
are compared with the local scheduled start before choosing the inclusive end
date. Parts such as BYSETPOS, multiple weekdays, RDATE, EXDATE, EXRULE, and
multiple rules remain as their raw Google rule and a readable diagnostic;
they are never converted into a guessed local schedule. If Google supplies
expanded instances but its master cannot be read, the instances are retained
as opaque evidence and that series is read-only locally.

Google's API defines `originalStartTime` as the identity of an instance even
when its actual start moves. “This and following” edits require separate remote
operations and can reset later exceptions. The local proposal flow therefore
keeps recurrence occurrence edits local and marks the Google scope as requiring
remote review; local persistence does not claim that Google accepted the
change. A live test-calendar round trip remains a separate acceptance gate.
