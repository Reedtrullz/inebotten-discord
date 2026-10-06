from dataclasses import dataclass
import json
import re
import unicodedata


MAX_ACTION_DRAFT_CHARS = 4096
MAX_EVENT_TITLE_CHARS = 160
MAX_EVENT_DATE_CHARS = 40
MAX_EVENT_TIME_CHARS = 20
_LEGACY_EVENT_RE = re.compile(
    r"^\[SAVE_EVENT:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\]$"
)


@dataclass
class SaveEventAction:
    action: str = "SAVE_EVENT"
    title: str = ""
    date: str = ""
    time: str = ""


@dataclass
class ShowDashboardAction:
    action: str = "SHOW_DASHBOARD"


@dataclass
class NoAction:
    action: str = "NONE"


def parse_action_draft(raw: str) -> dict | None:
    """Parse one bounded, allowlisted AI draft without executing it."""
    if not isinstance(raw, str) or not raw or len(raw) > MAX_ACTION_DRAFT_CHARS:
        return None
    if any(unicodedata.category(char).startswith("C") for char in raw):
        return None

    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError, TypeError):
        match = _LEGACY_EVENT_RE.fullmatch(raw.strip())
        if match is None:
            return None
        title, date, time = (part.strip() for part in match.groups())
        return _validated_event(title, date, time)

    if not isinstance(value, dict) or not isinstance(value.get("action"), str):
        return None
    action = value["action"]
    if action == "SHOW_DASHBOARD":
        return {"action": action} if set(value) == {"action"} else None
    if action == "SAVE_EVENT":
        if not set(value).issubset({"action", "title", "date", "time"}):
            return None
        title = value.get("title")
        date = value.get("date", "")
        time = value.get("time", "")
        if not all(isinstance(field, str) for field in (title, date, time)):
            return None
        return _validated_event(title, date, time)
    return None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate action field")
        result[key] = value
    return result


def _validated_event(title: str, date: str, time: str) -> dict | None:
    if any(
        unicodedata.category(char).startswith("C")
        for field in (title, date, time)
        for char in field
    ):
        return None
    title = title.strip()
    date = date.strip()
    time = time.strip()
    if not title or len(title) > MAX_EVENT_TITLE_CHARS:
        return None
    if len(date) > MAX_EVENT_DATE_CHARS or len(time) > MAX_EVENT_TIME_CHARS:
        return None
    return {"action": "SAVE_EVENT", "title": title, "date": date, "time": time}
