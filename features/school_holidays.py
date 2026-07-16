#!/usr/bin/env python3
"""
Norwegian School Holidays Module for Inebotten
Contains a limited set of school vacation dates by fylke (county) for 2025-2026.

The data is static and must not be presented as a complete or current calendar.
"""

import re
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple


# Norwegian counties (fylker)
FYLKE_NAMES = {
    'oslo': 'Oslo',
    'rogaland': 'Rogaland',
    'møre_og_romsdal': 'Møre og Romsdal',
    'nordland': 'Nordland',
    'akershus': 'Akershus',
    'buskerud': 'Buskerud',
    'østfold': 'Østfold',
    'innlandet': 'Innlandet',
    'vestfold': 'Vestfold',
    'telemark': 'Telemark',
    'agder': 'Agder',
    'vestland': 'Vestland',
    'trøndelag': 'Trøndelag',
    'troms': 'Troms',
    'finnmark': 'Finnmark',
}

# School zones for winter holiday (vinterferie)
# Norway splits winter holiday into 3 weeks
VINTERFERIE_ZONES = {
    'uke_8': [
        'oslo', 'akershus', 'buskerud', 'østfold', 'innlandet',
        'vestfold', 'telemark',
    ],
    'uke_9': ['rogaland', 'agder', 'vestland'],
    'uke_10': [
        'møre_og_romsdal', 'trøndelag', 'nordland', 'troms', 'finnmark',
    ],
}

# 2025-2026 school year holidays
# Format: (start_date, end_date, name, affected_fylker or None for all)
SCHOOL_HOLIDAYS_2025_2026: List[Tuple[str, str, str, Optional[List[str]]]] = [
    # Autumn holiday (høstferie)
    ('06.10.2025', '10.10.2025', 'Høstferie', None),
    
    # Winter holiday (vinterferie) - different weeks by zone
    ('17.02.2026', '21.02.2026', 'Vinterferie (Uke 8)', VINTERFERIE_ZONES['uke_8']),
    ('24.02.2026', '28.02.2026', 'Vinterferie (Uke 9)', VINTERFERIE_ZONES['uke_9']),
    ('03.03.2026', '07.03.2026', 'Vinterferie (Uke 10)', VINTERFERIE_ZONES['uke_10']),
    
    # Easter holiday (påskeferie)
    ('30.03.2026', '06.04.2026', 'Påskeferie', None),
    
    # May break (sommerferie-start for some)
    # Note: Actual summer vacation varies by school, typically mid-June
]


CITY_TO_FYLKE = {
    'oslo': 'oslo',
    'drammen': 'buskerud',
    'fredrikstad': 'østfold',
    'sarpsborg': 'østfold',
    'lillestrøm': 'akershus',
    'sandvika': 'akershus',
    'ski': 'akershus',
    'stavanger': 'rogaland',
    'sandnes': 'rogaland',
    'haugesund': 'rogaland',
    'bergen': 'vestland',
    'førde': 'vestland',
    'sogndal': 'vestland',
    'trondheim': 'trøndelag',
    'steinkjer': 'trøndelag',
    'molde': 'møre_og_romsdal',
    'ålesund': 'møre_og_romsdal',
    'kristiansund': 'møre_og_romsdal',
    'bodø': 'nordland',
    'narvik': 'nordland',
    'svolvær': 'nordland',
    'tromsø': 'troms',
    'alta': 'finnmark',
    'hammerfest': 'finnmark',
    'kirkenes': 'finnmark',
    'kristiansand': 'agder',
    'arendal': 'agder',
    'grimstad': 'agder',
    'lillehammer': 'innlandet',
    'hamar': 'innlandet',
    'gjøvik': 'innlandet',
    'elverum': 'innlandet',
    'kongsvinger': 'innlandet',
    'tønsberg': 'vestfold',
    'tonsberg': 'vestfold',
    'sandefjord': 'vestfold',
    'larvik': 'vestfold',
    'porsgrunn': 'telemark',
    'skien': 'telemark',
    'notodden': 'telemark',
}


def parse_date(date_str: str) -> date:
    """Parse DD.MM.YYYY string to date"""
    return datetime.strptime(date_str, '%d.%m.%Y').date()


