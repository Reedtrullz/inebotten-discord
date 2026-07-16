"""Scoped, synchronous pending-action capability state."""

from __future__ import annotations

import copy
import re
import unicodedata
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum

from discord.utils import escape_markdown

from cal_system.temporal_resolver import TemporalResolver
from core.dispatch_result import DispatchOutcome
from core.intent_models import BotIntent, IntentResult
from core.message_context import ConversationKey
from core.nlu_metrics import NLUMetrics
from core.utterance_semantics import CONFIRMATIONS, TRAILING_CANCELLATIONS


class PendingKind(str, Enum):
    CONFIRMATION = "confirmation"
    CHOICE = "choice"


class PendingStatus(str, Enum):
    PRESENTING = "presenting"
    READY = "ready"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class PendingResolutionKind(str, Enum):
    NONE = "none"
    CONFIRM = "confirm"
    CANCEL = "cancel"
    SELECT = "select"
    CORRECT = "correct"
    EXPIRED = "expired"


class PendingTargetFamily(str, Enum):
    CALENDAR = "calendar"
    REMINDER = "reminder"
    POLL = "poll"
    WATCHLIST = "watchlist"
    QUOTE = "quote"
    BIRTHDAY = "birthday"
    MEMORY = "memory"


def _without_discord_control_surface(value: object) -> str:
    without_controls = "".join(
        char
        for char in str(value)
        if unicodedata.category(char) not in {"Cc", "Cf"}
    )
    one_line = " ".join(without_controls.split())
    url_safe = re.sub(
        r"(?i)\bhttps?://",
        lambda match: match.group(0).replace("://", "：//"),
        one_line,
    )
    token_safe = re.sub(r"<(?=[@#])", "‹", url_safe)
    mention_safe = token_safe.replace("@", "＠")
    return " ".join(
        escape_markdown(mention_safe, as_needed=False).split()
    )


def sanitize_pending_label(value: object, *, fallback: str) -> str:
    """Return one inert, mention-safe label capped for Discord previews."""

    bounded = _without_discord_control_surface(value)[:200].rstrip("\\")
    return bounded or fallback


def sanitize_pending_detail(value: object, *, fallback: str) -> str:
    """Return inert single-line detail or reject oversized preview data."""

    detail = _without_discord_control_surface(value)
    if len(detail) > 4_000:
        raise ValueError("pending_detail_too_large")
    return detail or fallback


def sanitize_pending_summary(value: object, *, fallback: str) -> str:
    """Return bounded inert bookkeeping without constraining the preview."""

    # The lossless confirmation messages are the authoritative user-visible
    # proposition.  PendingAction.summary is only bounded bookkeeping, so cap
    # before markdown escaping can expand schema-maximum material values.
    bounded_input = str(value)[:1_000]
    bounded = _without_discord_control_surface(bounded_input)[:500].rstrip(
        "\\"
    )
    return bounded or fallback


def _optional_nonblank_string(value: object, *, code: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(code)
    normalized = value.strip()
    return normalized or None


@dataclass(frozen=True, slots=True)
class PendingTargetGuard:
    family: PendingTargetFamily
    stable_id: str | None
    original_position: int | None
    fingerprint: str | None
    revision: str | None
    label: str
    display_detail: str = ""
    proposition_hash: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.family, PendingTargetFamily):
            raise ValueError("invalid_target_family")
        stable_id = _optional_nonblank_string(
            self.stable_id,
            code="invalid_stable_id",
        )
        fingerprint = _optional_nonblank_string(
            self.fingerprint,
            code="invalid_fingerprint",
        )
        revision = _optional_nonblank_string(
            self.revision,
            code="invalid_revision",
        )
        proposition_hash = _optional_nonblank_string(
            self.proposition_hash,
            code="invalid_proposition_hash",
        )
        if int(stable_id is not None) + int(fingerprint is not None) != 1:
            raise ValueError("exactly_one_target_identity")
        if stable_id is not None and revision is None:
            raise ValueError("stable_id_requires_revision")
        if self.original_position is not None and (
            isinstance(self.original_position, bool)
            or not isinstance(self.original_position, int)
            or self.original_position < 1
        ):
            raise ValueError("invalid_original_position")

        safe_label = sanitize_pending_label(
            self.label,
            fallback="valgt element",
        )
        object.__setattr__(self, "stable_id", stable_id)
        object.__setattr__(self, "fingerprint", fingerprint)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "proposition_hash", proposition_hash)
        object.__setattr__(self, "label", safe_label)
        object.__setattr__(
            self,
            "display_detail",
            sanitize_pending_detail(
                self.display_detail or safe_label,
                fallback="valgt element",
            ),
        )


