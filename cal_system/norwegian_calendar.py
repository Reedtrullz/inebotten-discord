#!/usr/bin/env python3
"""
Norwegian Calendar Data Module
Contains name days (navnedager), flag days (flaggdager), and Norwegian calendar utilities
"""

from datetime import datetime, date
import math

# Norwegian name days (navnedager) - simplified list with most common names
NAVNEDAGER = {
    1: {
        1: ["Nyttårsdag"],
        2: ["Dag", "Dagfinn"],
        3: ["Alfred", "Alf"],
        4: ["Roald"],
        5: ["Hanna", "Hanne"],
        6: ["Aslaug", "Åslaug"],
        7: ["Eldbjørg"],
        8: ["Gudmund", "Gunnar"],
        9: ["Gunnar", "Gunder"],
        10: ["Stig", "Stian"],
        11: ["Bente", "Bent"],
        12: ["Reidar", "Reidun"],
        13: ["Gisle"],
        14: ["Frode"],
        15: ["Lasse", "Lars"],
        16: ["Hjalmar"],
        17: ["Anton", "Tønnes"],
        18: ["Hildur", "Hild"],
        19: ["Marius"],
        20: ["Fabian", "Sebastian"],
        21: ["Agnes", "Agnete"],
        22: ["Ivan", "Vanja"],
        23: ["Emil", "Emilie"],
        24: ["Joakim", "Jakob"],
        25: ["Paul", "Pål"],
        26: ["Øystein", "Esten"],
        27: ["Gittan", "Gjertrud"],
        28: ["Karl", "Karla"],
        29: ["Herdis", "Hermod"],
        30: ["Gunnhild", "Gunhild"],
        31: ["Vidar", "Vigdis"],
    },
    2: {
        1: ["Birgit", "Birger"],
        2: ["Jomar", "Jomann"],
        3: ["Ansgar", "Åse"],
        4: ["Veronika", "Vera"],
        5: ["Agathe", "Ågot"],
        6: ["Dortea", "Dorte"],
        7: ["Rikard", "Rigmor"],
        8: ["Åshild", "Åsmund"],
        9: ["Lone", "Lona"],
        10: ["Ingfrid", "Ingrid"],
        11: ["Sigmund", "Sigrid"],
        12: ["Randulf", "Randall"],
        13: ["Svanhild", "Svanhilde"],
        14: ["Valentin"],
        15: ["Sigfred", "Sigfrid"],
        16: ["Julianne", "Julian"],
        17: ["Aleksander", "Alex"],
        18: ["Frøydis", "Frøy"],
        19: ["Ella", "Ellen"],
        20: ["Halldor", "Halldis"],
        21: ["Laura", "Laurits"],
        22: ["Marta", "Marte"],
        23: ["Torstein", "Torunn"],
        24: ["Mattias", "Mats"],
        25: ["Viktor", "Viktoria"],
        26: ["Ingeleif", "Ingeleiv"],
        27: ["Laila", "Lage"],
        28: ["Marit", "Maren"],
    },
    3: {
        1: ["Audny", "Audun"],
        2: ["Erland", "Erlend"],
        3: ["Gunnar", "Gunvor"],
        4: ["Ada", "Adolf"],
        5: ["Patrick", "Patrik"],
        6: ["Christer", "Kristian"],
        7: ["Arild", "Are"],
        8: ["Beate", "Beatrice"],
        9: ["Sverre", "Sverker"],
        10: ["Edel", "Edle"],
        11: ["Edvin", "Einar"],
        12: ["Grethe", "Greta"],
        13: ["Gjertrud", "Trude"],
        14: ["Matilde", "Mathilda"],
        15: ["Christel", "Kristel"],
        16: ["Birger", "Borgar"],
        17: ["Bjarne", "Bjørn"],
        18: ["Edvard", "Edmund"],
        19: ["Josef", "Josefine"],
        20: ["Aase", "Åse"],
        21: ["Bendik", "Benedikte"],
        22: ["Paula", "Pål"],
        23: ["Joakim", "Jakob"],
        24: ["Marie", "Mari"],
        25: ["Gabriel", "Gry"],
        26: ["Rudolf", "Rudi"],
        27: ["Lydia", "Lydie"],
        28: ["Jonas", "Jonatan"],
        29: ["Holger", "Olga"],
        30: ["Rolf", "Rolv"],
        31: ["Jon", "Jona"],
    },
    4: {
        1: ["Aron", "Arve"],
        2: ["Gudny", "Gudrun"],
        3: ["Frideborg", "Frida"],
        4: ["Nanna", "Nanni"],
        5: ["Irene", "Irina"],
        6: ["Didrik", "Diderik"],
        7: ["Gjermund", "Germund"],
        8: ["Pål", "Paul"],
        9: ["Gøran", "Jøran"],
        10: ["Erlend", "Erling"],
        11: ["Ylva", "Ulf"],
        12: ["Julius", "Julian"],
        13: ["Asta", "Astrid"],
        14: ["Ellen", "Elna"],
        15: ["Oliver", "Olivia"],
        16: ["Magnus", "Magne"],
        17: ["Gunnvald", "Gunvor"],
        18: ["Fredrik", "Fred"],
        19: ["Engel", "Engla"],
        20: ["Bjørnar", "Bjartmar"],
        21: ["Jean", "Jens"],
        22: ["Albert", "Albin"],
        23: ["Georg", "Jørgen"],
        24: ["Jarle", "Jarl"],
        25: ["Markus", "Mark"],
        26: ["Terese", "Terje"],
        27: ["Rolf", "Rune"],
        28: ["Peter", "Petter"],
        29: ["Toralf", "Torhild"],
        30: ["Gina", "Gine"],
    },
    5: {
        1: ["Valborg", "Valborga"],
        2: ["Katarina", "Katrine"],
        3: ["Gjert", "Gjøran"],
        4: ["Monika", "Mona"],
        5: ["Gøril", "Gørill"],
        6: ["Gudbrand", "Gullborg"],
        7: ["Torhild", "Torill"],
        8: ["Åge", "Åke"],
        9: ["Gisle", "Gislaug"],
        10: ["Aud", "Unn"],
        11: ["Helga", "Helge"],
        12: ["Halvard", "Hallvard"],
        13: ["Oda", "Odin"],
        14: ["Karl", "Karla"],
        15: ["Hallbjørn", "Halbjørg"],
        16: ["Sara", "Sarah"],
        17: ["Rebekka", "Rebecka"],
        18: ["Ingeborg", "Ingebjørg"],
        19: ["Erlend", "Erling"],
        20: ["Bjørn", "Bjørnar"],
        21: ["Hedda", "Hedvig"],
        22: ["Emil", "Emilie"],
        23: ["Einar", "Eindride"],
        24: ["Elisabeth", "Elisa"],
        25: ["Sofie", "Sofia"],
        26: ["Ragna", "Ragnar"],
        27: ["Ramona", "Ramund"],
        28: ["Gunnbjørg", "Gunnlaug"],
        29: ["Håkon", "Haakon"],
        30: ["Gard", "Geir"],
        31: ["Pernille", "Preben"],
    },
    6: {
        1: ["Runa", "Runar"],
        2: ["Erland", "Erlend"],
        3: ["Hege", "Hedda"],
        4: ["Marianne", "Mariann"],
        5: ["Torbjørg", "Torbjørn"],
        6: ["Gustav", "Gustavs"],
        7: ["Robert", "Robin"],
        8: ["Renate", "René"],
        9: ["Bergljot", "Bergly"],
        10: ["Ingvild", "Ingve"],
        11: ["Borgar", "Borghild"],
        12: ["Sigfrid", "Sigrunn"],
        13: ["Tone", "Tony"],
        14: ["Eskil", "Eskill"],
        15: ["Margit", "Margot"],
        16: ["Torhild", "Torill"],
        17: ["Torbjørn", "Tor"],
        18: ["Bjarne", "Bjørn"],
        19: ["Dagrun", "Dagny"],
        20: ["Torolf", "Torun"],
        21: ["Agnar", "Agnes"],
        22: ["Håkon", "Magne"],
        23: ["Sigrunn", "Sigvor"],
        24: ["Johanne", "Jannike"],
        25: ["Jonas", "Jonatan"],
        26: ["Stig", "Stian"],
        27: ["Torstein", "Torunn"],
        28: ["Lea", "Leif"],
        29: ["Peter", "Petter"],
        30: ["Solfrid", "Solfrød"],
    },
    7: {
        1: ["Jørgen", "Georg"],
        2: ["Kjartan", "Kjellaug"],
        3: ["Tom", "Tommy"],
        4: ["Ulrik", "Ulrika"],
        5: ["Kjellaug", "Kjetil"],
        6: ["Torbjørn", "Torvald"],
        7: ["Håkon", "Haakon"],
        8: ["Rakel", "Ragnhild"],
        9: ["Gøran", "Jøran"],
        10: ["Knut", "Knutt"],
        11: ["Kjetil", "Kjell"],
        12: ["Einar", "Eindride"],
        13: ["Gudrun", "Gunda"],
        14: ["Andrea", "Andrine"],
        15: ["Torbjørg", "Torbjørn"],
        16: ["Gudmund", "Gunnar"],
        17: ["Gullik", "Gulli"],
        18: ["Arnfinn", "Arnstein"],
        19: ["Gerhard", "Gert"],
        20: ["Margareta", "Margareth"],
        21: ["Johanne", "Jannike"],
        22: ["Malene", "Malin"],
        23: ["Brita", "Britt"],
        24: ["Kristine", "Kristin"],
        25: ["Jakob", "Jakoba"],
        26: ["Ana", "Anna"],
        27: ["Marta", "Marte"],
        28: ["Stig", "Stian"],
        29: ["Olav", "Olaf"],
        30: ["Astrid", "Asta"],
        31: ["Helge", "Helga"],
    },
    8: {
        1: ["Peder", "Petra"],
        2: ["Karin", "Kåre"],
        3: ["Torbjørg", "Torbjørn"],
        4: ["Arne", "Arnold"],
        5: ["Osvald", "Oskar"],
        6: ["Gjertrud", "Trude"],
        7: ["Didrik", "Diderik"],
        8: ["Trygve", "Tryggve"],
        9: ["Randi", "Randolf"],
        10: ["Lorents", "Lars"],
        11: ["Leksa", "Lekse"],
        12: ["Klara", "Claire"],
        13: ["Malle", "Mally"],
        14: ["Hallvard", "Halvor"],
        15: ["Sølvi", "Solveig"],
        16: ["Brynhild", "Brynjar"],
        17: ["Bernhard", "Bernt"],
        18: ["Tormod", "Tormund"],
        19: ["Sigvald", "Sigvard"],
        20: ["Bjørn", "Bjørnar"],
        21: ["Gyda", "Gydel"],
        22: ["Haldor", "Haldis"],
        23: ["Signe", "Signy"],
        24: ["Torben", "Torbjørn"],
        25: ["Ludvig", "Lovise"],
        26: ["Jørgen", "Georg"],
        27: ["Inga", "Inge"],
        28: ["Elisabet", "Isabel"],
        29: ["Rolf", "Rolv"],
        30: ["Benjamin", "Benedicte"],
        31: ["Hjalmar"],
    },
    9: {
        1: ["Runhild", "Runar"],
        2: ["Alvhild", "Alv"],
        3: ["Dina", "Dine"],
        4: ["Mikael", "Mikal"],
        5: ["Kjartan", "Kjellaug"],
        6: ["Randi", "Randolf"],
        7: ["Regine", "Ragne"],
        8: ["Alfhild", "Alf"],
        9: ["Torbjørg", "Torbjørn"],
        10: ["Tord", "Tor"],
        11: ["Dagny", "Dag"],
        12: ["Tora", "Tor"],
        13: ["Stian", "Stig"],
        14: ["Ingebjørg", "Ingeborg"],
        15: ["Lillian", "Lilly"],
        16: ["Gyda", "Gydel"],
        17: ["Ingvar", "Ingvild"],
        18: ["Erling", "Erlend"],
        19: ["Marta", "Marte"],
        20: ["Signe", "Signy"],
        21: ["Liv", "Lifa"],
        22: ["Kåre", "Karin"],
        23: ["Sverre", "Sverker"],
        24: ["Torbjørn", "Torleif"],
        25: ["Ingegerd", "Ingegjerd"],
        26: ["Einar", "Eindride"],
        27: ["Dag", "Daga"],
        28: ["Lena", "Lene"],
        29: ["Mikael", "Mikal"],
        30: ["Helga", "Helge"],
    },
    10: {
        1: ["Solveig", "Sølvi"],
        2: ["Ludvig", "Lovise"],
        3: ["Oda", "Odin"],
        4: ["Randi", "Randolf"],
        5: ["Brynjar", "Brynjulf"],
        6: ["Torbjørg", "Torbjørn"],
        7: ["Birgitte", "Birgit"],
        8: ["Nils", "Nina"],
        9: ["Maren", "Marit"],
        10: ["Knut", "Knutt"],
        11: ["Kjetil", "Kjell"],
        12: ["Egil", "Einar"],
        13: ["Trude", "Gjertrud"],
        14: ["Kaia", "Kai"],
        15: ["Hedda", "Hedvig"],
        16: ["Morten", "Martin"],
        17: ["Inger", "Inge"],
        18: ["Kasper", "Jesper"],
        19: ["Henrik", "Henry"],
        20: ["Bente", "Bent"],
        21: ["Birger", "Borgar"],
        22: ["Kjellaug", "Kjetil"],
        23: ["Søren", "Sølvi"],
        24: ["Ragna", "Ragnar"],
        25: ["Sverre", "Sverker"],
        26: ["Torbjørn", "Toralf"],
        27: ["Birgit", "Birger"],
        28: ["Simon", "Simen"],
        29: ["Nils", "Nina"],
        30: ["Aksel", "Åse"],
        31: ["Hallvard", "Halvor"],
    },
    11: {
        1: ["Vigdis", "Vigdís"],
        2: ["Tove", "Tuva"],
        3: ["Dagny", "Dag"],
        4: ["Omar", "Odd"],
        5: ["Torbjørg", "Torbjørn"],
        6: ["Gudrun", "Gunda"],
        7: ["Ingeborg", "Ingebjørg"],
        8: ["Rolf", "Rolv"],
        9: [["Torstein", "Torunn"]],
        10: ["Gudmund", "Gunnar"],
        11: ["Martin", "Martine"],
        12: ["Torkjell", "Torkil"],
        13: ["Kirsten", "Kirsti"],
        14: ["Fredrik", "Fred"],
        15: ["Oddfrid", "Oddvar"],
        16: ["Edmund", "Edward"],
        17: ["Håkon", "Magne"],
        18: ["Marianne", "Mariann"],
        19: ["Elisabeth", "Elisa"],
        20: ["Cecilie", "Cecilia"],
        21: ["Mikael", "Mikal"],
        22: ["Cecilie", "Cecilia"],
        23: ["Klement", "Klaus"],
        24: ["Gudrun", "Gunda"],
        25: ["Katarina", "Katrine"],
        26: ["Trine", "Trond"],
        27: ["Ludvig", "Lovise"],
        28: ["Ruben", "Rune"],
        29: ["Frode", "Frøydis"],
        30: ["Trygve", "Tryggve"],
    },
    12: {
        1: ["Arnold", "Arnt"],
        2: ["Borghild", "Borgny"],
        3: ["Sveinung", "Svein"],
        4: ["Barbara", "Barbro"],
        5: ["Sigrid", "Sigrunn"],
        6: ["Gunnbjørg", "Gunnlaug"],
        7: ["Ingegerd", "Ingegjerd"],
        8: ["Ida", "Idar"],
        9: ["Gudrun", "Gunda"],
        10: ["Aron", "Arve"],
        11: ["Dagmar", "Dagmær"],
        12: ["Daniel", "Dan"],
        13: ["Lucia", "Lukas"],
        14: ["Steinar", "Stein"],
        15: ["Hildur", "Hild"],
        16: ["Inga", "Inge"],
        17: ["Inga", "Inge"],
        18: ["Kristian", "Kristen"],
        19: ["Abraham", "Abram"],
        20: ["Isak", "Isa"],
        21: ["Tomas", "Tom"],
        22: ["Ingebrigt", "Ingeborg"],
        23: ["Signe", "Signy"],
        24: ["Juleaften"],
        25: ["Jul", "Juledag"],
        26: ["Stefan", "Steffen"],
        27: ["Torbjørn", "Toralf"],
        28: ["Unni", "Unn"],
        29: ["Vida", "Vidar"],
        30: ["Ragnhild", "Ragni"],
        31: ["Sylvester", "Sylfest"],
    },
}