def _location_aliases() -> Dict[str, str]:
    aliases = {
        fylke_key.replace('_', ' '): fylke_key
        for fylke_key in FYLKE_NAMES
    }
    aliases.update({
        fylke_name.casefold(): fylke_key
        for fylke_key, fylke_name in FYLKE_NAMES.items()
    })
    aliases.update(CITY_TO_FYLKE)
    return aliases


def get_fylke_from_exact_location(location_hint: str) -> Optional[str]:
    """Resolve one complete place/county phrase, with an optional preposition."""

    if not isinstance(location_hint, str) or not location_hint.strip():
        return None
    normalized = " ".join(
        location_hint.casefold().replace('_', ' ').split()
    )
    normalized = re.sub(r"^(?:i|in|for)\s+", "", normalized, count=1)
    return _location_aliases().get(normalized)


def get_fylke_from_location(location_hint: str) -> Optional[str]:
    """Try to determine a county from a longer natural-language hint."""

    if not isinstance(location_hint, str) or not location_hint.strip():
        return None

    location_lower = " ".join(
        location_hint.casefold().replace('_', ' ').split()
    )
    aliases = _location_aliases()

    # Match complete place names only. Sorting longest-first makes overlapping
    # names deterministic, while the Unicode-aware word guards prevent e.g.
    # "Skien" and "skiing" from being interpreted as the town Ski.
    for place in sorted(aliases, key=len, reverse=True):
        pattern = rf"(?<!\w){re.escape(place)}(?!\w)"
        if re.search(pattern, location_lower):
            return aliases[place]
    
    return None


def get_school_holidays(
    fylke: Optional[str] = None,
    include_all: bool = False,
    reference_date: Optional[date] = None,
) -> List[Dict]:
    """
    Get school holidays for a specific fylke or all Norway
    
    Args:
        fylke: Fylke key (e.g., 'oslo', 'trøndelag') or None for all
        include_all: With no fylke, include every regional holiday. Kept for
            backwards compatibility when a fylke is supplied; it never adds
            another county's mutually exclusive regional holiday.
        reference_date: Date from which holidays count as current/upcoming.
    
    Returns:
        List of holiday dicts
    """
    today = reference_date or date.today()
    holidays = []
    
    for start_str, end_str, name, affected_fylker in SCHOOL_HOLIDAYS_2025_2026:
        start_date = parse_date(start_str)
        end_date = parse_date(end_str)
        
        # Check if this holiday applies to the requested fylke
        if affected_fylker is None:
            applies = True
        elif fylke:
            applies = fylke.casefold() in affected_fylker
        else:
            applies = include_all
        
        if applies and end_date >= today:
            holidays.append({
                'name': name,
                'start': start_str,
                'end': end_str,
                'start_date': start_date,
                'end_date': end_date,
                'affected_fylker': affected_fylker,
            })
    
    # Sort by start date
    holidays.sort(key=lambda x: x['start_date'])
    return holidays


def get_upcoming_holiday(
    fylke: Optional[str] = None,
    reference_date: Optional[date] = None,
) -> Optional[Dict]:
    """Get the next upcoming holiday for a fylke"""
    today = reference_date or date.today()
    holidays = get_school_holidays(
        fylke,
        include_all=True,
        reference_date=today,
    )
    
    for holiday in holidays:
        if holiday['end_date'] >= today:
            return holiday
    
    return None


def calculate_days_until(
    date_obj: date,
    reference_date: Optional[date] = None,
) -> int:
    """Calculate days until a date"""
    today = reference_date or date.today()
    delta = date_obj - today
    return delta.days


def format_holiday(
    holiday: Dict,
    lang: str = 'no',
    reference_date: Optional[date] = None,
) -> str:
    """Format a single holiday for display in specified language"""
    start = holiday['start']
    end = holiday['end']
    name = holiday['name']
    
    today = reference_date or date.today()
    days_until = calculate_days_until(holiday['start_date'], today)
    
    if lang == 'no':
        if days_until == 0:
            when = "Starter i dag!"
        elif days_until == 1:
            when = "Starter i morgen!"
        elif days_until < 0:
            # Already started
            days_left = calculate_days_until(holiday['end_date'], today)
            if days_left >= 0:
                when = f"Pågår! {days_left + 1} dager igjen"
            else:
                when = "Nettopp avsluttet"
        else:
            when = f"Om {days_until} dager"
    else:
        if days_until == 0:
            when = "Starts today!"
        elif days_until == 1:
            when = "Starts tomorrow!"
        elif days_until < 0:
            # Already started
            days_left = calculate_days_until(holiday['end_date'], today)
            if days_left >= 0:
                when = f"Ongoing! {days_left + 1} days left"
            else:
                when = "Just ended"
        else:
            when = f"In {days_until} days"
    
    return f"📚 **{name}**\n   {start} – {end}\n   {when}"