@dataclass(frozen=True, slots=True)
class PendingAction:
    action_id: str
    key: ConversationKey
    kind: PendingKind
    routes: tuple[IntentResult, ...]
    summary: str
    created_at: datetime
    expires_at: datetime
    status: PendingStatus = PendingStatus.PRESENTING
    claim_id: str | None = None
    target_guards: tuple[PendingTargetGuard | None, ...] = ()
    settled_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, str) or not self.action_id:
            raise ValueError("invalid_action_id")
        if not isinstance(self.key, ConversationKey):
            raise ValueError("invalid_conversation_key")
        if not isinstance(self.kind, PendingKind):
            raise ValueError("invalid_pending_kind")
        if not isinstance(self.status, PendingStatus):
            raise ValueError("invalid_pending_status")
        if self.claim_id is not None and (
            not isinstance(self.claim_id, str) or not self.claim_id.strip()
        ):
            raise ValueError("invalid_claim_id")
        if (self.status is PendingStatus.EXECUTING) != (
            self.claim_id is not None
        ):
            raise ValueError("claim_id_status_mismatch")
        if not isinstance(self.routes, tuple) or any(
            not isinstance(route, IntentResult) for route in self.routes
        ):
            raise ValueError("invalid_pending_routes")
        if len(self.target_guards) != len(self.routes):
            raise ValueError("guard_count_mismatch")
        if any(
            guard is not None and not isinstance(guard, PendingTargetGuard)
            for guard in self.target_guards
        ):
            raise ValueError("invalid_target_guard")
        if not isinstance(self.summary, str):
            raise ValueError("invalid_pending_summary")
        for value in (self.created_at, self.expires_at):
            if (
                not isinstance(value, datetime)
                or value.tzinfo is None
                or value.utcoffset() is None
            ):
                raise ValueError("pending_time_must_be_aware")
        if self.expires_at <= self.created_at:
            raise ValueError("invalid_pending_expiry")

        terminal = self.status in {
            PendingStatus.COMPLETED,
            PendingStatus.FAILED,
        }
        if terminal != (self.settled_at is not None):
            raise ValueError("settled_at_status_mismatch")
        if self.settled_at is not None and (
            not isinstance(self.settled_at, datetime)
            or self.settled_at.tzinfo is None
            or self.settled_at.utcoffset() is None
        ):
            raise ValueError("pending_time_must_be_aware")
        if terminal:
            if self.routes or self.target_guards or self.summary:
                raise ValueError("terminal_pending_retains_payload")
        elif self.kind is PendingKind.CONFIRMATION and len(self.routes) != 1:
            raise ValueError("confirmation_route_count")
        elif self.kind is PendingKind.CHOICE and not 2 <= len(self.routes) <= 5:
            raise ValueError("choice_count_must_be_two_to_five")


@dataclass(frozen=True, slots=True)
class PendingPresentation:
    pending: PendingAction
    previous: PendingAction | None
    corrected: bool = False


@dataclass(frozen=True, slots=True)
class PendingSelection:
    route: IntentResult
    target_guard: PendingTargetGuard | None


