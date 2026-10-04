"""Validated notification choices and deterministic aware scheduling."""
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from cal_system.event_schema import EventTime, TimeResolutionError

CARD_IDS = ('date', 'calendar', 'weather', 'birthdays', 'market', 'aurora', 'watchlist')


def occurrence_identity(item):
    return str(item.get('occurrence_id') or f"{item['id']}:{item.get('date', item.get('due_date', ''))}:{item.get('time', '')}")


@dataclass(frozen=True)
class NotificationProfile:
    enabled: bool
    scope_id: str
    destination_id: str | None
    lead_minutes: tuple[int, ...] = (30, 0)
    quiet_start: time | None = None
    quiet_end: time | None = None
    morning_time: time | None = None
    timezone: str = 'Europe/Oslo'
    card_ids: tuple[str, ...] = ('calendar',)

    def __post_init__(self):
        if type(self.enabled) is not bool or not isinstance(self.scope_id, str) or not 1 <= len(self.scope_id) <= 100:
            raise ValueError('invalid_notification_profile')
        if self.destination_id is not None and (not isinstance(self.destination_id, str) or not self.destination_id.isdecimal() or len(self.destination_id) > 30):
            raise ValueError('invalid_notification_destination')
        if (not isinstance(self.lead_minutes, (tuple, list)) or len(self.lead_minutes) > 8
            or any(type(v) is not int or not 0 <= v <= 1440 for v in self.lead_minutes)):
            raise ValueError('invalid_notification_leads')
        if not isinstance(self.card_ids, (tuple, list)) or len(self.card_ids) > len(CARD_IDS) or any(v not in CARD_IDS for v in self.card_ids):
            raise ValueError('invalid_digest_cards')
        for value in (self.quiet_start, self.quiet_end, self.morning_time):
            if value is not None and (type(value) is not time or value.tzinfo is not None or value.second or value.microsecond):
                raise ValueError('invalid_notification_clock')
        if (self.quiet_start is None) != (self.quiet_end is None) or self.quiet_start is not None and self.quiet_start == self.quiet_end:
            raise ValueError('invalid_quiet_hours')
        ZoneInfo(self.timezone)
        object.__setattr__(self, 'lead_minutes', tuple(dict.fromkeys(self.lead_minutes)))
        object.__setattr__(self, 'card_ids', tuple(dict.fromkeys(self.card_ids)))

    def document(self):
        return {'enabled': self.enabled, 'scope_id': self.scope_id, 'destination_id': self.destination_id,
                'lead_minutes': list(self.lead_minutes), 'card_ids': list(self.card_ids), 'timezone': self.timezone,
                **{k: getattr(self, k).isoformat(timespec='minutes') if getattr(self, k) else None
                   for k in ('quiet_start', 'quiet_end', 'morning_time')}}

    @classmethod
    def from_document(cls, value):
        value = dict(value)
        for key in ('quiet_start', 'quiet_end', 'morning_time'):
            if value.get(key) is not None:
                value[key] = time.fromisoformat(value[key])
        return cls(**value)


def local_instant(day, wall_time, zone, *, not_before=None):
    """First real minute after a gap; first eligible fold at an ambiguous boundary."""
    naive = datetime.combine(day, wall_time)
    for offset in range(181):
        shifted = naive + timedelta(minutes=offset)
        for fold in (0, 1):
            try:
                value = EventTime('event', shifted.date(), shifted.time(), zone, fold=fold).aware_start().astimezone(timezone.utc)
                if not_before is None or value >= not_before.astimezone(timezone.utc):
                    return value
            except TimeResolutionError:
                pass
    raise ValueError('notification_boundary_unavailable')


def after_quiet_hours(profile, instant):
    if instant.tzinfo is None:
        raise ValueError('aware_delivery_required')
    if profile.quiet_start is None:
        return instant.astimezone(timezone.utc)
    local = instant.astimezone(ZoneInfo(profile.timezone))
    wall = local.time().replace(tzinfo=None)
    start, end = profile.quiet_start, profile.quiet_end
    quiet = start <= wall < end if start < end else wall >= start or wall < end
    if not quiet:
        return instant.astimezone(timezone.utc)
    day = local.date() + (timedelta(days=1) if start > end and wall >= start else timedelta())
    return local_instant(day, end, profile.timezone, not_before=instant)


def next_delivery(profile, event_time, clock):
    if not profile.enabled or not profile.destination_id:
        return None
    if event_time.tzinfo is None:
        raise ValueError('aware_event_required')
    now = clock.now('UTC')
    start = event_time.astimezone(timezone.utc)
    choices = [after_quiet_hours(profile, start - timedelta(minutes=lead)) for lead in profile.lead_minutes]
    return min((v for v in choices if now <= v <= start), default=None)
