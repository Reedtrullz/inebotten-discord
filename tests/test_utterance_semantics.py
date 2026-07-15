import pytest

from core.utterance import normalize_utterance
from core.utterance_semantics import (
    SpeechAct, analyze_utterance, evidence_is_quoted_only, is_negated_action,
)


@pytest.mark.parametrize(
    "text",
    [
        "ikke slett kalenderen", "slett ikke kalenderen",
        "ikkje slett kalenderen", "do not delete the calendar",
        "never delete the calendar",
        "jeg vil ikke at du skal slette kalenderen",
        "I do not want you to delete the calendar",
    ],
)
def test_negated_delete_disallows_mutation(text):
    utterance = normalize_utterance(text)
    assert is_negated_action(
        utterance,
        ("slett", "slette", "sletter", "slettar", "delete"),
    ) is True
    assert analyze_utterance(utterance).allows_mutation is False


@pytest.mark.parametrize(
    "text",
    [
        "I can't delete the calendar",
        "I can’t delete the calendar",
        "I cannot delete the calendar",
        "I won't delete the calendar",
        "I won’t delete the calendar",
        "I shouldn't delete the calendar",
        "I shouldn’t delete the calendar",
    ],
)
def test_english_contraction_negations_disallow_mutation(text):
    utterance = normalize_utterance(text)
    assert is_negated_action(utterance, ("delete",)) is True
    assert analyze_utterance(utterance).allows_mutation is False


@pytest.mark.parametrize(
    "text",
    [
        "ikke glem møte i morgen kl 14",
        "ikkje gløym møte i morgon klokka 14",
        "don't forget the meeting tomorrow at 2pm",
    ],
)
def test_do_not_forget_idiom_is_positive(text):
    assert analyze_utterance(normalize_utterance(text)).allows_mutation is True


@pytest.mark.parametrize(
    "text",
    [
        "ikke glem å ikke opprette møtet",
        "ikkje gløym å ikkje opprette møtet",
        "don't forget not to create the meeting",
    ],
)
def test_second_negation_is_not_erased_by_positive_forget(text):
    utterance = normalize_utterance(text)
    assert is_negated_action(
        utterance,
        ("opprette", "create"),
        allow_positive_forget=True,
    ) is True


@pytest.mark.parametrize(
    "text",
    [
        (
            "slett poll 1 fordi den er gammel og ingen har stemt på den "
            "på flere uker, men ikke gjør det"
        ),
        (
            "slett sitat 2 fordi det ikkje lenger er relevant for nokon i "
            "kanalen, men ikkje gjer det"
        ),
        (
            "delete quote 2 because it has been obsolete for everyone here "
            "for several weeks, but do not do it"
        ),
        (
            "legg til Interstellar på watchlisten for helgen sammen med de "
            "andre filmene, men avbryt"
        ),
        (
            "husk å kjøpe melk etter jobb når butikken fortsatt er åpen "
            "og jeg er på vei hjem, men stopp"
        ),
        (
            "add Dune Part Two to the watchlist for the weekend with the "
            "rest of the films, but cancel it"
        ),
        (
            "opprett møte med Eva i morgen klokken 14 for å gå gjennom "
            "hele planen. Avbryt."
        ),
    ],
)
def test_distant_trailing_cancellation_disallows_mutation(text):
    semantics = analyze_utterance(normalize_utterance(text))
    assert semantics.speech_act is SpeechAct.DIRECTIVE
    assert semantics.allows_mutation is False
    assert "negated_action" in semantics.reasons


@pytest.mark.parametrize(
    ("text", "action_terms"),
    [
        ("slett poll 1 avbryt", ("slett", "poll")),
        ("delete poll 1 cancel", ("delete", "poll")),
        ("kalender auth cancel", ("auth", "kalender")),
        ("kalenderkode avbryt", ("kalenderkode",)),
        (
            "endre møte med Ola til fredag avbryt",
            ("endre", "møte"),
        ),
        (
            "edit meeting with Ola to Friday cancel",
            ("edit", "meeting"),
        ),
        (
            "legg Arrival på watchlisten avbryt",
            ("legg", "watchlisten"),
        ),
        (
            "add Arrival to the watchlist cancel",
            ("add", "watchlist"),
        ),
        ("husk å kjøpe melk stopp", ("husk",)),
    ],
)
def test_bare_terminal_cancellation_after_complete_frame_is_control(
    text, action_terms
):
    assert is_negated_action(
        normalize_utterance(text), action_terms
    ) is True


