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

Parser round trips are engineering checks. Acceptance through two selected
calendar clients, with recorded versions and human-reviewed dates, remains a
separate gate. No calendar-client acceptance has been performed yet.

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
