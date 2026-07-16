# Inebotten – eksempelbank for naturlig språk

Inebotten er mention-gated. Tagg botten og beskriv målet ditt med vanlige ord;
du trenger ikke huske en fast kommandosyntaks.

```text
@inebotten Kan du legge inn et møte med Ola i morgen klokka 14?
```

Eksemplene på denne siden er kjørbare kontrakter mot produksjonsruteren. De
viser formuleringer som er testet, men er ikke en uttømmende liste over lovlige
varianter. Bokmål, flere nynorskformer, utvalgte dialektnære former og enkel
engelsk inngår i den versjonerte NLU-evalueringen.

## Kalender og påminnelser

| Mål | Eksempel |
|---|---|
| Legge inn en avtale | `@inebotten Kan du legge inn et møte med Ola i morgen klokka 14?` |
| Se kalenderen | `@inebotten Kan du vise meg kalenderen?` |
| Flytte en avtale | `@inebotten Kan du flytte møtet med Ola til fredag klokka 10?` |
| Markere noe ferdig | `@inebotten Kan du markere møtet med Ola ferdig?` |
| Slette en avtale | `@inebotten Kan du slette møtet med Ola?` |
| Lage en påminnelse | `@inebotten Kan du minne meg på å ringe legen om to timer?` |
| Se påminnelser | `@inebotten Kan du vise påminnelsene mine?` |
| Fullføre en påminnelse | `@inebotten Kan du markere påminnelse 1 som ferdig?` |
| Søke | `@inebotten Kan du søke i kalenderen etter møte?` |

Tid kan uttrykkes på flere måter, blant annet `i morgen`, `i overmorgen`,
`imorgen`, `i morra`, `på mandag`, `15. juli`, `klokka 15`, `at 3 pm`,
`om seks timer` og `day after tomorrow`. Uklare tidspunkter gir en presisering
i stedet for et skjult standardvalg.

Gjentakelser som `hver fredag`, `annenhver uke`, `hver måned` og `hvert år`
bevares som strukturerte gjentakelser. Motstridende dato-, tids- eller
gjentakelsesbevis blir avvist.

## Avstemninger, sitater og watchlist

| Mål | Eksempel |
|---|---|
| Lage en avstemning | `@inebotten Kan du lage en avstemning: Hva spiser vi? pizza, burger eller taco` |
| Se aktive avstemninger | `@inebotten Kan du vise aktive avstemninger?` |
| Stemme | `@inebotten Jeg stemmer på alternativ 1` |
| Endre spørsmål | `@inebotten Kan du redigere avstemningen 1 spørsmål: Middag?` |
| Lukke | `@inebotten Kan du lukke avstemning 1?` |
| Lagre et sitat | `@inebotten Kan du lagre dette som et sitat: Et klokt sitat` |
| Se sitater | `@inebotten Kan du vise meg sitatene?` |
| Legge til noe å se | `@inebotten Kan du huske at jeg vil se Inception?` |
| Få et forslag | `@inebotten Hva skal vi se?` |

## Bursdager

Førstepersonsformuleringer bindes til Discord-brukeren som skrev meldingen:

```text
@inebotten Kan du legge til bursdagen min 15. mai?
@inebotten Kan du endre bursdagen min til 20. mai?
@inebotten Kven har bursdag snart?
```

Et fritt navn blir ikke gjettet som Discord-identitet. Bruk en løst Discord-
mention når forespørselen gjelder en annen bruker; ellers spør botten hvem du
mener.

## Verktøy

| Mål | Eksempel |
|---|---|
| Kryptopris | `@inebotten Hvis du har tid kan du vise prisen på BTC?` |
| Regne | `@inebotten Kan du regne ut 2,5 + 1?` |
| Konvertere | `@inebotten Kan du konvertere 10,5 km til meter?` |
| Temperatur | `@inebotten Kan du konvertere 25 °C til °F?` |
| Nedtelling | `@inebotten Kan du fortelle meg hvor mange dager det er til jul?` |
| ISO-dato | `@inebotten How many days until 2026-12-25?` |
| Horoskop | `@inebotten Kan du vise meg horoskopet for Løven?` |
| Forkorte lenke | `@inebotten Kan du forkorte https://example.invalid?` |
| Søke på nettet | `@inebotten Kan du søke etter tog til Trondheim?` |
| Nordlys | `@inebotten Kan du vise meg nordlysvarselet?` |
| Dagens ord | `@inebotten Kan du gi meg dagens ord?` |

