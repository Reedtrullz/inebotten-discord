#!/usr/bin/env python3
"""Central intent router for Inebotten message handling."""

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Dict, Optional


class BotIntent(Enum):
    HELP = "help"
    STATUS = "status"
    PROFILE = "profile"
    CALENDAR_HELP = "calendar_help"
    CALENDAR_LIST = "calendar_list"
    CALENDAR_SYNC = "calendar_sync"
    CALENDAR_DELETE = "calendar_delete"
    CALENDAR_COMPLETE = "calendar_complete"
    CALENDAR_EDIT = "calendar_edit"
    CALENDAR_CLEAR = "calendar_clear"
    CALENDAR_ITEM = "calendar_item"
    POLL_CREATE = "poll_create"
    POLL_VOTE = "poll_vote"
    COUNTDOWN = "countdown"
    WATCHLIST = "watchlist"
    WORD_OF_DAY = "word_of_day"
    QUOTE = "quote"
    AURORA = "aurora"
    SCHOOL_HOLIDAYS = "school_holidays"
    PRICE = "price"
    HOROSCOPE = "horoscope"
    COMPLIMENT = "compliment"
    CALCULATOR = "calculator"
    SHORTEN_URL = "shorten_url"
    DAILY_DIGEST = "daily_digest"
    SEARCH = "search"
    DASHBOARD = "dashboard"
    SET_LOCATION = "set_location"
    AI_CHAT = "ai_chat"


@dataclass(frozen=True)
class IntentResult:
    intent: BotIntent
    confidence: float
    payload: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""


HELP_KEYWORDS = [
    "hjelp", "help", "kommandoer", "commands",
    "hva kan du gjøre", "hva kan du", "hva gjør du",
    "funksjoner", "features", "capabilities",
    "hva er du", "hvem er du", "what can you do",
]

STATUS_KEYWORDS = [
    "bot status", "status bot", "inebotten status",
    "health", "helse", "diagnose", "diagnostics",
]

CALENDAR_KEYWORDS = [
    "kalender", "calendar", "arrangementer", "events",
    "kommende", "planlagt", "påminnelser", "huskeliste",
    "synk", "sync", "synkroniser", "gcal",
]
SYNC_KEYWORDS = ["synk", "sync", "synkroniser", "hent fra google", "oppdater fra google"]
DELETE_KEYWORDS = ["slett", "delete", "fjern"]
COMPLETE_KEYWORDS = ["ferdig", "done", "complete", "fullført"]
EDIT_KEYWORDS = ["endre", "edit", "oppdater"]
LIST_KEYWORDS = ["liste", "vis", "se", "oversikt"]
CLEAR_KEYWORDS = ["tøm", "clear", "empty", "slett alt", "fjern alt"]

PROFILE_KEYWORDS = [
    "status", "bio", "om meg", "about me", "endre navn", "spiller", "ser på",
    "playing", "watching",
]

WORD_OF_DAY_KEYWORDS = ["dagens ord", "word of the day", "lære meg et ord"]
AURORA_KEYWORDS = ["nordlys", "aurora", "nordly"]
SCHOOL_HOLIDAYS_KEYWORDS = ["skoleferie", "skoleferier", "vinterferie", "påskeferie"]
DAILY_DIGEST_KEYWORDS = ["daglig oppsummering", "daily digest", "oppsummering", "summary"]