# Norwegian flag days (flaggdager) - when the Norwegian flag should be flown
FLAGGDAGER = {
    (1, 1): "Nyttårsdag",
    (1, 21): "Prinsesse Ingrid Alexandras fødselsdag",
    (2, 6): "Samefolkets dag",
    (2, 21): "Kong Harald Vs fødselsdag",
    (3, 8): "Kvinnedagen",
    (3, 20): "Vårdagjevning (Flaggdag 2025)",
    (4, 1): "Aprilsnarr (ikke offisiell)",
    (4, 9): "Befrielsesdagen 1940",
    (4, 21): "Dronning Mauds fødselsdag (offisiell)",
    (5, 1): "Arbeidernes dag",
    (5, 8): "Frigjøringsdagen 1945",
    (5, 17): "Grunnlovsdagen",
    (5, 20): "Kronprinsparets fødselsdag",
    (6, 7): "Unionsoppløsningen 1905",
    (6, 23): "Sankthans",
    (7, 4): "Dronning Sonjas fødselsdag",
    (7, 20): "Kronprins Haakon Magnuss fødselsdag",
    (7, 29): "Olsok",
    (8, 19): "Kronprinsesse Mette-Marits fødselsdag",
    (9, 15): "Stortingsvalg (ved valgår)",
    (10, 24): "FN-dagen",
    (11, 1): "Allehelgensdag",
    (12, 10): "Nobeldagen",
    (12, 25): "Juledag",
}