@dataclass(frozen=True, slots=True)
class PendingResolution:
    kind: PendingResolutionKind
    action_id: str | None = None
    choice_index: int | None = None
    correction_text: str | None = None


class PendingBusyError(RuntimeError):
    """Raised when a visible presentation or dispatch already owns a key."""


_CONFIRM = CONFIRMATIONS
_CANCEL = frozenset(TRAILING_CANCELLATIONS)
_CONFIRM_WRAPPER = re.compile(
    r"(?:"
    r"(?:ja|yes)\s*,?\s*(?:takk|please)|"
    r"ja\s*,?\s*(?:gjør|gjer)\s+det|"
    r"(?:ok|okay)\s*,?\s*(?:kjør|køyr)(?:\s+på)?|"
    r"det\s+kan\s+du"
    r")",
    re.IGNORECASE,
)
_CANCEL_WRAPPER = re.compile(
    r"(?:"
    r"(?:nei|no)\s*,?\s*(?:avbryt|cancel)"
    r"(?:\s*,?\s*(?:takk|please))?|"
    r"(?:avbryt|cancel)\s*,?\s*(?:takk|please)|"
    r"(?:vent|stopp)\s+litt"
    r")",
    re.IGNORECASE,
)
_ORDINALS = {
    "første": 0,
    "fyrste": 0,
    "first": 0,
    "andre": 1,
    "annen": 1,
    "second": 1,
    "tredje": 2,
    "third": 2,
    "fjerde": 3,
    "fourth": 3,
    "femte": 4,
    "fifth": 4,
}
_EXPLICIT_CORRECTION = re.compile(
    r"^(?:(?:endre til|i stedet|isteden|heller)\b\s*[:\-]?|"
    r"(?:endring|rettelse|korreksjon)\s*:)\s*\S(?:.*\S)?$",
    re.IGNORECASE,
)
_PENDING_TEMPORAL_RESOLVER = TemporalResolver()
_PENDING_TEMPORAL_REFERENCE = datetime(2000, 1, 1, tzinfo=timezone.utc)
_TITLE_EVIDENCE = re.compile(
    r"^(?:tittel|tekst|navn|spørsmål|question|kall den|endre tittel til|"
    r"endre teksten til)\s*[:\-]?\s*\S+",
    re.IGNORECASE,
)
_OPTION_EVIDENCE = re.compile(
    r"^(?:alternativ|valg|options?)\s*[:\-]?\s*\S+",
    re.IGNORECASE,
)