class IntentRouter:
    """Routes cleaned, authorized message text to one concrete bot intent."""

    def __init__(self, monitor):
        self.monitor = monitor

    def route(self, content: str, guild_id: Optional[int] = None) -> IntentResult:
        content_lower = content.lower().strip()

        # Explicit operational/help/calendar commands first.
        if "kalender" in content_lower and any(word in content_lower for word in ["hjelp", "help", "guide"]):
            return IntentResult(BotIntent.CALENDAR_HELP, 0.99, reason="calendar_help_keyword")

        if self._is_status_command(content_lower):
            return IntentResult(BotIntent.STATUS, 0.99, reason="status_keyword")

        if any(keyword in content_lower for keyword in HELP_KEYWORDS):
            return IntentResult(BotIntent.HELP, 0.96, reason="help_keyword")

        if self._is_profile_command(content_lower):
            return IntentResult(BotIntent.PROFILE, 0.95, reason="profile_keyword")

        calendar_command = self._route_calendar_command(content_lower)
        if calendar_command:
            return calendar_command

        poll_cmd = self.monitor.parse_poll_command(content)
        if poll_cmd:
            return IntentResult(BotIntent.POLL_CREATE, 0.95, {"poll": poll_cmd}, "poll_parser")

        vote = self.monitor.parse_vote(content)
        if vote and self._has_active_poll(guild_id):
            return IntentResult(BotIntent.POLL_VOTE, 0.95, {"vote": vote}, "active_poll_vote")

        countdown_result = self.monitor.countdown.parse_countdown_query(content)
        if countdown_result:
            return IntentResult(BotIntent.COUNTDOWN, 0.93, {"countdown": countdown_result}, "countdown_parser")

        watchlist_cmd = self.monitor.parse_watchlist_command(content)
        if watchlist_cmd:
            return IntentResult(BotIntent.WATCHLIST, 0.93, {"watchlist": watchlist_cmd}, "watchlist_parser")

        if any(phrase in content_lower for phrase in WORD_OF_DAY_KEYWORDS):
            return IntentResult(BotIntent.WORD_OF_DAY, 0.95, reason="word_of_day_keyword")

        quote_cmd = self.monitor.parse_quote_command(content)
        if quote_cmd:
            return IntentResult(BotIntent.QUOTE, 0.9, {"quote": quote_cmd}, "quote_parser")

        if any(word in content_lower for word in AURORA_KEYWORDS):
            return IntentResult(BotIntent.AURORA, 0.9, reason="aurora_keyword")

        if any(phrase in content_lower for phrase in SCHOOL_HOLIDAYS_KEYWORDS):
            return IntentResult(BotIntent.SCHOOL_HOLIDAYS, 0.9, reason="school_holidays_keyword")

        price_cmd = self.monitor.parse_price_command(content)
        if price_cmd:
            return IntentResult(BotIntent.PRICE, 0.88, {"price": price_cmd}, "price_parser")

        horoscope_cmd = self.monitor.parse_horoscope_command(content)
        if horoscope_cmd:
            return IntentResult(BotIntent.HOROSCOPE, 0.88, {"horoscope": horoscope_cmd}, "horoscope_parser")

        compliment_cmd = self.monitor.parse_compliment_command(content)
        if compliment_cmd:
            return IntentResult(BotIntent.COMPLIMENT, 0.86, {"compliment": compliment_cmd}, "compliment_parser")

        calc_cmd = self.monitor.parse_calculator_command(content)
        if calc_cmd:
            return IntentResult(BotIntent.CALCULATOR, 0.9, {"calculator": calc_cmd}, "calculator_parser")

        shorten_cmd = self.monitor.parse_shorten_command(content)
        if shorten_cmd:
            return IntentResult(BotIntent.SHORTEN_URL, 0.9, {"shorten": shorten_cmd}, "shorten_parser")

        if any(phrase in content_lower for phrase in DAILY_DIGEST_KEYWORDS):
            return IntentResult(BotIntent.DAILY_DIGEST, 0.9, reason="daily_digest_keyword")

        calendar_item = self._route_calendar_item(content)
        if calendar_item:
            return calendar_item

        search_info = self.monitor.detect_search_intent(content)
        if search_info and self._looks_contextual_enough_for_search(content_lower, search_info):
            return IntentResult(BotIntent.SEARCH, 0.72, {"search": search_info}, "search_intent")

        wants_dashboard, dashboard_reason = self.monitor.conversation.should_show_dashboard(content, guild_id)
        if wants_dashboard:
            return IntentResult(BotIntent.DASHBOARD, 0.7, {"dashboard_reason": dashboard_reason}, "dashboard_intent")

        location_cmd = self._route_location_command(content)
        if location_cmd:
            return location_cmd

        return IntentResult(BotIntent.AI_CHAT, 0.5, reason="fallback")

    def _route_calendar_command(self, content_lower: str) -> Optional[IntentResult]:
        if not any(word in content_lower for word in CALENDAR_KEYWORDS + DELETE_KEYWORDS + COMPLETE_KEYWORDS + EDIT_KEYWORDS + CLEAR_KEYWORDS):
            return None

        if any(word in content_lower for word in SYNC_KEYWORDS):
            return IntentResult(BotIntent.CALENDAR_SYNC, 0.98, reason="calendar_sync_keyword")
        if any(word in content_lower for word in DELETE_KEYWORDS):
            return IntentResult(BotIntent.CALENDAR_DELETE, 0.98, reason="calendar_delete_keyword")
        if any(word in content_lower for word in COMPLETE_KEYWORDS):
            return IntentResult(BotIntent.CALENDAR_COMPLETE, 0.98, reason="calendar_complete_keyword")
        if any(word in content_lower for word in EDIT_KEYWORDS):
            return IntentResult(BotIntent.CALENDAR_EDIT, 0.95, reason="calendar_edit_keyword")
        if any(word in content_lower for word in CLEAR_KEYWORDS):
            return IntentResult(BotIntent.CALENDAR_CLEAR, 0.98, reason="calendar_clear_keyword")
        if any(word in content_lower for word in LIST_KEYWORDS) or content_lower in CALENDAR_KEYWORDS:
            return IntentResult(BotIntent.CALENDAR_LIST, 0.92, reason="calendar_list_keyword")
        return IntentResult(BotIntent.CALENDAR_LIST, 0.85, reason="calendar_keyword_default")

    def _route_calendar_item(self, content: str) -> Optional[IntentResult]:
        try:
            parsed = self.monitor.nlp_parser.parse_task_with_recurrence(content)
            if not parsed:
                parsed = self.monitor.nlp_parser.parse_event(content)
        except (ValueError, KeyError, AttributeError) as exc:
            return IntentResult(BotIntent.AI_CHAT, 0.2, {"error": str(exc)}, "calendar_parser_error")

        if parsed:
            parsed = self._resolve_calendar_followup(content, parsed)
            return IntentResult(BotIntent.CALENDAR_ITEM, 0.86, {"calendar_item": parsed}, "calendar_nlp")
        return None

    def _route_location_command(self, content: str) -> Optional[IntentResult]:
        """Detect when a user is setting their location."""
        content_lower = content.lower()
        
        # Phrases like "Jeg bor i Trondheim", "Min lokasjon er Oslo", "Sett lokasjon til Bergen"
        patterns = [
            r"(?:jeg bor i|min lokasjon er|sett (?:min )?lokasjon(?:en)? til|jeg er fra|jeg holder til i)\s+([a-zæøå\s]+)",
            r"(?:i'm from|i live in|my location is|set (?:my )?location to)\s+([a-z\s]+)"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content_lower)
            if match:
                city = match.group(1).strip()
                # Validate if it's a known city or at least seems like one
                from features.weather_api import extract_city
                found_city = extract_city(city)
                if found_city:
                    return IntentResult(BotIntent.SET_LOCATION, 0.95, {"city": found_city}, "location_pattern")
        
        return None

    def _resolve_calendar_followup(self, content: str, parsed: Dict[str, Any]) -> Dict[str, Any]:
        """Replace vague follow-up titles like "det" with the recent offered reminder topic."""
        title = str(parsed.get("title", "")).strip()
        content_lower = content.lower()
        vague_title = re.fullmatch(r"(det|that|dette|den|it)(?:\s+.*)?", title.lower() or "") is not None
        reminder_followup = any(phrase in content_lower for phrase in ["minn meg", "påminn meg", "remind me"])

        if not (vague_title and reminder_followup):
            return parsed

        topic = self._infer_recent_reminder_topic()
        if topic:
            parsed = dict(parsed)
            parsed["title"] = topic[0].upper() + topic[1:]
            parsed["type"] = "task"
        return parsed

    def _infer_recent_reminder_topic(self) -> Optional[str]:
        conversation = getattr(self.monitor, "conversation", None)
        threads = getattr(conversation, "threads", None)
        if not threads:
            return None

        recent_messages = []
        for messages in threads.values():
            recent_messages.extend(messages[-6:])

        recent_messages.sort(key=lambda msg: msg.get("timestamp"), reverse=True)
        for msg in recent_messages:
            if not msg.get("is_bot"):
                continue
            topic = self._extract_reminder_offer_topic(str(msg.get("content", "")))
            if topic:
                return topic
        return None

    def _extract_reminder_offer_topic(self, text: str) -> Optional[str]:
        patterns = [
            r"påminnelse\s+om\s+å\s+([^?!.:\n]+)",
            r"minne\s+deg\s+på\s+å\s+([^?!.:\n]+)",
            r"reminder\s+to\s+([^?!.:\n]+)",
            r"remind\s+you\s+to\s+([^?!.:\n]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            topic = re.sub(r"\s+", " ", match.group(1)).strip(" -–—,")
            topic = re.sub(r"\s+(eller|or)\s+.*$", "", topic, flags=re.IGNORECASE).strip(" -–—,")
            if len(topic) >= 2:
                return topic
        return None

    def _is_status_command(self, content_lower: str) -> bool:
        return any(keyword in content_lower for keyword in STATUS_KEYWORDS)

    def _is_profile_command(self, content_lower: str) -> bool:
        if self._is_status_command(content_lower):
            return False
        if content_lower.startswith(("bio ", "about me ", "endre bio ")):
            return True
        if content_lower.startswith(("spiller ", "playing ", "ser på ", "watching ")):
            return True
        if content_lower.startswith("status "):
            return any(status in content_lower for status in ["online", "idle", "dnd", "invisible", "offline"])
        return any(keyword in content_lower for keyword in PROFILE_KEYWORDS if keyword not in {"status"})

    def _has_active_poll(self, guild_id: Optional[int]) -> bool:
        if guild_id is None:
            return False
        try:
            return bool(self.monitor.poll.get_active_polls(guild_id))
        except Exception:
            return False

    def _looks_contextual_enough_for_search(self, content_lower: str, search_info: Dict[str, str]) -> bool:
        if search_info.get("type") == "news":
            return True
        if content_lower.strip() in {"hva skjer", "hva skjer?", "what's up", "what is up"}:
            return False
        context_markers = [
            " i ", " på ", " om ", " for ", " hos ", "til ", "trondheim", "oslo",
            "bergen", "tromsø", "helga", "helgen", "siste", "nå", "today",
        ]
        return any(marker in content_lower for marker in context_markers)