def get_navnedag(month, day):
    """
    Get Norwegian name day for a given date
    Returns list of names or empty list if none
    """
    try:
        names = NAVNEDAGER.get(month, {}).get(day, [])
        # Handle case where names might be nested in a list
        if names and isinstance(names[0], list):
            names = names[0]
        return names
    except Exception as e:
        print(f"[CALENDAR] Holiday parse error: {e}")
        return []


def get_flaggdag(month, day):
    """
    Get Norwegian flag day description for a given date
    Returns description string or None
    """
    return FLAGGDAGER.get((month, day))


def get_week_number(date_obj=None):
    """
    Get ISO week number for a date
    Norwegian standard (ISO 8601)
    """
    if date_obj is None:
        date_obj = date.today()
    return date_obj.isocalendar()[1]


def format_date_norwegian(date_obj=None, include_week=True):
    """
    Format date in Norwegian style with week number
    Example: "Mandag 17. mars 2025 (Uke 12)"
    """
    if date_obj is None:
        date_obj = datetime.now()

    weekdays = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag"]
    months = [
        "januar",
        "februar",
        "mars",
        "april",
        "mai",
        "juni",
        "juli",
        "august",
        "september",
        "oktober",
        "november",
        "desember",
    ]

    weekday = weekdays[date_obj.weekday()]
    day = date_obj.day
    month = months[date_obj.month - 1]
    year = date_obj.year

    date_str = f"{weekday} {day}. {month} {year}"

    if include_week:
        week = get_week_number(date_obj)
        date_str += f" (Uke {week})"

    return date_str


