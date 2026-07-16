from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from collections.abc import Iterable

from core.list_read_filters import looks_like_list_read_request
from core.utterance import NormalizedUtterance, normalize_utterance


class SpeechAct(str, Enum):
    DIRECTIVE = "directive"
    INFORMATION_REQUEST = "information_request"
    STATEMENT = "statement"
    HYPOTHETICAL = "hypothetical"
    META = "meta"
    CONFIRMATION = "confirmation"
    REJECTION = "rejection"


@dataclass(frozen=True, slots=True)
class UtteranceSemantics:
    speech_act: SpeechAct
    reasons: tuple[str, ...]
    allows_mutation: bool


CONFIRMATIONS = frozenset({
    "ja", "yes", "jepp", "japp", "bekreft", "confirm", "ok", "okay",
    "gjør det", "gjer det", "kjør på", "køyr på", "det stemmer",
    "go ahead", "sure", "yep",
})
REJECTIONS = frozenset({
    "nei", "no", "avbryt", "cancel", "stopp", "dropp det",
    "ikke gjør det", "ikkje gjer det", "nei takk", "no thanks",
    "ikke likevel", "ikkje likevel", "glem det", "gløym det",
    "la oss droppe det", "lat oss droppe det", "never mind", "nope",
})

# The dispatch contract can execute exactly one user-visible action per turn.
# Keep this sequencer grammar here so deterministic parsers and the model
# bridge cannot drift into different partial-execution policies.  Quoted/code
# spans are already absent from ``NormalizedUtterance.control_text``.
_SEQUENCED_DOMAIN = (
    r"kalender(?:en)?|calendar|gcal|møte(?:t)?|meeting|avtale(?:n)?|"
    r"arrangement(?:et)?|event|påminnelse(?:n)?|påminning(?:a)?|reminder|"
    r"poll|avstemning(?:en)?|avstemming(?:a)?|watchlist(?:a)?|"
    r"sitat(?:et)?|quote|minne(?:t)?|memory|"
    r"bursdag(?:en)?|birthday"
)
_SEQUENCED_ARTICLE = r"(?:(?:en|ei|et|a|an|the)\s+)?"
_SEQUENCED_READ_MODIFIER = (
    r"(?:(?:all|alle|my|min|mine|the|active|aktive|upcoming|kommende|"
    r"komande|a|an|en|ei|et|eit)\s+)*"
)
_SEQUENCED_READ_TARGET = (
    r"reminders|påminnels(?:er|ene)|påminningar|calendar|kalender(?:en)?|"
    r"schedule|timeplan(?:en)?|"
    r"polls|avstemninger|avstemmingar|watchlist(?:a|en)?|watch\s+list|"
    r"quotes|sitat(?:er|ene)|birthdays|bursdager|bursdagar|"
    r"word\s+of\s+the\s+day|dagens\s+ord|aurora|nordlys(?:varselet)?|"
    r"school\s+holidays|skoleferie(?:r|ne)?|weather|vær(?:et)?|"
    r"bot\s+status|botstatus|profile|profil(?:en)?|birthday|bursdag(?:en)?|"
    r"quote|sitat(?:et)?|memory|minne(?:t)?|commands|kommandoer|oversikt|overview|"
    r"dagens\s+oppsummering|daily\s+(?:digest|summary)"
)
_SEQUENCED_READ_HEAD = (
    rf"(?:show|list|vis|vise|liste)\s+"
    rf"(?:(?:me|meg|mæ)\s+)?{_SEQUENCED_READ_MODIFIER}"
    rf"(?:{_SEQUENCED_READ_TARGET})\b|"
    r"(?:show|vis|vise)\s+(?:(?:me|meg|mæ)\s+)?"
    r"(?:what\s+you\s+remember\s+about\s+me|"
    r"hva\s+du\s+husker\s+om\s+meg)\b|"
    r"(?:export|eksporter|eksportere)\s+(?:my\s+memory|minnet\s+mitt)\b"
)
_SEQUENCED_ACTION_HEAD = (
    rf"(?:{_SEQUENCED_READ_HEAD})|"
    # Bounded self-describing heads that production parsers intentionally
    # accept without a command verb.  Keep these here for ActionBridge, which
    # has no manager/router dependency; IntentRouter additionally performs a
    # context-aware collector probe for the complete supported surface.
    r"(?:hjelp|help|status)\b|"
    r"(?:møte|meeting)\b|"
    r"(?:ikke\s+(?:glem|la\s+meg\s+glemme)|"
    r"ikkje\s+(?:gløym|lat\s+meg\s+gløyme)|"
    r"don['’]?t\s+(?:let\s+me\s+)?forget)\b|"
    r"(?:husk|huske|hugs|hugse)\b|"
    r"(?:spiller|playing)\s+[^,;.?!]+|"
    r"(?:pris|price|roast)\b|"
    r"(?:høstferie|haustferie|school\s+holidays)\b|"
    r"(?:make)\s+(?:a\s+)?poll\b|"
    r"(?:make|set|put)\s+(?:a\s+)?reminder"
    r"(?:\s+for\s+me)?\s+(?:to|about)\b|"
    r"(?:i['’]d|i\s+would)\s+like\s+(?:a\s+)?reminder\s+to\b|"
    r"(?:i\s+(?:want|need)|(?:can|could)\s+i\s+get)\s+"
    r"(?:a\s+)?reminder(?:\s+for\s+me)?\s+(?:to|about)\b|"
    r"give\s+me\s+(?:a\s+)?reminder(?:\s+for\s+me)?\s+"
    r"(?:to|about)\b|"
    r"make\s+(?:a|an)\s+(?:[^,;.?!]+\s+)?appointment\b|"
    r"(?:legg(?:e)?\s+til)\s+(?:(?:en|ei|et|eit)\s+)?"
    r"(?:møte|avtale|arrangement)\b|"
    r"(?:finn|find)\s+(?:påminnels(?:e|en)|påminning|reminder)\b|"
    r"(?:check|sjekk|sjekke)\s+(?:(?:the|min|mitt|my)\s+)?"
    r"(?:price|prisen|horoscope|horoskop(?:et)?)\b|"
    r"(?:hva|kva|ka)\s+(?:skjer|vet|veit|står|er\s+status)\b|"
    r"(?:når|when)\s+(?:går|leaves|does)\b|"
    r"(?:hvordan|korleis|how)\s+(?:er|is)\s+(?:været|weather)\b|"
    r"what\s+(?:is\s+on\s+my\s+calendar|reminders\s+do\s+i\s+have|"
    r"quotes\s+have\s+i\s+saved|is\s+.+?\s+worth)\b|"
    r"(?:fortell|fortelje|tell)\s+(?:(?:meg|mæ|me)\s+)?"
    r"(?:om\s+(?:påminnelsene|påminningane)|(?:the\s+)?days\s+until|"
    r"how\s+long)\b|"
    r"(?:si|sei)\s+(?:(?:meg|mæ)\s+)?(?:hvor|kor)\s+lenge\b|"
    r"(?:hva|kva|ka)\s+(?:kan\s+du\s+(?:gjøre|gjere)|"
    r"har\s+(?:jeg|eg|æ)\s+på\s+watchlist(?:a|en)?\s+(?:min|mi|mitt)|"
    r"skal\s+(?:vi|me)\s+(?:se|sjå))\b|"
    r"(?:what\s+can\s+you\s+help\s+me\s+with|"
    r"tell\s+me\s+what\s+you\s+can\s+do|"
    r"show\s+me\s+what\s+you\s+can\s+do|"
    r"how\s+can\s+you\s+help(?:\s+me)?|"
    r"what\s+(?:are\s+you\s+capable\s+of|"
    r"capabilities\s+do\s+you\s+have|features\s+do\s+you\s+have))\b|"
    r"(?:hva|kva|ka)\s+kan\s+du\s+hjelpe"
    r"(?:\s+(?:meg|mæ))?\s+med\b|"
    r"(?:hva|kva|ka)\s+kan\s+(?:jeg|eg|æ)\s+bruke\s+"
    r"(?:deg|dæ)\s+til\b|"
    r"hvilke\s+ting\s+kan\s+du\s+(?:gjøre|gjere)\b|"
    r"har\s+(?:jeg|eg|æ)\s+(?:noen|nokon)\s+"
    r"(?:påminnelser|påminningar)\b|"
    r"har\s+(?:jeg|eg|æ)\s+(?:påminnelser|påminningar)\s+"
    r"(?:i\s+morgen|i\s+morgon)\b|"
    r"(?:any\s+reminders\s+for\s+me|"
    r"can\s+i\s+see\s+my\s+reminders|"
    r"what\s+do\s+i\s+need\s+to\s+remember|"
    r"(?:is\s+there\s+)?anything\s+i\s+need\s+to\s+remember)\b|"
    r"har\s+(?:jeg|eg|æ)\s+noe\s+i\s+kalenderen\s+"
    r"(?:i\s+morgen|i\s+morgon)\b|"
    r"kan\s+(?:jeg|eg|æ)\s+(?:se|sjå)\s+(?:kalenderen|"
    r"påminnelsene|påminningane)\s+min(?:e)?\b|"
    r"(?:hva|kva|ka)\s+(?:må\s+(?:jeg|eg|æ)\s+(?:huske|hugse)|"
    r"står\s+på\s+(?:huskelista|hugselista))\b|"
    r"når\s+har\s+(?:jeg|eg|æ)\s+bursdag\b|"
    r"could\s+i\s+see\s+my\s+(?:calendar|reminders)\b|"
    r"can\s+i\s+see\s+my\s+calendar\b|"
    r"will\s+it\s+rain(?:\s+today)?\b|"
    r"is\s+it\s+going\s+to\s+rain(?:\s+today)?\b|"
    r"do\s+i\s+need\s+(?:an?\s+)?umbrella(?:\s+today)?\b|"
    r"(?:trenger|treng)\s+(?:jeg|eg|æ)\s+"
    r"(?:(?:en|ei|ein)\s+)?paraply(?:\s+i\s+dag)?\b|"
    r"what(?:\s+is|['’]s)\s+(?:the\s+)?forecast(?:\s+today)?\b|"
    r"what\s+is\s+the\s+weather\s+forecast\b|"
    r"what\s+is\s+coming\s+up\s+on\s+my\s+calendar\b|"
    r"(?:how(?:\s+is|['’]s)\s+(?:the\s+)?weather|"
    r"(?:hvordan|korleis)\s+(?:er|blir)\s+(?:været|vêret)|"
    r"blir\s+det\s+regn(?:\s+i\s+dag)?|"
    r"(?:how\s+warm\s+is\s+it|(?:hvor|kor)\s+varmt\s+er\s+det)\s+"
    r"(?:in|i))\b|"
    r"(?:kven|hvem|who)\s+har\s+(?:bursdag|birthday)\s+snart\b|"
    r"(?:legg(?:e)?\s+inn)\b|"
    r"(?:book|booke|set\s+up|sette\s+opp|setje\s+opp)\s+"
    r"[^,;.?!]{1,120}\b|"
    r"put(?!\s+(?:differently|another\s+way)\b)\s+"
    r"[^,;.?!]{1,120}\s+(?:on|in)\s+(?:my|the)\s+calendar\b|"
    r"add\s+[^,;.?!]{1,120}\s+to\s+(?:my|the)\s+calendar\b|"
    r"(?:i['’]d|i\s+would)\s+like\s+to\s+add\s+"
    r"[^,;.?!]{1,120}\s+to\s+(?:my|the)\s+calendar\b|"
    r"(?:schedule\s+(?!is\b|are\b|for\b|today\b|tomorrow\b|tonight\b)"
    r"\S+|planlegg(?:e|je)?\s+\S+)\b|"
    r"(?:marker|markere)\s+(?:møte(?:t)?|avtale(?:n)?|"
    r"påminnelse(?:n)?)\b|"
    r"(?:kalender|calendar|gcal)\s+(?:auth|login|kode|code)\b|"
    r"(?:jeg|eg|æ|i)\s+(?:stemmer|røystar|vote)\s+"
    r"(?:på|for)\s+(?:alternativ|option)\s+(?:\d+|en|ett|one|to|two)\b|"
    r"(?:jeg|eg|æ|i)\s+(?:bor|bur|live)\s+(?:i|in)\b|"
    rf"(?:slett|slette|delete|fjern|fjerne|remove|tøm|tømme|clear|"
    rf"endre|rediger|redigere|edit|flytt|flytte|move|oppdater|oppdatere|"
    rf"update|lukk|lukke|close|avslutt|avslutte|steng|stenge|"
    rf"fullfør|fullføre|complete|finish|ferdig|done|synk|synkroniser|"
    rf"synkronisere|sync)\s+{_SEQUENCED_ARTICLE}(?:{_SEQUENCED_DOMAIN})\b|"
    rf"(?:opprett|opprette|create|lag|lage|book|booke|planlegg|planlegge|"
    rf"planleggje|"
    rf"schedule)\s+{_SEQUENCED_ARTICLE}(?:{_SEQUENCED_DOMAIN})\b|"
    r"(?:endre|rediger|redigere|edit|change)\s+"
    r"(?:tittel(?:en)?|(?:the\s+)?title)\b|"
    r"(?:påminn(?:e)?|minn(?:e)?)\s+(?:meg|mæ)\b|remind\s+me\b|"
    r"(?:husk|remember)\s+(?:å|to)\b|"
    r"i\s+need\s+to\s+remember\s+to\b|"
    r"(?:jeg|eg|æ)\s+må\s+(?:huske|hugse)\s+(?:å|at)\b|"
    r"(?:pass\s+på|sørg\s+for|syt\s+for)\s+at\b|"
    r"make\s+sure(?:\s+that)?\s+i(?:\s+remember\s+to)?\b|"
    r"(?:husk|huske|hugs|hugse)\s+at\s+(?:jeg|eg|æ)\s+"
    r"(?:vil|skal)\s+(?:se|sjå)\b|"
    r"(?:stem|vote)(?:\s+(?:på|for))?\s+(?:\d+|en|one|to|two)\b|"
    r"(?:lagre|save)\s+(?:(?:dette|this)\s+(?:som|as)\s+)?"
    r"(?:(?:et|eit|a)\s+)?(?:sitat|quote)\b|"
    r"(?:legg(?:e)?\s+til\s+bursdag(?:en)?"
    r"(?:\s+(?:min|mi|mitt))?|add\s+(?:my\s+)?birthday)\b|"
    r"(?:legg(?:e)?(?:\s+til)?|add)\b(?=[^,;.]{1,120}\b(?:"
    r"watchlist(?:a|en)?|filmlist(?:e|a|en))\b)|"
    r"(?:forkort|forkorte|kort\s+ned|korte\s+ned|shorten)\b|"
    r"(?:søk|søke|søkje|search|look\s+up)\b|"
    r"(?:vis|vise|show)\s+(?:(?:meg|mæ|me)\s+)?"
    r"(?:(?:your|dine|the|my|min|mitt)\s+)?"
    r"(?:prisen?|price|horoskop(?:et)?|horoscope|status|"
    r"nedtelling(?:en)?|countdown|påminnelser|påminningar|reminders|"
    r"watchlist(?:a|en)?|watch\s+list|sitater|quotes|commands|kommandoer|"
    r"daily\s+(?:digest|summary)|daglig\s+oppsummering|"
    r"aurora\s+forecast|nordlysvarselet)\b|"
    r"(?:how\s+many\s+reminders\s+do\s+i\s+have|"
    r"do\s+i\s+have\s+any\s+reminders|"
    r"what\s+polls\s+are\s+active|"
    r"are\s+there\s+any\s+active\s+polls|"
    r"(?:what\s+is|what['’]s)\s+on\s+my\s+(?:watchlist|watch\s+list)|"
    r"which\s+(?:movies|films|series|shows)\s+are\s+on\s+my\s+"
    r"(?:watchlist|watch\s+list)|"
    r"(?:when|what)(?:\s+is|['’]s)\s+my\s+birthday|"
    r"who\s+has\s+(?:a\s+)?birthday\s+coming\s+up|"
    r"give\s+me\s+(?:a\s+)?random\s+quote|"
    r"make\s+this\s+url\s+shorter)\b|"
    r"(?:hva|kva|ka|what)\s+(?:koster|kostar|does\s+.+?\s+cost)\b|"
    r"how\s+much\s+(?:is|does)\b|"
    r"(?:regn(?:e)?\s+ut|rekn(?:e)?\s+ut|kalk(?:uler(?:e)?)?|"
    r"calculate|calc|compute|work\s+out|konverter(?:e)?|convert|"
    r"omgjør|gjør\s+om|gjer\s+om)\b|"
    r"(?:(?:hvor\s+(?:lenge|mange\s+dager)|"
    r"kor\s+(?:lenge|mange\s+dagar))(?:\s+er\s+det)?|"
    r"når\s+er|how\s+long(?:\s+is\s+it)?|"
    r"how\s+many\s+days(?:\s+are\s+there)?|when\s+is|"
    r"(?:dager|dagar|days)\s+(?:til|to|until)|"
    r"(?:nedtelling|nedteljing|countdown|count\s+down)(?:en|a)?)\b|"
    r"(?:what|when)['’]s\b|"
    r"(?:lær|lære|teach)(?:\s+(?:meg|mæ|me))?\s+"
    r"(?:(?:et|eit|a)\s+(?:ord|word)|dagens\s+ord)\b|"
    r"(?:gi|gje|give)\s+(?:(?:meg|mæ|me)\s+)?"
    r"(?:(?:det|the)\s+)?(?:dagens\s+ord|word\s+of\s+the\s+day)\b|"
    r"(?:(?:kan|vil)\s+(?:jeg|eg|æ)\s+(?:se|sjå)\s+"
    r"(?:nordlys|aurora)|(?:blir|er)\s+det\s+(?:nordlys|aurora)|"
    r"(?:will|can|could)\s+i\s+see\s+(?:the\s+)?"
    r"(?:aurora|northern\s+lights)|(?:is\s+there|will\s+there\s+be)\s+"
    r"(?:an?\s+|the\s+)?(?:aurora|northern\s+lights))\b|"
    r"(?:sett|sette|set)\s+(?:(?:min|my)\s+)?"
    r"(?:status(?:en)?|aktivitet(?:en)?|activity|location|lokasjon)\b|"
    r"(?:fortell|fortelle|fortelj|fortelje|tell)\s+"
    r"(?:(?:meg|mæ|me)\s+)?(?:hvor|kor|how)\s+"
    r"(?:mange\s+(?:dager|dagar)|many\s+days)\b|"
    r"(?:start|vis|vise|show)\s+(?:en\s+|a\s+)?"
    r"(?:nedtelling|countdown)\b|"
    r"(?:gi|gje|give)\s+(?:(?:meg|mæ|me)\s+)?"
    r"(?:@?[^\s,;.?!]+\s+)?(?:(?:et|eit|a)\s+)?"
    r"(?:kompliment|compliment)\b"
)
_COURTESY_CONDITION = (
    r"(?:(?:hvis|om|når)\s+du\s+har\s+tid|"
    r"(?:hvis|om)\s+du\s+kan|hvis\s+det\s+passer|"
    r"(?:if|when)\s+you\s+have\s+time|if\s+(?:it(?:'s|\s+is)\s+)?"
    r"convenient|if\s+you\s+can|if\s+possible)"
)
_POLITE_REQUEST_HEAD = (
    r"(?:kan\s+du|kunne\s+du|vil\s+du|can\s+you|could\s+you|"
    r"would\s+you|will\s+you|please|vennligst)"
)
_BOUNDED_REQUEST_SHELL = (
    r"(?:(?:"
    rf"{_POLITE_REQUEST_HEAD}(?:(?:\s*,\s*|\s+)"
    rf"{_COURTESY_CONDITION}\s*,?)?\s+|"
    rf"{_COURTESY_CONDITION}(?:(?:\s*,\s*|\s+)"
    rf"{_POLITE_REQUEST_HEAD}\s+|\s*,\s*)"
    r"))?"
)
_TRAILING_REQUEST_COURTESY = re.compile(
    rf"(?:\s*,?\s+{_COURTESY_CONDITION}|"
    r"\s*[,;]?\s+(?:takk(?:\s+skal\s+du\s+ha)?|tusen\s+takk|"
    r"please|thanks|thank\s+you))\s*[?.!]*$",
    re.IGNORECASE,
)
_SEQUENCED_ACTION_REQUEST = re.compile(
    r"(?:"
    r"\b(?:og\s+så|and\s+then|deretter|så|then|after\s+that)\b|"
    r"(?:\r?\n)+|[?!]|&|"
    r"[,;.]\s*(?:(?:og|and)\s+)?"
    r"(?:(?:så|deretter|then|after\s+that)\s+)?|"
    r"\b(?:also|plus|også|pluss|samt)\b|"
    r"\b(?:og|and)\b"
    r")\s*"
    rf"{_BOUNDED_REQUEST_SHELL}"
    rf"(?:{_SEQUENCED_ACTION_HEAD})",
    re.IGNORECASE,
)
_SEQUENCED_TARGET_REQUEST = re.compile(
    r"^(?:(?:(?:kan|kunne|vil|can|could|would|will)\s+"
    r"(?:du|you)\s+)|(?:(?:vennligst|please)\s+))?"
    r"(?:slett|slette|delete|fjern|fjerne|remove|lukk|close|"
    r"avslutt|steng|fullfør|fullføre|complete|ferdig|done)\s+"
    r"(?:(?:poll|avstemning|avstemming|påminnelse|påminning|reminder|"
    r"sitat|quote|film|movie|show|watchlist|møte|avtale|event|"
    r"kalender|calendar)\s+)?"
    r"(?:\d+|siste|last)\s*(?:,|/|\bog\b|\band\b)\s*"
    r"(?:(?:poll|avstemning|avstemming|påminnelse|påminning|reminder|"
    r"sitat|quote|film|movie|show|watchlist|møte|avtale|event|"
    r"kalender|calendar)\s+)?(?:\d+|siste|last)\b",
    re.IGNORECASE,
)
_POLL_TARGET_MUTATION_START = re.compile(
    r"^(?:(?:(?:kan|kunne|vil|can|could|would|will)\s+"
    r"(?:du|you)\s+)|(?:(?:vennligst|please)\s+))?"
    r"(?:slett|slette|delete|fjern|fjerne|remove|lukk|lukke|close|"
    r"avslutt|avslutte|steng|stenge)\s+"
    r"(?:(?:den|det|en|ei|the)\s+)?"
    r"(?:poll(?:en)?|avstemning(?:en|a)?|avstemming(?:en|a)?)\b",
    re.IGNORECASE,
)
_POLL_TARGET_MUTATION_COMPLETE = re.compile(
    r"^(?:(?:(?:kan|kunne|vil|can|could|would|will)\s+"
    r"(?:du|you)\s+)|(?:(?:vennligst|please)\s+))?"
    r"(?:slett|slette|delete|fjern|fjerne|remove|lukk|lukke|close|"
    r"avslutt|avslutte|steng|stenge)\s+"
    r"(?:(?:den|det|en|ei|the)\s+)?"
    r"(?:poll(?:en)?|avstemning(?:en|a)?|avstemming(?:en|a)?)"
    r"(?:\s+(?:(?:nummer|number|nr\.?|no\.?|#)\s*)?"
    r"(?:[1-9]\d*|siste|last))?"
    r"(?:\s+(?:nå|now|med\s+en\s+gang|right\s+now))?"
    r"(?:\s*,?\s*(?:takk|please|thanks))?\s*[?.!]*$",
    re.IGNORECASE,
)
_CONTROL_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_SEQUENCE_CLAUSE_BOUNDARY = re.compile(
    r"\b(?:og\s+så|and\s+then|after\s+that|deretter|then|så|og|and)\b|"
    r"\b(?:also|plus|også|pluss|samt)\b|"
    r"(?:\r?\n)+|&|[?!](?=\s)|(?<!\d)\.(?=\s+[^\W\d_])|;|,(?=\s)",
    re.IGNORECASE,
)
# Discord messages are bounded, but keep route probes bounded independently so
# a conjunction-heavy payload cannot amplify parser work without limit.  The
# lexical guard above still scans the complete utterance; this cap applies only
# to the parser-aware fallback used by IntentRouter.
MAX_SEQUENCE_CLAUSE_PROBES = 24
HYPOTHETICAL_FRAMES = (
    "hva skjer hvis", "kva skjer om", "ka skjer hvis", "what happens if",
    "hvis jeg", "om jeg", "if i ", "hvis du", "om du", "if you ",
)
HYPOTHETICAL_PATTERNS = (
    re.compile(r"\b(?:jeg|eg)\s+vurderer\s+(?:kanskje\s+)?å\b"),
    re.compile(r"\b(?:jeg|eg)\s+tenker\s+på\s+å\b"),
    re.compile(r"\bi\s+am\s+considering\b"),
    re.compile(r"\bmaybe\s+i\s+should\b"),
    # A self-modal possibility is descriptive/hypothetical, unlike the
    # bounded request shell "Could you ...".
    re.compile(r"^(?:i\s+could|(?:jeg|eg|æ)\s+kunne)\b"),
)
_POLITE_CONDITIONAL_DIRECTIVE = re.compile(
    rf"^(?:"
    rf"{_POLITE_REQUEST_HEAD}(?:\s*,\s*|\s+)"
    rf"{_COURTESY_CONDITION}\s*,?\s+.+|"
    rf"{_COURTESY_CONDITION}(?:\s*,\s*|\s+)"
    rf"{_POLITE_REQUEST_HEAD}\s+.+|"
    rf"{_COURTESY_CONDITION}\s*,\s*.+|"
    rf"{_POLITE_REQUEST_HEAD}\s+.+?\s*,?\s+{_COURTESY_CONDITION}|"
    rf".+?\s*,?\s+{_COURTESY_CONDITION}"
    rf")\s*[?.!]*$",
    re.IGNORECASE,
)
META_FRAMES = (
    "jeg skrev", "eg skreiv", "i wrote", "eksempel", "example",
    "hva betyr", "kva tyder", "what does", "hvordan skriver",
)
META_PATTERNS = (
    re.compile(
        r"^(?:(?:jeg|eg|æ)\s+sa|i\s+said|"
        r"(?!(?:hva|kva|ka|what|who|where|when|how)\b)"
        r"[^\W\d_]+\s+(?:sa|said))\b"
    ),
    re.compile(r"^(?:jeg\s+leste|eg\s+las|i\s+read)\b"),
)
POLITE_DIRECTIVES = (
    "kan du", "kunne du", "vil du", "vennligst", "vær så snill",
    "can you", "could you", "would you", "will you", "please",
)
QUESTION_STARTS = (
    "hva ", "kva ", "ka ", "hvordan ", "korleis ", "når ", "where ",
    "when ", "what ", "how ", "why ", "hvor ", "kor ",
)
INFORMATION_MUTATION_PATTERNS = (
    re.compile(r"^(?:hvorfor|kvifor|why)\b"),
    re.compile(
        r"^(?:kan\s+man|er\s+det\s+mulig\s+å|can\s+one|"
        r"is\s+it\s+possible\s+to)\b"
    ),
    re.compile(
        r"^(?:(?:kan|kunne|vil)\s+du\s+)?"
        r"(?:forklare|vise|fortelle|fortelje|si|seie|"
        r"lære)(?:\s+(?:meg|mæ))?\b.*"
        r"\b(?:hvordan|korleis)\b"
    ),
    re.compile(
        r"^(?:(?:can|could|would|will)\s+you\s+)?"
        r"(?:explain|show|tell|teach)(?:\s+me)?\b.*\bhow\b"
    ),
    re.compile(
        r"^(?:should\s+i|do\s+you\s+think\s+i\s+should|"
        r"would\s+it\s+be\s+(?:a\s+)?good\s+idea\s+to|"
        r"(?:bør|skal)\s+(?:jeg|eg|æ)|"
        r"tror\s+du\s+(?:jeg|eg|æ)\s+bør)\b"
    ),
)
PERMISSION_QUESTION_PATTERN = re.compile(
    r"^(?:kan\s+(?:jeg|eg|æ)|can\s+i|may\s+i|could\s+i)\b"
)
_PROFILE_ACTIVITY_VALUE = re.compile(
    r"^(?:playing|watching|spiller|ser\s+på)\s+(?P<value>.+?)\s*[.!?]*$",
    re.IGNORECASE,
)
_LOCATION_FRAGMENT = re.compile(
    r"^(?:(?:jeg|eg|æ)\s+(?:bor|bur)\s+i|i\s+live\s+in)\s+"
    r"(?P<value>.+?)\s*[.!?]*$",
    re.IGNORECASE,
)
_TITLE_VALUE_CONNECTORS = frozenset({
    "a", "an", "and", "are", "at", "av", "er", "for", "i", "in", "is",
    "of", "og", "on", "the", "to", "was", "were",
})
_CALENDAR_DATE_FRAGMENT = (
    r"(?:i\s+(?:morgen|morgon|morra|dag|kveld|overmorgen|overmorgon)|"
    r"idag|imorgen|imorra|imårra|overmorgen|overmorgon|"
    r"tomorrow|today|tonight|day\s+after\s+tomorrow|"
    r"(?:hver|kvar|every)\s+(?:mandag|tirsdag|onsdag|torsdag|fredag|"
    r"lørdag|laurdag|søndag|monday|tuesday|wednesday|thursday|"
    r"friday|saturday|sunday)|"
    r"(?:neste|next)\s+(?:mandag|tirsdag|onsdag|torsdag|fredag|"
    r"lørdag|laurdag|søndag|monday|tuesday|wednesday|thursday|"
    r"friday|saturday|sunday)|"
    r"mandag|tirsdag|onsdag|torsdag|fredag|lørdag|laurdag|søndag|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?|"
    r"\d{1,2}\.?\s+(?:januar|februar|mars|april|mai|juni|juli|"
    r"august|september|oktober|november|desember|january|february|"
    r"march|may|june|july|august|september|october|november|"
    r"december)(?:\s+\d{4})?)"
)
_CALENDAR_TIME_FRAGMENT = (
    r"(?:kl(?:okka)?\.?\s*)?"
    r"(?:\d{1,2}(?:[:.]\d{2})?|halv\s+(?:\d{1,2}|[^\W\d_]+)|"
    r"kvart\s+(?:over|på)\s+(?:\d{1,2}|[^\W\d_]+))"
    r"(?:\s+på\s+(?:morgenen|formiddagen|ettermiddagen|kvelden|"
    r"natta|natten))?|"
    r"at\s+(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)?|noon|midnight)|"
    r"morgen|tidlig|morning|afternoon|evening|noon|midnight"
)
_CALENDAR_FRAGMENT = re.compile(
    rf"^(?:møte|meeting|avtale|appointment|arrangement|event)"
    rf"(?:\s+(?!{_CALENDAR_DATE_FRAGMENT}(?:\s|$))"
    rf"(?:(?:med|with)\s+)?(?P<with_value>.+?))?\s+"
    rf"(?P<date>{_CALENDAR_DATE_FRAGMENT})"
    rf"(?:\s+(?P<time>{_CALENDAR_TIME_FRAGMENT}))?\s*[.!?]*$",
    re.IGNORECASE,
)
_REMINDER_FRAGMENT = re.compile(
    r"^(?:påminnelse|påminning|reminder)\s+"
    r"(?P<value>[^,;!?]{1,200}?)\s+"
    r"(?:i\s+(?:morgen|morgon|dag|kveld)|tomorrow|today|tonight|"
    r"om\s+[1-9]\d*\s+(?:minutt(?:er)?|time(?:r)?|dag(?:er)?|uke(?:r)?)|"
    r"in\s+[1-9]\d*\s+(?:minutes?|hours?|days?|weeks?)|"
    r"\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)"
    r"(?:\s+(?:kl(?:okka)?\.?\s*\d{1,2}(?:[:.]\d{2})?|"
    r"at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?|"
    r"morgen|tidlig|morning|afternoon|evening))?\s*[.!?]*$",
    re.IGNORECASE,
)
_POLL_CREATE_FRAGMENT = re.compile(
    r"^(?:avstemning|avstemming|poll)\s+[^/|\r\n]{1,160}\?"
    r"(?:\s*[/|]\s*[^/|\r\n]{1,80}){2,8}\s*[.!]*$",
    re.IGNORECASE,
)
_BIRTHDAY_FRAGMENT = re.compile(
    r"^(?:bursdagen\s+min\s+er|fødselsdagen\s+min\s+er|"
    r"(?:jeg|eg|æ)\s+har\s+bursdag|bursdag|my\s+birthday\s+is)\s+(?:"
    r"\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?|"
    r"\d{1,2}\.?\s+(?:januar|februar|mars|april|mai|juni|juli|"
    r"august|september|oktober|november|desember)"
    r"(?:\s+\d{4})?|"
    r"(?:january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\s+\d{1,2}"
    r"(?:,?\s+\d{4})?"
    r")\s*[.!?]*$",
    re.IGNORECASE,
)
_PROFILE_STATUS_FRAGMENT = re.compile(
    r"^status\s+(?:online|offline|idle|dnd|invisible)\s*[.!?]*$",
    re.IGNORECASE,
)
_CALENDAR_AUTH_FRAGMENT = re.compile(
    r"^(?:kalender|calendar|gcal)\s+(?:auth|login)\s*[.!?]*$",
    re.IGNORECASE,
)
_CONTEXTUAL_POLL_VOTE_FRAGMENT = re.compile(r"^[1-9]\d*\s*[.!?]*$")
_BOUNDED_NATURAL_DIRECTIVE = re.compile(
    r"^(?:"
    r"(?:i['’]d|i\s+would)\s+like\s+(?:a\s+)?reminder"
    r"(?:\s+for\s+me)?\s+to\b|"
    r"put(?!\s+(?:differently|another\s+way)\b)\s+"
    r"[^\r\n]{1,160}\s+(?:on|in)\s+(?:my|the)\s+calendar\b|"
    r"(?:make|set|put|create|add)\s+(?:a\s+)?reminder"
    r"(?:\s+for\s+me)?\s+(?:to|about)\b"
    r")",
    re.IGNORECASE,
)
_FUTURE_WEATHER_TOPIC = re.compile(
    r"\b(?:weather|forecast|rain(?:y|ing)?|umbrella|"
    r"vær(?:et)?|vêret|værmelding|regn(?:e|a|er|ar)?|paraply)\b",
    re.IGNORECASE,
)
_FUTURE_WEATHER_TIME = re.compile(
    r"\b(?:tomorrow|day\s+after\s+tomorrow|tonight|later(?:\s+today)?|"
    r"this\s+(?:morning|afternoon|evening|week|weekend|month|year)|"
    r"(?:next|coming|upcoming)\s+(?:hour|day|week|weekend|month|year|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"(?:over|during)\s+the\s+weekend|"
    r"(?:in|within)\s+(?:(?:an?|one|two|three|four|five|six|seven|"
    r"eight|nine|ten|\d+)\s+)?(?:minute|minutes|hour|hours|day|days|"
    r"week|weeks|month|months|year|years)|"
    r"at\s+(?:noon|midnight|\d{1,2}(?::\d{2})?\s*(?:am|pm))|"
    r"(?:on\s+)?(?:monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday)|"
    r"(?:january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\s+\d{1,2}(?:st|nd|rd|th)?"
    r"(?:,?\s+\d{4})?|"
    r"\d{1,2}(?:st|nd|rd|th)?\s+(?:january|february|march|april|"
    r"may|june|july|august|september|october|november|december)"
    r"(?:\s+\d{4})?|"
    r"\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?|"
    r"i\s+morgen|i\s+morgon|imorgen|imorgon|i\s+overmorgen|"
    r"i\s+overmorgon|overmorgen|overmorgon|i\s+kveld|i\s+natt|"
    r"i\s+ettermiddag|(?:senere|seinare)(?:\s+i\s+dag)?|"
    r"(?:denne|den\s+kommende|den\s+komande)\s+"
    r"(?:uka|uken|veka|helga|helgen|måneden|månaden|året)|"
    r"(?:i|til)\s+helg(?:a|en)?|"
    r"om\s+(?:en|ei|ett|ein|to|tre|fire|fem|seks|sju|\d+)\s+"
    r"(?:minutt(?:er)?|time|timer|timar|dag|dager|dagar|uke|uker|"
    r"veke|veker|måned|måneder|månad|månadar|år)|"
    r"(?:kl(?:okka|okken)?\.?)\s*\d{1,2}(?::\d{2})?|"
    r"(?:neste|kommende|komande)\s+(?:time|dag|uke|veke|helg|"
    r"måned|månad|år|"
    r"mandag|måndag|tirsdag|onsdag|torsdag|fredag|lørdag|laurdag|"
    r"søndag|sundag)|"
    r"(?:på\s+)?(?:mandag|måndag|tirsdag|onsdag|torsdag|fredag|"
    r"lørdag|laurdag|søndag|sundag)|"
    r"\d{1,2}\.?\s+(?:januar|februar|mars|april|mai|juni|juli|august|"
    r"september|oktober|november|desember)(?:\s+\d{4})?)\b",
    re.IGNORECASE,
)
_FUTURE_WEATHER_REQUEST_HEAD = re.compile(
    r"^(?:"
    r"what(?:\s+is|['’]s)\s+(?:the\s+)?(?:weather|forecast)\b|"
    r"what\s+will\s+(?:the\s+)?weather\s+be(?:\s+like)?\b|"
    r"how\s+will\s+(?:the\s+)?weather\s+be\b|"
    r"(?:will\s+it|is\s+it\s+going\s+to)\s+"
    r"(?:rain|be\s+rainy)\b|"
    r"do\s+i\s+need\s+(?:an?\s+)?umbrella\b|"
    r"(?:show|tell\s+me|check)\s+(?:the\s+)?"
    r"(?:weather|forecast)\b|"
    r"(?:blir\s+det\s+regn|(?:kommer|kjem)\s+det\s+til\s+å\s+"
    r"regn(?:e|a))\b|"
    r"(?:trenger|treng)\s+(?:jeg|eg|æ)\s+"
    r"(?:(?:en|ei|ein)\s+)?paraply\b|"
    r"(?:hvordan|korleis)\s+blir\s+(?:været|vêret)\b|"
    r"(?:hva|kva|ka)\s+blir\s+(?:været|vêret)\b|"
    r"(?:vis|sjekk)\s+(?:været|vêret|værmeldinga|værmeldingen)\b|"
    r"(?:weather|forecast|vær(?:et)?|vêret|værmelding)\b"
    r")",
    re.IGNORECASE,
)
_ENGLISH_CREATE_COURTESY = (
    r"(?:(?:(?:can|could|would|will)\s+you|please)\s+)?"
)
_CALENDAR_EVENT_SUFFIX = (
    r"(?=\s*(?:$|[?!.]|(?:with|for|about|called|named|titled|at|on|in|"
    r"today|tomorrow|tonight|next|this)\b|\d{1,2}[./-]))"
)
_BOUNDED_ENGLISH_CALENDAR_CREATE = re.compile(
    rf"^(?:(?:i['’]d|i\s+would)\s+like\s+to\s+"
    r"(?P<would_add>add)\s+[^\r\n]{1,160}\s+to\s+"
    r"(?:my|the)\s+calendar\b|"
    rf"{_ENGLISH_CREATE_COURTESY}(?:"
    r"(?P<put>put)(?!\s+(?:differently|another\s+way)\b)\s+"
    r"[^\r\n]{1,160}\s+(?:on|in)\s+(?:my|the)\s+calendar\b|"
    r"(?P<add>add)\s+[^\r\n]{1,160}\s+to\s+(?:my|the)\s+calendar\b|"
    r"(?P<book>book)(?:\s+me)?\s+(?:a|an)?\s*"
    r"[^\r\n?!.]{0,100}\b(?:appointment|meeting|event)\b"
    rf"{_CALENDAR_EVENT_SUFFIX}|"
    r"(?P<book_plain>book)(?:\s+me)?\s+"
    r"(?=[^\r\n?!.]{1,100}\b(?:today|tomorrow|tonight|monday|"
    r"tuesday|wednesday|thursday|friday|saturday|sunday|next)\b)"
    r"[^\r\n?!.]{1,100}|"
    r"(?P<make>make)\s+(?:a|an)\s+[^\r\n?!.]{0,80}?"
    r"appointment\b"
    rf"{_CALENDAR_EVENT_SUFFIX}|"
    r"(?P<create>create)\s+(?:(?:a|an)\s+)?"
    r"[^\r\n?!.]{0,80}?\b(?:appointment|meeting|event)\b"
    rf"{_CALENDAR_EVENT_SUFFIX}|"
    r"(?P<direct_add>add)\s+(?:(?:a|an)\s+)?"
    r"[^\r\n?!.]{0,80}?\b(?:appointment|meeting|event)\b"
    rf"{_CALENDAR_EVENT_SUFFIX}|"
    r"(?P<setup>set\s+up)\s+(?:(?:a|an)\s+)?"
    r"[^\r\n?!.]{0,80}?\b(?:appointment|meeting|event)\b"
    rf"{_CALENDAR_EVENT_SUFFIX}|"
    r"(?P<setup_plain>set\s+up)\s+"
    r"(?=[^\r\n?!.]{1,100}\b(?:today|tomorrow|tonight|monday|"
    r"tuesday|wednesday|thursday|friday|saturday|sunday|next)\b)"
    r"[^\r\n?!.]{1,100}|"
    r"(?P<schedule>schedule)\s+"
    r"(?!is\b|are\b|for\b|today\b|tomorrow\b|tonight\b)\S+"
    r"))",
    re.IGNORECASE,
)
_BOUNDED_ENGLISH_REMINDER_CREATE = re.compile(
    rf"^(?:{_ENGLISH_CREATE_COURTESY}"
    r"(?P<verb>create|add|make|set|put|set\s+up)\s+"
    r"(?:a\s+)?reminder(?:\s+for\s+me)?\s+(?:to|about)|"
    r"(?P<want>(?:i\s+want|i\s+need))\s+(?:a\s+)?reminder"
    r"(?:\s+for\s+me)?\s+(?:to|about)|"
    r"(?P<get>(?:can|could)\s+i\s+get)\s+(?:a\s+)?reminder"
    r"(?:\s+for\s+me)?\s+(?:to|about)|"
    r"(?P<give>give\s+me)\s+(?:a\s+)?reminder"
    r"(?:\s+for\s+me)?\s+(?:to|about))\b",
    re.IGNORECASE,
)
_INDEPENDENT_CONVERSATIONAL_REQUEST_HEAD = re.compile(
    r"^(?:(?:can|could|would|will)\s+you|"
    r"(?:kan|kunne|vil)\s+du|please|vennligst|"
    r"tell\s+me|fortell(?:e|je)?\s+(?:meg|mæ)|"
    r"give\s+me|gi\s+(?:meg|mæ)|gje\s+(?:meg|mæ)|"
    r"teach\s+me|lær\s+(?:meg|mæ)|"
    r"explain\b|forklar\b|make\s+me\b|write(?:\s+me)?\b)",
    re.IGNORECASE,
)
ACTION_TERMS = frozenset({
    "slett", "slette", "sletter", "slettar", "delete", "deleting",
    "fjern", "fjerne", "remove", "tøm", "tømme", "clear", "endre", "edit",
    "change", "rediger", "redigere", "flytt", "flytte", "move", "opprett",
    "opprette", "create", "lag", "lage", "add", "legg", "legge", "make",
    "book", "booke", "schedule", "save", "lagre", "registrer",
    "put",
    "planlegg", "planlegge", "planleggje",
    "husk", "huske", "hugs", "hugse", "glem", "glemme", "gløym",
    "gløyme", "forget", "remember", "påminn", "påminne", "minn", "minne",
    "remind", "stem", "stemmer",
    "røyst", "røystar", "vote",
    "lukk", "lukke", "close", "avslutt", "avslutte", "steng", "stenge",
    "fullfør", "fullføre", "ferdig", "finish", "done", "complete", "synk",
    "synkroniser", "synkronisere", "sync", "forkort",
    "forkorte", "shorten", "søk", "søke", "søkje", "search", "look up",
    "regn", "regne", "rekn", "rekne", "kalk", "kalkuler",
    "calculate", "calc", "compute", "work out",
    "vis", "vise", "show", "fortell", "fortelje", "tell",
    "gi", "gje", "give",
    "lær", "lære", "teach",
    "eksporter", "eksportere", "export",
    "pris", "price", "verdi", "value", "kurs", "roast",
    "kompliment", "compliment", "horoskop", "horoscope",
    "konverter", "konvertere", "convert", "omgjør", "gjør om", "gjer om",
    "countdown", "count down", "nedtelling", "nedteljing", "sett", "sette",
    "set", "oppdater", "oppdatere", "update", "marker", "markere", "mark",
    "jeg må", "eg må", "i need", "i need to", "jeg trenger", "jeg treng",
    "eg trenger", "eg treng", "sørg for at", "syt for at", "pass på at",
    "ensure that",
    "jeg vil gjerne ha", "eg vil gjerne ha", "jeg går for", "eg går for",
})


