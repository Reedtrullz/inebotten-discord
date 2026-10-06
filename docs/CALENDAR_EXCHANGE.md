# Reviewed calendar file exchange

The parser candidate is `icalendar` 7.3.0, the stable PyPI release checked on
5 October 2026. It is BSD-2-Clause, supports Python >=3.10 and uses python-dateutil,
tzdata and typing-extensions on Python <3.13. The production, development and
desktop graphs must include its reviewed hash pins. Sources:
[PyPI metadata](https://pypi.org/project/icalendar/7.3.0/),
[stable API guide](https://icalendar.readthedocs.io/en/stable/how-to/usage.html),
and [RFC 5545](https://www.rfc-editor.org/rfc/rfc5545).

The local exchange boundary accepts uploaded bytes only, never URLs. Limits are
1 MiB, 8 KiB per unfolded line, nesting depth 4 and 256 event/task masters.
Exports and imports require authorization for one explicit scope. Import creates
an actor-, scope-, revision- and expiry-bound preview; applying rechecks policy
and revision. File UIDs are data, never provider identifiers or instructions.
Stable UID mappings live inside calendar records and make reimport idempotent.
Applying a file does not synchronize to Google or send invitations.

Supported records are VEVENT with DATE or aware DATE-TIME start and end, and
VTODO with a DATE due date. Unicode titles and descriptions are preserved.
Floating times, custom timezones, invitations/attendees, attachments, alarms,
URLs, remote actions, ambiguous folds and unsupported recurrence components are
reported explicitly. IANA timezone definitions are ignored in favor of the
installed zoneinfo data; uploaded definitions cannot replace the trusted clock.
Timed event ends use UTC so elapsed durations survive the repeated autumn hour.
Ambiguous starts are refused because the local ICS date-time cannot carry the
Python fold choice. A large preview includes a complete review attachment;
unconfirmed delivery invalidates that confirmation token.

The first recurrence subset uses DAILY, WEEKLY with one matching weekday,
biweekly, MONTHLY on days 1–28, and YEARLY except February 29. COUNT and UNTIL
follow the existing supported Google/RFC subset. The local day-clamping rules
for month ends and leap days cannot be emitted as a plain RFC rule, so those
exports are refused rather than silently changing the schedule. Series with
occurrence exceptions, completed occurrences or split history require a later
reviewed exchange extension. Reimport cannot overwrite such local history or
pending provider mutations.

## Verified client compatibility — 5 October 2026

The selected event subset was imported and exported through two actual web
clients. Export PRODID identifies Google Calendar 70.9054 and Proton
WebCalendar 5.0.423.0.a; these are producer-declared versions. The submitted
recordings show the imports, and the returned files were compared read-only.
Apple Calendar was not exercised.

| Fixture | Google Calendar | Proton Calendar |
| --- | --- | --- |
| Unicode title and multiline description | Preserved | Preserved |
| 4 January 2027, 09:30–11:00 Oslo | Same instants and duration | Same instants and duration |
| Two all-day dates, 4–5 January, exclusive end 6 January | Preserved | Preserved |
| Five Monday occurrences, 4 January–1 February | Preserved | Preserved |
| 28 March, 01:30–04:30 Oslo, 120 elapsed minutes across DST | Preserved | Preserved |
| Stable event UIDs | Preserved | Preserved |
| Due-date task Frist (VTODO) | Omitted by client | Omitted by client |
| Original timezone metadata | Europe/Oslo preserved | Timed TZIDs rewritten to Europe/Berlin; custom fields removed |

Acceptance covers these event schedules and the previously declared recurrence
subset. It does not promise lossless task or timezone-identifier round trips.
Inebotten retains due-date tasks as VTODO and warns on exports that select tasks;
it does not invent an event time to accommodate a client. Keep the original
local task or the original ICS when the receiving client omits it.

Proton's returned all-day record has no timezone metadata, so the import uses
UTC for that date-only item. This preserves the fixture dates but changes the
stored timezone identity. An import confirmation now shows the timezone, with
old → new values for timezone changes. Review them before confirming: matching
these January/March instants does not make two timezone names interchangeable
for arbitrary historical dates or future rules.

Returned Google events preview against the original five-item store as four
duplicates; Proton events preview as four timezone changes. Neither creates
new event identities or deletes the absent task. Importing either returned file
into a separate empty fixture store gives four events; importing it again gives
four duplicates without changing the revision. Imports add/update selected UIDs;
absence from a file is never a deletion instruction.

Private source files remain outside Git. Local review receipts contain only the
synthetic fixtures, aggregate counts, file hashes and comparisons. The selected
reader trial also verified all seven guarded CSV IDs, names and discriminator
values in Google Sheets; raw JSON remains the lossless member-export reference.

## Commands

Mention the bot, then use `kalender eksporter ics alle` or
`kalender eksporter ics ID,ID` to select exact stored IDs in the configured
scope. The shared sender delivers a file to the authorized invocation channel;
private scopes require a private audience. Export does not move old guild
buckets into the configured scope. Linked recurring Google records are refused
until their complete exception history can be reviewed.

Attach exactly one `.ics` file to `kalender importer ics`. The download accepts
only the Discord CDN attachment path for that message's channel and attachment
ID, refuses redirects/compression, and enforces a five-second deadline and a
streamed 1 MiB cap. Review the displayed titles, dates, counts and unsupported
items before `bekreft ics TOKEN`. Only supported entries are applied. The token
is case-sensitive, expires after five minutes and cannot be replayed.