def get_todays_info():
    """
    Get all relevant Norwegian calendar info for today
    Returns dict with navnedag, flaggdag, week number
    """
    today = date.today()

    return {
        "date": today,
        "formatted_date": format_date_norwegian(today),
        "week_number": get_week_number(today),
        "navnedag": get_navnedag(today.month, today.day),
        "flaggdag": get_flaggdag(today.month, today.day),
        "is_sunday": today.weekday() == 6,
        "is_holiday": FLAGGDAGER.get((today.month, today.day)) is not None,
    }


# Moon phase calculations
def get_moon_phase(date_obj=None):
    """
    Calculate moon phase for a given date
    Returns tuple: (phase_name_norwegian, emoji, illumination_percent)
    """
    if date_obj is None:
        date_obj = date.today()

    # Known new moon: January 6, 2000
    known_new_moon = date(2000, 1, 6)
    days_since_new = (date_obj - known_new_moon).days

    # Lunar cycle is approximately 29.53 days
    lunar_cycle = 29.53059
    moon_age = days_since_new % lunar_cycle

    # Calculate phase
    phase = moon_age / lunar_cycle

    # Determine phase name
    if phase < 0.03 or phase > 0.97:
        return ("Nymåne", "🌑", int((1 - abs(phase - 0.5) * 2) * 100))
    elif phase < 0.22:
        return ("Voksende månesigd", "🌒", int(phase * 4 * 100))
    elif phase < 0.28:
        return ("Første kvarter", "🌓", 50)
    elif phase < 0.47:
        return ("Voksende måne", "🌔", int(phase * 2 * 100))
    elif phase < 0.53:
        return ("Fullmåne", "🌕", 100)
    elif phase < 0.72:
        return ("Minkende måne", "🌖", int((1 - phase) * 2 * 100))
    elif phase < 0.78:
        return ("Siste kvarter", "🌗", 50)
    else:
        return ("Minkende månesigd", "🌘", int((1 - phase) * 4 * 100))


