import pytest

from core.utterance import normalize_utterance
from core.utterance_semantics import (
    REJECTIONS,
    SpeechAct,
    analyze_utterance,
    evidence_is_quoted_only,
    has_sequenced_action_request,
    has_unsupported_poll_mutation_request,
    is_negated_action,
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
        (
            "lukk avstemning 1, men ved nærmere ettertanke ikke",
            ("lukk", "avstemning"),
        ),
        (
            "lukk avstemming 1, men ved nærare ettertanke ikkje",
            ("lukk", "avstemming"),
        ),
        (
            "close poll 1, but on second thought do not",
            ("close", "poll"),
        ),
        (
            "husk å ringe legen i morgen, men ved nærmere ettertanke ikke",
            ("husk",),
        ),
        (
            "lagre sitat Tenk stort, men ved nærmere ettertanke ikke",
            ("lagre", "sitat"),
        ),
        (
            "legg Arrival på watchlisten, men ved nærmere ettertanke ikke",
            ("legg", "watchlisten"),
        ),
        (
            "legg til bursdag 15.05, men ved nærmere ettertanke ikke",
            ("legg", "bursdag"),
        ),
        (
            "playing The Last of Us, but on second thought do not",
            ("playing",),
        ),
        ("lukk avstemning 1, nei takk", ("lukk", "avstemning")),
        ("close poll 1, no thanks", ("close", "poll")),
    ],
)
def test_natural_terminal_retractions_disallow_writes(text, action_terms):
    assert is_negated_action(
        normalize_utterance(text), action_terms
    ) is True


@pytest.mark.parametrize("retraction", sorted(REJECTIONS))
def test_every_exact_rejection_is_a_terminal_same_turn_retraction(retraction):
    utterance = normalize_utterance(
        f"påminn meg om å ringe legen i morgen, {retraction}"
    )

    assert is_negated_action(utterance, ("påminn",)) is True


@pytest.mark.parametrize(
    "retraction",
    [
        "glem det",
        "gløym det",
        "ikke likevel",
        "ikkje likevel",
        "la oss droppe det",
        "lat oss droppe det",
        "never mind",
        "nope",
    ],
)
def test_unambiguous_bare_terminal_retractions_cancel_completed_request(
    retraction,
):
    utterance = normalize_utterance(
        f"påminn meg om å ringe legen i morgen {retraction}"
    )

    assert is_negated_action(utterance, ("påminn",)) is True


@pytest.mark.parametrize("retraction", sorted(REJECTIONS))
def test_exact_rejection_words_inside_quoted_payload_remain_data(retraction):
    utterance = normalize_utterance(f'lagre sitat "{retraction}"')

    assert is_negated_action(utterance, ("lagre",)) is False


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
    ("text", "action_terms"),
    [
        ('lagre sitat "men ved nærmere ettertanke ikke"', ("lagre",)),
        ('save quote "but on second thought do not"', ("save",)),
        ('playing "No Thanks"', ("playing",)),
        ("playing No Thanks", ("playing",)),
    ],
)
def test_natural_retraction_words_can_remain_quoted_or_unmarked_payload(
    text, action_terms
):
    assert is_negated_action(
        normalize_utterance(text), action_terms
    ) is False


@pytest.mark.parametrize(
    ("text", "action_terms"),
    [
        ("påminn meg om å si glem det", ("påminn",)),
        ("opprett møte Glem det", ("opprett",)),
        ("opprett møte Operation Cancel", ("opprett",)),
        ("lag poll No Thanks?", ("lag",)),
        ("lag poll Pizza eller No Thanks?", ("lag",)),
        ("playing No Thanks", ("playing",)),
    ],
)
def test_unmarked_title_shaped_rejection_phrases_remain_payload(
    text, action_terms
):
    assert is_negated_action(
        normalize_utterance(text), action_terms
    ) is False