@pytest.mark.parametrize(
    ("text", "action_terms"),
    [
        ("husk å si stopp", ("husk",)),
        ("husk å se Stop", ("husk",)),
        ("playing Stop", ("playing",)),
        ("playing The Last Stop", ("playing",)),
        ("husk å se The Last Stop", ("husk",)),
        ("legg til filmen Cancel", ("legg",)),
        ("legg til filmen Operation Cancel", ("legg",)),
        ("add film Cancel", ("add",)),
        (
            "legg til filmen Cancel på watchlisten",
            ("legg", "watchlisten"),
        ),
        ("endre tittel til Cancel", ("endre",)),
        ("endre tittel til Operation Cancel", ("endre",)),
        ("lagre sitat Operation Cancel", ("lagre", "sitat")),
        ("save quote The Last Stop", ("save", "quote")),
    ],
)
def test_bare_cancellation_word_can_be_the_payload_target(
    text, action_terms
):
    assert is_negated_action(
        normalize_utterance(text), action_terms
    ) is False


@pytest.mark.parametrize(
    "text",
    [
        "ikke glem å kjøpe melk på dager der jeg ikke gjør det ofte",
        "ikkje gløym å kjøpe mjølk på dagar der eg ikkje gjer det ofte",
        "don't forget to buy milk on days when I do not do it often",
        "legg til filmen Cancel på watchlisten",
        "husk å si stopp",
        "opprett et møte om hvordan Per ikke gjør det",
    ],
)
def test_payload_words_and_distant_negation_are_not_cancellation(text):
    semantics = analyze_utterance(normalize_utterance(text))
    assert semantics.speech_act is SpeechAct.DIRECTIVE
    assert semantics.allows_mutation is True


@pytest.mark.parametrize(
    "text",
    [
        "Hvorfor slettet du kalenderen?",
        "Kan man slette kalenderen?",
        "Er det mulig å slette kalenderen?",
        "Kan du forklare hvordan jeg sletter kalenderen?",
        "Kan du si hvordan jeg kan flytte møtet?",
        "Kan du seie korleis eg kan flytte møtet?",
        "Could you explain how to delete a reminder?",
        "Why did you delete the calendar?",
        "Is it possible to delete the calendar?",
    ],
)
def test_questions_about_mutation_are_information_requests(text):
    semantics = analyze_utterance(normalize_utterance(text))
    assert semantics.speech_act is SpeechAct.INFORMATION_REQUEST
    assert semantics.allows_mutation is False


@pytest.mark.parametrize(
    "text",
    [
        "Kan jeg slette kalenderen?",
        "Kan eg slette kalenderen?",
        "Kan æ slette kalenderen?",
        "Can I delete the calendar?",
        "May I delete reminder 1?",
        "Could I delete reminder 1?",
    ],
)
def test_permission_questions_about_mutation_are_information_requests(text):
    semantics = analyze_utterance(normalize_utterance(text))
    assert semantics.speech_act is SpeechAct.INFORMATION_REQUEST
    assert semantics.allows_mutation is False
    assert semantics.reasons == ("permission_question",)


@pytest.mark.parametrize(
    "text",
    [
        "Hvis du sletter kalenderen, mister jeg alt",
        "Om du slettar kalenderen, mistar eg alt",
        "If you delete the calendar, I lose everything",
    ],
)
def test_subject_general_conditionals_are_hypothetical(text):
    semantics = analyze_utterance(normalize_utterance(text))
    assert semantics.speech_act is SpeechAct.HYPOTHETICAL
    assert semantics.allows_mutation is False


@pytest.mark.parametrize(
    "text",
    [
        "det var et godt forslag",
        "kalenderen ble slettet i går",
        "the reminder was deleted yesterday",
    ],
)
def test_substrings_and_past_descriptions_are_not_directives(text):
    semantics = analyze_utterance(normalize_utterance(text))
    assert semantics.speech_act is SpeechAct.STATEMENT


def test_quoted_action_is_not_control_evidence():
    utterance = normalize_utterance(
        'hva skjer hvis jeg skriver "slett kalenderen"?'
    )
    assert evidence_is_quoted_only(utterance, ("slett", "kalender")) is True
    assert analyze_utterance(utterance).speech_act is SpeechAct.HYPOTHETICAL


@pytest.mark.parametrize(
    "text",
    ["kan du slette kalenderen?", "could you delete reminder 1?"],
)
def test_polite_question_form_is_a_directive(text):
    semantics = analyze_utterance(normalize_utterance(text))
    assert semantics.speech_act is SpeechAct.DIRECTIVE
    assert semantics.allows_mutation is True


def test_information_question_does_not_allow_mutation():
    semantics = analyze_utterance(
        normalize_utterance("Når går toget i morgen kl 8?")
    )
    assert semantics.speech_act is SpeechAct.INFORMATION_REQUEST
    assert semantics.allows_mutation is False


@pytest.mark.parametrize(
    "text",
    [
        "jeg vurderer kanskje å slette møte",
        "eg vurderer å slette møte",
        "jeg tenker på å slette møte",
        "I am considering deleting the meeting",
        "maybe I should delete the meeting",
    ],
)
def test_hedged_action_is_hypothetical_not_a_directive(text):
    semantics = analyze_utterance(normalize_utterance(text))
    assert semantics.speech_act is SpeechAct.HYPOTHETICAL
    assert semantics.allows_mutation is False