def has_future_weather_request(utterance: NormalizedUtterance) -> bool:
    """Return whether a weather-shaped request asks beyond current conditions."""

    control = utterance.control_text.strip()
    return bool(
        _FUTURE_WEATHER_TOPIC.search(control)
        and _FUTURE_WEATHER_TIME.search(control)
    )


def has_bounded_future_weather_request(
    utterance: NormalizedUtterance,
) -> bool:
    """Recognize a direct dated forecast request, excluding topic discussion."""

    return bool(
        has_future_weather_request(utterance)
        and _FUTURE_WEATHER_REQUEST_HEAD.match(
            utterance.control_text.strip()
        )
    )


def bounded_english_calendar_create_head(
    utterance: NormalizedUtterance,
) -> str | None:
    """Return the directive-position English calendar verb, if bounded."""

    match = _BOUNDED_ENGLISH_CALENDAR_CREATE.match(
        utterance.control_text.strip()
    )
    if match is None:
        return None
    matched_name, value = next(
        (
            (name, candidate)
            for name, candidate in match.groupdict().items()
            if isinstance(candidate, str) and candidate
        )
    )
    if (
        matched_name in {"book_plain", "setup_plain", "schedule"}
        and re.search(
            r"\b(?:is|are|was|were|looks?|sounds?|seems?)\b",
            utterance.control_text,
            re.IGNORECASE,
        )
    ):
        return None
    return value.casefold()