Høflighet kan stå først eller sist, med eller uten komma:

```text
@inebotten Kan du hvis du har tid vise prisen på BTC?
@inebotten Hvis du har tid kan du vise prisen på BTC?
@inebotten Vis prisen på BTC, hvis du har tid.
```

Høflighetsfrasen fjernes før payloaden bygges. Den blir derfor ikke en del av
søkestrengen, tittelen, URL-en eller kryptonavnet.

## Vær, sted og skoleferier

```text
@inebotten Kan du vise meg været?
@inebotten Jeg bor i Trondheim.
@inebotten Kan du vise skoleferiene i Tromsø?
@inebotten Can you show school holidays in Tromsø?
```

Skoleferier varierer regionalt. Botten velger fylke fra et avgrenset stedsnavn
og blander ikke gjensidig utelukkende ferieuker. Den innebygde datatabellen er
begrenset til verifiserte datoer i skoleåret 2025–2026; etter siste dekningsdato
sier botten tydelig at den ikke kan bekrefte datoene, i stedet for å påstå at
ingen ferie er planlagt.

## Profil, status og minne

```text
@inebotten Kan du vise meg botstatus?
@inebotten Kan du sette statusen til online?
@inebotten Kan du sette aktiviteten til å spille CS2?
@inebotten Kan du vise hva du husker om meg?
@inebotten Kan du eksportere minnet mitt?
@inebotten Kan du slette minnet mitt?
```

Bare allowlistet brukerminne sendes til en ekstern AI-leverandør. Discord-ID,
rå samtalehistorikk og handlingers strukturerte payload blir ikke brukt som
vilkårlig modellkontekst.

## Bekreftelse, avbrytelse og rettelser

Eksplisitte, komplette og trygge forespørsler kan behandles direkte. Sletting,
autentisering og modellforeslåtte skrivehandlinger vises først som en
kanal- og brukeravgrenset forhåndsvisning.

Naturlige svar på en aktiv forhåndsvisning inkluderer:

```text
ja takk
ok, kjør
nei, avbryt
don't do it
jeg ombestemte meg
jeg mener den andre
alternativ 2
i overmorgen klokka 15
spørsmål: Nytt spørsmål?
```

En rettelse endrer bare feltene som er uttrykkelig nevnt, lager en ny
forhåndsvisning og krever ny bekreftelse. En avbrutt handling kan ikke vekkes
til live av et senere `ja`, og to samtidige bekreftelser kan utføre handlingen
høyst én gang.

## Når botten lar være å handle

Disse formene skal forbli samtale eller gi en trygg presisering:

- sitert eller kodeformatert handlingstekst;
- negasjoner som `ikke slett møtet`;
- hypotetiske og metaspørsmål som `hva skjer hvis jeg sletter møtet?`;
- flere handlinger i én melding;
- uklare eller motstridende datoer;
- fritt skrevne identitetsnavn uten løst Discord-eierskap;
- vanlige utsagn som bare nevner `aurora`, `sommerferie` eller `daily digest`.

## Hjelp og drift

Spør `@inebotten kva kan du gjere?` eller åpne siden **Eksempler** i
webkonsollen. Begge rendres fra samme typede hjelpekatalog som testes mot
produksjonsruteren.

For lokal oppstart og drift:

```bash
python3 setup.py
python3 scripts/run_both.py
```

Webkonsollen ligger normalt på `http://localhost:8080`. Se
[DOCUMENTATION.md](DOCUMENTATION.md), [ARCHITECTURE.md](ARCHITECTURE.md) og
[VPS_DEPLOYMENT.md](VPS_DEPLOYMENT.md) for tekniske detaljer.
