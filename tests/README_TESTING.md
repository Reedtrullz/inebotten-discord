# Inebotten Test & Tune System

> Automatisk testing og forbedring av botens naturlige samtaleevner

## Hva dette gjør

1. **Tester** botten med 50 naturlige meldinger
2. **Analyserer** svarene for kvalitet
3. **Foreslår** prompt-forbedringer automatisk
4. **Tracker** fremgang over tid

## Rask start

```bash
cd tests

# 1. Kjør testen (tar ~2-3 minutter)
python3 natural_chat_test.py

# 2. Se analysen og forbedringsforslag
python3 auto_tune_prompts.py
```

## Hva testes?

### 50 Naturlige meldinger:
- **Hilsener** (10): "Hei!", "God morgen!", etc.
- **Personlig spørsmål** (10): "Hvem er du?", "Hva kan du gjøre?"
- **Filosofiske/emosjonelle** (10): "Hvordan føler du deg?", "Er du ekte?"
- **Tilfeldig prat** (10): "Jeg er sliten...", "Liker du kaffe?"
- **Blandet** (10): "Takk!", "Ha det bra!", "Kan jeg spørre deg noe?"

### Kvalitetskriterier:

| Godt tegn | Dårlig tegn |
|-----------|-------------|
| ✅ Naturlig norsk | ❌ "Skjønte ikke helt..." |
| ✅ Kort og vennlig | ❌ Lister opp kommandoer |
| ✅ Bruker emojis | ❌ Broken norsk ("Jeg er godt") |
| ✅ Still oppfølging | ❌ Engelske ord |
| ✅ Kontekstuelt svar | ❌ For langt (>200 tegn) |

## Forstå resultatene

### Eksempel output:
```
Total tests: 50
Natural responses: 35 (70.0%)
Robotic/Command lists: 8
Fallback errors: 5
Broken Norwegian: 2
```

**Mål:** Over 80% naturlige svar

### Problem-analyse

Testen identifiserer:
- Hvilke spørsmål som forvirrer botten
- Om den lister kommandoer for ofte
- Grammatikk-feil
- Engelsk-blanding

## Auto-tune systemet

Etter testen genererer `auto_tune_prompts.py`:

1. **Forbedret prompt** med eksempler for problematiske spørsmål
2. **Konfigurasjons-endringer** (temperature, penalties)
3. **Grammatikk-regler** hvis nødvendig

### Eksempel forbedring:

**Før:**
```
Du er Ine. Snakk norsk.
```

**Etter (auto-generert):**
```
Du er Ine. Snakk norsk. Vær vennlig.

EKSEMPLER:
Q: Hvem er du?
A: Jeg er Ine, din kalender-venn! 📅

Q: Hva kan du gjøre?
A: Jeg kan hjelpe deg med kalenderen og prate! 😊

REGLER:
- Svar naturlig
- Ikke list kommandoer
- Bruk "det går bra" ikke "jeg er godt"
```

## Tips for best resultat

1. **Kjør testen flere ganger** etter hver justering
2. **Sammenlign rapporter** for å se fremgang
3. **Fokuser på de verste** først (fallback-spørsmål)
4. **Vær tålmodig** - AI-tuning tar tid!

## Avansert bruk

### Tilpass test-meldinger

Rediger `TEST_MESSAGES` i `natural_chat_test.py`:

```python
TEST_MESSAGES = [
    "Din egen test-melding her",
    "Og en til...",
    # etc.
]
```

### Manuell evaluering

Se på individuelle svar i JSON-rapporten:

```bash
cat test_report_20240115_143022.json | python3 -m json.tool | less
```

### Kontinuerlig testing

Sett opp cron-job for daglig testing:

```bash
# crontab -e
0 9 * * * cd /home/reed/.hermes/discord/tests && python3 natural_chat_test.py >> daily_tests.log 2>&1
```

## Feilsøking

**"Cannot connect to Hermes"**
→ Sjekk at `python3 hermes_bridge_server.py` kjører

**"No test reports found"**
→ Kjør `natural_chat_test.py` først

**Alle svar er "Skjønte ikke helt"**
→ AI-modellen er ikke lastet i LM Studio

## Resultat-filer

- `test_report_YYYYMMDD_HHMMSS.json` - Detaljerte resultater
- `improved_prompt_YYYYMMDD_HHMMSS.txt` - Foreslått forbedret prompt
- `daily_tests.log` - Hvis du bruker cron (valgfritt)

---

**Happy testing!** 🧪🤖🇳🇴