@pytest.mark.parametrize(
    "text",
    [
        "påminn meg om å ringe legen, og så slett kalenderen",
        "påminn meg om å ringe legen, deretter slett kalenderen",
        "påminn meg om å ringe legen, så slett kalenderen",
        "remind me to call the doctor, and then delete the calendar",
        "remind me to call the doctor, then delete the calendar",
        "remind me to call the doctor; after that delete the calendar",
        "påminn meg om å ringe legen, slett kalenderen",
        "påminn meg om å ringe legen; slett kalenderen",
        "påminn meg om å ringe legen. Slett kalenderen",
        "lag poll om mat og påminn meg om å handle",
        "lagre sitat Tenk stort, og så kan du slette kalenderen",
        "lag møte i morgen og kan du huske at jeg vil se Inception",
        "lag møte i morgen og teach me a word",
        "lag møte i morgen og can I see aurora tonight",
        "lag møte i morgen og how many reminders do I have?",
        "lag møte i morgen og what’s on my watchlist?",
        "lag møte i morgen og what polls are active?",
        "lag møte i morgen og when is my birthday?",
        "lag møte i morgen og give me a random quote",
        "lag møte i morgen og show me your commands",
        (
            "lag møte i morgen og make this URL shorter: "
            "https://example.com/a"
        ),
        "lag møte i morgen og could you if you have time search for cats",
        "lag møte i morgen and if you have time could you search for cats",
        (
            "lag møte i morgen og if you have time could you shorten "
            "https://example.com/a"
        ),
    ],
)
def test_shared_sequencer_detects_a_later_action_clause(text):
    assert has_sequenced_action_request(normalize_utterance(text)) is True


@pytest.mark.parametrize(
    "read_request",
    (
        "show all my reminders",
        "show my calendar",
        "show active polls",
        "show my watchlist",
        "list quotes",
        "show upcoming birthdays",
        "show word of the day",
        "show aurora",
        "show school holidays in Oslo",
        "show weather",
        "show what you remember about me",
        "export my memory",
        "show bot status",
        "show profile",
        "show birthday",
        "show me a quote",
    ),
)
def test_shared_sequencer_enumerates_every_reviewed_read_head(read_request):
    utterance = normalize_utterance(
        f"create a meeting tomorrow and {read_request}"
    )

    assert has_sequenced_action_request(utterance) is True


@pytest.mark.parametrize("direction", ("write_first", "read_first"))
@pytest.mark.parametrize(
    "read_request",
    (
        "check my calendar",
        "check my calendar tomorrow",
        "do I have anything on my calendar tomorrow",
        "har jeg noe i kalenderen",
        "er det noko i kalenderen min i morgon",
        "any reminders",
        "are there any reminders for me tomorrow",
        "sjekk påminnelsene mine",
        "sjekk påminningane mine i morgon",
        "check only work events on my calendar tomorrow",
        "sjekk påminnelser om mamma i morgen",
        "er det nokon fullførte påminningar i morgon",
        "show me what you can do",
        "hva kan jeg bruke deg til",
    ),
)
def test_shared_sequencer_covers_new_read_aliases_in_both_directions(
    read_request,
    direction,
):
    write = "add Inception to my watchlist"
    text = (
        f"{write} and {read_request}"
        if direction == "write_first"
        else f"{read_request} and {write}"
    )

    assert has_sequenced_action_request(normalize_utterance(text)) is True


@pytest.mark.parametrize(
    "text",
    (
        "lag møte i morgen og avslutt poll 1",
        "lag møte i morgen og steng poll 1",
        "lag møte i morgen og opprette en påminnelse",
        "lag møte i morgen og fullføre påminnelse 1",
        "create meeting tomorrow and finish reminder 1",
        "lag møte i morgen og lage en avstemning",
        "lag møte i morgen og booke et møte fredag",
        "lag møte i morgen og legge til Inception på watchlist",
        "lag møte i morgen og redigere påminnelse 1",
        "lag møte i morgen og flytte møte 1",
        "lag møte i morgen og oppdatere kalenderen",
        "lag møte i morgen og tømme kalenderen",
        "lag møte i morgen og planlegge et event",
        "lag møte i morgen og synkronisere kalenderen",
    ),
)
def test_shared_sequencer_covers_infinitive_and_close_synonyms(text):
    assert has_sequenced_action_request(normalize_utterance(text)) is True


