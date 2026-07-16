"""Pure contracts for scoped, acknowledged pending-action state."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from core.dispatch_result import DispatchOutcome
from core.intent_models import (
    BotIntent,
    IntentResult,
    IntentRisk,
    IntentSource,
)
from core.message_context import ConversationKey
from core.nlu_metrics import NLUMetrics
from core.pending_actions import (
    PendingActionStore,
    PendingBusyError,
    PendingResolutionKind,
    PendingStatus,
    PendingTargetFamily,
    PendingTargetGuard,
)
from core.utterance_semantics import TRAILING_CANCELLATIONS


OSLO = ZoneInfo("Europe/Oslo")


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 14, 12, 0, tzinfo=OSLO)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


def key(
    user_id: int = 7,
    channel_id: int = 10,
    guild_id: int | None = 1,
) -> ConversationKey:
    return ConversationKey(guild_id, channel_id, user_id)


def reminder_route(*, text: str = "ringe legen") -> IntentResult:
    return IntentResult(
        BotIntent.REMINDER_CREATE,
        0.91,
        {
            "reminder": {
                "action": "add",
                "text": text,
                "due_at": "2026-07-15T09:00:00+02:00",
            }
        },
        "semantic_action",
        source=IntentSource.SEMANTIC,
        risk=IntentRisk.ADDITIVE,
        requires_confirmation=True,
    )


def list_routes() -> tuple[IntentResult, IntentResult]:
    return (
        IntentResult(BotIntent.CALENDAR_LIST, 0.9),
        IntentResult(BotIntent.REMINDER_LIST, 0.9),
    )


def calendar_auth_route(*, auth_code: str = "4/SECRET-CODE") -> IntentResult:
    return IntentResult(
        BotIntent.CALENDAR_AUTH,
        1.0,
        {"calendar_auth": {"auth_code": auth_code}},
        "calendar_auth_code",
    )


def control_route(
    intent: BotIntent,
    action_id: object,
    **pending_fields: object,
) -> IntentResult:
    return IntentResult(
        intent,
        1.0,
        {
            "pending": {
                "action_id": action_id,
                **pending_fields,
            }
        },
        f"pending_{intent.value}",
    )


def ready_confirmation(
    store: PendingActionStore,
    key_value: ConversationKey,
    route: IntentResult,
    summary: str = "Ringe legen",
):
    draft = store.begin_confirmation(key_value, route, summary)
    ready = store.activate_presentation(draft)
    assert ready is not None
    return ready


def ready_choices(
    store: PendingActionStore,
    key_value: ConversationKey,
    routes: tuple[IntentResult, ...],
    guards: tuple[PendingTargetGuard | None, ...] | None = None,
):
    draft = store.begin_choices(
        key_value,
        routes,
        "Velg ett alternativ",
        target_guards=guards or tuple(None for _ in routes),
    )
    ready = store.activate_presentation(draft)
    assert ready is not None
    return ready


def test_confirmation_is_scoped_and_claimed_once():
    store = PendingActionStore(now_provider=Clock())
    pending = ready_confirmation(store, key(), reminder_route())

    assert store.resolve(key(user_id=8), "ja").kind is PendingResolutionKind.NONE
    assert store.resolve(key(channel_id=11), "ja").kind is PendingResolutionKind.NONE
    assert store.resolve(key(guild_id=2), "ja").kind is PendingResolutionKind.NONE
    assert store.resolve(key(), "ja").kind is PendingResolutionKind.CONFIRM

    claimed = store.claim(key(), pending.action_id)
    assert claimed is not None
    assert claimed.status is PendingStatus.EXECUTING
    assert store.claim(key(), pending.action_id) is None


def test_presentation_is_inert_until_delivery_activation():
    metrics = NLUMetrics()
    store = PendingActionStore(now_provider=Clock(), metrics=metrics)
    draft = store.begin_confirmation(key(), reminder_route(), "Ringe legen")

    assert store.peek(key()).status is PendingStatus.PRESENTING
    assert store.resolve(key(), "ja").kind is PendingResolutionKind.NONE
    assert store.claim(key(), draft.pending.action_id) is None
    assert metrics.snapshot()["pending"] == {"claim_failed": 1}

    ready = store.activate_presentation(draft)
    assert ready is not None
    assert ready.status is PendingStatus.READY
    assert metrics.snapshot()["pending"] == {
        "claim_failed": 1,
        "staged": 1,
    }


def test_activation_starts_a_fresh_full_ttl():
    clock = Clock()
    store = PendingActionStore(
        now_provider=clock,
        ttl=timedelta(minutes=10),
    )
    draft = store.begin_confirmation(key(), reminder_route(), "Ringe")
    clock.advance(timedelta(minutes=9))
    ready = store.activate_presentation(draft)
    assert ready is not None
    assert ready.created_at == clock.value
    assert ready.expires_at == clock.value + timedelta(minutes=10)

    clock.advance(timedelta(minutes=9, seconds=59))
    assert store.resolve(key(), "ja").kind is PendingResolutionKind.CONFIRM


def test_store_deep_copies_mutable_route_payloads_on_every_boundary():
    store = PendingActionStore(now_provider=Clock())
    route = reminder_route()
    expected = deepcopy(route.payload)
    pending = ready_confirmation(store, key(), route)

    route.payload["reminder"]["text"] = "forgiftet"
    peeked = store.peek(key())
    assert peeked.routes[0].payload == expected
    peeked.routes[0].payload["reminder"]["text"] = "også forgiftet"

    claimed = store.claim(key(), pending.action_id)
    assert claimed is not None
    assert claimed.routes[0].payload == expected


def test_stable_target_guard_requires_one_identity_and_nonblank_revision():
    base = {
        "family": PendingTargetFamily.REMINDER,
        "stable_id": "reminder-a",
        "original_position": 1,
        "fingerprint": None,
        "revision": "revision-a",
        "label": "Ringe legen",
        "display_detail": "Ringe legen klokken 09:00",
    }
    for revision in (None, "", "   "):
        with pytest.raises(ValueError, match="stable_id_requires_revision"):
            PendingTargetGuard(**{**base, "revision": revision})
    with pytest.raises(ValueError, match="exactly_one_target_identity"):
        PendingTargetGuard(**{**base, "stable_id": None})
    with pytest.raises(ValueError, match="exactly_one_target_identity"):
        PendingTargetGuard(**{**base, "fingerprint": "fingerprint-a"})


def test_target_guard_sanitizes_discord_and_link_surface():
    guard = PendingTargetGuard(
        family=PendingTargetFamily.REMINDER,
        stable_id=" reminder-a ",
        original_position=1,
        fingerprint=None,
        revision=" revision-a ",
        label="  <@123> **Ringe** http://example.invalid\n ",
        display_detail="<@&456> _detalj_ https://example.invalid/path",
    )

    assert guard.stable_id == "reminder-a"
    assert guard.revision == "revision-a"
    assert "<@" not in guard.label
    assert "@" not in guard.label
    assert "http://" not in guard.label
    assert "\n" not in guard.label
    assert len(guard.label) <= 200
    assert "<@" not in guard.display_detail
    assert "https://" not in guard.display_detail


def test_target_guard_rejects_invalid_position_and_oversize_detail():
    for position in (True, 0, -1, 1.5, "1"):
        with pytest.raises(ValueError, match="invalid_original_position"):
            PendingTargetGuard(
                PendingTargetFamily.REMINDER,
                "id",
                position,
                None,
                "revision",
                "label",
            )
    with pytest.raises(ValueError, match="pending_detail_too_large"):
        PendingTargetGuard(
            PendingTargetFamily.REMINDER,
            "id",
            1,
            None,
            "revision",
            "label",
            "x" * 4_001,
        )


def test_target_guards_are_copied_across_store_and_selection_boundaries():
    guard = PendingTargetGuard(
        PendingTargetFamily.REMINDER,
        "reminder-a",
        1,
        None,
        "revision-a",
        "Ringe legen",
    )
    store = PendingActionStore(now_provider=Clock())
    ready = ready_choices(
        store,
        key(),
        list_routes(),
        guards=(guard, None),
    )

    stored_guard = store.peek(key()).target_guards[0]
    assert stored_guard == guard
    assert stored_guard is not guard
    selected = store.consume_choice(key(), ready.action_id, 0)
    assert selected is not None
    assert selected.target_guard == guard
    assert selected.target_guard is not guard
    assert selected.target_guard is not stored_guard


@pytest.mark.parametrize(
    "text",
    [
        "ja",
        "Ja!",
        "jepp",
        "japp",
        "ok",
        "okay",
        "bekreft",
        "gjør det",
        "gjer det",
        "kjør på",
        "køyr på",
        "det stemmer",
        "yes",
        "go ahead",
        "sure",
        "yep",
        "ja takk",
        "ja, gjør det",
        "ja, gjer det",
        "yes please",
        "ok, kjør",
        "ok, køyr",
        "det kan du",
    ],
)
def test_natural_confirmation_resolution(text):
    store = PendingActionStore(now_provider=Clock())
    ready_confirmation(store, key(), reminder_route())
    assert store.resolve(key(), text).kind is PendingResolutionKind.CONFIRM


NATURAL_CANCEL_REPLIES = tuple(sorted(set(TRAILING_CANCELLATIONS).union({
    "nei",
    "nei takk",
    "ikke likevel",
    "ikkje likevel",
    "glem det",
    "gløym det",
    "la oss droppe det",
    "lat oss droppe det",
    "avbryt",
    "stopp",
    "dropp det",
    "ikke gjør det",
    "ikkje gjer det",
    "nope",
    "no thanks",
    "never mind",
    "nei, avbryt",
    "avbryt, takk",
    "cancel please",
    "vent litt",
    "stopp litt",
    "vent nå",
    "wait please",
    "la være da",
    "jeg ombestemte meg",
    "forget it",
    "scratch that",
})))


@pytest.mark.parametrize("text", NATURAL_CANCEL_REPLIES)
def test_natural_cancel_resolution(text):
    store = PendingActionStore(now_provider=Clock())
    ready_confirmation(store, key(), reminder_route())
    assert store.resolve(key(), text).kind is PendingResolutionKind.CANCEL


@pytest.mark.parametrize("text", NATURAL_CANCEL_REPLIES)
def test_natural_cancel_does_not_leave_destructive_action_armed(text):
    store = PendingActionStore(now_provider=Clock())
    destructive = replace(
        reminder_route(),
        intent=BotIntent.REMINDER_DELETE,
        risk=IntentRisk.DESTRUCTIVE,
    )
    pending = ready_confirmation(store, key(), destructive)

    canceled = store.resolve(key(), text)
    assert canceled.kind is PendingResolutionKind.CANCEL
    assert store.cancel(key(), pending.action_id) is True
    assert store.claim(key(), pending.action_id) is None


@pytest.mark.parametrize(
    "text",
    [
        "ja takk, men kanskje ikke",
        "yes please explain",
        "det kan du kanskje",
        "ok, kjør og slett noe annet",
        "avbryt takk senere",
        "jeg tror vi bør stoppe litt",
    ],
)
def test_confirmation_and_cancel_wrappers_remain_anchored(text):
    store = PendingActionStore(now_provider=Clock())
    ready_confirmation(store, key(), reminder_route())
    assert store.resolve(key(), text).kind is PendingResolutionKind.NONE


@pytest.mark.parametrize(
    ("text", "index"),
    [
        ("1", 0),
        ("nummer 2", 1),
        ("første", 0),
        ("den andre", 1),
        ("andre alternativet", 1),
        ("alternativ 2", 1),
        ("valg 2", 1),
        ("option 2", 1),
        ("2 takk", 1),
        ("jeg velger 2", 1),
        ("jeg mener den andre", 1),
        ("jeg velger den andre", 1),
        ("I choose the second", 1),
        ("I mean the second", 1),
        ("den andre, takk", 1),
    ],
)
def test_natural_choice_resolution(text, index):
    store = PendingActionStore(now_provider=Clock())
    ready_choices(store, key(), list_routes())
    resolved = store.resolve(key(), text)
    assert resolved.kind is PendingResolutionKind.SELECT
    assert resolved.choice_index == index


@pytest.mark.parametrize(
    "text",
    [
        "tredje",
        "nummer 5",
        "0",
        "nummer 02",
        "siste",
        "begge",
        "both",
        "alternativ 2 og 1",
        "jeg tror alternativ 2 passer",
        "jeg velger den andre fordi den passer",
        "I choose the second option because it is best",
        "2 takk, fordi det er best",
        "ordre 2 skal til rom 1",
    ],
)
def test_out_of_range_or_unrecognized_choice_is_inert(text):
    store = PendingActionStore(now_provider=Clock())
    ready_choices(store, key(), list_routes())
    assert store.resolve(key(), text).kind is PendingResolutionKind.NONE


def test_cancel_wrapper_precedes_choice_resolution():
    store = PendingActionStore(now_provider=Clock())
    ready_choices(store, key(), list_routes())
    assert (
        store.resolve(key(), "nei, avbryt").kind
        is PendingResolutionKind.CANCEL
    )


def test_temporal_correction_requires_exposed_temporal_slot():
    store = PendingActionStore(now_provider=Clock())
    ready_confirmation(store, key(), reminder_route())
    corrected = store.resolve(key(), "i morgen kl 14")
    assert corrected.kind is PendingResolutionKind.CORRECT
    assert corrected.correction_text == "i morgen kl 14"

    ready_confirmation(
        store,
        key(),
        IntentResult(BotIntent.HELP, 1.0),
        "Hjelp",
    )
    assert store.resolve(key(), "i morgen kl 14").kind is PendingResolutionKind.NONE


@pytest.mark.parametrize(
    "text",
    [
        "kan vi snakke om i morgen?",
        "jeg gleder meg til i morgen",
        "hva skjer kl 15?",
        "møtet var i går, men i morgen passer kanskje",
        "og i morgen",
        "i morgen og",
    ],
)
def test_conversational_temporal_mentions_are_not_pending_corrections(text):
    store = PendingActionStore(now_provider=Clock())
    ready_confirmation(store, key(), reminder_route())
    assert store.resolve(key(), text).kind is PendingResolutionKind.NONE


@pytest.mark.parametrize(
    "text",
    [
        "kl 15",
        "i morgen",
        "i morgen kl 15",
        "rettelse: i morgen",
        "endre til kl 15",
        "i kveld",
        "this evening",
        "tonight",
        "på kvelden",
        "på mandag",
        "i overmorgen",
        "overmorgen",
        "imorgen",
        "i morra",
        "day after tomorrow",
        "at 3 pm",
        "15 July",
        "om seks timer",
        "in six hours",
    ],
)
def test_bounded_temporal_correction_frames_are_recognized(text):
    store = PendingActionStore(now_provider=Clock())
    ready_confirmation(store, key(), reminder_route())
    assert store.resolve(key(), text).kind is PendingResolutionKind.CORRECT


@pytest.mark.parametrize("text", ["vær i Oslo", "hjelp", "vis kalenderen", "hei igjen"])
def test_unrelated_message_does_not_become_correction(text):
    store = PendingActionStore(now_provider=Clock())
    ready_confirmation(store, key(), reminder_route())
    assert store.resolve(key(), text).kind is PendingResolutionKind.NONE


def test_safe_initial_abort_restores_previous_ready_snapshot():
    store = PendingActionStore(now_provider=Clock())
    previous = ready_confirmation(store, key(), reminder_route(text="første"))
    draft = store.begin_confirmation(key(), reminder_route(text="andre"), "Andre")

    assert store.abort_presentation(draft, safe_to_restore_previous=True)
    restored = store.peek(key())
    assert restored.action_id == previous.action_id
    assert restored.routes[0].payload["reminder"]["text"] == "første"


def test_safe_initial_abort_drops_draft_when_no_previous_exists():
    store = PendingActionStore(now_provider=Clock())
    draft = store.begin_confirmation(key(), reminder_route(), "Ringe")
    assert store.abort_presentation(draft, safe_to_restore_previous=True)
    assert store.peek(key()) is None


def test_unknown_or_partial_delivery_abort_invalidates_old_and_new_actions():
    store = PendingActionStore(now_provider=Clock())
    previous = ready_confirmation(store, key(), reminder_route(text="første"))
    draft = store.begin_confirmation(key(), reminder_route(text="andre"), "Andre")

    assert store.abort_presentation(draft, safe_to_restore_previous=False)
    failed = store.peek(key())
    assert failed.status is PendingStatus.FAILED
    assert failed.action_id != previous.action_id
    assert failed.routes == ()
    assert store.resolve(key(), "ja").kind is PendingResolutionKind.CONFIRM


def test_failed_correction_presentation_never_restores_old_action():
    store = PendingActionStore(now_provider=Clock())
    previous = ready_confirmation(store, key(), reminder_route(text="første"))
    draft = store.begin_correction(
        key(),
        previous.action_id,
        reminder_route(text="rettet"),
        "Rettet",
        target_guard=None,
    )
    assert draft is not None

    assert store.abort_presentation(draft, safe_to_restore_previous=True)
    assert store.peek(key()).status is PendingStatus.FAILED
    assert store.resolve(key(), "ja").kind is PendingResolutionKind.CONFIRM


def test_stale_presentation_tokens_cannot_activate_or_abort_new_state():
    store = PendingActionStore(now_provider=Clock())
    first = store.begin_confirmation(key(), reminder_route(), "Første")
    assert store.abort_presentation(first, safe_to_restore_previous=True)
    second = store.begin_confirmation(key(), reminder_route(), "Andre")

    assert store.activate_presentation(first) is None
    assert not store.abort_presentation(first, safe_to_restore_previous=True)
    assert store.peek(key()).action_id == second.pending.action_id


def test_forged_presentation_copy_is_not_an_acknowledgement_capability():
    store = PendingActionStore(now_provider=Clock())
    draft = store.begin_confirmation(key(), reminder_route(), "Ringe")
    forged = replace(draft, corrected=True)

    assert store.activate_presentation(forged) is None
    assert not store.abort_presentation(
        forged,
        safe_to_restore_previous=True,
    )
    assert store.peek(key()).status is PendingStatus.PRESENTING
    assert store.activate_presentation(draft) is not None


def test_abort_requires_exact_boolean_delivery_proof():
    store = PendingActionStore(now_provider=Clock())
    draft = store.begin_confirmation(key(), reminder_route(), "Ringe")

    with pytest.raises(ValueError, match="invalid_restore_proof"):
        store.abort_presentation(
            draft,
            safe_to_restore_previous="yes",  # type: ignore[arg-type]
        )
    assert store.peek(key()).status is PendingStatus.PRESENTING


def test_presenting_and_executing_actions_cannot_be_replaced():
    store = PendingActionStore(now_provider=Clock())
    draft = store.begin_confirmation(key(), reminder_route(), "Ringe")
    with pytest.raises(PendingBusyError):
        store.begin_confirmation(key(), reminder_route(), "Ny")

    ready = store.activate_presentation(draft)
    assert ready is not None
    assert store.claim(key(), ready.action_id) is not None
    with pytest.raises(PendingBusyError):
        store.begin_confirmation(key(), reminder_route(), "Ny")


def test_only_proven_retryable_prewrite_failure_releases():
    store = PendingActionStore(now_provider=Clock())
    pending = ready_confirmation(store, key(), reminder_route())
    assert store.claim(key(), pending.action_id) is not None

    assert not store.release_retryable(
        key(),
        pending.action_id,
        DispatchOutcome(ok=True, retryable=True),
    )
    assert not store.release_retryable(
        key(),
        pending.action_id,
        DispatchOutcome.failure("unknown", commit_unknown=True),
    )
    assert not store.release_retryable(
        key(),
        pending.action_id,
        DispatchOutcome.failure("send_failed", mutated=True, retryable=True),
    )
    assert store.peek(key()).status is PendingStatus.EXECUTING

    assert store.release_retryable(
        key(),
        pending.action_id,
        DispatchOutcome.failure("not_found", retryable=True),
    )
    assert store.peek(key()).status is PendingStatus.READY


def test_terminal_failure_never_reauthorizes_action():
    store = PendingActionStore(now_provider=Clock())
    pending = ready_confirmation(store, key(), reminder_route())
    assert store.claim(key(), pending.action_id) is not None
    assert store.fail_terminal(key(), pending.action_id)
    assert store.peek(key()).status is PendingStatus.FAILED
    assert store.claim(key(), pending.action_id) is None


def test_duplicate_confirmation_stays_on_bounded_control_path():
    store = PendingActionStore(now_provider=Clock())
    pending = ready_confirmation(store, key(), reminder_route())
    assert store.claim(key(), pending.action_id) is not None
    assert store.complete(key(), pending.action_id)

    duplicate = store.resolve(key(), "ja")

    assert duplicate.kind is PendingResolutionKind.CONFIRM
    assert duplicate.action_id == pending.action_id
    assert store.claim(key(), pending.action_id) is None


def test_expiry_is_reported_once_and_removed():
    clock = Clock()
    metrics = NLUMetrics()
    store = PendingActionStore(
        now_provider=clock,
        ttl=timedelta(minutes=10),
        metrics=metrics,
    )
    pending = ready_confirmation(store, key(), reminder_route())
    clock.advance(timedelta(minutes=10))

    expired = store.resolve(key(), "ja")
    assert expired.kind is PendingResolutionKind.EXPIRED
    assert expired.action_id == pending.action_id
    assert store.resolve(key(), "ja").kind is PendingResolutionKind.NONE
    assert metrics.snapshot()["pending"]["expired"] == 1


def test_expired_pending_does_not_consume_a_fresh_explicit_request():
    clock = Clock()
    store = PendingActionStore(
        now_provider=clock,
        ttl=timedelta(minutes=10),
    )
    ready_confirmation(store, key(), reminder_route())
    clock.advance(timedelta(minutes=10))

    fresh = store.resolve(key(), "kan du vise meg kalenderen?")

    assert fresh.kind is PendingResolutionKind.NONE
    assert store.peek(key()) is None
    assert store.resolve(key(), "ja").kind is PendingResolutionKind.NONE


def test_executing_claim_does_not_expire_while_manager_is_awaited():
    clock = Clock()
    store = PendingActionStore(
        now_provider=clock,
        ttl=timedelta(minutes=10),
    )
    pending = ready_confirmation(store, key(), reminder_route())
    claimed = store.claim(key(), pending.action_id)
    assert claimed is not None
    clock.advance(timedelta(minutes=11))

    assert store.is_executing(key(), claimed)
    assert store.is_action_executing(
        key(),
        claimed.action_id,
        BotIntent.REMINDER_CREATE,
        claim_id=claimed.claim_id,
    )
    assert store.resolve(key(), "ja").kind is PendingResolutionKind.NONE
    with pytest.raises(PendingBusyError):
        store.begin_confirmation(key(), reminder_route(), "Ny")
    assert store.complete(key(), pending.action_id)


def test_cancel_and_choice_are_each_consumed_once():
    store = PendingActionStore(now_provider=Clock())
    confirmation = ready_confirmation(store, key(), reminder_route())
    assert store.cancel(key(), confirmation.action_id)
    assert not store.cancel(key(), confirmation.action_id)

    choice = ready_choices(store, key(), list_routes())
    selected = store.consume_choice(key(), choice.action_id, 1)
    assert selected is not None
    assert selected.route.intent is BotIntent.REMINDER_LIST
    assert selected.target_guard is None
    assert store.consume_choice(key(), choice.action_id, 1) is None


@pytest.mark.parametrize(
    ("intent", "pending_fields"),
    [
        (BotIntent.ACTION_CONFIRM, {}),
        (BotIntent.ACTION_CANCEL, {}),
        (
            BotIntent.ACTION_CORRECT,
            {"correction_text": "bruk den nye koden"},
        ),
    ],
)
def test_confirmation_controls_inherit_the_frozen_route_policy(
    intent,
    pending_fields,
):
    store = PendingActionStore(now_provider=Clock())
    frozen = calendar_auth_route()
    pending = ready_confirmation(store, key(), frozen)

    routes = store.effective_routes_for_history(
        key(),
        control_route(intent, pending.action_id, **pending_fields),
    )

    assert routes == (frozen,)
    assert routes[0] is not frozen
    routes[0].payload["calendar_auth"]["auth_code"] = "POISONED"
    assert (
        store.peek(key()).routes[0].payload["calendar_auth"]["auth_code"]
        == "4/SECRET-CODE"
    )


def test_selection_inherits_every_choice_even_when_selection_is_not_sensitive():
    store = PendingActionStore(now_provider=Clock())
    sensitive = calendar_auth_route()
    non_sensitive = IntentResult(BotIntent.HELP, 1.0)
    pending = ready_choices(
        store,
        key(),
        (sensitive, non_sensitive),
    )
    control = control_route(
        BotIntent.ACTION_SELECT,
        pending.action_id,
        choice_index=1,
    )

    routes = store.effective_routes_for_history(key(), control)
    assert routes == (sensitive, non_sensitive)
    routes[0].payload["poison"] = True
    assert "poison" not in store.peek(key()).routes[0].payload


@pytest.mark.parametrize(
    "choice_index",
    [None, True, -1, 99, "1"],
)
def test_malformed_choice_index_cannot_downgrade_a_sensitive_menu(
    choice_index,
):
    store = PendingActionStore(now_provider=Clock())
    sensitive = calendar_auth_route()
    non_sensitive = IntentResult(BotIntent.HELP, 1.0)
    pending = ready_choices(
        store,
        key(),
        (sensitive, non_sensitive),
    )
    pending_fields = (
        {} if choice_index is None else {"choice_index": choice_index}
    )

    routes = store.effective_routes_for_history(
        key(),
        control_route(
            BotIntent.ACTION_SELECT,
            pending.action_id,
            **pending_fields,
        ),
    )

    assert routes == (sensitive, non_sensitive)


@pytest.mark.parametrize(
    "other_key",
    [
        key(user_id=8),
        key(channel_id=11),
        key(guild_id=2),
        key(guild_id=None),
    ],
)
def test_effective_control_routes_require_the_exact_conversation_key(
    other_key,
):
    store = PendingActionStore(now_provider=Clock())
    pending = ready_confirmation(store, key(), calendar_auth_route())
    control = control_route(BotIntent.ACTION_CONFIRM, pending.action_id)

    assert store.effective_routes_for_history(other_key, control) is None


def test_effective_control_routes_require_the_exact_current_action_id():
    store = PendingActionStore(now_provider=Clock())
    stale = ready_confirmation(store, key(), calendar_auth_route())
    current = ready_confirmation(
        store,
        key(),
        reminder_route(text="ny handling"),
    )

    assert current.action_id != stale.action_id
    assert store.effective_routes_for_history(
        key(),
        control_route(BotIntent.ACTION_CONFIRM, stale.action_id),
    ) is None
    assert store.effective_routes_for_history(
        key(),
        control_route(BotIntent.ACTION_CONFIRM, current.action_id),
    ) == current.routes


@pytest.mark.parametrize(
    "route",
    [
        IntentResult(BotIntent.ACTION_CONFIRM, 1.0, {}),
        IntentResult(
            BotIntent.ACTION_CONFIRM,
            1.0,
            {"pending": None},
        ),
        IntentResult(
            BotIntent.ACTION_CONFIRM,
            1.0,
            {"pending": {}},
        ),
        control_route(BotIntent.ACTION_CONFIRM, None),
        control_route(BotIntent.ACTION_CONFIRM, ""),
        control_route(BotIntent.ACTION_CONFIRM, True),
        control_route(BotIntent.ACTION_CONFIRM, 123),
    ],
)
def test_malformed_or_missing_control_identity_fails_closed(route):
    store = PendingActionStore(now_provider=Clock())
    ready_confirmation(store, key(), calendar_auth_route())

    assert store.effective_routes_for_history(key(), route) is None


def test_missing_pending_state_fails_closed():
    store = PendingActionStore(now_provider=Clock())

    assert store.effective_routes_for_history(
        key(),
        control_route(BotIntent.ACTION_CONFIRM, "missing-action"),
    ) is None


def test_expired_pending_state_fails_closed_and_is_removed():
    clock = Clock()
    store = PendingActionStore(
        now_provider=clock,
        ttl=timedelta(seconds=1),
    )
    pending = ready_confirmation(store, key(), calendar_auth_route())
    clock.advance(timedelta(seconds=1))

    assert store.effective_routes_for_history(
        key(),
        control_route(BotIntent.ACTION_CONFIRM, pending.action_id),
    ) is None
    assert store.peek(key()) is None


@pytest.mark.parametrize("terminal", ["completed", "failed"])
def test_terminal_pending_state_fails_closed(terminal):
    store = PendingActionStore(now_provider=Clock())
    pending = ready_confirmation(store, key(), calendar_auth_route())
    assert store.claim(key(), pending.action_id) is not None
    if terminal == "completed":
        assert store.complete(key(), pending.action_id)
    else:
        assert store.fail_terminal(key(), pending.action_id)

    assert store.effective_routes_for_history(
        key(),
        control_route(BotIntent.ACTION_CONFIRM, pending.action_id),
    ) is None


@pytest.mark.parametrize("state", ["presenting", "executing"])
def test_non_ready_pending_state_fails_closed(state):
    store = PendingActionStore(now_provider=Clock())
    presentation = store.begin_confirmation(
        key(),
        calendar_auth_route(),
        "Kalenderautentisering",
    )
    if state == "presenting":
        action_id = presentation.pending.action_id
    else:
        ready = store.activate_presentation(presentation)
        assert ready is not None
        claimed = store.claim(key(), ready.action_id)
        assert claimed is not None
        action_id = claimed.action_id

    assert store.effective_routes_for_history(
        key(),
        control_route(BotIntent.ACTION_CONFIRM, action_id),
    ) is None


@pytest.mark.parametrize("corruption", ["empty", "non_route"])
def test_malformed_authoritative_pending_routes_fail_closed(corruption):
    store = PendingActionStore(now_provider=Clock())
    pending = ready_confirmation(store, key(), calendar_auth_route())
    stored = store._items[key()]
    object.__setattr__(
        stored,
        "routes",
        () if corruption == "empty" else (object(),),
    )

    assert store.effective_routes_for_history(
        key(),
        control_route(BotIntent.ACTION_CONFIRM, pending.action_id),
    ) is None


def test_terminal_tombstone_drops_sensitive_payload_and_expires():
    clock = Clock()
    store = PendingActionStore(
        now_provider=clock,
        terminal_ttl=timedelta(minutes=10),
    )
    pending = ready_confirmation(store, key(), reminder_route(), "SECRET-SUMMARY")
    assert store.claim(key(), pending.action_id)
    assert store.complete(key(), pending.action_id)

    tombstone = store.peek(key())
    assert tombstone.status is PendingStatus.COMPLETED
    assert tombstone.routes == ()
    assert tombstone.target_guards == ()
    assert tombstone.summary == ""
    clock.advance(timedelta(minutes=10))
    assert store.peek(key()) is None


def test_terminal_tombstones_have_global_lru_bound():
    clock = Clock()
    store = PendingActionStore(now_provider=clock, max_terminal=1_000)
    first_key = key(channel_id=1)
    for index in range(1_002):
        current_key = key(channel_id=index + 1)
        pending = ready_confirmation(store, current_key, reminder_route())
        assert store.claim(current_key, pending.action_id)
        assert store.complete(current_key, pending.action_id)
        clock.advance(timedelta(microseconds=1))

    assert store.peek(first_key) is None
    assert store.counts()["completed"] == 1_000


def test_pending_metrics_record_only_bounded_transition_events():
    metrics = NLUMetrics()
    store = PendingActionStore(now_provider=Clock(), metrics=metrics)
    pending = ready_confirmation(store, key(), reminder_route())
    assert store.claim(key(), "PRIVATE-WRONG-ID") is None
    assert store.claim(key(), pending.action_id) is not None
    assert store.release_retryable(
        key(),
        pending.action_id,
        DispatchOutcome.failure("not_found", retryable=True),
    )
    assert metrics.snapshot()["pending"] == {
        "claim_failed": 1,
        "confirmed": 1,
        "dispatch_failed": 1,
        "staged": 1,
    }


def test_retry_reclaim_rotates_attempt_capability():
    store = PendingActionStore(now_provider=Clock())
    pending = ready_confirmation(store, key(), reminder_route())
    first = store.claim(key(), pending.action_id)
    assert first is not None and first.claim_id
    assert store.release_retryable(
        key(),
        first.action_id,
        DispatchOutcome.failure("storage_write_failed", retryable=True),
    )
    ready = store.peek(key())
    assert ready is not None
    assert ready.status is PendingStatus.READY
    assert ready.claim_id is None

    second = store.claim(key(), first.action_id)
    assert second is not None and second.claim_id
    assert second.claim_id != first.claim_id
    assert not store.is_action_executing(
        key(),
        first.action_id,
        BotIntent.REMINDER_CREATE,
        claim_id=first.claim_id,
    )
    assert store.is_action_executing(
        key(),
        second.action_id,
        BotIntent.REMINDER_CREATE,
        claim_id=second.claim_id,
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ttl": timedelta(0)},
        {"terminal_ttl": timedelta(seconds=-1)},
        {"max_terminal": 0},
        {"max_terminal": True},
    ],
)
def test_store_rejects_invalid_bounds(kwargs):
    with pytest.raises(ValueError):
        PendingActionStore(now_provider=Clock(), **kwargs)


def test_store_rejects_naive_clock_before_mutating_state():
    store = PendingActionStore(
        now_provider=lambda: datetime(2026, 7, 14, 12, 0),
    )
    with pytest.raises(ValueError, match="pending_clock_must_be_aware"):
        store.begin_confirmation(key(), reminder_route(), "Ringe")
    assert store._items == {}


def test_choice_count_and_guard_count_are_exact():
    store = PendingActionStore(now_provider=Clock())
    with pytest.raises(ValueError, match="choice_count_must_be_two_to_five"):
        store.begin_choices(
            key(),
            (IntentResult(BotIntent.HELP, 1.0),),
            "Velg",
            target_guards=(None,),
        )
    with pytest.raises(ValueError, match="guard_count_mismatch"):
        store.begin_choices(
            key(),
            list_routes(),
            "Velg",
            target_guards=(None,),
        )
