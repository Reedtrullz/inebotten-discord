from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo


OSLO = ZoneInfo("Europe/Oslo")
MIN_YEAR = 1900
MAX_YEAR = 2100

DATE_ALIASES = {
    "i dag": 0,
    "idag": 0,
    "today": 0,
    "i morgen": 1,
    "imorgen": 1,
    "i morra": 1,
    "imorra": 1,
    "imårra": 1,
    "i morgon": 1,
    "tomorrow": 1,
    "i overmorgen": 2,
    "overmorgen": 2,
    "i overmorgon": 2,
    "overmorgon": 2,
    "day after tomorrow": 2,
}
DAYPART_HOURS = {
    "i morges": "10:00",
    "i formiddag": "10:00",
    "på formiddagen": "10:00",
    "i ettermiddag": "14:00",
    "på ettermiddagen": "14:00",
    "i kveld": "19:00",
    "på kvelden": "19:00",
    "i natt": "22:00",
    "på natten": "22:00",
    "this morning": "08:00",
    "this afternoon": "14:00",
    "this evening": "19:00",
    "tonight": "19:00",
}
_CONTEXT_DAYPART_HOURS = {
    "på morgenen": "08:00",
    "på morgonen": "08:00",
    "om morgenen": "08:00",
    "om morgonen": "08:00",
    "morgenen": "08:00",
    "morgonen": "08:00",
    "tidlig": "08:00",
    "early": "08:00",
    "morning": "08:00",
    "formiddag": "10:00",
    "ettermiddag": "14:00",
    "afternoon": "14:00",
    "kveld": "19:00",
    "evening": "19:00",
    "natt": "22:00",
    "night": "22:00",
}
_CONTEXT_DAYPART_KINDS = {
    "på morgenen": "morges",
    "på morgonen": "morges",
    "om morgenen": "morges",
    "om morgonen": "morges",
    "morgenen": "morges",
    "morgonen": "morges",
    "tidlig": "morges",
    "early": "morges",
    "morning": "morges",
    "formiddag": "formiddag",
    "ettermiddag": "ettermiddag",
    "afternoon": "ettermiddag",
    "kveld": "kveld",
    "evening": "kveld",
    "natt": "natt",
    "night": "natt",
}
_DAYPART_KINDS = {
    "i morges": "morges",
    "i formiddag": "formiddag",
    "på formiddagen": "formiddag",
    "i ettermiddag": "ettermiddag",
    "på ettermiddagen": "ettermiddag",
    "i kveld": "kveld",
    "på kvelden": "kveld",
    "i natt": "natt",
    "på natten": "natt",
    "this morning": "morges",
    "this afternoon": "ettermiddag",
    "this evening": "kveld",
    "tonight": "kveld",
    **_CONTEXT_DAYPART_KINDS,
}
_DAYPART_MINUTE_RANGES = {
    "morges": ((0, 12 * 60),),
    "formiddag": ((6 * 60, 12 * 60),),
    "ettermiddag": ((12 * 60, 18 * 60),),
    "kveld": ((18 * 60, 24 * 60),),
    "natt": ((22 * 60, 24 * 60), (0, 6 * 60)),
}
SPECIAL_HOURS = {
    "noon": "12:00",
    "midnatt": "00:00",
    "midnight": "00:00",
}

_HOUR_WORD = (
    r"[a-zæøå]+"
    r"(?:[- ]+(?!på\b|am\b|pm\b)[a-zæøå]+)?"
)
NATURAL_TIME_RE = re.compile(
    rf"\b(?P<cue>kl(?:okka|okken)?\.?|at|rundt|about)\s+"
    rf"(?P<hour>-?\d{{1,2}}|{_HOUR_WORD})"
    r"(?:(?::|\.)(?P<minute>\d{2}))?"
    r"(?:\s*(?P<suffix>am|pm)\b"
    r"|\s+på\s+(?P<daypart>morgenen|morgonen|ettermiddagen|kvelden)\b)?"
    r"(?![\w:])",
    re.IGNORECASE,
)
NATURAL_QUARTER_RE = re.compile(
    rf"\b(?:(?:kl(?:okka|okken)?\.?)\s+)?"
    rf"(?:kvart\s+over|quarter\s+past)\s+"
    rf"(?P<hour>\d{{1,2}}|{_HOUR_WORD})"
    r"(?:\s+på\s+(?P<daypart>morgenen|morgonen|ettermiddagen|kvelden)\b)?"
    r"(?![\w:])",
    re.IGNORECASE,
)
NATURAL_NORWEGIAN_HALF_RE = re.compile(
    rf"\b(?:(?:kl(?:okka|okken)?\.?)\s+)?halv\s+"
    rf"(?P<hour>\d{{1,2}}|{_HOUR_WORD})"
    r"(?:\s+på\s+(?P<daypart>morgenen|morgonen|ettermiddagen|kvelden)\b)?"
    r"(?![\w:])",
    re.IGNORECASE,
)
MALFORMED_CUE_TIME_RE = re.compile(
    r"\b(?:kl(?:okka|okken)?\.?|at|rundt|about)\s+"
    r"[+-]?\d{3,}(?![\d./:])",
    re.IGNORECASE,
)
AMBIGUOUS_TEMPORAL_RE = re.compile(
    r"(?<!\w)(?:senere\s+i\s+dag|seinare\s+i\s+dag|later\s+today|"
    r"neste\s+helg|neste\s+weekend|next\s+weekend)(?!\w)",
    re.IGNORECASE,
)
RAW_TIME_RE = re.compile(
    r"(?<![\d.:])(?P<hour>-?\d{1,2}):(?P<minute>\d{2})(?![\d:])"
)
_BARE_AMPM_RE = re.compile(
    r"(?<![\w:])(?P<hour>\d{1,2})\s*(?P<suffix>am|pm)(?!\w)",
    re.IGNORECASE,
)
_NUMERIC_DATE_RE = re.compile(
    r"(?<![\d./])(?P<day>\d{1,2})[./](?P<month>\d{1,2})"
    r"(?:[./](?P<year>\d{2}|\d{4}))?(?![\d./])"
)