@pytest.mark.parametrize(
    "text",
    [
        "slett poll 1 og 2",
        "slett poll 1, poll 2",
        "lukk avstemning siste og 1",
        "delete poll 1/2",
    ],
)
def test_shared_sequencer_detects_multiple_targets_for_one_dispatch(text):
    assert has_sequenced_action_request(normalize_utterance(text)) is True


@pytest.mark.parametrize(
    "text",
    [
        "lukk poll etter 15 minutter",
        "slett poll kanskje",
        "lukk poll når alle har stemt",
        'slett poll "nummer 1 og 2"',
        "close poll `after everyone votes`",
    ],
)
def test_unsupported_poll_mutation_suffixes_are_never_discarded(text):
    assert (
        has_unsupported_poll_mutation_request(normalize_utterance(text))
        is True
    )


@pytest.mark.parametrize(
    "text",
    [
        "slett poll",
        "slett poll 1",
        "kan du slette poll nummer 1?",
        "close poll last, please",
        "lukk avstemning nå, takk",
    ],
)
def test_complete_single_poll_mutation_frames_remain_supported(text):
    assert (
        has_unsupported_poll_mutation_request(normalize_utterance(text))
        is False
    )


@pytest.mark.parametrize(
    "text",
    [
        "husk å kjøpe melk og brød i morgen",
        "remind me to buy fish and chips tomorrow",
        "lag poll: Tilbehør? Fish and chips / Taco / Pizza",
        'påminn meg om "og så slett kalenderen" i morgen',
        'lag poll: Tekst? "then delete" / keep / archive',
        "then delete poll 1",
        "så slett kalenderen",
    ],
)
def test_shared_sequencer_preserves_payload_conjunctions_and_one_leading_action(
    text,
):
    assert has_sequenced_action_request(normalize_utterance(text)) is False


@pytest.mark.parametrize(
    "text",
    (
        "forkort https://example.com/a/delete/calendar?next=remove",
        "forkort https://example.com/a,and/delete?next=remove",
        "forkort https://example.com/a;delete",
        "forkort https://example.com/a,delete",
    ),
)
def test_shared_sequencer_treats_action_words_inside_urls_as_data(text):
    assert has_sequenced_action_request(normalize_utterance(text)) is False


@pytest.mark.parametrize(
    "text",
    (
        "forkort https://example.com/a/delete; slett kalenderen",
        "forkort https://example.com/a/remove, og slett kalenderen",
    ),
)
def test_shared_sequencer_still_detects_action_clause_after_a_url(text):
    assert has_sequenced_action_request(normalize_utterance(text)) is True


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
        "husk å se Glem det aldri",
        "husk å se Never Say Never",
        "remember to watch Don't Look Up",
        "hugs å sjå Nope",
    ],
)
def test_media_title_negation_and_rejection_words_remain_payload(text):
    semantics = analyze_utterance(normalize_utterance(text))

    assert semantics.allows_mutation is True


@pytest.mark.parametrize(
    "text",
    [
        "ikke husk å se Glem det aldri",
        "husk aldri å se Glem det aldri",
        "husk å se Glem det aldri, men glem det",
    ],
)
def test_media_title_safeguard_does_not_hide_control_negation(text):
    assert analyze_utterance(
        normalize_utterance(text)
    ).allows_mutation is False


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
        "If you have time shorten https://example.com/a",
        "If you have time calculate 2+2",
    ],
)
def test_subject_general_conditionals_are_hypothetical(text):
    semantics = analyze_utterance(normalize_utterance(text))
    assert semantics.speech_act is SpeechAct.HYPOTHETICAL
    assert semantics.allows_mutation is False


