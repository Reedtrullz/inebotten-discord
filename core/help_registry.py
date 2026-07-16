"""Immutable, executable help catalog shared by Discord, web, and tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.eval_fixtures import EvalFixture
from core.intent_models import BotIntent, IntentRisk


@dataclass(frozen=True, slots=True)
class HelpCategory:
    id: str
    title_no: str
    title_en: str
    description_no: str
    description_en: str


@dataclass(frozen=True, slots=True)
class HelpExample:
    id: str
    category: str
    locale: Literal["nb", "nn", "en"]
    display_phrase: str
    route_phrase: str
    intent: BotIntent
    operation: str
    expected_payload_json: str
    risk_level: IntentRisk
    requires_confirmation: bool
    fixture: EvalFixture


HELP_CATEGORIES: tuple[HelpCategory, ...] = (
    HelpCategory(
        "hjelp",
        "🤖 Hjelp",
        "🤖 Help",
        "Se hva Inebotten kan gjøre.",
        "See what Inebotten can do.",
    ),
    HelpCategory(
        "kalender",
        "📅 Kalender",
        "📅 Calendar",
        "Opprett, finn og endre kalenderoppføringer.",
        "Create, find, and change calendar entries.",
    ),
    HelpCategory(
        "påminnelser",
        "⏰ Påminnelser",
        "⏰ Reminders",
        "Opprett og følg opp personlige påminnelser.",
        "Create and follow up personal reminders.",
    ),
    HelpCategory(
        "avstemning",
        "📊 Avstemninger",
        "📊 Polls",
        "Lag, vis og administrer avstemninger.",
        "Create, view, and manage polls.",
    ),
    HelpCategory(
        "watchlist",
        "🎬 Watchlist",
        "🎬 Watchlist",
        "Lagre filmer og serier du vil se.",
        "Save movies and series you want to watch.",
    ),
    HelpCategory(
        "sitater",
        "💬 Sitater",
        "💬 Quotes",
        "Lagre, vis og rediger sitater.",
        "Save, view, and edit quotes.",
    ),
    HelpCategory(
        "bursdager",
        "🎂 Bursdager",
        "🎂 Birthdays",
        "Registrer og vis bursdager med løst Discord-eierskap.",
        "Register and view birthdays with resolved Discord ownership.",
    ),
    HelpCategory(
        "vær",
        "🌦️ Vær og sted",
        "🌦️ Weather and location",
        "Vis væroversikt og lagre fast sted.",
        "View weather overview and save a home location.",
    ),
    HelpCategory(
        "verktøy",
        "🧰 Verktøy",
        "🧰 Tools",
        "Søk, regn og forkort lenker.",
        "Search, calculate, and shorten links.",
    ),
    HelpCategory(
        "profil",
        "👤 Profil",
        "👤 Profile",
        "Endre Inebotten-status og aktivitet.",
        "Change Inebotten status and activity.",
    ),
    HelpCategory(
        "minne",
        "🧠 Minne",
        "🧠 Memory",
        "Vis, eksporter eller slett ditt lagrede brukerminne.",
        "View, export, or delete your stored user memory.",
    ),
    HelpCategory(
        "oversikt",
        "📋 Oversikt",
        "📋 Overview",
        "Vis botstatus og samlede oversikter.",
        "View bot status and combined overviews.",
    ),
    HelpCategory(
        "moro",
        "✨ Moro",
        "✨ Fun",
        "Hent nordlys, priser, horoskop og andre lette funksjoner.",
        "Get aurora, prices, horoscopes, and other light features.",
    ),
)


def _example(
    id: str,
    category: str,
    locale: Literal["nb", "nn", "en"],
    phrase: str,
    intent: BotIntent,
    operation: str,
    payload: str,
    risk: IntentRisk,
    confirm: bool = False,
    fixture: EvalFixture = EvalFixture.EMPTY,
) -> HelpExample:
    return HelpExample(
        id=id,
        category=category,
        locale=locale,
        display_phrase=phrase,
        route_phrase=phrase,
        intent=intent,
        operation=operation,
        expected_payload_json=payload,
        risk_level=risk,
        requires_confirmation=confirm,
        fixture=fixture,
    )


RO = IntentRisk.READ_ONLY
ADD = IntentRisk.ADDITIVE
MUT = IntentRisk.MUTATING
DEST = IntentRisk.DESTRUCTIVE

HELP_EXAMPLES: tuple[HelpExample, ...] = (
    _example("help-nb", "hjelp", "nb", "hva kan du gjøre?", BotIntent.HELP, "help", "{}", RO),
    _example("help-nn", "hjelp", "nn", "kva kan du gjere?", BotIntent.HELP, "help", "{}", RO),
    _example("help-en", "hjelp", "en", "show me your commands", BotIntent.HELP, "help", "{}", RO),
    _example("cal-create", "kalender", "nb", "kan du legge inn et møte med Ola i morgen kl 14?", BotIntent.CALENDAR_ITEM, "calendar_item", '{"calendar_item":{"title":"Møte med Ola","date":"15.07.2026","time":"14:00","type":"event","days_offset":1}}', ADD),
    _example("cal-list", "kalender", "nb", "kan du vise meg kalenderen?", BotIntent.CALENDAR_LIST, "calendar_list", "{}", RO),
    _example("cal-search", "kalender", "nb", "søk kalender møte", BotIntent.CALENDAR_SEARCH, "calendar_search", '{"query":"møte"}', RO, fixture=EvalFixture.CALENDAR_TITLE_MEETING),
    _example("cal-fact-check-nb", "kalender", "nb", "jeg tror tidspunktet for Møte med Ola er feil", BotIntent.CALENDAR_FACT_CHECK, "calendar_fact_check", '{"calendar_fact_check":{"action":"start","field":"schedule","target":"Møte med Ola"}}', RO, fixture=EvalFixture.CALENDAR_TITLE_MEETING),
    _example("cal-fact-check-nn", "kalender", "nn", "eg trur tidspunktet for Møte med Ola er feil", BotIntent.CALENDAR_FACT_CHECK, "calendar_fact_check", '{"calendar_fact_check":{"action":"start","field":"schedule","target":"Møte med Ola"}}', RO, fixture=EvalFixture.CALENDAR_TITLE_MEETING),
    _example("cal-fact-check-en", "kalender", "en", "I think the time for Møte med Ola is wrong", BotIntent.CALENDAR_FACT_CHECK, "calendar_fact_check", '{"calendar_fact_check":{"action":"start","field":"schedule","target":"Møte med Ola"}}', RO, fixture=EvalFixture.CALENDAR_TITLE_MEETING),
    _example("cal-edit", "kalender", "nb", "endre møte med Ola til fredag kl 10", BotIntent.CALENDAR_EDIT, "calendar_edit", '{"calendar_edit":{"target":"møte med Ola","changes":{"date":"17.07.2026","time":"10:00"}}}', MUT, fixture=EvalFixture.CALENDAR_TITLE_MEETING),
    _example("cal-delete", "kalender", "nb", "kan du slette møtet med Ola?", BotIntent.CALENDAR_DELETE, "calendar_delete", '{"calendar_target":{"target":"møte med Ola"}}', DEST, True, EvalFixture.CALENDAR_TITLE_MEETING),
    _example("cal-complete", "kalender", "nb", "kan du markere møtet med Ola ferdig?", BotIntent.CALENDAR_COMPLETE, "calendar_complete", '{"calendar_target":{"target":"møte med Ola"}}', MUT, fixture=EvalFixture.CALENDAR_TITLE_MEETING),
    _example("cal-sync", "kalender", "nb", "synk kalender", BotIntent.CALENDAR_SYNC, "calendar_sync", "{}", MUT),
    _example("cal-auth", "kalender", "nb", "kalender auth", BotIntent.CALENDAR_AUTH, "calendar_auth", '{}', MUT, True),
    _example("cal-list-en", "kalender", "en", "show calendar", BotIntent.CALENDAR_LIST, "calendar_list", "{}", RO),
    _example("rem-create", "påminnelser", "nb", "kan du minne meg på å ringe legen om 2 timer?", BotIntent.REMINDER_CREATE, "reminder.add", '{"reminder":{"action":"add","text":"ringe legen","due_at":"2026-07-14T14:00:00+02:00","due_date":"14.07.2026","time":"14:00","timezone":"Europe/Oslo"}}', ADD),
    _example("rem-list", "påminnelser", "nb", "kan du vise meg alle påminnelsene mine?", BotIntent.REMINDER_LIST, "reminder.list", '{"reminder":{"action":"list"}}', RO, fixture=EvalFixture.ACTIVE_REMINDER),
    _example("rem-search", "påminnelser", "nb", "søk påminnelse lege", BotIntent.REMINDER_SEARCH, "reminder.search", '{"reminder":{"action":"search","query":"lege"}}', RO, fixture=EvalFixture.ACTIVE_REMINDER),
    _example("rem-edit", "påminnelser", "nb", "endre påminnelse 1 tekst: Ring tannlegen", BotIntent.REMINDER_EDIT, "reminder.edit", '{"reminder":{"action":"edit","number":1,"changes":{"text":"Ring tannlegen"}}}', MUT, fixture=EvalFixture.ACTIVE_REMINDER),
    _example("rem-complete", "påminnelser", "nb", "ferdig påminnelse 1", BotIntent.REMINDER_COMPLETE, "reminder.complete", '{"reminder":{"action":"complete","number":1}}', MUT, fixture=EvalFixture.ACTIVE_REMINDER),
    _example("rem-delete", "påminnelser", "nb", "kan du slette påminnelsen 1?", BotIntent.REMINDER_DELETE, "reminder.delete", '{"reminder":{"action":"delete","number":1}}', DEST, True, EvalFixture.ACTIVE_REMINDER),
    _example("rem-create-en", "påminnelser", "en", "remind me to call the doctor in 2 hours", BotIntent.REMINDER_CREATE, "reminder.add", '{"reminder":{"action":"add","text":"call the doctor","due_at":"2026-07-14T14:00:00+02:00","due_date":"14.07.2026","time":"14:00","timezone":"Europe/Oslo"}}', ADD),
    _example("poll-create", "avstemning", "nb", "kan du lage en avstemning: Hva spiser vi? pizza, burger eller taco", BotIntent.POLL_CREATE, "poll_create", '{"poll":{"question":"Hva spiser vi?","options":["pizza","burger","taco"],"lang":"no"}}', ADD),
    _example("poll-list", "avstemning", "nb", "kan du vise aktive avstemninger?", BotIntent.POLL_LIST, "poll_list", "{}", RO, fixture=EvalFixture.ACTIVE_POLL),
    _example("poll-vote", "avstemning", "nb", "stem 1", BotIntent.POLL_VOTE, "poll_vote", '{"vote":{"option":1,"poll_id":"poll-1"}}', MUT, fixture=EvalFixture.ACTIVE_POLL),
    _example("poll-edit", "avstemning", "nb", "kan du redigere avstemningen 1 spørsmål: Middag?", BotIntent.POLL_EDIT, "poll_edit", '{"poll_edit":{"target":1,"question":"Middag?"}}', MUT, fixture=EvalFixture.ACTIVE_POLL),
    _example("poll-close", "avstemning", "nb", "kan du lukke avstemningen 1?", BotIntent.POLL_CLOSE, "poll_close", '{"poll_close":{"target":1}}', MUT, fixture=EvalFixture.ACTIVE_POLL),
    _example("poll-delete", "avstemning", "nb", "kan du slette avstemningen 1?", BotIntent.POLL_DELETE, "poll_delete", '{"poll_delete":{"target":1}}', DEST, True, EvalFixture.ACTIVE_POLL),
    _example("watch-add", "watchlist", "nb", "kan du huske at jeg vil se Inception?", BotIntent.WATCHLIST, "watchlist.add", '{"watchlist":{"action":"add","title":"Inception","type":null,"lang":"no"}}', ADD),
    _example("watch-list", "watchlist", "nb", "hva har jeg på watchlisten min?", BotIntent.WATCHLIST, "watchlist.status", '{"watchlist":{"action":"status","lang":"no"}}', RO),
    _example("watch-suggest", "watchlist", "nb", "hva skal vi se?", BotIntent.WATCHLIST, "watchlist.suggest", '{"watchlist":{"action":"suggest","type":null,"genre":null,"lang":"no"}}', RO),
    _example("watch-edit", "watchlist", "nb", "endre watchlist 1 tittel: The Matrix", BotIntent.WATCHLIST, "watchlist.edit", '{"watchlist":{"action":"edit","index":1,"title":"The Matrix","lang":"no"}}', MUT),
    _example("watch-remove", "watchlist", "nb", "fjern watchlist 1", BotIntent.WATCHLIST, "watchlist.remove", '{"watchlist":{"action":"remove","index":1,"type":null,"lang":"no"}}', DEST, True),
    _example("watch-add-en", "watchlist", "en", "could you add Inception to my watchlist?", BotIntent.WATCHLIST, "watchlist.add", '{"watchlist":{"action":"add","title":"Inception","type":null,"lang":"en"}}', ADD),
    _example("quote-get", "sitater", "nb", "kan du vise meg et sitat?", BotIntent.QUOTE, "quote.get", '{"quote":{"action":"get","lang":"no"}}', RO),
    _example("quote-list", "sitater", "nb", "kan du vise meg sitatene?", BotIntent.QUOTE_LIST, "quote.list", '{"quote":{"action":"list","lang":"no"}}', RO),
    _example("quote-save", "sitater", "nb", "kan du lagre dette som et sitat: Et klokt sitat", BotIntent.QUOTE, "quote.save", '{"quote":{"action":"save","text":"Et klokt sitat","lang":"no"}}', ADD),
    _example("quote-edit", "sitater", "nb", "endre sitat 1 tekst: Ny tekst", BotIntent.QUOTE_EDIT, "quote.edit", '{"quote":{"action":"edit","index":1,"text":"Ny tekst","lang":"no"}}', MUT),
    _example("quote-delete", "sitater", "nb", "slett sitat 1", BotIntent.QUOTE_DELETE, "quote.delete", '{"quote":{"action":"delete","index":1,"lang":"no"}}', DEST, True),
    _example("birthday-add", "bursdager", "nb", "kan du legge til bursdagen min 15. mai?", BotIntent.BIRTHDAY_CREATE, "birthday.add", '{"birthday":{"action":"add","user_id":7,"display_name":"Kari","day":15,"month":5}}', ADD),
    _example("birthday-list", "bursdager", "nn", "kven har bursdag snart?", BotIntent.BIRTHDAY_LIST, "birthday.list", '{"birthday":{"action":"list","scope":"upcoming"}}', RO),
    _example("birthday-edit", "bursdager", "nb", "kan du endre bursdagen min til 20. mai?", BotIntent.BIRTHDAY_EDIT, "birthday.edit", '{"birthday":{"action":"edit","user_id":7,"day":20,"month":5}}', MUT),
    _example("weather", "vær", "nb", "kan du vise meg været?", BotIntent.DASHBOARD, "dashboard", '{"dashboard_reason":"explicit_request"}', RO),
    _example("location", "vær", "nb", "jeg bor i Trondheim", BotIntent.SET_LOCATION, "set_location", '{"city":"trondheim"}', MUT),
    _example("shorten", "verktøy", "nb", "kan du forkorte https://example.invalid", BotIntent.SHORTEN_URL, "shorten_url", '{"shorten":{"url":"https://example.invalid"}}', RO),
    _example("calculate", "verktøy", "nb", "kan du regne ut 2+2?", BotIntent.CALCULATOR, "calculator", '{"calculator":{"type":"math","expression":"2+2"}}', RO),
    _example("search", "verktøy", "nb", "kan du søke på nettet etter tog til Trondheim?", BotIntent.SEARCH, "search", '{"search":{"query":"tog til Trondheim","type":"web"}}', RO),
    _example("profile-status", "profil", "nb", "kan du sette statusen til online?", BotIntent.PROFILE, "profile.status", '{"profile":{"action":"status","value":"online"}}', MUT),
    _example("profile-playing", "profil", "nb", "kan du sette aktiviteten til å spille CS2?", BotIntent.PROFILE, "profile.playing", '{"profile":{"action":"playing","value":"CS2"}}', MUT),
    _example("profile-watching", "profil", "nb", "kan du sette aktiviteten til å se på Netflix?", BotIntent.PROFILE, "profile.watching", '{"profile":{"action":"watching","value":"Netflix"}}', MUT),
    _example("memory-view", "minne", "nb", "kan du vise hva du husker om meg?", BotIntent.MEMORY_VIEW, "memory.view", '{"memory":{"action":"view"}}', RO),
    _example("memory-export", "minne", "nb", "kan du eksportere minnet mitt?", BotIntent.MEMORY_EXPORT, "memory.export", '{"memory":{"action":"export"}}', RO),
    _example("memory-delete", "minne", "nb", "kan du slette minnet mitt?", BotIntent.MEMORY_DELETE, "memory.delete", '{"memory":{"action":"delete"}}', DEST, True),
    _example("dashboard", "oversikt", "nb", "kan du vise meg en oversikt?", BotIntent.DASHBOARD, "dashboard", '{"dashboard_reason":"explicit_request"}', RO),
    _example("status", "oversikt", "nb", "kan du vise meg botstatus?", BotIntent.STATUS, "status", "{}", RO),
    _example("digest", "oversikt", "nb", "kan du vise meg dagens oppsummering?", BotIntent.DAILY_DIGEST, "daily_digest", "{}", RO),
    _example("aurora", "moro", "nb", "kan jeg se nordlys i kveld?", BotIntent.AURORA, "aurora", "{}", RO),
    _example("school-holidays", "moro", "nb", "kan du vise skoleferiene i Tromsø?", BotIntent.SCHOOL_HOLIDAYS, "school_holidays", "{}", RO),
    _example("word", "moro", "nb", "kan du lære meg et ord?", BotIntent.WORD_OF_DAY, "word_of_day", "{}", RO),
    _example("price", "moro", "nb", "kan du vise meg prisen på BTC?", BotIntent.PRICE, "price", '{"price":{"type":"crypto","asset":"BTC","coin_id":"bitcoin","display_name":"BTC"}}', RO),
    _example("horoscope", "moro", "nb", "kan du vise meg horoskopet for væren?", BotIntent.HOROSCOPE, "horoscope", '{"horoscope":{"sign":"Aries","sign_key":"væren"}}', RO),
    _example("compliment", "moro", "nb", "kan du gi meg et kompliment?", BotIntent.COMPLIMENT, "compliment", '{"compliment":{"action":"compliment","user":null}}', RO),
)


def examples_for_catalog(locale: str) -> tuple[HelpExample, ...]:
    normalized = locale.casefold()
    if normalized not in {"no", "nb", "nn", "en"}:
        raise ValueError(f"unsupported help locale: {locale}")
    accepted = {"en"} if normalized == "en" else {"nb", "nn"}
    return tuple(
        example for example in HELP_EXAMPLES if example.locale in accepted
    )


def catalog_sections(
    locale: str,
) -> tuple[tuple[HelpCategory, tuple[HelpExample, ...]], ...]:
    examples = examples_for_catalog(locale)
    return tuple(
        (category, rows)
        for category in HELP_CATEGORIES
        if (
            rows := tuple(
                row for row in examples if row.category == category.id
            )
        )
    )


DISCORD_MESSAGE_LIMIT = 2_000


def render_discord_help_chunks(locale: str) -> tuple[str, ...]:
    english = locale.casefold() == "en"
    chunks: list[str] = []
    current = ""
    for category, examples in catalog_sections(locale):
        section_lines = [
            category.title_en if english else category.title_no,
            (
                category.description_en
                if english
                else category.description_no
            ),
            *(
                f"• @Inebotten {example.display_phrase}"
                for example in examples
            ),
        ]
        section = "\n".join(section_lines)
        if len(section) <= DISCORD_MESSAGE_LIMIT:
            candidate = f"{current}\n{section}" if current else section
            if len(candidate) <= DISCORD_MESSAGE_LIMIT:
                current = candidate
                continue
            if current:
                chunks.append(current)
            current = section
            continue

        if current:
            chunks.append(current)
            current = ""
        for line in section_lines:
            if len(line) > DISCORD_MESSAGE_LIMIT:
                raise ValueError("help line exceeds Discord message limit")
            candidate = f"{current}\n{line}" if current else line
            if len(candidate) <= DISCORD_MESSAGE_LIMIT:
                current = candidate
                continue
            chunks.append(current)
            current = line
    if current:
        chunks.append(current)
    return tuple(chunks)


__all__ = [
    "DISCORD_MESSAGE_LIMIT",
    "HELP_CATEGORIES",
    "HELP_EXAMPLES",
    "HelpCategory",
    "HelpExample",
    "catalog_sections",
    "examples_for_catalog",
    "render_discord_help_chunks",
]