def bounded_english_reminder_create_head(
    utterance: NormalizedUtterance,
) -> str | None:
    """Return a noun-create reminder verb only with a content connector."""

    match = _BOUNDED_ENGLISH_REMINDER_CREATE.match(
        utterance.control_text.strip()
    )
    if match is None:
        return None
    return next(
        value.casefold()
        for value in match.groupdict().values()
        if isinstance(value, str) and value
    )


def is_independent_conversational_request(
    utterance: NormalizedUtterance,
) -> bool:
    """Recognize a bounded model-only request after a clause boundary."""

    semantics = analyze_utterance(utterance)
    control = utterance.control_text.strip()
    if semantics.speech_act is SpeechAct.INFORMATION_REQUEST:
        return bool(
            control.endswith("?")
            or control.startswith(QUESTION_STARTS)
            or re.match(
                r"^(?:do|does|did|is|are|was|were|can|could|should|"
                r"would|will|may)\b",
                control,
                re.IGNORECASE,
            )
        )
    return bool(
        semantics.speech_act is SpeechAct.DIRECTIVE
        and semantics.allows_mutation
        and _INDEPENDENT_CONVERSATIONAL_REQUEST_HEAD.match(control)
    )


COURTESY_REQUEST_TERMS = ACTION_TERMS.union(
    {
        "hvor lenge",
        "kor lenge",
        "hvor mange dager",
        "kor mange dagar",
        "når er",
        "how long",
        "how many days",
        "when is",
        "when's",
        "when’s",
        "days to",
        "days until",
        "how much",
    }
)
NEGATIONS = frozenset({
    "ikke", "ikkje", "aldri", "not", "never", "don't", "don’t",
    "can't", "can’t", "cannot", "won't", "won’t",
    "shouldn't", "shouldn’t",
})
POSITIVE_FORGET = (
    "ikke glem",
    "ikke la meg glemme",
    "ikkje gløym",
    "ikkje lat meg gløyme",
    "don't forget",
    "don’t forget",
    "don't let me forget",
    "don’t let me forget",
)
_TRAILING_CANCELLATION_FORMS = (
    "ikke gjør det", "ikke gjør dette", "ikke gjør det likevel",
    "gjør det ikke", "ikkje gjer det", "ikkje gjer dette",
    "ikkje gjer det likevel", "gjer det ikkje", "la være",
    "la det være", "lat vere", "lat det vere", "dropp det",
    "do not do it", "don't do it", "don’t do it",
    "do not do that", "don't do that", "don’t do that",
    "do not proceed", "don't proceed", "don’t proceed",
    "do not do it after all", "don't do it after all",
    "don’t do it after all", "never mind",
    "avbryt", "avbryt det", "avbryt likevel", "stopp", "stopp litt", "stopp det",
    "stopp likevel", "cancel", "cancel it", "cancel that", "stop",
    "stop it", "stop that", "wait", "wait a moment", "wait please",
    "vent", "vent litt", "vent nå", "vent no",
    "la være da", "la det være da", "lat vere då", "lat det vere då",
    "jeg ombestemte meg", "eg ombestemte meg", "i changed my mind",
    "jeg ombestemte meg om det", "eg ombestemte meg om det",
    "ombestemte meg om det", "i changed my mind about that",
    "changed my mind about that", "i no longer want that",
    "forget it", "forget it then", "forget about it", "scratch that",
    "scratch that please", "scratch it", "leave it", "no actually",
    "cancel that please", "cancel it after all", "dropp den", "avlys det",
    "glem det da", "gløym det då",
    "ved nærmere ettertanke ikke", "ved nærare ettertanke ikkje",
    "ved nærmare ettertanke ikkje",
    "on second thought do not", "on second thought don't",
    "on second thought don’t", "on second thoughts do not",
    "on second thoughts don't", "on second thoughts don’t",
    "nei takk", "no thanks",
)
TRAILING_CANCELLATIONS = tuple(
    sorted(set(_TRAILING_CANCELLATION_FORMS).union(REJECTIONS))
)
TRAILING_CANCELLATION_MARKERS = frozenset({
    "men", "but", "however", "likevel", "derimot", "nei", "no",
    "vent", "wait", "egentlig", "actually",
    "beklager", "sorry",
})
TRAILING_CANCELLATION_LOOKBACK = 12
# Some rejections are unambiguous standalone imperatives after a completed
# value.  Bare ``nei/no`` and ``ikke gjør det`` remain boundary-dependent:
# they are also common poll options or subordinate payload text.
BARE_TRAILING_CANCELLATIONS = frozenset({
    "avbryt", "cancel", "stopp", "stop", "dropp det",
    "nei takk", "no thanks", "ikke likevel", "ikkje likevel",
    "glem det", "gløym det", "la oss droppe det",
    "lat oss droppe det", "never mind", "nope",
    "jeg ombestemte meg", "eg ombestemte meg", "i changed my mind",
    "jeg ombestemte meg om det", "eg ombestemte meg om det",
    "ombestemte meg om det", "i changed my mind about that",
    "changed my mind about that", "i no longer want that",
    "forget about it", "forget it then", "scratch it", "scratch that please",
    "leave it", "no actually", "cancel that please", "cancel it after all",
    "dropp den", "avlys det", "glem det da", "gløym det då",
})
_NATURAL_BARE_RETRACTIONS = frozenset({
    "jeg ombestemte meg", "eg ombestemte meg", "i changed my mind",
    "jeg ombestemte meg om det", "eg ombestemte meg om det",
    "ombestemte meg om det", "i changed my mind about that",
    "changed my mind about that", "i no longer want that",
    "forget about it", "forget it then", "scratch it", "scratch that please",
    "leave it", "no actually", "cancel that please", "cancel it after all",
    "dropp den", "avlys det", "glem det da", "gløym det då",
})
_BARE_RETRACTION_VALUE_INTRODUCERS = frozenset({
    "as", "called", "kalt", "named", "som", "til", "title", "titled",
    "tittel", "to",
})
_BARE_RETRACTION_COMPLETE_PREFIXES = (
    # A concrete temporal anchor completes a terse reminder/calendar frame.
    re.compile(
        r"\b(?:i\s+(?:morgen|morgon|dag)|tomorrow|today|tonight|"
        r"neste|next|kl(?:okka)?|at\s+\d{1,2}|"
        r"(?:mandag|tirsdag|onsdag|torsdag|fredag|lørdag|søndag|"
        r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
        r"\d{1,2}(?::\d{2}|[./]\d{1,2}(?:[./]\d{2,4})?))\b"
    ),
    # Self-describing profile/location frames need one value before control.
    re.compile(r"^(?:spiller|playing|watching)\s+\S+(?:\s+\S+)*$"),
    re.compile(r"^(?:ser\s+på)\s+\S+(?:\s+\S+)*$"),
    re.compile(
        r"^(?:(?:jeg|eg|æ)\s+(?:bor|bur)\s+i|i\s+live\s+in)\s+"
        r"\S+(?:\s+\S+)*$"
    ),
    # A closed target selector or a watchlist domain after its title is also
    # a complete value.  Free-form quote/poll titles intentionally require a
    # comma, conjunction, or quotation before a retraction.
    re.compile(
        r"\b(?:poll|avstemning|avstemming|reminder|påminnelse|"
        r"påminning|quote|sitat|meeting|møte|event|avtale)\s+"
        r"(?:\d+|last|siste)\b"
    ),
    re.compile(r"\b(?:to|på)\s+(?:my\s+|min\s+|mi\s+)?watchlist"),
)
_BARE_CANCELLATION_COMPLETE_FRAMES = frozenset({
    ("kalender", "auth"),
    ("kalender", "login"),
    ("kalender", "kode"),
    ("gcal", "auth"),
    ("gcal", "login"),
    ("gcal", "kode"),
    ("kalenderkode",),
})
_BARE_CANCELLATION_PAYLOAD_SHELLS = (
    re.compile(
        r"^(?:husk|hugs)\s+(?:å|at)\s+(?:si|se|sjå)"
        r"(?:\s+.+)?$"
    ),
    re.compile(r"^remember\s+to\s+(?:say|watch)(?:\s+.+)?$"),
    re.compile(
        r"^(?:påminn(?:e)?\s+meg(?:\s+(?:om|på))?|"
        r"minn(?:e)?\s+(?:meg|mæ)(?:\s+(?:om|på))?|"
        r"remind\s+me(?:\s+(?:to|that))?)\s+"
        r"(?:å\s+|to\s+)?(?:si|se|sjå|say|watch)(?:\s+.+)?$"
    ),
    re.compile(
        r"^(?:spiller|playing|ser\s+på|watching)(?:\s+.+)?$"
    ),
    re.compile(
        r"^(?:legg(?:\s+til)?|add)\s+"
        r"(?:filmen|film|serien|serie|movie|show|series)"
        r"(?:\s+.+)?$"
    ),
    re.compile(
        r"^(?:endre|rediger|edit|change)\s+(?:tittel|title)\s+"
        r"(?:til|to)(?:\s+.+)?$"
    ),
    re.compile(
        r"^(?:lag|opprett|create|add|planlegg|schedule)\s+"
        r"(?:(?:et|en|ei|a|an|the)\s+)?"
        r"(?:møte|avtale|event|meeting|appointment|poll|avstemning)"
        r"(?:\s+.+)?$"
    ),
    re.compile(r"^(?:poll|avstemning)(?:\s+.+)?$"),
    re.compile(r"^(?:lagre|save)\s+(?:sitat|quote)(?:\s+.+)?$"),
    re.compile(
        r"^(?:husk\s+dette|lagre\s+dette|remember\s+this|"
        r"save\s+this|quote\s+this)(?:\s+.+)?$"
    ),
)
_NEGATION_PAYLOAD_PREFIX = re.compile(
    rf"^{_BOUNDED_REQUEST_SHELL}(?:"
    r"(?:husk\s+å\s+se|hugs\s+å\s+sjå|"
    r"remember\s+to\s+watch)\s+|"
    r"(?:forkort|forkorte|kort\s+ned|korte\s+ned|shorten)\s+"
    r"(?:denne\s+|this\s+)?|"
    r"(?:søk|søke|søkje|search|look\s+up)\s+"
    r"(?:(?:etter|for|på\s+nett(?:et)?|(?:on\s+)?the\s+web)\s+)?)",
    re.IGNORECASE,
)


