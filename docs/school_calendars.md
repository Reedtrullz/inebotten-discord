# Skolerutedata: dekning og vedlikehold

Kalenderdataene i `features/data/school_calendars.json` gjelder skoleåret 2026–2027 og ble kontrollert 4. oktober 2026. Dataene er knyttet til kommunen og skoleåret. De skal ikke tolkes som fylkesdekkende ruter eller som en lagret brukerpreferanse.

## Kilder og avgrensning

| Kommune | Dekning | Offisiell kilde |
| --- | --- | --- |
| Oslo | Kvalitetssikret felles skolerute for offentlige grunnskoler og videregående skoler. Kommunen sier at planleggingsdager er inkludert i oppførte ferier/fridager, og tar forbehold om endringer når eksamensplanen publiseres. | [Skoleruta – ferie og fridager, Oslo kommune](https://www.oslo.kommune.no/skole-og-utdanning/ferie-og-fridager-i-skolen/) |
| Trondheim | Delvis dekning for kommunale barne- og ungdomsskoler: felles ferieperioder og publiserte skolefrie dager. Individuelle planleggingsdager er ikke inkludert fordi kommunen sier at de varierer mellom skoler og SFO. Sjekk skolens egen nettside for dem. | [Skoleruta, Trondheim kommune](https://www.trondheim.kommune.no/tema/skole/trondheimsskolen/overganger/ferie-og-fridager/) |

Trondheims juleferie er lagret fra og med dagen etter kommunens publiserte siste skoledag før ferien til og med dagen før publiserte første skoledag etter ferien. Sommerferien er tilsvarende avgrenset fra dagen etter siste skoledag til dagen før første skoledag i neste kalenderår. Disse intervallene er inklusive og tar med helgene.

## Brukergrensesnitt og dekning

- Brukeren må nevne Oslo eller Trondheim i forespørselen. Ingen kommune lagres som standard før lokalitetsvalg er del av en egen godkjent preferanseflyt.
- `verified` betyr at den publiserte kommunale kalenderen er kontrollert for oppgitt avgrensning. `partial` viser kjente datoer sammen med et tydelig varsel om manglende dekning. `unavailable` brukes når sted eller skoleår mangler eller ikke kan leses.
- En tom liste fra en verifisert kalender betyr bare at ingen oppførte ferier faller innenfor visningsperioden. Manglende eller delvis kalender vises aldri som «ingen ferier planlagt».
- Kontrolltidspunktet er gyldig i 365 dager. Etter utløp nedgraderes kalenderen til delvis dekning inntil datoene er kontrollert på nytt. Manglende skoleår er utilgjengelig; datoer flyttes aldri automatisk fra forrige skoleår.

## Årlig vedlikehold

1. Finn den offisielle kommunen sin publiserte skolerute for nytt skoleår.
2. Kontroller hvert datointervall, målgruppe, fridager, kilde-URL og eventuelle forbehold. Ikke utled fylkesruter eller skolevise planleggingsdager fra naboskoler.
3. Oppdater `verified_at`, dekning, notat og kildelenke i JSON. Bruk `partial` hvis kommunen avgrenser bort skolevise dager; bruk `unavailable` når det ikke finnes en kontrollert rute.
4. Kjør `tests/test_school_calendar_coverage.py`, eksisterende ferie-/rutingstester og den isolerte offline-suiten.
5. Oppdater denne siden dersom kilde, skoleomfang eller kjente begrensninger endres.
