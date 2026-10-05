"""Local recurring series and stable, anchor-based occurrence identities."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import calendar
import re
import uuid
from zoneinfo import ZoneInfo

from cal_system.event_schema import EventTime


SUPPORTED_FREQUENCIES = frozenset(("daily", "weekly", "biweekly", "monthly", "yearly"))
OCCURRENCE_STATES = frozenset(("planned", "completed", "skipped"))
MAX_EXPANDED_OCCURRENCES = 512
_WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_DAY_NAMES = {
    "mandag": "MO", "tirsdag": "TU", "onsdag": "WE", "torsdag": "TH",
    "fredag": "FR", "lørdag": "SA", "lordag": "SA", "søndag": "SU", "sondag": "SU",
}


@dataclass(frozen=True)
class Series:
    series_id: str
    anchor_time: EventTime
    rule: dict
    end_count: int | None = None
    end_date: date | None = None
    index_offset: int = 0

    def __post_init__(self):
        if not isinstance(self.series_id, str) or not self.series_id or len(self.series_id) > 1024:
            raise ValueError("invalid_series_id")
        if not isinstance(self.anchor_time, EventTime):
            raise ValueError("invalid_series_anchor")
        rule = normalize_rule(self.rule)
        object.__setattr__(self, "rule", rule)
        if type(self.index_offset) is not int or self.index_offset < 0:
            raise ValueError("invalid_recurrence_index_offset")
        if self.end_count is not None and (type(self.end_count) is not int or self.end_count < 1):
            raise ValueError("invalid_recurrence_end_count")
        if self.end_count is not None and self.end_count <= self.index_offset:
            raise ValueError("recurrence_end_before_current")
        if self.end_date is not None and type(self.end_date) is not date:
            raise ValueError("invalid_recurrence_end_date")
        if self.end_date is not None and self.end_date < self.anchor_time.local_date:
            raise ValueError("recurrence_end_precedes_anchor")
        if self.end_count is not None and self.end_date is not None:
            raise ValueError("ambiguous_recurrence_end")

    def to_document(self):
        return {
            "series_id": self.series_id,
            "anchor_time": self.anchor_time.fields(),
            "rule": deepcopy(self.rule),
            "end_count": self.end_count,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "index_offset": self.index_offset,
        }

    @classmethod
    def from_document(cls, value):
        if not isinstance(value, dict):
            raise ValueError("invalid_series_document")
        raw_end = value.get("end_date")
        return cls(
            value.get("series_id", ""), EventTime.from_item(value.get("anchor_time", {})),
            value.get("rule", {}), value.get("end_count"),
            date.fromisoformat(raw_end) if raw_end else None, value.get("index_offset", 0),
        )


@dataclass(frozen=True)
class Occurrence:
    occurrence_id: str
    series_id: str
    original_start: datetime
    state: str = "planned"
    override: dict | None = None

    def __post_init__(self):
        if not isinstance(self.occurrence_id, str) or not 1 <= len(self.occurrence_id) <= 128:
            raise ValueError("invalid_occurrence_id")
        if not isinstance(self.series_id, str) or not 1 <= len(self.series_id) <= 1024:
            raise ValueError("invalid_series_id")
        if not isinstance(self.original_start, datetime) or self.original_start.tzinfo is None:
            raise ValueError("occurrence_requires_aware_original_start")
        if self.state not in OCCURRENCE_STATES:
            raise ValueError("invalid_occurrence_state")
        if self.override is not None:
            if not isinstance(self.override, dict) or len(self.override) > 12:
                raise ValueError("invalid_occurrence_override")
            allowed = {'date', 'time', 'timezone', 'duration_minutes', 'fold', 'all_day',
                'title', 'description', 'kind', 'gcal_instance_id'}
            if set(self.override) - allowed:
                raise ValueError("invalid_occurrence_override_field")
            for field in ('date', 'time'):
                value = self.override.get(field)
                if value is not None:
                    if not isinstance(value, str) or len(value) > 32:
                        raise ValueError("invalid_occurrence_override_time")
                    if field == 'date':
                        datetime.strptime(value, '%d.%m.%Y')
                    elif value:
                        time.fromisoformat(value)
            zone = self.override.get('timezone')
            if zone is not None:
                ZoneInfo(zone)
            duration = self.override.get('duration_minutes')
            if duration is not None and (type(duration) is not int or duration <= 0):
                raise ValueError("invalid_occurrence_override_duration")
            fold = self.override.get('fold')
            if fold is not None and (type(fold) is not int or fold not in (0, 1)):
                raise ValueError("invalid_occurrence_override_fold")
            all_day = self.override.get('all_day')
            if all_day is not None and type(all_day) is not bool:
                raise ValueError("invalid_occurrence_override_all_day")
            kind = self.override.get('kind')
            if kind is not None and kind not in ('event', 'task'):
                raise ValueError("invalid_occurrence_override_kind")
            for field in ('title', 'description', 'gcal_instance_id'):
                value = self.override.get(field)
                if value is not None and (not isinstance(value, str) or len(value) > 10000):
                    raise ValueError("invalid_occurrence_override_text")
        object.__setattr__(self, "override", deepcopy(self.override) if self.override is not None else None)

    def to_document(self):
        return {
            "occurrence_id": self.occurrence_id, "series_id": self.series_id,
            "original_start": self.original_start.isoformat(), "state": self.state,
            "override": deepcopy(self.override),
        }

    @classmethod
    def from_document(cls, value):
        if not isinstance(value, dict):
            raise ValueError("invalid_occurrence_document")
        original_start = datetime.fromisoformat(value.get("original_start", ""))
        return cls(value.get("occurrence_id", ""), value.get("series_id", ""), original_start,
                   value.get("state", "planned"), value.get("override"))


def normalize_weekday(value):
    if value is None:
        return None
    day = str(value).strip()
    upper = day.upper()
    if upper in _WEEKDAYS:
        return upper
    return _DAY_NAMES.get(day.casefold())


def normalize_rule(rule):
    if isinstance(rule, str):
        rule = {"frequency": rule}
    if not isinstance(rule, dict):
        raise ValueError("invalid_recurrence_rule")
    frequency = rule.get("frequency", rule.get("type"))
    if frequency not in SUPPORTED_FREQUENCIES:
        raise ValueError("unsupported_recurrence_rule")
    interval = rule.get("interval", 2 if frequency == "biweekly" else 1)
    if type(interval) is not int or interval < 1:
        raise ValueError("invalid_recurrence_interval")
    if frequency == "biweekly" and interval != 2 or frequency == "weekly" and interval not in (1, 2):
        raise ValueError("unsupported_recurrence_interval")
    if frequency not in ("weekly", "biweekly") and interval != 1:
        raise ValueError("unsupported_recurrence_interval")
    weekdays = rule.get("weekdays")
    weekday = rule.get("weekday", rule.get("recurrence_day"))
    if weekdays is not None and weekday is not None:
        raise ValueError("duplicate_recurrence_weekday")
    if weekday is not None:
        weekdays = [weekday]
    if weekdays is not None:
        if frequency not in ("weekly", "biweekly") or not isinstance(weekdays, (list, tuple)) or not weekdays:
            raise ValueError("unsupported_recurrence_weekday")
        normalized = [normalize_weekday(value) for value in weekdays]
        if any(value is None for value in normalized) or len(normalized) != 1:
            raise ValueError("invalid_recurrence_weekday")
        weekdays = normalized
    result = {"frequency": frequency, "interval": interval}
    if weekdays:
        result["weekdays"] = weekdays
    return result


def occurrence_id_for(series_id: str, original_start: datetime, *, index: int | None = None) -> str:
    if original_start.tzinfo is None:
        raise ValueError("occurrence_requires_aware_original_start")
    if index is not None:
        if type(index) is not int or index < 0:
            raise ValueError("invalid_occurrence_index")
        return uuid.uuid5(uuid.NAMESPACE_URL, f"inebotten:occurrence:{series_id}:index:{index}").hex
    stable_start = original_start.isoformat(timespec="seconds")
    return uuid.uuid5(uuid.NAMESPACE_URL, f"inebotten:occurrence:{series_id}:{stable_start}").hex


def occurrence_at(series: Series, index: int) -> Occurrence | None:
    if type(index) is not int or index < 0:
        raise ValueError("invalid_occurrence_index")
    if series.end_count is not None and index >= series.end_count:
        return None
    if index < series.index_offset:
        return None
    relative_index = index - series.index_offset
    anchor = series.anchor_time
    start_day = anchor.local_date
    frequency = series.rule["frequency"]
    interval = series.rule["interval"]
    if frequency == "daily":
        day = start_day + timedelta(days=relative_index)
    elif frequency in ("weekly", "biweekly"):
        weeks = relative_index * interval
        day = start_day + timedelta(weeks=weeks)
        weekdays = series.rule.get("weekdays")
        if weekdays and relative_index:
            target = _WEEKDAYS[weekdays[0]]
            first_delta = (target - start_day.weekday()) % 7
            if first_delta == 0:
                first_delta = 7 * interval
            day = start_day + timedelta(days=first_delta + (relative_index - 1) * 7 * interval)
    elif frequency == "monthly":
        month_index = start_day.year * 12 + start_day.month - 1 + relative_index * interval
        year, month = divmod(month_index, 12)
        month += 1
        day = date(year, month, min(start_day.day, calendar.monthrange(year, month)[1]))
    else:
        year = start_day.year + relative_index * interval
        day = date(year, start_day.month, min(start_day.day, calendar.monthrange(year, start_day.month)[1]))
    if series.end_date is not None and day > series.end_date:
        return None
    local = EventTime(anchor.kind, day, anchor.local_time, anchor.timezone, anchor.all_day,
                      anchor.duration_minutes, anchor.fold)
    if anchor.all_day:
        original_start = datetime.combine(day, time.min, tzinfo=ZoneInfo(anchor.timezone))
    else:
        original_start = local.aware_start()
    return Occurrence(occurrence_id_for(series.series_id, original_start, index=index), series.series_id, original_start)


def expand_series(series: Series, start_date: date, end_date: date, *, exceptions=None,
                  limit=MAX_EXPANDED_OCCURRENCES) -> list[Occurrence]:
    if type(start_date) is not date or type(end_date) is not date or end_date < start_date:
        raise ValueError("invalid_occurrence_window")
    if type(limit) is not int or not 1 <= limit <= MAX_EXPANDED_OCCURRENCES:
        raise ValueError("invalid_occurrence_limit")
    anchor = series.anchor_time.local_date
    if end_date < anchor:
        return []
    exceptions = exceptions or {}
    frequency = series.rule["frequency"]
    step = series.rule["interval"]
    offset = series.index_offset
    if frequency == "daily":
        index = offset + max(0, (start_date - anchor).days - 1)
    elif frequency in ("weekly", "biweekly"):
        index = offset + max(0, (start_date - anchor).days // (7 * step) - 1)
    elif frequency == "monthly":
        months = (start_date.year - anchor.year) * 12 + start_date.month - anchor.month
        index = offset + max(0, months - 1)
    else:
        index = offset + max(0, start_date.year - anchor.year - 1)
    results = []
    while len(results) < limit:
        occurrence = occurrence_at(series, index)
        if occurrence is None:
            break
        if occurrence.original_start.date() > end_date:
            break
        if occurrence.original_start.date() >= start_date:
            saved = exceptions.get(occurrence.occurrence_id)
            if saved is not None:
                if isinstance(saved, dict):
                    saved = Occurrence.from_document(saved)
                if saved.series_id != series.series_id or saved.original_start != occurrence.original_start:
                    raise ValueError("occurrence_exception_identity_mismatch")
                occurrence = saved
            results.append(occurrence)
        index += 1
    return results


def series_from_item(item, *, legacy=False) -> Series:
    if isinstance(item.get("series"), dict):
        return Series.from_document(item["series"])
    recurrence = item.get("recurrence")
    if not recurrence:
        raise ValueError("item_has_no_recurrence")
    rule = {"frequency": recurrence}
    if item.get("recurrence_day") or item.get("rrule_day"):
        rule["weekday"] = item.get("rrule_day") or item.get("recurrence_day")
    end_count = item.get("recurrence_end_count")
    end_date_value = item.get("recurrence_end_date")
    end_date = date.fromisoformat(end_date_value) if end_date_value else None
    return Series(str(item.get("series_id") or item["id"]), EventTime.from_item(item), rule,
                  end_count, end_date)


def parse_google_recurrence(lines, anchor_time: EventTime):
    """Parse the app's recurrence subset while retaining raw unsupported rules."""
    raw = list(lines) if isinstance(lines, (list, tuple)) else []
    result = {"supported": False, "raw": raw, "readable": " · ".join(map(str, raw)),
              "rule": None, "end_count": None, "end_date": None,
              "reason_code": "unsupported_google_recurrence"}
    if len(raw) != 1 or not isinstance(raw[0], str) or not raw[0].startswith("RRULE:"):
        return result
    parts = raw[0][6:].split(";")
    fields = {}
    for part in parts:
        key, separator, value = part.partition("=")
        if not separator or not key or not value or key in fields:
            result["reason_code"] = "malformed_google_recurrence"
            return result
        fields[key] = value
    allowed = {"FREQ", "INTERVAL", "BYDAY", "COUNT", "UNTIL"}
    if set(fields) - allowed or ("COUNT" in fields and "UNTIL" in fields):
        return result
    frequency_name = fields.get("FREQ")
    frequency = {"DAILY": "daily", "WEEKLY": "weekly", "MONTHLY": "monthly", "YEARLY": "yearly"}.get(frequency_name)
    if frequency is None:
        return result
    try:
        interval = int(fields.get("INTERVAL", "1"))
        if frequency == "weekly" and interval == 2:
            frequency = "biweekly"
        rule = {"frequency": frequency, "interval": interval}
        if "BYDAY" in fields:
            weekdays = fields["BYDAY"].split(",")
            anchor_weekday = next(code for code, day in _WEEKDAYS.items()
                if day == anchor_time.local_date.weekday())
            if (frequency not in ("weekly", "biweekly") or len(weekdays) != 1
                or normalize_weekday(weekdays[0]) != anchor_weekday):
                return result
            rule["weekdays"] = weekdays
        rule = normalize_rule(rule)
        end_count = int(fields["COUNT"]) if "COUNT" in fields else None
        end_date = None
        if "UNTIL" in fields:
            until = fields["UNTIL"]
            if re.fullmatch(r"\d{8}", until):
                end_date = datetime.strptime(until, "%Y%m%d").date()
            elif re.fullmatch(r"\d{8}T\d{6}Z", until):
                utc_until = datetime.strptime(until, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                local_until = utc_until.astimezone(ZoneInfo(anchor_time.timezone))
                end_date = local_until.date()
                if not anchor_time.all_day:
                    final_start = EventTime(anchor_time.kind, end_date, anchor_time.local_time,
                        anchor_time.timezone, False, anchor_time.duration_minutes, anchor_time.fold)
                    try:
                        if final_start.aware_start().astimezone(timezone.utc) > utc_until:
                            end_date -= timedelta(days=1)
                    except ValueError:
                        return result
            else:
                return result
        Series("google-import-check", anchor_time, rule, end_count, end_date)
    except (ValueError, TypeError, OverflowError):
        return result
    return {"supported": True, "raw": raw, "readable": " · ".join(raw), "rule": rule,
            "end_count": end_count, "end_date": end_date, "reason_code": None}
