"""Explicit local calendar semantics and lossless Google time adapters."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone as utc_timezone
from time import monotonic as system_monotonic
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class TimeResolutionError(ValueError):
    def __init__(self, reason_code):
        self.reason_code = reason_code
        super().__init__(reason_code)


class Clock:
    def __init__(self, *, wall=None, monotonic=None):
        self._wall = wall or (lambda: datetime.now(utc_timezone.utc))
        self._monotonic = monotonic or system_monotonic

    def now(self, timezone='Europe/Oslo'):
        now = self._wall()
        if now.tzinfo is None:
            raise ValueError('clock_requires_aware_time')
        return now.astimezone(ZoneInfo(timezone))

    def monotonic(self):
        return self._monotonic()


@dataclass(frozen=True)
class EventTime:
    kind: str
    local_date: date
    local_time: time | None
    timezone: str = 'Europe/Oslo'
    all_day: bool = False
    duration_minutes: int | None = None
    fold: int | None = None
    inferred_fields: tuple[str, ...] = field(default=(), compare=False)

    def __post_init__(self):
        if self.kind not in ('event', 'task') or type(self.local_date) is not date:
            raise ValueError('invalid_event_kind_or_date')
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, TypeError, ValueError) as error:
            raise ValueError('invalid_timezone') from error
        if type(self.all_day) is not bool or self.all_day != (self.local_time is None):
            raise ValueError('inconsistent_all_day_time')
        if self.local_time is not None and (type(self.local_time) is not time or self.local_time.tzinfo is not None):
            raise ValueError('invalid_local_time')
        if self.duration_minutes is not None and (type(self.duration_minutes) is not int or self.duration_minutes <= 0):
            raise ValueError('invalid_duration')
        if self.all_day and self.duration_minutes is not None and self.duration_minutes % 1440:
            raise ValueError('all_day_duration_requires_whole_days')
        if self.fold is not None and (type(self.fold) is not int or self.fold not in (0, 1)):
            raise ValueError('invalid_fold')

    def aware_start(self):
        if self.local_time is None:
            raise TimeResolutionError('date_only_has_no_instant')
        naive = datetime.combine(self.local_date, self.local_time)
        zone = ZoneInfo(self.timezone)
        choices = []
        for fold in (0, 1):
            candidate = naive.replace(tzinfo=zone, fold=fold)
            back = candidate.astimezone(utc_timezone.utc).astimezone(zone)
            if back.replace(tzinfo=None) == naive and back.fold == fold:
                choices.append(candidate)
        if not choices:
            raise TimeResolutionError('nonexistent_time')
        if len(choices) > 1 and self.fold is None:
            raise TimeResolutionError('ambiguous_time')
        if self.fold is not None:
            for choice in choices:
                if choice.fold == self.fold:
                    return choice
            raise TimeResolutionError('invalid_fold_for_time')
        return choices[0]

    def validate_local(self):
        if self.local_time is not None:
            self.aware_start()
        return self

    def preview(self):
        reason = None
        try:
            self.validate_local()
        except TimeResolutionError as error:
            reason = error.reason_code
        return {**self.fields(), 'inferred_fields': list(self.inferred_fields),
                'requires_resolution': reason is not None, 'reason_code': reason,
                'remote_ready': self.kind == 'event' and reason is None and (self.all_day or self.duration_minutes is not None)}

    def fields(self):
        return {'kind': self.kind, 'date': self.local_date.strftime('%d.%m.%Y'),
                'time': self.local_time.isoformat(timespec='microseconds' if self.local_time.microsecond else 'seconds' if self.local_time.second else 'minutes') if self.local_time else None,
                'timezone': self.timezone, 'all_day': self.all_day,
                'duration_minutes': self.duration_minutes, 'fold': self.fold}

    @classmethod
    def from_item(cls, item):
        raw = item.get('date', '')
        local_date = datetime.strptime(raw, '%d.%m.%Y').date()
        raw_time = item.get('time')
        local_time = time.fromisoformat(raw_time) if raw_time else None
        kind = item.get('kind', item.get('type', 'event'))
        inferred = tuple(key for key in ('kind', 'timezone', 'all_day') if key not in item)
        return cls(kind, local_date, local_time, item.get('timezone', 'Europe/Oslo'),
                   item.get('all_day', local_time is None), item.get('duration_minutes'),
                   item.get('fold'), inferred)

    def google_times(self):
        if self.kind != 'event':
            raise TimeResolutionError('task_not_event')
        if self.all_day:
            days = self.duration_minutes // 1440 if self.duration_minutes is not None else 1
            return ({'date': self.local_date.isoformat()},
                    {'date': (self.local_date + timedelta(days=days)).isoformat()})
        start = self.aware_start()
        if self.duration_minutes is None:
            raise TimeResolutionError('duration_required')
        end = (start.astimezone(utc_timezone.utc) + timedelta(minutes=self.duration_minutes)).astimezone(ZoneInfo(self.timezone))
        return ({'dateTime': start.isoformat(), 'timeZone': self.timezone},
                {'dateTime': end.isoformat(), 'timeZone': self.timezone})

    @classmethod
    def from_google(cls, event):
        start, end = event['start'], event.get('end', {})
        if 'date' in start:
            day = date.fromisoformat(start['date'])
            days = (date.fromisoformat(end['date']) - day).days if end.get('date') else 1
            if days < 1:
                raise ValueError('invalid_remote_end')
            return cls('event', day, None, 'Europe/Oslo', True, days*1440 if days > 1 else None)
        zone = start.get('timeZone') or 'Europe/Oslo'
        parsed = datetime.fromisoformat(start['dateTime'].replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('remote_offset_required')
        local = parsed.astimezone(ZoneInfo(zone))
        duration = None
        if end.get('dateTime'):
            finish = datetime.fromisoformat(end['dateTime'].replace('Z', '+00:00'))
            if finish.tzinfo is None:
                raise ValueError('remote_offset_required')
            minutes = (finish.astimezone(utc_timezone.utc)-parsed.astimezone(utc_timezone.utc)).total_seconds()/60
            if minutes <= 0 or not minutes.is_integer():
                raise ValueError('invalid_remote_duration')
            duration = int(minutes)
        return cls('event', local.date(), local.time().replace(tzinfo=None), zone, False, duration, local.fold)