def strip_bounded_request_courtesy(text: str) -> str:
    """Strip only the shared, finite courtesy shell around one request.

    The leading grammar deliberately requires either a polite request head or
    a comma-delimited known courtesy adjunct.  Consequently a true open-ended
    conditional such as ``if you see aurora, tell me`` is left untouched.
    Trailing courtesy is removed only when a substantive request precedes it.
    """

    cleaned = text.strip()
    leading = re.match(_BOUNDED_REQUEST_SHELL, cleaned, re.IGNORECASE)
    if leading is not None and leading.end() > 0:
        cleaned = cleaned[leading.end() :].lstrip()
    trailing = _TRAILING_REQUEST_COURTESY.search(cleaned)
    if trailing is not None and cleaned[: trailing.start()].strip(" ,;?.!"):
        cleaned = cleaned[: trailing.start()]
    return cleaned.strip().rstrip("?!.,")


def _contains_phrase(text: str, phrases: Iterable[str]) -> bool:
    tokens = tuple(re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)?", text.casefold()))
    return any(
        needle and any(True for _ in _token_starts(tokens, needle))
        for needle in (_term_tokens(phrase) for phrase in phrases)
    )


def _is_bounded_title_value(value: str) -> bool:
    """Accept one plain value or a finite title-cased multi-word value."""

    cleaned = value.strip().strip(".!?")
    if len(cleaned) < 1 or len(cleaned) > 100:
        return False
    if (
        len(cleaned) >= 2
        and cleaned[0] in {'"', "'", "“", "‘", "«"}
        and cleaned[-1] in {'"', "'", "”", "’", "»"}
    ):
        return bool(cleaned[1:-1].strip())
    words = re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)?|\d+", cleaned)
    if len(words) == 1:
        return True
    meaningful = [
        word
        for word in words
        if not word.isdigit()
        and word.casefold() not in _TITLE_VALUE_CONNECTORS
    ]
    return bool(meaningful) and all(
        word[0].isupper() or word.isupper() for word in meaningful
    )