def _normalize_reply(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", normalized).strip(" \t\r\n.!?")


def _is_confirmation_reply(normalized: str) -> bool:
    return normalized in _CONFIRM or bool(
        _CONFIRM_WRAPPER.fullmatch(normalized)
    )


def _is_cancel_reply(normalized: str) -> bool:
    return (
        normalized in _CANCEL
        or bool(_CANCEL_WRAPPER.fullmatch(normalized))
    )


def _is_bare_temporal_correction(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", text).casefold().strip()
    normalized = normalized.strip(" \t\r\n,;:.!?")
    if not normalized:
        return False

    # A conjunction is safe only between two temporal fragments.  Keeping it
    # away from either edge prevents conversational continuations such as
    # ``og i morgen`` and ``i morgen og`` from claiming a pending action.
    if re.match(r"^(?:og|and)\b", normalized, re.IGNORECASE):
        return False
    if re.search(r"\b(?:og|and)$", normalized, re.IGNORECASE):
        return False

    remaining = _PENDING_TEMPORAL_RESOLVER.strip_temporal_evidence(
        normalized,
        reference=_PENDING_TEMPORAL_REFERENCE,
    )
    if remaining == normalized:
        return False
    return (
        re.fullmatch(
            r"(?:(?:på|at)\s*)?(?:(?:og|and)\s*)*",
            remaining,
        )
        is not None
    )


def _clone_route(route: IntentResult) -> IntentResult:
    return replace(route, payload=copy.deepcopy(route.payload))


def _clone_pending(pending: PendingAction) -> PendingAction:
    return replace(
        pending,
        routes=tuple(_clone_route(route) for route in pending.routes),
        target_guards=copy.deepcopy(pending.target_guards),
    )


def _payload_keys(value: object) -> set[str]:
    result: set[str] = set()
    if isinstance(value, Mapping):
        result.update(key for key in value if isinstance(key, str))
        for nested in value.values():
            result.update(_payload_keys(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            result.update(_payload_keys(nested))
    return result


class PendingActionStore:
    """One in-memory capability state per exact conversation key."""

    def __init__(
        self,
        *,
        now_provider: Callable[[], datetime] | None = None,
        ttl: timedelta = timedelta(minutes=10),
        terminal_ttl: timedelta = timedelta(minutes=10),
        max_terminal: int = 1_000,
        metrics: NLUMetrics | None = None,
    ) -> None:
        if not isinstance(ttl, timedelta) or ttl <= timedelta(0):
            raise ValueError("ttl_must_be_positive")
        if (
            not isinstance(terminal_ttl, timedelta)
            or terminal_ttl <= timedelta(0)
        ):
            raise ValueError("terminal_ttl_must_be_positive")
        if (
            isinstance(max_terminal, bool)
            or not isinstance(max_terminal, int)
            or max_terminal < 1
        ):
            raise ValueError("max_terminal_must_be_positive")
        if now_provider is not None and not callable(now_provider):
            raise ValueError("invalid_now_provider")
        if metrics is not None and not isinstance(metrics, NLUMetrics):
            raise ValueError("invalid_nlu_metrics")

        self._now_provider = now_provider or (
            lambda: datetime.now(timezone.utc)
        )
        self._ttl = ttl
        self._terminal_ttl = terminal_ttl
        self._max_terminal = max_terminal
        self.metrics = metrics if metrics is not None else NLUMetrics()
        self._items: dict[ConversationKey, PendingAction] = {}
        self._presentations: dict[str, PendingPresentation] = {}

    def _now(self) -> datetime:
        now = self._now_provider()
        if (
            not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
        ):
            raise ValueError("pending_clock_must_be_aware")
        return now

    @property
    def now_provider(self) -> Callable[[], datetime]:
        return self._now_provider

    def _prune_terminal(self, now: datetime | None = None) -> None:
        reference = now if now is not None else self._now()
        terminal = self._terminal_items()
        for settled_at, key in terminal:
            if reference - settled_at >= self._terminal_ttl:
                self._items.pop(key, None)
        terminal = self._terminal_items()
        for _, key in terminal[:-self._max_terminal]:
            self._items.pop(key, None)

    def _terminal_items(
        self,
    ) -> list[tuple[datetime, ConversationKey]]:
        return sorted(
            (
                (pending.settled_at, key)
                for key, pending in self._items.items()
                if pending.settled_at is not None
            ),
            key=lambda item: (
                item[0],
                item[1].guild_id is None,
                item[1].guild_id if item[1].guild_id is not None else -1,
                item[1].channel_id,
                item[1].user_id,
            ),
        )

    def _settle(
        self,
        pending: PendingAction,
        status: PendingStatus,
    ) -> PendingAction:
        if status not in {PendingStatus.COMPLETED, PendingStatus.FAILED}:
            raise ValueError("terminal_status_required")
        now = self._now()
        tombstone = replace(
            pending,
            routes=(),
            summary="",
            target_guards=(),
            status=status,
            claim_id=None,
            settled_at=now,
        )
        self._items[pending.key] = tombstone
        self._prune_terminal(now)
        return tombstone

    def _read(
        self,
        key: ConversationKey,
    ) -> tuple[PendingAction | None, PendingAction | None]:
        now = self._now()
        self._prune_terminal(now)
        pending = self._items.get(key)
        if pending is None:
            return None, None
        if (
            pending.status is PendingStatus.READY
            and now >= pending.expires_at
        ):
            del self._items[key]
            self.metrics.record_pending("expired")
            return None, pending
        return pending, None

    def _begin(
        self,
        key: ConversationKey,
        kind: PendingKind,
        routes: tuple[IntentResult, ...],
        summary: str,
        target_guards: tuple[PendingTargetGuard | None, ...],
        *,
        expected_action_id: str | None = None,
        corrected: bool = False,
    ) -> PendingPresentation | None:
        if not isinstance(key, ConversationKey):
            raise ValueError("invalid_conversation_key")
        if not isinstance(routes, tuple) or any(
            not isinstance(route, IntentResult) for route in routes
        ):
            raise ValueError("invalid_pending_routes")
        if not isinstance(target_guards, tuple) or any(
            guard is not None and not isinstance(guard, PendingTargetGuard)
            for guard in target_guards
        ):
            raise ValueError("invalid_target_guard")
        if len(routes) != len(target_guards):
            raise ValueError("guard_count_mismatch")
        safe_summary = sanitize_pending_summary(
            summary,
            fallback="ventende handling",
        )

        current, _ = self._read(key)
        if current is not None and current.status in {
            PendingStatus.PRESENTING,
            PendingStatus.EXECUTING,
        }:
            raise PendingBusyError("pending_action_executing")
        if expected_action_id is not None and (
            current is None
            or current.status is not PendingStatus.READY
            or current.action_id != expected_action_id
        ):
            return None

        now = self._now()
        pending = PendingAction(
            action_id=uuid.uuid4().hex,
            key=key,
            kind=kind,
            routes=tuple(_clone_route(route) for route in routes),
            summary=safe_summary,
            created_at=now,
            expires_at=now + self._ttl,
            status=PendingStatus.PRESENTING,
            target_guards=copy.deepcopy(target_guards),
            settled_at=None,
        )
        self._items[key] = pending
        presentation = PendingPresentation(
            pending=_clone_pending(pending),
            previous=(
                _clone_pending(current)
                if current is not None
                and current.status is PendingStatus.READY
                else None
            ),
            corrected=corrected,
        )
        self._presentations[pending.action_id] = presentation
        return presentation

    def begin_confirmation(
        self,
        key: ConversationKey,
        route: IntentResult,
        summary: str,
        *,
        target_guard: PendingTargetGuard | None = None,
    ) -> PendingPresentation:
        presentation = self._begin(
            key,
            PendingKind.CONFIRMATION,
            (route,),
            summary,
            (target_guard,),
        )
        assert presentation is not None
        return presentation

    def begin_choices(
        self,
        key: ConversationKey,
        routes: tuple[IntentResult, ...],
        summary: str,
        *,
        target_guards: tuple[PendingTargetGuard | None, ...],
    ) -> PendingPresentation:
        if not isinstance(routes, tuple) or not 2 <= len(routes) <= 5:
            raise ValueError("choice_count_must_be_two_to_five")
        presentation = self._begin(
            key,
            PendingKind.CHOICE,
            routes,
            summary,
            target_guards,
        )
        assert presentation is not None
        return presentation

    def begin_correction(
        self,
        key: ConversationKey,
        action_id: str,
        route: IntentResult,
        summary: str,
        *,
        target_guard: PendingTargetGuard | None,
    ) -> PendingPresentation | None:
        return self._begin(
            key,
            PendingKind.CONFIRMATION,
            (route,),
            summary,
            (target_guard,),
            expected_action_id=action_id,
            corrected=True,
        )

    def activate_presentation(
        self,
        presentation: PendingPresentation,
    ) -> PendingAction | None:
        if not isinstance(presentation, PendingPresentation):
            return None
        registered = self._presentations.get(
            presentation.pending.action_id
        )
        if registered is not presentation:
            return None
        current, _ = self._read(presentation.pending.key)
        if (
            current is None
            or current.status is not PendingStatus.PRESENTING
            or current.action_id != presentation.pending.action_id
        ):
            return None
        self._presentations.pop(current.action_id, None)
        now = self._now()
        ready = replace(
            current,
            created_at=now,
            expires_at=now + self._ttl,
            status=PendingStatus.READY,
            settled_at=None,
        )
        self._items[current.key] = ready
        self.metrics.record_pending("staged")
        if presentation.corrected:
            self.metrics.record_pending("corrected")
        return _clone_pending(ready)

    def abort_presentation(
        self,
        presentation: PendingPresentation,
        *,
        safe_to_restore_previous: bool,
    ) -> bool:
        if not isinstance(safe_to_restore_previous, bool):
            raise ValueError("invalid_restore_proof")
        if not isinstance(presentation, PendingPresentation):
            return False
        registered = self._presentations.get(
            presentation.pending.action_id
        )
        if registered is not presentation:
            return False
        key = presentation.pending.key
        current = self._items.get(key)
        if (
            current is None
            or current.status is not PendingStatus.PRESENTING
            or current.action_id != presentation.pending.action_id
        ):
            return False
        self._presentations.pop(current.action_id, None)
        previous = presentation.previous
        if presentation.corrected or not safe_to_restore_previous:
            self._settle(current, PendingStatus.FAILED)
        elif (
            previous is not None
            and previous.key == key
            and previous.status is PendingStatus.READY
            and self._now() < previous.expires_at
        ):
            self._items[key] = _clone_pending(previous)
        else:
            del self._items[key]
        self.metrics.record_pending("presentation_failed")
        return True

    def resolve(self, key: ConversationKey, text: str) -> PendingResolution:
        pending, expired = self._read(key)
        if expired is not None and isinstance(text, str):
            normalized = _normalize_reply(text)
            targets_expired = bool(
                _is_confirmation_reply(normalized)
                or _is_cancel_reply(normalized)
                or (
                    expired.kind is PendingKind.CHOICE
                    and (choice := self._choice_index(normalized)) is not None
                    and choice < len(expired.routes)
                )
                or (
                    expired.kind is PendingKind.CONFIRMATION
                    and self._looks_like_correction(expired.routes[0], text)
                )
            )
            if not targets_expired:
                return PendingResolution(PendingResolutionKind.NONE)
            return PendingResolution(
                PendingResolutionKind.EXPIRED,
                action_id=expired.action_id,
            )
        if (
            pending is None
            or not isinstance(text, str)
        ):
            return PendingResolution(PendingResolutionKind.NONE)
        normalized = _normalize_reply(text)
        if pending.status in {
            PendingStatus.COMPLETED,
            PendingStatus.FAILED,
        }:
            if _is_cancel_reply(normalized):
                return PendingResolution(
                    PendingResolutionKind.CANCEL,
                    action_id=pending.action_id,
                )
            if _is_confirmation_reply(normalized):
                return PendingResolution(
                    PendingResolutionKind.CONFIRM,
                    action_id=pending.action_id,
                )
            return PendingResolution(PendingResolutionKind.NONE)
        if pending.status is not PendingStatus.READY:
            return PendingResolution(PendingResolutionKind.NONE)
        if _is_cancel_reply(normalized):
            return PendingResolution(
                PendingResolutionKind.CANCEL,
                action_id=pending.action_id,
            )
        if (
            pending.kind is PendingKind.CONFIRMATION
            and _is_confirmation_reply(normalized)
        ):
            return PendingResolution(
                PendingResolutionKind.CONFIRM,
                action_id=pending.action_id,
            )
        if pending.kind is PendingKind.CHOICE:
            index = self._choice_index(normalized)
            if index is not None and index < len(pending.routes):
                return PendingResolution(
                    PendingResolutionKind.SELECT,
                    action_id=pending.action_id,
                    choice_index=index,
                )
        if (
            pending.kind is PendingKind.CONFIRMATION
            and self._looks_like_correction(pending.routes[0], text)
        ):
            return PendingResolution(
                PendingResolutionKind.CORRECT,
                action_id=pending.action_id,
                correction_text=text,
            )
        return PendingResolution(PendingResolutionKind.NONE)

    @staticmethod
    def _choice_index(normalized: str) -> int | None:
        if re.search(r"(?<!\w)(?:begge|both)(?!\w)", normalized):
            return None
        numeric = re.fullmatch(
            r"(?:(?:nummer|alternativ|valg|option)\s*)?([1-5])"
            r"(?:\s*,?\s*(?:takk|please))?",
            normalized,
        )
        if numeric is None:
            numeric = re.fullmatch(
                r"(?:(?:jeg|eg)\s+velger|i\s+choose)\s+"
                r"(?:(?:nummer|alternativ|valg|option)\s*)?([1-5])",
                normalized,
            )
        if numeric:
            return int(numeric.group(1)) - 1
        for word, index in _ORDINALS.items():
            if re.fullmatch(
                rf"(?:(?:(?:jeg|eg)\s+(?:mener|meiner|velger|vel)|"
                rf"i\s+(?:mean|choose))\s+)?"
                rf"(?:(?:den|the)\s+)?{re.escape(word)}"
                rf"(?:\s+(?:ene|alternativet|valget|option))?"
                rf"(?:\s*,?\s*(?:takk|please))?",
                normalized,
            ):
                return index
        return None

    @staticmethod
    def _looks_like_correction(route: IntentResult, text: str) -> bool:
        stripped = text.strip()
        if _EXPLICIT_CORRECTION.fullmatch(stripped):
            return True
        keys = _payload_keys(route.payload)
        if keys & {"date", "time", "due_at", "due_date"}:
            if _is_bare_temporal_correction(text):
                return True
        if keys & {"title", "text", "question", "description"}:
            if _TITLE_EVIDENCE.search(stripped):
                return True
        if "options" in keys and _OPTION_EVIDENCE.search(stripped):
            return True
        return False

    def claim(
        self,
        key: ConversationKey,
        action_id: str,
    ) -> PendingAction | None:
        pending, _ = self._read(key)
        if (
            pending is None
            or pending.action_id != action_id
            or pending.kind is not PendingKind.CONFIRMATION
            or pending.status is not PendingStatus.READY
        ):
            self.metrics.record_pending("claim_failed")
            return None
        executing = replace(
            pending,
            status=PendingStatus.EXECUTING,
            claim_id=uuid.uuid4().hex,
        )
        self._items[key] = executing
        self.metrics.record_pending("confirmed")
        return _clone_pending(executing)

    def is_executing(
        self,
        key: ConversationKey,
        claimed: PendingAction,
    ) -> bool:
        pending, _ = self._read(key)
        return bool(
            pending is not None
            and pending.action_id == claimed.action_id
            and pending.status is PendingStatus.EXECUTING
            and pending == claimed
        )

    def is_action_executing(
        self,
        key: ConversationKey,
        action_id: str,
        expected_intent: BotIntent,
        *,
        claim_id: str,
    ) -> bool:
        pending, _ = self._read(key)
        return bool(
            pending is not None
            and pending.action_id == action_id
            and pending.claim_id == claim_id
            and pending.status is PendingStatus.EXECUTING
            and len(pending.routes) == 1
            and pending.routes[0].intent is expected_intent
        )

    def consume_choice(
        self,
        key: ConversationKey,
        action_id: str,
        choice_index: int,
    ) -> PendingSelection | None:
        pending, _ = self._read(key)
        if (
            pending is None
            or pending.action_id != action_id
            or pending.kind is not PendingKind.CHOICE
            or pending.status is not PendingStatus.READY
            or isinstance(choice_index, bool)
            or not isinstance(choice_index, int)
            or not 0 <= choice_index < len(pending.routes)
        ):
            return None
        selected = PendingSelection(
            route=_clone_route(pending.routes[choice_index]),
            target_guard=copy.deepcopy(
                pending.target_guards[choice_index]
            ),
        )
        self._settle(pending, PendingStatus.COMPLETED)
        self.metrics.record_pending("selected")
        return selected

    def complete(self, key: ConversationKey, action_id: str) -> bool:
        pending, _ = self._read(key)
        if (
            pending is None
            or pending.action_id != action_id
            or pending.status is not PendingStatus.EXECUTING
        ):
            return False
        self._settle(pending, PendingStatus.COMPLETED)
        return True

    def release_retryable(
        self,
        key: ConversationKey,
        action_id: str,
        outcome: DispatchOutcome,
    ) -> bool:
        pending, _ = self._read(key)
        if (
            pending is None
            or pending.action_id != action_id
            or pending.status is not PendingStatus.EXECUTING
            or not isinstance(outcome, DispatchOutcome)
            or outcome.ok
            or outcome.mutated
            or outcome.commit_unknown
            or not outcome.retryable
        ):
            return False
        self._items[key] = replace(
            pending,
            status=PendingStatus.READY,
            claim_id=None,
            settled_at=None,
        )
        self.metrics.record_pending("dispatch_failed")
        return True

    def fail_terminal(self, key: ConversationKey, action_id: str) -> bool:
        pending, _ = self._read(key)
        if (
            pending is None
            or pending.action_id != action_id
            or pending.status is not PendingStatus.EXECUTING
        ):
            return False
        self._settle(pending, PendingStatus.FAILED)
        self.metrics.record_pending("dispatch_failed")
        return True

    def cancel(self, key: ConversationKey, action_id: str) -> bool:
        pending, _ = self._read(key)
        if (
            pending is None
            or pending.action_id != action_id
            or pending.status is not PendingStatus.READY
        ):
            return False
        del self._items[key]
        self.metrics.record_pending("canceled")
        return True

    def effective_routes_for_history(
        self,
        key: ConversationKey,
        route: IntentResult,
    ) -> tuple[IntentResult, ...] | None:
        control_intents = {
            BotIntent.ACTION_CONFIRM,
            BotIntent.ACTION_CANCEL,
            BotIntent.ACTION_SELECT,
            BotIntent.ACTION_CORRECT,
        }
        if not isinstance(key, ConversationKey) or not isinstance(
            route,
            IntentResult,
        ):
            return None
        if route.intent not in control_intents:
            try:
                return (_clone_route(route),)
            except Exception:
                return None
        if not isinstance(route.payload, Mapping):
            return None
        pending_payload = route.payload.get("pending")
        if not isinstance(pending_payload, Mapping):
            return None
        action_id = pending_payload.get("action_id")
        if not isinstance(action_id, str) or not action_id:
            return None
        pending, _ = self._read(key)
        if (
            pending is None
            or pending.status is not PendingStatus.READY
            or pending.action_id != action_id
        ):
            return None
        if not pending.routes or any(
            not isinstance(item, IntentResult) for item in pending.routes
        ):
            return None
        try:
            return tuple(_clone_route(item) for item in pending.routes)
        except Exception:
            return None

    def peek(self, key: ConversationKey) -> PendingAction | None:
        pending, _ = self._read(key)
        return _clone_pending(pending) if pending is not None else None

    def counts(self) -> dict[str, int]:
        for key in tuple(self._items):
            self._read(key)
        result = {status.value: 0 for status in PendingStatus}
        for pending in self._items.values():
            result[pending.status.value] += 1
        return result


__all__ = [
    "PendingAction",
    "PendingActionStore",
    "PendingBusyError",
    "PendingKind",
    "PendingPresentation",
    "PendingResolution",
    "PendingResolutionKind",
    "PendingSelection",
    "PendingStatus",
    "PendingTargetFamily",
    "PendingTargetGuard",
    "sanitize_pending_detail",
    "sanitize_pending_label",
]
