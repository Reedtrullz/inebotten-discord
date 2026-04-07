# Plan: Forbedre norsk språkstøtte i Inebotten

**Dato:** 2026-03-30  
**Mål:** Øke gjennomsnittlig norsk-score fra 29.4% til minimum 50% gjennom system prompt-forbedringer og dialekt-støtte

---

## Bakgrunn

Live testing med LM Studio (gemma-3-4b) viste at Inebotten har følgende utfordringer:

- **Gjennomsnittlig norsk-score:** 29.4%
- **Største svakhet:** Dialekt/uttrykk (19%) - skjønner ikke "kjekt", "tøft", "rått"
- **Andre svakheter:** Hilsener (22%), follow-up (19%), kalenderkommandoer

Sterke sider: Følelser (36%), norsk kultur (37%), hverdagsprat (38%)

---

## Mål

1. **Øke norsk-score til minimum 50%** gjennom bedre system prompt
2. **Legge til støtte for norske dialekt-uttrykk** ("kjekt", "tøft", "råft", etc.)
3. **Forbedre kalender-kommando-gjenkjenning** slik at praktiske kommandoer ikke går til AI
4. **Beholde all eksisterende funksjonalitet** (157 tester må fortsatt bestå)

---

## Steg-for-steg implementasjon

### Fase 1: Forberedelser og analyse (15 min)

**Steg 1.1: Inspiser eksisterende system prompt**
- Fil: Sjekk om det finnes en system prompt-fil i `ai/` mappen
- Alternativ: Sjekk `ai/hermes_connector.py` for hardkodede prompts
- Mål: Forstå nåværende prompt-struktur

**Steg 1.2: Inspiser conversation_context.py**
- Fil: `memory/conversation_context.py`
- Se på `SMALL_TALK_PATTERNS` for å forstå nåværende mønstre
- Identifiser hvilke norske uttrykk som allerede er støttet

### Fase 2: Forbedre system prompt (30 min)

**Steg 2.1: Opprett/oppdater system prompt for norsk språkbruk**

Opprett eller modifiser filen `ai/system_prompt.txt` (eller tilsvarende):

```
Du er Ine (Inebotten), en vennlig Discord-bot for norske brukere.

VIKTIG - SPRÅK:
- Svar ALLTID på norsk (bokmål/nynorsk)
- Bruk naturlige, uformelle norske uttrykk
- Inkluder gjerne: "kjempe", "supert", "flott", "skjønner", "nok", "vel", "altså"
- Bruk norske hverdagsuttrykk som passer konteksten

EKSEMPLER på ønsket stil:
- "Det var kjekt å høre!" (ikke "Det var gøy")
- "Skikkelig tøft!" (ikke "Veldig kult")
- "Jeg skjønner!" (ikke "Jeg forstår")
- "Kanskje det?" (ikke "Mulig")

DIALEKT-UTTRYKK du bør gjenkjenne:
- "kjekt" = gøy/fint
- "tøft" = kult/imponerende  
- "rått" = ekstremt bra
- "skikkelig" = veldig/ordentlig
- "morn" = god morgen
- "kvelden" = god kveld

Du er "den velinformerte vennen" - hjelpsom, varm og kunnskapsrik.
```

**Steg 2.2: Modifiser HermesConnector til å bruke system prompt**
- Fil: `ai/hermes_connector.py`
- Endring: Sørg for at `generate_response()` sender system prompt til bridge
- Verifiser at payload inkluderer `system_prompt` feltet

### Fase 3: Legge til dialekt-støtte (20 min)

**Steg 3.1: Utvid SMALL_TALK_PATTERNS**
- Fil: `memory/conversation_context.py`
- Legg til mønstre for:
  - `r'\bkjekt\b'` - gjenkjenne ordet "kjekt"
  - `r'\btøft\b'` - gjenkjenne ordet "tøft"
  - `r'\brått\b'` - gjenkjenne ordet "rått"
  - `r'\bskikkelig\b'` - gjenkjenne ordet "skikkelig"
  - `r'\bmorn\b'` - allerede delvis støttet, verifiser

**Steg 3.2: Vurder å legge til dialekt-responser i personality.py**
- Fil: `ai/personality.py`
- Legg til metode eller utvid eksisterende for å respondere på dialekt-uttrykk
- Eksempel: `respond_to_dialect(phrase)` som returnerer passende respons

### Fase 4: Eksperimentere med temp og max_tokens (25 min)

**Steg 4.1: Inspiser nåværende API-kall**
- Fil: `ai/hermes_connector.py`
- Sjekk `generate_response()` metoden
- Identifiser hvordan parametere sendes til LM Studio bridge

**Steg 4.2: Legg til temperatur-kontroll**
- Modifiser `generate_response()` til å støtte `temperature` parameter
- Eksperimenter med verdier:
  - `0.3` - mer konsistent, mindre kreativ
  - `0.7` - balansert (standard)
  - `0.9` - mer kreativ, kan gi mer naturlig norsk
- Test hvilken temperatur som gir best norsk flyt

**Steg 4.3: Legg til max_tokens-kontroll**
- Modifiser `generate_response()` til å støtte `max_tokens` parameter
- Eksperimenter med:
  - `100` - korte, konsise svar
  - `200` - mellomlange svar (standard)
  - `400` - lengre, mer detaljerte svar
- Vurder om kortere svar gir mer konsistent norsk kvalitet