def is_trusted_mutation_fragment(utterance: NormalizedUtterance) -> bool:
    """Recognize only complete legacy shorthand that intentionally writes.

    Ordinary statements fail closed.  This finite grammar is the sole opt-in
    for supported write-shaped fragments which do not carry a live directive
    verb.  Keeping it beside speech-act analysis gives deterministic routing
    and the model bridge the same boundary.
    """

    control = utterance.control_text.strip()
    raw = utterance.text.strip()
    calendar = _CALENDAR_FRAGMENT.fullmatch(raw)
    if calendar is not None:
        participant = calendar["with_value"]
        return participant is None or _is_bounded_title_value(participant)
    activity = _PROFILE_ACTIVITY_VALUE.fullmatch(raw)
    if activity is not None:
        return _is_bounded_title_value(activity["value"])
    location = _LOCATION_FRAGMENT.fullmatch(raw)
    if location is not None:
        return _is_bounded_title_value(location["value"])
    return bool(
        _BIRTHDAY_FRAGMENT.fullmatch(control)
        or _REMINDER_FRAGMENT.fullmatch(control)
        or _POLL_CREATE_FRAGMENT.fullmatch(control)
        or _PROFILE_STATUS_FRAGMENT.fullmatch(control)
        or _CALENDAR_AUTH_FRAGMENT.fullmatch(control)
        or _CONTEXTUAL_POLL_VOTE_FRAGMENT.fullmatch(control)
    )