def format_holidays_list(
    fylke: Optional[str] = None,
    days: int = 90,
    lang: str = 'no',
    reference_date: Optional[date] = None,
) -> str:
    """
    Format upcoming holidays for display in specified language
    
    Args:
        fylke: Specific fylke or None for all
        days: How many days ahead to show
        lang: 'no' or 'en'
        reference_date: Start of the requested window. Defaults to today.
    
    Returns:
        Formatted string
    """
    today = reference_date or date.today()
    holidays = get_school_holidays(
        fylke,
        include_all=True,
        reference_date=today,
    )
    cutoff = today + timedelta(days=days)
    
    # Filter to upcoming holidays
    upcoming = [h for h in holidays if h['start_date'] <= cutoff]
    
    fylke_name = FYLKE_NAMES.get(fylke, 'Norge') if fylke else 'Norge'
    
    if not upcoming:
        last_verified = max(
            parse_date(end_str)
            for _, end_str, _, _ in SCHOOL_HOLIDAYS_2025_2026
        )
        if lang == 'no':
            if today > last_verified:
                coverage = (
                    "Datagrunnlaget inneholder bare verifiserte datoer til "
                    f"og med {last_verified.strftime('%d.%m.%Y')}, så jeg kan "
                    "ikke bekrefte skoleferier for perioden du spurte om. "
                    "Sjekk skolen eller kommunen for oppdaterte datoer."
                )
            else:
                coverage = (
                    "Jeg har ingen verifiserte feriedatoer for denne perioden. "
                    "Det betyr ikke at skolene ikke har ferie; sjekk skolen "
                    "eller kommunen for sikre datoer."
                )
            return f"📚 **Skoleferier – {fylke_name}**\n\n{coverage}"
        else:
            if today > last_verified:
                coverage = (
                    "The dataset only contains verified dates through "
                    f"{last_verified.strftime('%d.%m.%Y')}, so I cannot "
                    "confirm school holidays for the period you asked about. "
                    "Check the school or municipality for current dates."
                )
            else:
                coverage = (
                    "I do not have verified holiday dates for this period. "
                    "That does not mean schools have no holiday; check the "
                    "school or municipality for confirmed dates."
                )
            return f"📚 **School Holidays – {fylke_name}**\n\n{coverage}"
    
    if lang == 'no':
        lines = [f"📚 **Skoleferier – {fylke_name}**", ""]
    else:
        lines = [f"📚 **School Holidays – {fylke_name}**", ""]
    
    for holiday in upcoming[:5]:
        lines.append(format_holiday(holiday, lang, reference_date=today))
        lines.append("")
    
    return "\n".join(lines)


def get_next_vinterferie_week(fylke: str) -> Optional[int]:
    """Get which week winter holiday is for a specific fylke"""
    for week, fylker in VINTERFERIE_ZONES.items():
        if fylke in fylker:
            return int(week.split('_')[1])
    return None


# Quick test
if __name__ == "__main__":
    print("=== Norwegian School Holidays Test ===\n")
    
    # Test Oslo
    print("Oslo holidays:")
    print(format_holidays_list('oslo'))
    print()
    
    # Test Tromsø
    print("Troms og Finnmark holidays:")
    print(format_holidays_list('troms'))
    print()
    
    # Test location detection
    print("Location detection test:")
    locations = ['Jeg bor i Tromsø', 'Oslo sentrum', 'Bergen by', 'Trondheim']
    for loc in locations:
        fylke = get_fylke_from_location(loc)
        print(f"  '{loc}' → {FYLKE_NAMES.get(fylke, 'Unknown')}")