def get_sunrise_sunset(day_of_year=None, latitude=59.9, longitude=10.7):
    """
    Calculate approximate sunrise and sunset times for Oslo
    This is a simplified calculation
    """
    if day_of_year is None:
        day_of_year = date.today().timetuple().tm_yday

    # Oslo coordinates approximately 59.9°N, 10.7°E
    # Simplified calculation - not precise but reasonable for display

    # Daylight variation throughout the year (Oslo)
    # Longest day ~18.5 hours (June 21)
    # Shortest day ~6 hours (December 21)

    import math

    # Convert day to radians (0 to 2π)
    day_rad = 2 * math.pi * (day_of_year - 1) / 365.25

    # Calculate daylight hours using sine wave
    # Peak at day ~172 (June 21)
    avg_daylight = 12.25
    amplitude = 6.25  # variation from average
    daylight_hours = avg_daylight + amplitude * math.sin(day_rad - 1.39)

    # Calculate sunrise/sunset from daylight hours (approximate)
    sunrise_hour = 12 - (daylight_hours / 2)
    sunset_hour = 12 + (daylight_hours / 2)

    sunrise = f"{int(sunrise_hour):02d}:{int((sunrise_hour % 1) * 60):02d}"
    sunset = f"{int(sunset_hour):02d}:{int((sunset_hour % 1) * 60):02d}"

    daylight = f"{int(daylight_hours)}t {int((daylight_hours % 1) * 60):02d}m"

    return sunrise, sunset, daylight


if __name__ == "__main__":
    # Test the module
    print("=== Norwegian Calendar Test ===\n")

    info = get_todays_info()
    print(f"Dato: {info['formatted_date']}")
    print(f"Ukenummer: {info['week_number']}")

    if info["navnedag"]:
        print(f"Navnedag: {', '.join(info['navnedag'])}")

    if info["flaggdag"]:
        print(f"Flaggdag: {info['flaggdag']} 🇳🇴")

    moon = get_moon_phase()
    print(f"Månefase: {moon[0]} {moon[1]}")

    sunrise, sunset, daylight = get_sunrise_sunset()
    print(f"Soloppgang: {sunrise}")
    print(f"Solnedgang: {sunset}")
    print(f"Dagslys: {daylight}")