MONTHS = {
    "januar": 1,
    "jan": 1,
    "january": 1,
    "februar": 2,
    "feb": 2,
    "february": 2,
    "mars": 3,
    "mar": 3,
    "march": 3,
    "april": 4,
    "apr": 4,
    "mai": 5,
    "may": 5,
    "juni": 6,
    "jun": 6,
    "june": 6,
    "juli": 7,
    "jul": 7,
    "july": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "oktober": 10,
    "okt": 10,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "desember": 12,
    "des": 12,
    "december": 12,
    "dec": 12,
}

WEEKDAYS = {
    "mandag": 0,
    "måndag": 0,
    "monday": 0,
    "tirsdag": 1,
    "tuesday": 1,
    "onsdag": 2,
    "wednesday": 2,
    "torsdag": 3,
    "thursday": 3,
    "fredag": 4,
    "friday": 4,
    "lørdag": 5,
    "laurdag": 5,
    "saturday": 5,
    "søndag": 6,
    "sundag": 6,
    "sunday": 6,
}

NUMBER_WORDS = {
    "null": 0,
    "zero": 0,
    "en": 1,
    "ett": 1,
    "ei": 1,
    "one": 1,
    "to": 2,
    "two": 2,
    "tre": 3,
    "three": 3,
    "fire": 4,
    "four": 4,
    "fem": 5,
    "five": 5,
    "seks": 6,
    "six": 6,
    "sju": 7,
    "syv": 7,
    "seven": 7,
    "åtte": 8,
    "eight": 8,
    "ni": 9,
    "nine": 9,
    "ti": 10,
    "ten": 10,
    "elleve": 11,
    "eleven": 11,
    "tolv": 12,
    "twelve": 12,
    "tretten": 13,
    "thirteen": 13,
    "fjorten": 14,
    "fourteen": 14,
    "femten": 15,
    "fifteen": 15,
    "seksten": 16,
    "sixteen": 16,
    "sytten": 17,
    "seventeen": 17,
    "atten": 18,
    "eighteen": 18,
    "nitten": 19,
    "nineteen": 19,
    "tjue": 20,
    "twenty": 20,
    "tjueen": 21,
    "tjue en": 21,
    "twenty one": 21,
    "tjueto": 22,
    "tjue to": 22,
    "twenty two": 22,
    "tjuetre": 23,
    "tjue tre": 23,
    "twenty three": 23,
    "tjuefire": 24,
    "tjue fire": 24,
    "twenty four": 24,
    "tjuefem": 25,
    "tjue fem": 25,
    "twenty five": 25,
    "tjueseks": 26,
    "tjue seks": 26,
    "twenty six": 26,
    "tjuesju": 27,
    "tjue sju": 27,
    "twenty seven": 27,
    "tjueåtte": 28,
    "tjue åtte": 28,
    "twenty eight": 28,
    "tjueni": 29,
    "tjue ni": 29,
    "twenty nine": 29,
    "tretti": 30,
    "thirty": 30,
    "trettien": 31,
    "tretti en": 31,
    "thirty one": 31,
}

_MONTH_PATTERN = "|".join(
    re.escape(value) for value in sorted(MONTHS, key=len, reverse=True)
)
_MONTH_DATE_RE = re.compile(
    rf"(?<!\w)(?P<day>\d{{1,2}})(?:\s*\.\s*|\s+)"
    rf"(?P<month>{_MONTH_PATTERN})"
    r"(?:\s+(?P<year>\d{2}|\d{4})(?![\w:]))?(?!\w)",
    re.IGNORECASE,
)
_DEN_DAY_RE = re.compile(r"(?<!\w)den\s+(?P<day>\d{1,2})\.(?!\d)", re.IGNORECASE)
_WEEKDAY_PATTERN = "|".join(
    re.escape(value) for value in sorted(WEEKDAYS, key=len, reverse=True)
)
_WEEKDAY_RE = re.compile(
    rf"(?<!\w)(?:(?P<prefix>neste|next|førstkommende|"
    rf"komande|kommande|kommende)\s+)?"
    rf"(?P<weekday>{_WEEKDAY_PATTERN})(?!\w)",
    re.IGNORECASE,
)
_NUMBER_PATTERN = "|".join(
    re.escape(value) for value in sorted(NUMBER_WORDS, key=len, reverse=True)
)
_RELATIVE_RE = re.compile(
    rf"(?<!\w)(?P<prefix>om|in)\s+(?:"
    r"(?P<half>(?:en|ein|ei)\s+halv(?:\s*time|time)|"
    r"half(?:\s+an?)?\s+hour)|"
    rf"(?P<number>\d+|{_NUMBER_PATTERN})\s+"
    r"(?P<unit>minutt(?:er)?|minutt|minutes?|time(?:r)?|hours?|"
    r"dag(?:er|ar)?|days?|uke(?:r)?|veke(?:r)?|weeks?))"
    r"(?!\w)",
    re.IGNORECASE,
)

