# OpenRouter-oppsett

Denne guiden viser hvordan Inebotten kan bruke OpenRouter i stedet for lokal LM Studio.

## Kortversjon

1. Lag API-nøkkel på [openrouter.ai/keys](https://openrouter.ai/keys).
2. Sett `AI_PROVIDER=openrouter` i `.env`.
3. Legg inn `OPENROUTER_API_KEY`.
4. Velg modell.
5. Start botten på nytt.

```bash
AI_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-din-nokkel
OPENROUTER_MODEL=google/gemma-3-4b-it:free
OPENROUTER_TEMPERATURE=0.7
OPENROUTER_MAX_TOKENS=200
```

```bash
python3 scripts/run_both.py
```

## Når bør du bruke OpenRouter?

| Velg | Når |
|------|-----|
| LM Studio | Du vil kjøre lokalt, gratis og uten sky-API |
| OpenRouter | Du vil slippe lokal modell, bruke flere modeller eller kjøre på svak maskin |

OpenRouter krever internett og API-nøkkel. Gratis modeller finnes, men de kan ha rate limits.

## Anbefalte modeller

| Modell | Kostnad | Norsk | Kommentar |
|--------|---------|-------|-----------|
| `google/gemma-3-4b-it:free` | Gratis | Svært god | Anbefalt startvalg |
| `meta-llama/llama-3-8b-instruct:free` | Gratis | God | Stabil generell modell |
| `mistralai/mistral-7b-instruct:free` | Gratis | Middels | Rask og kreativ |
| `anthropic/claude-3-haiku` | Betalt | Svært god | Billig og presis |
| `openai/gpt-3.5-turbo` | Betalt | God | Stabil og godt testet |

Sjekk alltid modellnavn og pris i OpenRouter før produksjonsbruk, siden tilgjengelighet og priser kan endre seg.

## Konfigurasjonsvalg

| Variabel | Påkrevd | Standard | Forklaring |
|----------|---------|----------|------------|
| `AI_PROVIDER` | Ja | `lm_studio` | Sett til `openrouter` for sky-API |
| `OPENROUTER_API_KEY` | Ja | Ingen | API-nøkkel fra OpenRouter |
| `OPENROUTER_MODEL` | Nei | `google/gemma-3-4b-it:free` | Modell-ID |
| `OPENROUTER_TEMPERATURE` | Nei | `0.7` | Høyere verdi gir friere svar |
| `OPENROUTER_MAX_TOKENS` | Nei | `200` | Maksimal lengde på AI-svar |
| `OPENROUTER_BASE_URL` | Nei | `https://openrouter.ai/api/v1` | Endres normalt ikke |

## Bytte tilbake til LM Studio

```bash
AI_PROVIDER=lm_studio
```

Start deretter botten på nytt. OpenRouter-verdiene kan bli liggende i `.env`, men nøkkelen må fortsatt holdes hemmelig.

## Kostnadskontroll

- Bruk gratis modell når du tester.
- Hold `OPENROUTER_MAX_TOKENS` lavt for korte Discord-svar.
- Følg med på forbruk i OpenRouter-dashboardet.
- Ikke logg API-nøkler.

## Feilsøking

| Problem | Sjekk |
|---------|-------|
| Ugyldig API-nøkkel | Nøkkelen starter med `sk-or-`, er aktiv og ligger i riktig `.env` |
| Rate limit | Bruk færre kall, bytt modell eller vent til grensen nullstilles |
| Modell finnes ikke | Kopier modell-ID direkte fra OpenRouter |
| Treg respons | Prøv en mindre modell og senk `OPENROUTER_MAX_TOKENS` |
| Dårlig norsk | Start med `google/gemma-3-4b-it:free` eller en bedre betalt modell |

## Sikkerhet

OpenRouter-nøkkelen er en hemmelighet. Ikke legg den i GitHub, skjermbilder, logger eller `launcher_config.json`.
