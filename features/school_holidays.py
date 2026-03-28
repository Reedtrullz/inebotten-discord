#!/usr/bin/env python3
"""
Norwegian School Holidays Module for Inebotten
Contains school vacation schedules by fylke (county) for 2025-2026
"""

from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple


# Norwegian counties (fylker)
FYLKE_NAMES = {
    'oslo': 'Oslo',
    'rogaland': 'Rogaland',
    'møre_og_romsdal': 'Møre og Romsdal',
    'nordland': 'Nordland',
    'viken': 'Viken',
    'innlandet': 'Innlandet',
    'vestfold_og_telemark': 'Vestfold og Telemark',
    'agder': 'Agder',
    'vestland': 'Vestland',
    'trøndelag': 'Trøndelag',
    'troms_og_finnmark': 'Troms og Finnmark',
}

# School zones for winter holiday (vinterferie)
# Norway splits winter holiday into 3 weeks
VINTERFERIE_ZONES = {
    'uke_8': ['oslo', 'viken', 'innlandet', 'vestfold_og_telemark'],
    'uke_9': ['rogaland', 'agder', 'vestland'],
    'uke_10': ['møre_og_romsdal', 'trøndelag', 'nordland', 'troms_og_finnmark'],
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


def parse_date(date_str: str) -> date:
    """Parse DD.MM.YYYY string to date"""
    return datetime.strptime(date_str, '%d.%m.%Y').date()


def get_fylke_from_location(location_hint: str) -> Optional[str]:
    """
    Try to determine fylke from location hint
    
    Args:
        location_hint: Text that might contain location info
    
    Returns:
        fylke key or None
    """
    location_lower = location_hint.lower()
    
    # Direct matches
    for fylke_key, fylke_name in FYLKE_NAMES.items():
        if fylke_key.replace('_', ' ') in location_lower:
            return fylke_key
        if fylke_name.lower() in location_lower:
            return fylke_key
    
    # City hints
    city_to_fylke = {
        'oslo': 'oslo',
        'drammen': 'viken',
        'fredrikstad': 'viken',
        'sarpsborg': 'viken',
        'lillestrøm': 'viken',
        'sandvika': 'viken',
        'ski': 'viken',
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
        'tromsø': 'troms_og_finnmark',
        'alta': 'troms_og_finnmark',
        'hammerfest': 'troms_og_finnmark',
        'kirkenes': 'troms_og_finnmark',
        'kristiansand': 'agder',
        'arendal': 'agder',
        'grimstad': 'agder',
        'lillehammer': 'innlandet',
        'hamar': 'innlandet',
        'gjøvik': 'innlandet',
        'elverum': 'innlandet',
        'kongsvinger': 'innlandet',
        'tonsberg': 'vestfold_og_telemark',
        'sandefjord': 'vestfold_og_telemark',
        'larvik': 'vestfold_og_telemark',
        'porsgrunn': 'vestfold_og_telemark',
        'skien': 'vestfold_og_telemark',
        'notodden': 'vestfold_og_telemark',
    }
    
    for city, fylke in city_to_fylke.items():
        if city in location_lower:
            return fylke
    
    return None


def get_school_holidays(fylke: Optional[str] = None, 
                        include_all: bool = False) -> List[Dict]:
    """
    Get school holidays for a specific fylke or all Norway
    
    Args:
        fylke: Fylke key (e.g., 'oslo', 'trøndelag') or None for all
        include_all: If True, include holidays that apply to all
    
    Returns:
        List of holiday dicts
    """
    today = date.today()
    holidays = []
    
    for start_str, end_str, name, affected_fylker in SCHOOL_HOLIDAYS_2025_2026:
        start_date = parse_date(start_str)
        end_date = parse_date(end_str)
        
        # Check if this holiday applies to the requested fylke
        if affected_fylker is None:
            # Applies to all
            applies = True
        elif fylke and fylke.lower() in affected_fylker:
            applies = True
        elif include_all:
            applies = True
        else:
            applies = False
        
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


def get_upcoming_holiday(fylke: Optional[str] = None) -> Optional[Dict]:
    """Get the next upcoming holiday for a fylke"""
    holidays = get_school_holidays(fylke, include_all=True)
    today = date.today()
    
    for holiday in holidays:
        if holiday['end_date'] >= today:
            return holiday
    
    return None


def calculate_days_until(date_obj: date) -> int:
    """Calculate days until a date"""
    today = date.today()
    delta = date_obj - today
    return delta.days


def format_holiday(holiday: Dict, lang: str = 'no') -> str:
    """Format a single holiday for display in specified language"""
    start = holiday['start']
    end = holiday['end']
    name = holiday['name']
    
    days_until = calculate_days_until(holiday['start_date'])
    
    if lang == 'no':
        if days_until == 0:
            when = "Starter i dag!"
        elif days_until == 1:
            when = "Starter i morgen!"
        elif days_until < 0:
            # Already started
            days_left = calculate_days_until(holiday['end_date'])
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
            days_left = calculate_days_until(holiday['end_date'])
            if days_left >= 0:
                when = f"Ongoing! {days_left + 1} days left"
            else:
                when = "Just ended"
        else:
            when = f"In {days_until} days"
    
    return f"📚 **{name}**\n   {start} – {end}\n   {when}"


def format_holidays_list(fylke: Optional[str] = None, days: int = 90, lang: str = 'no') -> str:
    """
    Format upcoming holidays for display in specified language
    
    Args:
        fylke: Specific fylke or None for all
        days: How many days ahead to show
        lang: 'no' or 'en'
    
    Returns:
        Formatted string
    """
    holidays = get_school_holidays(fylke, include_all=True)
    today = date.today()
    cutoff = today + timedelta(days=days)
    
    # Filter to upcoming holidays
    upcoming = [h for h in holidays if h['start_date'] <= cutoff]
    
    fylke_name = FYLKE_NAMES.get(fylke, 'Norge') if fylke else 'Norge'
    
    if not upcoming:
        if lang == 'no':
            return f"📚 **Skoleferier – {fylke_name}**\n\nIngen ferier planlagt de neste månedene."
        else:
            return f"📚 **School Holidays – {fylke_name}**\n\nNo holidays planned in the coming months."
    
    if lang == 'no':
        lines = [f"📚 **Skoleferier – {fylke_name}**", ""]
    else:
        lines = [f"📚 **School Holidays – {fylke_name}**", ""]
    
    for holiday in upcoming[:5]:
        lines.append(format_holiday(holiday, lang))
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
    print(format_holidays_list('troms_og_finnmark'))
    print()
    
    # Test location detection
    print("Location detection test:")
    locations = ['Jeg bor i Tromsø', 'Oslo sentrum', 'Bergen by', 'Trondheim']
    for loc in locations:
        fylke = get_fylke_from_location(loc)
        print(f"  '{loc}' → {FYLKE_NAMES.get(fylke, 'Unknown')}")