def has_sequenced_action_request(utterance: NormalizedUtterance) -> bool:
    """Return true when a later clause starts another executable action.

    A non-empty clause must precede the sequencer, so leading discourse such
    as ``then delete poll 1`` remains one request.  Ordinary payload
    conjunctions (``milk and bread``) do not match because the later clause
    must start with an action verb.
    """

    control = utterance.control_text.strip()
    # A bounded courtesy condition is an adjunct to one request, not a first
    # action.  Remove only the exact supported shell, then run the ordinary
    # multi-action detector over the remaining directive so a real second
    # action inside the request is still rejected.
    control = re.sub(
        rf"^{_COURTESY_CONDITION}(?:\s*,\s*|"
        rf"\s+(?={_POLITE_REQUEST_HEAD}\b))",
        "",
        control,
        count=1,
        flags=re.IGNORECASE,
    )
    control = re.sub(
        rf"^({_POLITE_REQUEST_HEAD})(?:\s*,\s*|\s+)"
        rf"{_COURTESY_CONDITION}\s*,?\s+",
        r"\1 ",
        control,
        count=1,
        flags=re.IGNORECASE,
    )
    control = re.sub(
        rf"\s*,?\s+{_COURTESY_CONDITION}\s*[?.!]*$",
        "",
        control,
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    control = strip_bounded_request_courtesy(control)
    control_chars = list(control)
    control = "".join(control_chars)
    for match in _CONTROL_URL.finditer(control):
        raw = match.group(0)
        core_length = len(raw)
        while core_length and raw[core_length - 1] in ".,;:!":
            core_length -= 1
        for closing, opening in ((")", "("), ("]", "["), ("}", "{")):
            while (
                core_length
                and raw[core_length - 1] == closing
                and raw[:core_length].count(closing)
                > raw[:core_length].count(opening)
            ):
                core_length -= 1
        for index in range(match.start(), match.start() + core_length):
            if not control_chars[index].isspace():
                control_chars[index] = " "
    control = "".join(control_chars)
    lexical_sequence = _SEQUENCED_TARGET_REQUEST.search(control) is not None or any(
        re.search(r"[^\W_]", control[:match.start()], re.UNICODE) is not None
        for match in _SEQUENCED_ACTION_REQUEST.finditer(control)
    )
    if lexical_sequence:
        return True
    clause_pairs = sequenced_clause_candidates(normalize_utterance(control))
    if any(looks_like_list_read_request(right) for _, right in clause_pairs):
        return True

    # A model-backed conversational request is still a second user-visible
    # action even when it has no dedicated deterministic intent.  Require the
    # left clause to begin with one of the finite executable heads before
    # applying this broader speech-act check, so ordinary multi-sentence chat
    # is not turned into a command conflict.  This closes the partial-write
    # hole where e.g. ``create ... tomorrow. tell me a joke`` was absorbed into
    # the first mutation's title.
    for left, right in clause_pairs:
        left_control = normalize_utterance(left).control_text.strip()
        if re.match(
            rf"^{_BOUNDED_REQUEST_SHELL}(?:{_SEQUENCED_ACTION_HEAD})",
            left_control,
            re.IGNORECASE,
        ) is None:
            continue
        if is_independent_conversational_request(
            normalize_utterance(right)
        ):
            return True
    return False


def sequenced_clause_candidates(
    utterance: NormalizedUtterance,
) -> tuple[tuple[str, str], ...]:
    """Return bounded, inert candidate clause pairs for route-only probing.

    This is deliberately not an action classifier.  It only identifies likely
    clause boundaries outside quoted/code spans (already masked in
    ``control_text``) and URLs (masked here without changing offsets).  The
    router must independently classify both sides before treating a pair as
    multiple executable actions.  Keeping splitting and URL treatment shared
    with the lexical guard prevents deterministic and semantic dispatch from
    developing different payload-conjunction rules.
    """

    control = utterance.control_text.strip()
    if not control:
        return ()
    masked_chars = list(control)
    for match in _CONTROL_URL.finditer(control):
        for index in range(match.start(), match.end()):
            if not masked_chars[index].isspace():
                masked_chars[index] = " "
    masked = "".join(masked_chars)

    candidates: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in _SEQUENCE_CLAUSE_BOUNDARY.finditer(masked):
        left = control[: match.start()].strip(" \t\r\n,;.")
        right = control[match.end() :].strip(" \t\r\n,;.")
        if not left or not right:
            continue
        pair = (left, right)
        if pair in seen:
            continue
        seen.add(pair)
        candidates.append(pair)
        # One extra pair is an overflow sentinel for IntentRouter.  It never
        # triggers another parser call; a leading write with more boundaries
        # than the bounded budget fails closed instead.
        if len(candidates) > MAX_SEQUENCE_CLAUSE_PROBES:
            break
    return tuple(candidates)


def has_unsupported_poll_mutation_request(
    utterance: NormalizedUtterance,
) -> bool:
    """Reject poll delete/close frames whose suffix cannot be executed.

    Targetless mutation is supported only when runtime state resolves one
    active poll.  Extra delay, condition, uncertainty, quoted/code payload or
    additional target text must not be silently discarded and executed now.
    """

    control = utterance.control_text.strip()
    if _POLL_TARGET_MUTATION_START.match(control) is None:
        return False
    # Retractions and negated/hypothetical frames already have a stronger
    # fail-closed classification; do not replace it with a syntax prompt.
    if not analyze_utterance(utterance).allows_mutation:
        return False
    raw_control = re.sub(r"<@!?\d+>", "", utterance.text).strip()
    raw_control = re.sub(
        r"^\s*@inebotten\b", "", raw_control, flags=re.IGNORECASE
    ).strip()
    return _POLL_TARGET_MUTATION_COMPLETE.fullmatch(raw_control) is None


def _term_tokens(term: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)?", term.casefold()))


def _token_starts(tokens: tuple[str, ...], needle: tuple[str, ...]):
    width = len(needle)
    for index in range(0, len(tokens) - width + 1):
        if tokens[index:index + width] == needle:
            yield index


def _negation_payload_start(
    utterance: NormalizedUtterance,
) -> int | None:
    """Locate data after a bounded parser-owned action frame.

    Words such as ``aldri``/``never`` and ``glem`` may be literal title text
    (for example ``Glem det aldri`` or a search for ``never gonna``).  Only
    these parser-owned frames get the exception; left-side or in-frame
    negation still blocks the action, and terminal retractions remain active.
    """

    match = _NEGATION_PAYLOAD_PREFIX.match(utterance.control_text)
    return len(_term_tokens(match.group(0))) if match is not None else None


def _terminal_cancellation(
    tokens: tuple[str, ...],
) -> tuple[int, tuple[str, ...]] | None:
    matches = sorted(
        (_term_tokens(phrase) for phrase in TRAILING_CANCELLATIONS),
        key=len,
        reverse=True,
    )
    for needle in matches:
        if needle and tokens[-len(needle):] == needle:
            return len(tokens) - len(needle), needle
    return None


def _has_hard_clause_boundary(
    text: str,
    cancellation: tuple[str, ...],
) -> bool:
    without_terminal_punctuation = re.sub(r"[.!?]+$", "", text).rstrip()
    clauses = re.split(r"[,.!?;]+", without_terminal_punctuation)
    return (
        len(clauses) > 1
        and _term_tokens(clauses[-1]) == cancellation
    )


def _bare_terminal_cancellation_is_control(
    tokens: tuple[str, ...],
    *,
    action_end: int,
    cancellation_start: int,
    cancellation: tuple[str, ...],
) -> bool:
    """Recognize a bare cancel suffix only after a completed action value."""
    if " ".join(cancellation) not in BARE_TRAILING_CANCELLATIONS:
        return False

    prefix = tokens[:cancellation_start]
    if prefix in _BARE_CANCELLATION_COMPLETE_FRAMES:
        return True

    # A terminal word can itself be the requested value ("playing Stop",
    # "endre tittel til Cancel", or a film named "Cancel"). In those
    # incomplete value shells there is no earlier payload to cancel.
    if not prefix or prefix[-1] in {"til", "to"}:
        return False
    joined_prefix = " ".join(prefix)
    cancellation_text = " ".join(cancellation)
    if (
        cancellation_text in _NATURAL_BARE_RETRACTIONS
        and prefix[-1] not in _BARE_RETRACTION_VALUE_INTRODUCERS
        and any(
            pattern.search(joined_prefix)
            for pattern in _BARE_RETRACTION_COMPLETE_PREFIXES
        )
    ):
        return action_end < cancellation_start
    if any(
        pattern.fullmatch(joined_prefix)
        for pattern in _BARE_CANCELLATION_PAYLOAD_SHELLS
    ):
        return False

    return action_end < cancellation_start


def _has_trailing_action_cancellation(
    utterance: NormalizedUtterance,
    *,
    action_end: int,
) -> bool:
    terminal = _terminal_cancellation(utterance.tokens)
    if terminal is None:
        return False
    cancellation_start, cancellation = terminal
    if action_end > cancellation_start:
        return False
    boundary_window = utterance.tokens[
        max(action_end, cancellation_start - TRAILING_CANCELLATION_LOOKBACK):
        cancellation_start
    ]
    return (
        any(token in TRAILING_CANCELLATION_MARKERS for token in boundary_window)
        or _has_hard_clause_boundary(utterance.control_text, cancellation)
        or _bare_terminal_cancellation_is_control(
            utterance.tokens,
            action_end=action_end,
            cancellation_start=cancellation_start,
            cancellation=cancellation,
        )
    )


def is_standalone_action_retraction(
    utterance: NormalizedUtterance,
) -> bool:
    """Return whether one complete clause is only a known retraction."""

    control = utterance.control_text.strip().rstrip("?.!").strip()
    return control in TRAILING_CANCELLATIONS


def is_negated_action(
    utterance: NormalizedUtterance,
    action_terms: Iterable[str],
    *,
    allow_positive_forget: bool = False,
) -> bool:
    tokens = utterance.tokens
    payload_start = _negation_payload_start(utterance)
    ignored_negations: set[int] = set()
    if allow_positive_forget:
        for phrase in POSITIVE_FORGET:
            needle = _term_tokens(phrase)
            for start in _token_starts(tokens, needle):
                ignored_negations.add(start)
    for term in action_terms:
        needle = _term_tokens(term)
        if not needle:
            continue
        for index in _token_starts(tokens, needle):
            if payload_start is not None and index >= payload_start:
                continue
            left = max(0, index - 8)
            right = min(
                len(tokens),
                index + len(needle) + 4,
                payload_start if payload_start is not None else len(tokens),
            )
            negated_indices = {
                offset
                for offset in range(left, right)
                if tokens[offset] in NEGATIONS
            }
            if negated_indices - ignored_negations:
                return True
            if _has_trailing_action_cancellation(
                utterance,
                action_end=index + len(needle),
            ):
                return True
    return False


def evidence_is_quoted_only(
    utterance: NormalizedUtterance, terms: Iterable[str]
) -> bool:
    normalized = tuple(
        term.casefold().strip() for term in terms if term.strip()
    )
    present = tuple(
        term for term in normalized
        if _contains_phrase(utterance.folded, (term,))
    )
    if not present:
        return False
    return not _contains_phrase(utterance.control_text, present)


def analyze_utterance(utterance: NormalizedUtterance) -> UtteranceSemantics:
    text = utterance.control_text.strip()
    # URL hosts, paths, queries, and fragments are payload, not discourse
    # evidence (for example ``example.com`` must not imply a meta example).
    frame_text = _CONTROL_URL.sub(" ", text)
    if text in CONFIRMATIONS:
        return UtteranceSemantics(
            SpeechAct.CONFIRMATION,
            ("exact_confirmation",),
            False,
        )
    if text in REJECTIONS:
        return UtteranceSemantics(
            SpeechAct.REJECTION,
            ("exact_rejection",),
            False,
        )
    polite_conditional = bool(
        _POLITE_CONDITIONAL_DIRECTIVE.fullmatch(frame_text)
        and _contains_phrase(frame_text, COURTESY_REQUEST_TERMS)
    )
    if not polite_conditional and (
        _contains_phrase(frame_text, HYPOTHETICAL_FRAMES)
        or any(pattern.search(frame_text) for pattern in HYPOTHETICAL_PATTERNS)
    ):
        return UtteranceSemantics(
            SpeechAct.HYPOTHETICAL,
            ("hypothetical_frame",),
            False,
        )
    if _contains_phrase(frame_text, META_FRAMES) or any(
        pattern.search(frame_text) for pattern in META_PATTERNS
    ):
        return UtteranceSemantics(SpeechAct.META, ("meta_frame",), False)
    if any(
        pattern.search(text)
        for pattern in INFORMATION_MUTATION_PATTERNS
    ):
        return UtteranceSemantics(
            SpeechAct.INFORMATION_REQUEST,
            ("information_question",),
            False,
        )
    if (
        PERMISSION_QUESTION_PATTERN.search(text)
        and _contains_phrase(text, ACTION_TERMS)
    ):
        return UtteranceSemantics(
            SpeechAct.INFORMATION_REQUEST,
            ("permission_question",),
            False,
        )
    if _contains_phrase(text, POLITE_DIRECTIVES):
        negated = is_negated_action(utterance, ACTION_TERMS)
        return UtteranceSemantics(
            SpeechAct.DIRECTIVE,
            ("polite_directive",) + (("negated_action",) if negated else ()),
            not negated,
        )
    if (
        bounded_english_calendar_create_head(utterance) is not None
        or bounded_english_reminder_create_head(utterance) is not None
    ):
        negated = is_negated_action(utterance, ACTION_TERMS)
        return UtteranceSemantics(
            SpeechAct.DIRECTIVE,
            ("bounded_english_create_directive",)
            + (("negated_action",) if negated else ()),
            not negated,
        )
    if _BOUNDED_NATURAL_DIRECTIVE.match(text):
        negated = is_negated_action(utterance, ACTION_TERMS)
        return UtteranceSemantics(
            SpeechAct.DIRECTIVE,
            ("bounded_natural_directive",)
            + (("negated_action",) if negated else ()),
            not negated,
        )
    if text.startswith(QUESTION_STARTS) or (
        text.endswith("?") and not _contains_phrase(text, ACTION_TERMS)
    ):
        return UtteranceSemantics(
            SpeechAct.INFORMATION_REQUEST,
            ("information_question",),
            False,
        )
    if _contains_phrase(text, ACTION_TERMS):
        negated = is_negated_action(
            utterance,
            ACTION_TERMS,
            allow_positive_forget=True,
        )
        return UtteranceSemantics(
            SpeechAct.DIRECTIVE,
            ("imperative_action",) + (("negated_action",) if negated else ()),
            not negated,
        )
    if is_trusted_mutation_fragment(utterance):
        return UtteranceSemantics(
            SpeechAct.STATEMENT,
            ("trusted_mutation_fragment",),
            True,
        )
    return UtteranceSemantics(
        SpeechAct.STATEMENT,
        ("statement_fallback",),
        False,
    )