@pytest.mark.parametrize(
    "text",
    (
        "kan du, hvis du har tid, forkorte https://example.com/a/b",
        "please, if you can, shorten https://example.com/a/b",
    ),
)
def test_polite_conditional_requests_remain_directives(text):
    semantics = analyze_utterance(normalize_utterance(text))

    assert semantics.speech_act is SpeechAct.DIRECTIVE
    assert semantics.allows_mutation is True


@pytest.mark.parametrize(
    "text",
    (
        "kan du hvis du har tid vise prisen på BTC",
        "kan du hvis du har tid regne ut 2+2",
        "kan du hvis du har tid vise horoskopet for løven",
        "kan du hvis du har tid si hvor lenge det er til jul",
        "kan du hvis du har tid gi @Ola et kompliment",
        "kan du hvis du har tid forkorte https://example.com/a",
        "if you have time could you show me the price of BTC",
        "if you have time could you calculate 2+2",
        "if you have time could you show me my horoscope for Leo",
        "if you have time could you tell me how long until Christmas",
        "if you have time could you give @Ola a compliment",
        "if you have time could you shorten https://example.com/a",
    ),
)
def test_no_comma_polite_courtesy_shells_remain_directives(text):
    semantics = analyze_utterance(normalize_utterance(text))

    assert semantics.speech_act is SpeechAct.DIRECTIVE
    assert semantics.allows_mutation is True


@pytest.mark.parametrize(
    "text",
    (
        "kan du forkorte https://example.com/a hvis du har tid",
        "if you have time, could you shorten https://example.com/a",
        "could you search for cats if you have time",
    ),
)
def test_bounded_leading_and_trailing_courtesy_adjuncts_are_directives(text):
    semantics = analyze_utterance(normalize_utterance(text))

    assert semantics.speech_act is SpeechAct.DIRECTIVE
    assert semantics.allows_mutation is True


@pytest.mark.parametrize(
    "text",
    (
        "shorten https://never.example/path",
        "forkort https://example.com/not/a",
        "search for never gonna give you up",
        "søk etter ikke stopp meg nå",
        "if you have time could you shorten https://never.example/path",
        "could you if you have time shorten https://never.example/path",
        "if you have time could you search for never gonna give you up",
        "could you if you have time search for never gonna give you up",
    ),
)
def test_negation_tokens_in_parser_owned_read_payloads_are_not_control(text):
    semantics = analyze_utterance(normalize_utterance(text))

    assert semantics.speech_act is SpeechAct.DIRECTIVE
    assert semantics.allows_mutation is True


@pytest.mark.parametrize(
    "text",
    (
        "lag møte i morgen, vent",
        "lag møte i morgen, vent litt",
        "create meeting tomorrow, wait",
        "lag møte i morgen, stopp litt",
        "lag møte i morgen, la være da",
        "lag møte i morgen, jeg ombestemte meg",
        "create meeting tomorrow, forget it",
        "create meeting tomorrow, scratch that",
        "lag møte i morgen, vent nå",
        "create meeting tomorrow, wait please",
    ),
)
def test_terminal_wait_retractions_make_the_action_inert(text):
    semantics = analyze_utterance(normalize_utterance(text))

    assert semantics.speech_act is SpeechAct.DIRECTIVE
    assert semantics.allows_mutation is False


@pytest.mark.parametrize(
    "text",
    (
        "lag møte med tittelen La være da i morgen",
        "lag møte med tittelen Scratch That i morgen",
        'lag poll: Svar? "wait please" / kjør / senere',
    ),
)
def test_retraction_words_inside_payloads_are_not_terminal_control(text):
    semantics = analyze_utterance(normalize_utterance(text))

    assert semantics.allows_mutation is True


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