**Steg 4.4: Dokumenter beste innstillinger**
- Test ulike kombinasjoner (temp + max_tokens)
- Logg resultater for:
  - Hilsener (korte svar)
  - Hverdagsprat (mellomstore)
  - Komplekse spørsmål (lengre svar)
- Velg optimal kombinasjon basert på norsk-score

### Fase 5: Forbedre kalender-gjenkjenning (20 min)

**Steg 5.1: Analyser NLP-parser**
- Fil: `cal_system/natural_language_parser.py`
- Identifiser hvorfor "Husk å kjøpe melk i morgen" ikke gjenkjennes
- Sjekk `parse_event()` og `parse_task()` metoder

**Steg 5.2: Utvid kalender-nøkkelord**
- Legg til "husk" som task-indicator
- Legg til "påminn meg" som reminder-indicator
- Vurder å legge til mønstre for:
  - `r'husk å .+'` - oppgaver
  - `r'påminn meg om .+'` - påminnelser
  - `r'kjøpe .+'` - handleliste-oppgaver

### Fase 6: Testing og validering (30 min)

**Steg 6.1: Kjør komprehensiv test suite**
```bash
python3 -m pytest tests/test_comprehensive.py -v
```
- Verifiser at alle 157 tester fortsatt består
- Hvis tester feiler, reparer før du fortsetter

**Steg 6.2: Kjør live norsk-test med ulike temp/max_tokens**
- Test med optimal temperatur (dokumentert i fase 4)
- Test med optimal max_tokens (dokumentert i fase 4)
- Sammenlign med baseline (29.4%)
- Mål: Minimum 50% gjennomsnittlig score

**Steg 6.3: Manuell verifisering av forbedrede områder**
Test spesifikt:
- [ ] "Dette var kjekt!" - skal gi respons med "kjekt" eller lignende
- [ ] "Skikkelig tøft!" - skal gjenkjenne uttrykket
- [ ] "Husk å kjøpe melk" - skal gå til kalender, ikke AI
- [ ] "Morn!" - skal gi naturlig morgen-hilsen
- [ ] Temperatur gir konsistente svar (ikke for variert)
- [ ] max_tokens gir passende lengde (ikke for kort/langt)

---

## Filer som vil endres

| Fil | Endring | Begrunnelse |
|-----|---------|-------------|
| `ai/system_prompt.txt` | Ny/opprettet | Definere norsk språkstil |
| `ai/hermes_connector.py` | Modifiser | Sende system prompt + temp/max_tokens til bridge |
| `memory/conversation_context.py` | Modifiser | Legge til dialekt-mønstre |
| `cal_system/natural_language_parser.py` | Modifiser | Forbedre kalender-gjenkjenning |
| `ai/personality.py` | Mulig modifisering | Dialekt-responser (valgfritt) |
| `.hermes/plans/temp_max_tokens_test_results.md` | Ny | Dokumentere eksperiment-resultater |

---

## Tester og validering

### Automatiske tester
1. **Komprehensiv suite:** `pytest tests/test_comprehensive.py` (må vise 157 passed)
2. **Norsk språktest:** Kjør live test mot LM Studio og sammenlign score

### Manuelle test-scenarioer
```python
test_cases = [
    ("Dette var kjekt!", "skal forstå og respondere på 'kjekt'"),
    ("Skikkelig tøft!", "skal gjenkjenne uttrykk"),
    ("Husk å kjøpe melk i morgen", "skal gå til kalender"),
    ("Morn! Lenge siden sist", "skal gi varm morgen-hilsen"),
    ("Jeg er stressa", "skal gi empati på norsk"),
]
```

---

## Risikoer og avveininger

| Risiko | Sannsynlighet | Mitigering |
|--------|---------------|------------|
| System prompt gjør AI for rigid | Middels | Test grundig, behold fallback |
| Dialekt-mønstre fanger for mye | Lav | Bruk word-boundaries (`\b`) |
| Kalender-endringer bryker eksisterende | Middels | Kjør alle 157 tester |
| LM Studio ignorerer system prompt | Mulig | Verifiser med live testing |
| Høy temperatur gir for ville svar | Middels | Test 0.7 først, øk gradvis |
| Lav temperatur gir for stive svar | Middels | Senk gradvis til optimal |
| max_tokens for lavt kutter gode svar | Lav | Test med 200 først |

---

## Neste steg etter implementasjon

1. **Hvis score < 50%:** Vurder ytterligere prompt-justeringer eller model-tuning
2. **Hvis score >= 50%:** Fokuser på spesifikke svake kategorier (f.eks. humor)
3. **Vurder å legge til nynorsk-støtte** hvis brukerbasen tilsier det
4. **Vurder å optimalisere temp/max_tokens ytterligere** basert på bruker-feedback

---

## Suksesskriterier

- [ ] Alle 157 eksisterende tester består
- [ ] Gjennomsnittlig norsk-score >= 50% (opp fra 29.4%)
- [ ] Dialekt-uttrykk gjenkjennes og besvares naturlig
- [ ] Kalender-kommandoer fungerer konsistent
- [ ] Optimal temperatur dokumentert (med begrunnelse)
- [ ] Optimal max_tokens dokumentert (med begrunnelse)
- [ ] Eksperiment-resultater logget i `.hermes/plans/temp_max_tokens_test_results.md`
