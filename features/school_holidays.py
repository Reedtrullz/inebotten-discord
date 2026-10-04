"""Reviewed, locality-specific Norwegian school calendars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
from typing import Any, Literal, Optional


Coverage = Literal["verified", "partial", "unavailable"]
CALENDAR_DATA_PATH = Path(__file__).resolve().parent / "data" / "school_calendars.json"
DEFAULT_MAX_AGE_DAYS = 365


@dataclass(frozen=True)
class SchoolSchedule:
    """A school-year schedule with explicit provenance and coverage."""

    locality_id: str
    locality_name: str
    school_year: str
    coverage: Coverage
    source_refs: list[str]
    verified_at: Optional[date]
    holidays: list[dict[str, Any]]
    coverage_note: str = ""
    coverage_note_en: str = ""


def parse_date(date_str: str) -> date:
    """Parse the legacy DD.MM.YYYY date representation."""
    return datetime.strptime(date_str, "%d.%m.%Y").date()


def get_locality_from_location(location_hint: str) -> Optional[str]:
    """Recognize only municipality names with reviewed local calendars."""
    normalized = (location_hint or "").casefold()
    for locality_id in ("oslo", "trondheim"):
        if re.search(rf"(?<!\w){locality_id}(?!\w)", normalized):
            return locality_id
    return None


def get_fylke_from_location(location_hint: str) -> Optional[str]:
    """Compatibility alias that recognizes covered municipalities only."""
    return get_locality_from_location(location_hint)


def _school_year_for(today: date) -> str:
    start_year = today.year if today.month >= 8 else today.year - 1
    return f"{start_year}-{start_year + 1}"


def _valid_school_year(school_year: str) -> bool:
    match = re.fullmatch(r"(\d{4})-(\d{4})", school_year or "")
    return bool(match and int(match.group(2)) == int(match.group(1)) + 1)


def _unavailable(
    locality_id: str,
    school_year: str,
    locality_name: Optional[str] = None,
    note: str = "",
) -> SchoolSchedule:
    return SchoolSchedule(
        locality_id=locality_id,
        locality_name=locality_name or locality_id,
        school_year=school_year,
        coverage="unavailable",
        source_refs=[],
        verified_at=None,
        holidays=[],
        coverage_note=note,
        coverage_note_en=note,
    )


def _append_note(existing: str, addition: str) -> str:
    return "; ".join(part for part in (existing.strip(), addition) if part)


def get_school_schedule(
    locality_id: str, school_year: str, today: date
) -> SchoolSchedule:
    """Load a reviewed schedule; missing, stale, and incomplete data stays explicit."""
    normalized_locality = (locality_id or "").strip().casefold()
    if not normalized_locality or not _valid_school_year(school_year):
        return _unavailable(
            normalized_locality or "unknown",
            school_year or "",
            note="Ugyldig kommune eller skoleår." if not _valid_school_year(school_year) else "",
        )

    try:
        data = json.loads(CALENDAR_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _unavailable(
            normalized_locality,
            school_year,
            note="Skolerutedataene kunne ikke leses.",
        )

    if not isinstance(data, dict) or data.get("schema_version") != 1:
        return _unavailable(
            normalized_locality,
            school_year,
            note="Skjemaversjonen for skolerutedata støttes ikke.",
        )

    calendars = data.get("calendars", {})
    locality = calendars.get(normalized_locality) if isinstance(calendars, dict) else None
    if not isinstance(locality, dict):
        return _unavailable(
            normalized_locality,
            school_year,
            note="Ingen kvalitetssikret skolerute er registrert for kommunen.",
        )

    locality_name = str(locality.get("name") or normalized_locality)
    years = locality.get("school_years", {})
    record = years.get(school_year) if isinstance(years, dict) else None
    if not isinstance(record, dict):
        return _unavailable(
            normalized_locality,
            school_year,
            locality_name,
            "Ingen kvalitetssikret skolerute er registrert for dette skoleåret.",
        )

    coverage = record.get("coverage")
    if coverage not in ("verified", "partial"):
        coverage = "partial"
    note_no = str(record.get("coverage_note") or "")
    note_en = str(record.get("coverage_note_en") or note_no)
    raw_sources = record.get("source_refs")
    if not isinstance(raw_sources, list):
        raw_sources = []
        coverage = "partial"
        note_no = _append_note(note_no, "Kildeliste mangler.")
        note_en = _append_note(note_en, "Source list is missing.")
    source_refs = [
        source
        for source in raw_sources
        if isinstance(source, str) and source.startswith("https://")
    ]
    if not source_refs:
        coverage = "partial"
        note_no = _append_note(note_no, "Ingen gyldige kildelenker er registrert.")
        note_en = _append_note(note_en, "No valid source links are recorded.")

    verified_at_value = record.get("verified_at")
    try:
        verified_at = date.fromisoformat(verified_at_value)
    except (TypeError, ValueError):
        verified_at = None
        coverage = "partial"
        note_no = _append_note(note_no, "Kontrolldato mangler eller er ugyldig.")
        note_en = _append_note(note_en, "Review date is missing or invalid.")

    if verified_at is not None:
        max_age_days = data.get("max_verified_age_days", DEFAULT_MAX_AGE_DAYS)
        if not isinstance(max_age_days, int) or isinstance(max_age_days, bool) or max_age_days < 1:
            max_age_days = DEFAULT_MAX_AGE_DAYS
        age_days = (today - verified_at).days
        if age_days < 0:
            coverage = "partial"
            note_no = _append_note(
                note_no,
                f"Kontrolldatoen ligger i fremtiden ({verified_at:%d.%m.%Y}).",
            )
            note_en = _append_note(
                note_en,
                f"Review date is in the future ({verified_at:%d.%m.%Y}).",
            )
        elif age_days > max_age_days:
            coverage = "partial"
            note_no = _append_note(
                note_no,
                f"Årlig datakontroll er utløpt ({verified_at:%d.%m.%Y}).",
            )
            note_en = _append_note(
                note_en,
                f"Annual data review expired ({verified_at:%d.%m.%Y}).",
            )

    raw_holidays = record.get("holidays")
    if not isinstance(raw_holidays, list):
        raw_holidays = []
        coverage = "partial"
        note_no = _append_note(note_no, "Ferielisten mangler eller er ugyldig.")
        note_en = _append_note(note_en, "Holiday list is missing or invalid.")

    start_year = int(school_year[:4])
    first_day = date(start_year, 8, 1)
    # The published school-year schedule also identifies the following August
    # start day, which bounds the summer break belonging to this school year.
    last_day = date(start_year + 1, 8, 31)
    holidays: list[dict[str, Any]] = []
    for item in raw_holidays:
        try:
            if not isinstance(item, dict) or not item.get("name"):
                raise ValueError("missing holiday name")
            start = date.fromisoformat(item["start"])
            end = date.fromisoformat(item["end"])
            if start > end or start < first_day or end > last_day:
                raise ValueError("invalid holiday range")
        except (KeyError, TypeError, ValueError):
            coverage = "partial"
            note_no = _append_note(note_no, "Ugyldig datoområde i ferielisten; oppføringen ble utelatt.")
            note_en = _append_note(note_en, "Invalid holiday range; the entry was omitted.")
            continue

        holiday = {
            "name": str(item["name"]),
            "start": start.strftime("%d.%m.%Y"),
            "end": end.strftime("%d.%m.%Y"),
            "start_date": start,
            "end_date": end,
        }
        if item.get("source_note"):
            holiday["source_note"] = str(item["source_note"])
        holidays.append(holiday)

    holidays.sort(key=lambda holiday: holiday["start_date"])
    return SchoolSchedule(
        locality_id=normalized_locality,
        locality_name=locality_name,
        school_year=school_year,
        coverage=coverage,
        source_refs=source_refs,
        verified_at=verified_at,
        holidays=holidays,
        coverage_note=note_no,
        coverage_note_en=note_en,
    )


def calculate_days_until(date_obj: date, today: Optional[date] = None) -> int:
    """Calculate whole calendar days from today to a date."""
    return (date_obj - (today or date.today())).days


def format_holiday(
    holiday: dict[str, Any], lang: str = "no", today: Optional[date] = None
) -> str:
    """Format a single holiday for display."""
    start = holiday["start"]
    end = holiday["end"]
    name = holiday["name"]
    days_until = calculate_days_until(holiday["start_date"], today)

    if days_until == 0:
        when = "Starter i dag!" if lang == "no" else "Starts today!"
    elif days_until == 1:
        when = "Starter i morgen!" if lang == "no" else "Starts tomorrow!"
    elif days_until < 0:
        days_left = calculate_days_until(holiday["end_date"], today)
        if days_left >= 0:
            if lang == "no":
                when = f"Pågår! {days_left + 1} dager igjen"
            else:
                when = f"Ongoing! {days_left + 1} days left"
        else:
            when = "Nettopp avsluttet" if lang == "no" else "Just ended"
    else:
        when = f"Om {days_until} dager" if lang == "no" else f"In {days_until} days"
    return f"📚 **{name}**\n   {start} – {end}\n   {when}"


def format_holidays_list(
    fylke: Optional[str] = None,
    days: int = 90,
    lang: str = "no",
    *,
    locality_id: Optional[str] = None,
    today: Optional[date] = None,
    school_year: Optional[str] = None,
) -> str:
    """Format upcoming holidays while keeping coverage and source visible."""
    norwegian = lang == "no"
    now = today or date.today()
    requested_locality = locality_id if locality_id is not None else fylke
    if requested_locality is None or not requested_locality.strip():
        if norwegian:
            return (
                "📚 **Velg kommune for skoleruta**\n\n"
                "Nevn Oslo eller Trondheim. Kvalitetssikrede data finnes for skoleåret 2026–2027."
            )
        return (
            "📚 **Choose a municipality for the school calendar**\n\n"
            "Mention Oslo or Trondheim. Reviewed data is available for school year 2026–2027."
        )

    year = school_year or _school_year_for(now)
    schedule = get_school_schedule(requested_locality, year, now)
    display_year = year.replace("-", "–")
    locality_name = schedule.locality_name
    if schedule.coverage == "unavailable":
        if norwegian:
            return (
                f"📚 **Skolerute ikke tilgjengelig – {locality_name} ({display_year})**\n\n"
                "Jeg har ingen kvalitetssikret skolerute for dette stedet og skoleåret. "
                "Velg Oslo eller Trondheim hvis det gjelder skoleåret 2026–2027."
            )
        return (
            f"📚 **School calendar unavailable – {locality_name} ({display_year})**\n\n"
            "I do not have a reviewed school calendar for this locality and school year. "
            "Choose Oslo or Trondheim for school year 2026–2027."
        )

    if norwegian:
        lines = [f"📚 **Skoleferier – {locality_name} ({display_year})**", ""]
        if schedule.coverage == "verified":
            lines.append(f"Dekning: kvalitetssikret {schedule.verified_at:%d.%m.%Y}.")
            if schedule.coverage_note:
                lines.append(f"Merknad: {schedule.coverage_note}")
        else:
            lines.append("⚠️ Dekning: delvis; noen fridager kan mangle.")
            if schedule.coverage_note:
                lines.append(schedule.coverage_note)
    else:
        lines = [f"📚 **School holidays – {locality_name} ({display_year})**", ""]
        if schedule.coverage == "verified":
            lines.append(f"Coverage: reviewed {schedule.verified_at:%d.%m.%Y}.")
            if schedule.coverage_note_en:
                lines.append(f"Note: {schedule.coverage_note_en}")
        else:
            lines.append("⚠️ Coverage: partial; some days off may be missing.")
            if schedule.coverage_note_en:
                lines.append(schedule.coverage_note_en)

    try:
        cutoff = now + timedelta(days=max(0, int(days)))
    except (OverflowError, TypeError, ValueError):
        cutoff = now
    upcoming = [
        holiday
        for holiday in schedule.holidays
        if holiday["end_date"] >= now and holiday["start_date"] <= cutoff
    ]
    if upcoming:
        lines.append("")
        lines.extend(format_holiday(holiday, lang, now) for holiday in upcoming[:5])
    elif norwegian:
        if schedule.coverage == "verified":
            lines.extend(["", f"Ingen oppførte ferier de neste {max(0, int(days))} dagene."])
        else:
            lines.extend(
                [
                    "",
                    "Ingen publiserte ferier i perioden; delvis dekning betyr at dette ikke bekrefter at alle dager er fridager.",
                ]
            )
    elif schedule.coverage == "verified":
        lines.extend(["", f"No listed holidays in the next {max(0, int(days))} days."])
    else:
        lines.extend(
            [
                "",
                "No published holidays in this period; partial coverage does not confirm that all days off are listed.",
            ]
        )

    lines.extend(["", "Kilde:" if norwegian else "Source:"])
    lines.extend(schedule.source_refs)
    return "\n".join(lines)


def get_school_holidays(
    fylke: Optional[str] = None,
    include_all: bool = False,
    *,
    today: Optional[date] = None,
    school_year: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Compatibility adapter; only reviewed locality IDs return a schedule."""
    del include_all  # Nationwide or county-wide fallback is intentionally unavailable.
    now = today or date.today()
    if not fylke:
        return []
    locality_id = fylke.strip().casefold()
    schedule = get_school_schedule(locality_id, school_year or _school_year_for(now), now)
    return [holiday for holiday in schedule.holidays if holiday["end_date"] >= now]


def get_upcoming_holiday(fylke: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Return the next holiday for a reviewed locality, if one is available."""
    holidays = get_school_holidays(fylke)
    return holidays[0] if holidays else None


def get_next_vinterferie_week(fylke: str) -> Optional[int]:
    """Return the ISO week for a locality's reviewed winter holiday."""
    today = date.today()
    schedule = get_school_schedule(fylke, _school_year_for(today), today)
    for holiday in schedule.holidays:
        if "vinterferie" in holiday["name"].casefold():
            return holiday["start_date"].isocalendar().week
    return None


if __name__ == "__main__":
    print("=== Norwegian School Holidays ===\n")
    for locality in ("oslo", "trondheim"):
        print(format_holidays_list(locality))
        print()