_LABELS = {
    "date_alias",
    "numeric_date",
    "month_date",
    "day_of_month",
    "weekday",
    "relative",
    "natural_time",
    "raw_time",
    "special_hour",
    "daypart",
}


@dataclass(frozen=True, slots=True)
class TemporalResolution:
    date: str | None = None
    time: str | None = None
    due_at: str | None = None
    matched_text: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True, slots=True)
class _DateEvidence:
    label: str
    span: tuple[int, int]
    day: int
    month: int
    year: int | None = None
    mode: str = "date"
    weekday: int | None = None
    prefix: str | None = None


@dataclass(frozen=True, slots=True)
class _TimeEvidence:
    label: str
    span: tuple[int, int]
    canonical: str | None
    error: str | None = None
    anchor_today: bool = False
    daypart: str | None = None


@dataclass(frozen=True, slots=True)
class _CollectedEvidence:
    dates: tuple[_DateEvidence, ...]
    times: tuple[_TimeEvidence, ...]
    relatives: tuple[re.Match[str], ...]


class TemporalResolver:
    def __init__(
        self,
        *,
        zone: ZoneInfo = OSLO,
        now_provider: Callable[[], datetime] | None = None,
    ):
        self.zone = zone
        self._now_provider = now_provider or (lambda: datetime.now(self.zone))

    def _capture_reference(self, reference: datetime | None) -> datetime:
        captured = self._now_provider() if reference is None else reference
        if captured.tzinfo is None or captured.utcoffset() is None:
            raise ValueError("temporal_reference_must_be_aware")
        return captured.astimezone(self.zone)

    @staticmethod
    def _format_date(value: date) -> str:
        return f"{value.day:02d}.{value.month:02d}.{value.year:04d}"

    @staticmethod
    def _format_time(value: time) -> str:
        return f"{value.hour:02d}:{value.minute:02d}"

    @staticmethod
    def _parse_number(value: str) -> int | None:
        folded = " ".join(value.casefold().replace("-", " ").split())
        if folded.isdigit():
            return int(folded)
        return NUMBER_WORDS.get(folded)

    @staticmethod
    def _overlaps(span: tuple[int, int], occupied: list[tuple[int, int]]) -> bool:
        start, end = span
        return any(start < other_end and end > other_start for other_start, other_end in occupied)

    @staticmethod
    def _bounded_matches(text: str, phrases: dict[str, object]):
        occupied: list[tuple[int, int]] = []
        for phrase in sorted(phrases, key=len, reverse=True):
            pattern = re.compile(
                rf"(?<!\w){re.escape(phrase)}(?!\w)",
                re.IGNORECASE,
            )
            for match in pattern.finditer(text):
                span = match.span()
                if not TemporalResolver._overlaps(span, occupied):
                    occupied.append(span)
                    yield phrase, match

    def _parse_time_scalar(self, value: str) -> time | None:
        match = re.fullmatch(r"\s*(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*", value)
        if match is None:
            return None
        hour = int(match.group("hour"))
        minute = int(match.group("minute") or 0)
        try:
            return time(hour, minute)
        except ValueError:
            return None

    def validate_time(self, value: str) -> str | None:
        if not isinstance(value, str):
            return None
        parsed = self._parse_time_scalar(value)
        return self._format_time(parsed) if parsed is not None else None

    def _valid_candidates(self, day: date, wall_time: time) -> tuple[datetime, ...]:
        naive = datetime.combine(day, wall_time)
        by_utc: dict[datetime, datetime] = {}
        for fold in (0, 1):
            candidate = naive.replace(tzinfo=self.zone, fold=fold)
            candidate_utc = candidate.astimezone(timezone.utc)
            projected = candidate_utc.astimezone(self.zone)
            if projected.replace(tzinfo=None) != naive:
                continue
            by_utc[candidate_utc] = candidate
        return tuple(by_utc[key] for key in sorted(by_utc))

    def resolve_recurrence_wall_time(self, local: datetime) -> datetime:
        """Apply the sole deterministic policy for recurring Oslo wall time.

        User-entered ambiguous/nonexistent values remain rejected by
        ``validate_fields``.  This method is intentionally recurrence-only:
        it keeps an accepted nominal wall-time schedule usable across later
        daylight-saving transitions.
        """
        if not isinstance(local, datetime) or local.tzinfo is not None:
            raise ValueError("recurrence_wall_time_must_be_naive")

        candidates = self._valid_candidates(local.date(), local.time())
        if candidates:
            # _valid_candidates is ordered by UTC instant, so the first value
            # is fold=0 (the earlier occurrence) when the wall time repeats.
            return candidates[0]

        # A nonexistent wall time round-trips to either side of the gap.  The
        # first valid projection after the requested nominal time represents
        # an exact forward shift by the transition gap (02:30 -> 03:30).
        projections: list[datetime] = []
        for fold in (0, 1):
            attached = local.replace(tzinfo=self.zone, fold=fold)
            projected = attached.astimezone(timezone.utc).astimezone(self.zone)
            if projected.replace(tzinfo=None) > local:
                projections.append(projected)
        if not projections:
            raise ValueError("invalid_recurrence_wall_time")
        return min(
            projections,
            key=lambda value: value.replace(tzinfo=None) - local,
        )

    def _parse_date_scalar(
        self,
        value: str,
        *,
        reference: datetime,
        wall_time: time | None,
    ) -> date | None:
        match = re.fullmatch(
            r"\s*(?P<day>\d{1,2})[./](?P<month>\d{1,2})"
            r"(?:[./](?P<year>\d{2}|\d{4}))?\s*",
            value,
        )
        if match is None:
            return None
        day = int(match.group("day"))
        month = int(match.group("month"))
        year_text = match.group("year")
        if year_text is not None:
            year = int(year_text)
            if len(year_text) == 2:
                year += 2000
            if not MIN_YEAR <= year <= MAX_YEAR:
                return None
            try:
                return date(year, month, day)
            except ValueError:
                return None
        return self._select_yearless(day, month, reference, wall_time)

    def _date_is_future(
        self,
        candidate: date,
        reference: datetime,
        wall_time: time | None,
    ) -> bool | None:
        if candidate > reference.date():
            return True
        if candidate < reference.date():
            return False
        if wall_time is None:
            return True
        candidates = self._valid_candidates(candidate, wall_time)
        if not candidates:
            return None
        reference_utc = reference.astimezone(timezone.utc)
        return any(value.astimezone(timezone.utc) >= reference_utc for value in candidates)

    def _select_yearless(
        self,
        day: int,
        month: int,
        reference: datetime,
        wall_time: time | None,
    ) -> date | None:
        try:
            current = date(reference.year, month, day)
        except ValueError:
            current = None

        if current is not None:
            future = self._date_is_future(current, reference, wall_time)
            if future is True or future is None:
                return current

        for year in range(reference.year + 1, MAX_YEAR + 1):
            try:
                return date(year, month, day)
            except ValueError:
                continue
        return None

    def validate_fields(
        self,
        date_value: str | None,
        time_value: str | None,
        *,
        due_at: str | None = None,
        reference: datetime | None = None,
    ) -> TemporalResolution:
        captured = self._capture_reference(reference)
        if date_value is None:
            if time_value is not None or due_at is not None:
                return TemporalResolution(errors=("missing_date",))
            return TemporalResolution()

        wall_time = None
        canonical_time = None
        if time_value is not None:
            wall_time = self._parse_time_scalar(time_value)
            if wall_time is None:
                return TemporalResolution(errors=("invalid_time",))
            canonical_time = self._format_time(wall_time)
        elif due_at is not None:
            return TemporalResolution(errors=("invalid_time",))

        parsed_date = self._parse_date_scalar(
            date_value,
            reference=captured,
            wall_time=wall_time,
        )
        if parsed_date is None:
            return TemporalResolution(time=canonical_time, errors=("invalid_date",))
        canonical_date = self._format_date(parsed_date)
        if wall_time is None:
            return TemporalResolution(date=canonical_date)

        valid_candidates = self._valid_candidates(parsed_date, wall_time)
        if not valid_candidates:
            return TemporalResolution(
                date=canonical_date,
                time=canonical_time,
                errors=("invalid_time",),
            )

        if due_at is not None:
            try:
                explicit = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
            except (TypeError, ValueError):
                return TemporalResolution(
                    date=canonical_date,
                    time=canonical_time,
                    errors=("invalid_time",),
                )
            if explicit.tzinfo is None or explicit.utcoffset() is None:
                return TemporalResolution(
                    date=canonical_date,
                    time=canonical_time,
                    errors=("invalid_time",),
                )
            projected = explicit.astimezone(self.zone)
            projected_wall = projected.timetz().replace(tzinfo=None)
            if (
                projected.date() != parsed_date
                or projected.microsecond != 0
                or (projected_wall.hour, projected_wall.minute)
                != (wall_time.hour, wall_time.minute)
            ):
                return TemporalResolution(
                    date=canonical_date,
                    time=canonical_time,
                    errors=("invalid_time",),
                )
            explicit_utc = explicit.astimezone(timezone.utc)
            precise_candidates = self._valid_candidates(parsed_date, projected_wall)
            matching = [
                candidate
                for candidate in precise_candidates
                if explicit_utc == candidate.astimezone(timezone.utc)
            ]
            if len(matching) != 1:
                return TemporalResolution(
                    date=canonical_date,
                    time=canonical_time,
                    errors=("invalid_time",),
                )
            return TemporalResolution(
                date=canonical_date,
                time=canonical_time,
                due_at=projected.isoformat(timespec="seconds"),
            )

        if len(valid_candidates) > 1:
            return TemporalResolution(
                date=canonical_date,
                time=canonical_time,
                errors=("ambiguous_time",),
            )
        return TemporalResolution(
            date=canonical_date,
            time=canonical_time,
            due_at=valid_candidates[0].isoformat(timespec="seconds"),
        )

    def _natural_time(self, match: re.Match[str]) -> tuple[str | None, str | None]:
        hour_text = match.group("hour")
        numeric = re.fullmatch(r"-?\d{1,2}", hour_text) is not None
        special = SPECIAL_HOURS.get(hour_text.casefold())
        if special is not None:
            if match.group("minute") or match.group("suffix") or match.group("daypart"):
                return None, "invalid_time"
            return special, None
        if numeric:
            hour = int(hour_text)
        else:
            words = hour_text.split()
            hour = None
            for end in range(len(words), 0, -1):
                parsed = self._parse_number(" ".join(words[:end]))
                if parsed is not None:
                    hour = parsed
                    break
        minute = int(match.group("minute") or 0)
        suffix = (match.group("suffix") or "").casefold()
        daypart = (match.group("daypart") or "").casefold()
        if hour is None:
            return None, None
        if minute > 59:
            return None, "invalid_time"

        if suffix:
            if not 1 <= hour <= 12:
                return None, "invalid_time"
            if suffix == "pm" and hour != 12:
                hour += 12
            elif suffix == "am" and hour == 12:
                hour = 0
        elif daypart:
            if not 0 <= hour <= 12:
                return None, "invalid_time"
            if daypart in {"ettermiddagen", "kvelden"} and 1 <= hour <= 11:
                hour += 12
        elif not numeric and 0 <= hour <= 11:
            return None, "ambiguous_time"

        if not 0 <= hour <= 23:
            return None, "invalid_time"
        canonical = f"{hour:02d}:{minute:02d}"
        daypart_kind = {
            "morgenen": "morges",
            "morgonen": "morges",
            "ettermiddagen": "ettermiddag",
            "kvelden": "kveld",
        }.get(daypart)
        if daypart_kind and not self._daypart_accepts(
            canonical,
            daypart_kind,
        ):
            return None, "conflicting_temporal"
        return canonical, None

    def _natural_quarter(
        self, match: re.Match[str]
    ) -> tuple[str | None, str | None]:
        hour_text = match.group("hour")
        hour = (
            int(hour_text)
            if hour_text.isdigit()
            else self._parse_number(hour_text)
        )
        daypart = (match.group("daypart") or "").casefold()
        if hour is None:
            return None, None
        if daypart:
            if not 0 <= hour <= 12:
                return None, "invalid_time"
            if daypart in {"ettermiddagen", "kvelden"} and 1 <= hour <= 11:
                hour += 12
        elif 0 <= hour <= 12:
            return None, "ambiguous_time"
        if not 0 <= hour <= 23:
            return None, "invalid_time"
        canonical = f"{hour:02d}:15"
        daypart_kind = {
            "morgenen": "morges",
            "morgonen": "morges",
            "ettermiddagen": "ettermiddag",
            "kvelden": "kveld",
        }.get(daypart)
        if daypart_kind and not self._daypart_accepts(
            canonical,
            daypart_kind,
        ):
            return None, "conflicting_temporal"
        return canonical, None

    def _natural_norwegian_half(
        self,
        match: re.Match[str],
    ) -> tuple[str | None, str | None]:
        """Resolve Norwegian ``halv tre`` as half an hour before three."""

        hour_text = match.group("hour")
        next_hour = (
            int(hour_text)
            if hour_text.isdigit()
            else self._parse_number(hour_text)
        )
        daypart = (match.group("daypart") or "").casefold()
        if next_hour is None:
            return None, None
        if daypart:
            if not 1 <= next_hour <= 12:
                return None, "invalid_time"
            if daypart == "kvelden" and next_hour == 12:
                next_hour = 24
            elif daypart in {"ettermiddagen", "kvelden"} and next_hour <= 11:
                next_hour += 12
        elif 1 <= next_hour <= 12:
            # Both numeric and word-hour 12-hour clock forms omit AM/PM. Do
            # not silently choose the early candidate.
            return None, "ambiguous_time"
        elif not 1 <= next_hour <= 24:
            return None, "invalid_time"

        canonical = f"{(next_hour - 1) % 24:02d}:30"
        daypart_kind = {
            "morgenen": "morges",
            "morgonen": "morges",
            "ettermiddagen": "ettermiddag",
            "kvelden": "kveld",
        }.get(daypart)
        if daypart_kind and not self._daypart_accepts(
            canonical,
            daypart_kind,
        ):
            return None, "conflicting_temporal"
        return canonical, None

    def _collect_times(
        self,
        text: str,
        *,
        has_date_evidence: bool = False,
    ) -> list[_TimeEvidence]:
        evidence: list[_TimeEvidence] = []
        occupied: list[tuple[int, int]] = []

        for match in NATURAL_NORWEGIAN_HALF_RE.finditer(text):
            canonical, error = self._natural_norwegian_half(match)
            if canonical is None and error is None:
                continue
            evidence.append(
                _TimeEvidence("natural_time", match.span(), canonical, error)
            )
            occupied.append(match.span())

        for match in NATURAL_TIME_RE.finditer(text):
            if self._overlaps(match.span(), occupied):
                continue
            canonical, error = self._natural_time(match)
            if canonical is None and error is None:
                continue
            evidence.append(_TimeEvidence("natural_time", match.span(), canonical, error))
            occupied.append(match.span())

        for match in NATURAL_QUARTER_RE.finditer(text):
            if self._overlaps(match.span(), occupied):
                continue
            canonical, error = self._natural_quarter(match)
            if canonical is None and error is None:
                continue
            evidence.append(
                _TimeEvidence("natural_time", match.span(), canonical, error)
            )
            occupied.append(match.span())

        for match in MALFORMED_CUE_TIME_RE.finditer(text):
            if self._overlaps(match.span(), occupied):
                continue
            evidence.append(
                _TimeEvidence(
                    "natural_time", match.span(), None, "invalid_time"
                )
            )
            occupied.append(match.span())

        for match in AMBIGUOUS_TEMPORAL_RE.finditer(text):
            if self._overlaps(match.span(), occupied):
                continue
            evidence.append(
                _TimeEvidence(
                    "natural_time", match.span(), None, "ambiguous_time"
                )
            )
            occupied.append(match.span())

        for match in _BARE_AMPM_RE.finditer(text):
            if self._overlaps(match.span(), occupied):
                continue
            hour = int(match.group("hour"))
            suffix = match.group("suffix").casefold()
            if not 1 <= hour <= 12:
                canonical, error = None, "invalid_time"
            else:
                if suffix == "pm" and hour != 12:
                    hour += 12
                elif suffix == "am" and hour == 12:
                    hour = 0
                canonical, error = f"{hour:02d}:00", None
            evidence.append(_TimeEvidence("natural_time", match.span(), canonical, error))
            occupied.append(match.span())

        for match in RAW_TIME_RE.finditer(text):
            if self._overlaps(match.span(), occupied):
                continue
            hour = int(match.group("hour"))
            minute = int(match.group("minute"))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                canonical, error = f"{hour:02d}:{minute:02d}", None
            else:
                canonical, error = None, "invalid_time"
            evidence.append(_TimeEvidence("raw_time", match.span(), canonical, error))
            occupied.append(match.span())

        for phrase, match in self._bounded_matches(text, SPECIAL_HOURS):
            if self._overlaps(match.span(), occupied):
                continue
            evidence.append(
                _TimeEvidence("special_hour", match.span(), SPECIAL_HOURS[phrase])
            )
            occupied.append(match.span())

        for phrase, match in self._bounded_matches(text, DAYPART_HOURS):
            if self._overlaps(match.span(), occupied):
                continue
            evidence.append(
                _TimeEvidence(
                    "daypart",
                    match.span(),
                    DAYPART_HOURS[phrase],
                    anchor_today=(
                        phrase.startswith("i ")
                        or phrase.startswith("this ")
                        or phrase == "tonight"
                    ),
                    daypart=_DAYPART_KINDS[phrase],
                )
            )
            occupied.append(match.span())

        if has_date_evidence:
            for phrase, match in self._bounded_matches(
                text,
                _CONTEXT_DAYPART_HOURS,
            ):
                if self._overlaps(match.span(), occupied):
                    continue
                evidence.append(
                    _TimeEvidence(
                        "daypart",
                        match.span(),
                        _CONTEXT_DAYPART_HOURS[phrase],
                        daypart=_DAYPART_KINDS[phrase],
                    )
                )
                occupied.append(match.span())
        return evidence

    def _daypart_accepts(self, canonical: str, daypart: str) -> bool:
        wall_time = self._parse_time_scalar(canonical)
        if wall_time is None:
            return False
        minute = wall_time.hour * 60 + wall_time.minute
        return any(
            start <= minute < end
            for start, end in _DAYPART_MINUTE_RANGES[daypart]
        )

    def _collect_dates(self, text: str) -> tuple[list[_DateEvidence], list[str]]:
        evidence: list[_DateEvidence] = []
        invalid: list[str] = []
        occupied: list[tuple[int, int]] = []

        for phrase, match in self._bounded_matches(text, DATE_ALIASES):
            evidence.append(
                _DateEvidence(
                    "date_alias",
                    match.span(),
                    0,
                    0,
                    mode="alias",
                    prefix=str(DATE_ALIASES[phrase]),
                )
            )
            occupied.append(match.span())

        for match in _NUMERIC_DATE_RE.finditer(text):
            if self._overlaps(match.span(), occupied):
                continue
            if "." in match.group(0) and re.search(
                r"(?:kl(?:okka|okken)?\.?|at|rundt|about)\s*$",
                text[: match.start()],
                re.IGNORECASE,
            ):
                # In Norwegian prose ``kl 14.30`` is an unambiguous clock
                # value.  Do not simultaneously reinterpret its scalar as an
                # impossible day/month pair.
                continue
            year_text = match.group("year")
            year = int(year_text) if year_text else None
            if year_text and len(year_text) == 2:
                year += 2000
            evidence.append(
                _DateEvidence(
                    "numeric_date",
                    match.span(),
                    int(match.group("day")),
                    int(match.group("month")),
                    year,
                )
            )
            occupied.append(match.span())

        for match in _MONTH_DATE_RE.finditer(text):
            if self._overlaps(match.span(), occupied):
                continue
            year_text = match.group("year")
            year = int(year_text) if year_text else None
            if year_text and len(year_text) == 2:
                year += 2000
            evidence.append(
                _DateEvidence(
                    "month_date",
                    match.span(),
                    int(match.group("day")),
                    MONTHS[match.group("month").casefold()],
                    year,
                )
            )
            occupied.append(match.span())

        for match in _DEN_DAY_RE.finditer(text):
            if self._overlaps(match.span(), occupied):
                continue
            evidence.append(
                _DateEvidence(
                    "day_of_month",
                    match.span(),
                    int(match.group("day")),
                    0,
                    mode="day_of_month",
                )
            )
            occupied.append(match.span())

        for match in _WEEKDAY_RE.finditer(text):
            if self._overlaps(match.span(), occupied):
                continue
            evidence.append(
                _DateEvidence(
                    "weekday",
                    match.span(),
                    0,
                    0,
                    mode="weekday",
                    weekday=WEEKDAYS[match.group("weekday").casefold()],
                    prefix=(match.group("prefix") or "").casefold() or None,
                )
            )
            occupied.append(match.span())

        return evidence, invalid

    def _collect_evidence(self, text: str) -> _CollectedEvidence:
        dates, _ = self._collect_dates(text)
        return _CollectedEvidence(
            dates=tuple(dates),
            times=tuple(
                self._collect_times(
                    text,
                    has_date_evidence=bool(dates),
                )
            ),
            relatives=tuple(_RELATIVE_RE.finditer(text)),
        )

    def strip_temporal_evidence(
        self,
        text: str,
        *,
        reference: datetime | None = None,
    ) -> str:
        if not isinstance(text, str):
            raise TypeError("temporal_text_must_be_str")
        self._capture_reference(reference)
        evidence = self._collect_evidence(text)
        spans = [
            value.span
            for value in (*evidence.dates, *evidence.times)
        ]
        spans.extend(match.span() for match in evidence.relatives)
        if not spans:
            return text
        chars = list(text)
        for start, end in spans:
            for index in range(start, end):
                if not chars[index].isspace():
                    chars[index] = " "
        cleaned = " ".join("".join(chars).split())
        cleaned = re.sub(
            r"(?:\s+(?:på|til|den|at|kl\.?|rundt|about|om|in))+$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"(?:\s*[-–—,;:]+\s*)+$", "", cleaned)
        return cleaned.strip()

    def _canonicalize_date_evidence(
        self,
        evidence: _DateEvidence,
        *,
        reference: datetime,
        wall_time: time | None,
    ) -> tuple[str | None, str | None]:
        if evidence.mode == "alias":
            target = reference.date() + timedelta(days=int(evidence.prefix or 0))
            return self._format_date(target), None

        if evidence.mode == "day_of_month":
            year, month = reference.year, reference.month
            for attempt in range(2):
                if attempt:
                    month += 1
                    if month == 13:
                        year += 1
                        month = 1
                try:
                    target = date(year, month, evidence.day)
                except ValueError:
                    continue
                future = self._date_is_future(target, reference, wall_time)
                if future is True or future is None:
                    return self._format_date(target), None
            return None, "invalid_date"

        if evidence.mode == "weekday":
            assert evidence.weekday is not None
            delta = (evidence.weekday - reference.weekday()) % 7
            candidate = reference.date() + timedelta(days=delta)
            if evidence.prefix in {"neste", "next"}:
                candidate = reference.date() + timedelta(
                    days=7 if delta == 0 else delta + 7
                )
            elif delta == 0:
                future = self._date_is_future(candidate, reference, wall_time)
                if future is not True:
                    candidate += timedelta(days=7)
            return self._format_date(candidate), None

        if evidence.year is not None:
            if not MIN_YEAR <= evidence.year <= MAX_YEAR:
                return None, "invalid_date"
            try:
                target = date(evidence.year, evidence.month, evidence.day)
            except ValueError:
                return None, "invalid_date"
        else:
            target = self._select_yearless(
                evidence.day,
                evidence.month,
                reference,
                wall_time,
            )
            if target is None:
                return None, "invalid_date"
        return self._format_date(target), None

    def _relative_target(
        self,
        match: re.Match[str],
        reference: datetime,
    ) -> datetime | None:
        reference = reference.replace(microsecond=0)
        if match.group("half") is not None:
            target = (
                reference.astimezone(timezone.utc) + timedelta(minutes=30)
            ).astimezone(self.zone)
            return target if MIN_YEAR <= target.year <= MAX_YEAR else None

        number = self._parse_number(match.group("number"))
        if number is None or not 0 <= number <= 100_000:
            return None
        unit = match.group("unit").casefold()
        if unit.startswith("minut") or unit.startswith("minute"):
            target = (
                reference.astimezone(timezone.utc) + timedelta(minutes=number)
            ).astimezone(self.zone)
            return target if MIN_YEAR <= target.year <= MAX_YEAR else None
        if unit.startswith("time") or unit.startswith("hour"):
            target = (
                reference.astimezone(timezone.utc) + timedelta(hours=number)
            ).astimezone(self.zone)
            return target if MIN_YEAR <= target.year <= MAX_YEAR else None
        days = number * (7 if unit.startswith(("uke", "veke", "week")) else 1)
        naive_target = reference.replace(tzinfo=None) + timedelta(days=days)
        if not MIN_YEAR <= naive_target.year <= MAX_YEAR:
            return None
        candidates = self._valid_candidates(naive_target.date(), naive_target.time())
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        same_fold = [candidate for candidate in candidates if candidate.fold == reference.fold]
        return (same_fold or list(candidates))[0]

    def _first_time_date(
        self,
        canonical_time: str,
        reference: datetime,
        *,
        anchor_today: bool,
    ) -> date:
        if anchor_today:
            return reference.date()
        wall_time = self._parse_time_scalar(canonical_time)
        assert wall_time is not None
        reference_utc = reference.astimezone(timezone.utc)
        for offset in range(367):
            candidate_date = reference.date() + timedelta(days=offset)
            candidates = self._valid_candidates(candidate_date, wall_time)
            if not candidates:
                continue
            if offset or any(
                candidate.astimezone(timezone.utc) >= reference_utc
                for candidate in candidates
            ):
                return candidate_date
        return reference.date()

    def resolve(
        self,
        text: str,
        *,
        reference: datetime | None = None,
    ) -> TemporalResolution:
        if not isinstance(text, str):
            raise TypeError("temporal_text_must_be_str")
        captured = self._capture_reference(reference)
        evidence = self._collect_evidence(text)
        time_evidence = evidence.times
        date_evidence = evidence.dates
        relative_matches = evidence.relatives

        labels: list[str] = []
        for value in (*date_evidence, *time_evidence):
            if value.label in _LABELS and value.label not in labels:
                labels.append(value.label)
        if relative_matches:
            labels.append("relative")

        if relative_matches and (date_evidence or time_evidence):
            return TemporalResolution(
                matched_text=tuple(labels),
                errors=("conflicting_temporal",),
            )

        if relative_matches:
            targets = [self._relative_target(match, captured) for match in relative_matches]
            if any(target is None for target in targets):
                return TemporalResolution(
                    matched_text=tuple(labels),
                    errors=("invalid_time",),
                )
            unique = {
                target.astimezone(timezone.utc): target
                for target in targets
                if target is not None
            }
            if len(unique) != 1:
                return TemporalResolution(
                    matched_text=tuple(labels),
                    errors=("conflicting_temporal",),
                )
            target = next(iter(unique.values()))
            return TemporalResolution(
                date=self._format_date(target.date()),
                time=self._format_time(target.timetz().replace(tzinfo=None)),
                due_at=target.isoformat(timespec="seconds"),
                matched_text=tuple(labels),
            )

        time_errors = [value.error for value in time_evidence if value.error]
        explicit_times = {
            value.canonical
            for value in time_evidence
            if value.label != "daypart" and value.canonical is not None
        }
        compatible_explicit = (
            next(iter(explicit_times)) if len(explicit_times) == 1 else None
        )
        canonical_times = set(explicit_times)
        for value in time_evidence:
            if value.label != "daypart" or value.canonical is None:
                continue
            comparison_time = value.canonical
            if (
                compatible_explicit is not None
                and value.daypart is not None
                and self._daypart_accepts(compatible_explicit, value.daypart)
            ):
                comparison_time = compatible_explicit
            canonical_times.add(comparison_time)
        if len(canonical_times) > 1:
            return TemporalResolution(
                matched_text=tuple(labels),
                errors=("conflicting_temporal",),
            )
        canonical_time = next(iter(canonical_times), None)
        wall_time = (
            self._parse_time_scalar(canonical_time)
            if canonical_time is not None
            else None
        )

        canonical_dates: list[str] = []
        date_errors: list[str] = []
        for evidence in date_evidence:
            canonical, error = self._canonicalize_date_evidence(
                evidence,
                reference=captured,
                wall_time=wall_time,
            )
            if canonical is not None:
                canonical_dates.append(canonical)
            if error is not None:
                date_errors.append(error)

        unique_dates = set(canonical_dates)
        if len(unique_dates) > 1:
            return TemporalResolution(
                matched_text=tuple(labels),
                errors=("conflicting_temporal",),
            )
        canonical_date = next(iter(unique_dates), None)

        if date_errors:
            return TemporalResolution(
                date=canonical_date,
                time=canonical_time,
                matched_text=tuple(labels),
                errors=("invalid_date",),
            )
        if time_errors:
            error = (
                "conflicting_temporal"
                if "conflicting_temporal" in time_errors
                else (
                    "ambiguous_time"
                    if "ambiguous_time" in time_errors
                    else "invalid_time"
                )
            )
            return TemporalResolution(
                date=canonical_date,
                time=canonical_time,
                matched_text=tuple(labels),
                errors=(error,),
            )

        if canonical_time is not None and canonical_date is None:
            canonical_date = self._format_date(
                self._first_time_date(
                    canonical_time,
                    captured,
                    anchor_today=any(value.anchor_today for value in time_evidence),
                )
            )

        validated = self.validate_fields(
            canonical_date,
            canonical_time,
            reference=captured,
        )
        return TemporalResolution(
            date=validated.date,
            time=validated.time,
            due_at=validated.due_at,
            matched_text=tuple(labels),
            errors=validated.errors,
        )
