# Bevisst minne og deling

Automatisk læring og deling av lagret personalisering med AI er av som standard. Eksisterende fakta slettes ikke for å innføre denne standarden. Tidligere tema uten sikker tidsmerking blir bevart lokalt, men sendes ikke som personalisering. Bevisst lagrede felt (sted, interesser, preferanser og skolekommune) er separate fra automatisk innlærte, tidsmerkede tema.

Alle kontroller gjelder bare personen som sender den autoriserte kommandoen:

- `@inebotten minne læring på` / `av`: styrer automatisk lagring av egne samtaletema. Pauset læring inkluderer ingen lagret personalisering eller historie i AI-prompten.
- `@inebotten minne del med lokal` / `openrouter` / `lokal og openrouter` / `ingen`: velger tillatt mottaker for personalisering. Valget erstatter tidligere deling; det legger ikke til en ny mottaker i det stille. Lokal betyr den konfigurerte Hermes/LM Studio-ruten, ikke en automatisk skyreserve.
- `@inebotten minne private fakta på` / `av`: tillater personlige felt og egne tidsmerkede tema i verifisert direktemelding, bare til en allerede tillatt provider. Slike felt tas ikke med i gruppe-/fellesprompt.
- `@inebotten minne behold tema 7 dager`: velg 1–365 dager; standard er 7. `ubegrenset` er et eksplisitt alternativ. Bare tema med kjent alder kan utløpe automatisk; sted, interesser og gamle tema uten alder blir ikke slettet med en gjetning.
- `@inebotten minne kommune oslo` / `trondheim`: lagrer et uttrykkelig kommunevalg. Skoleruta bruker dette automatisk bare i direktemelding når ingen støttet kommune er nevnt. To uttrykkelig nevnte kommuner krever fortsatt et entydig valg.
- `@inebotten vis minnet mitt`: viser lagrede felt og kontroller. `@inebotten slett minnet mitt bekreft`: sletter egen lokal brukerpost og egne midlertidige meldinger, inklusive nye botsvar med sikker tilknytning til personen.

Midlertidig kanalhistorie lever bare i minnet: høyst 256 aktive kanaler, 10 meldinger per kanal som standard, 4000 tegn per melding og 30 minutters utløp. Historien ryddes globalt ved innlegging/lesing, også for kanaler som ellers er inaktive. Den er avgrenset til faktisk kanal, ikke Discord-serveren. Automatisk temalæring bruker bare den aktuelle personens egne meldinger. Provider-filter kontrollerer avsenderens policy også for historikk; svar uten sikker person-tilknytning inngår ikke i AI-personalisering. Gamle botsvar uten kjent eier kan ikke trygt tilskrives og slettes derfor ikke som en annen persons data.

Når en deklarert AI-reserve gjenbruker samme prompt, må deling være tillatt for alle rutene som kan motta den. Hvis en av rutene er ukjent eller ikke tillatt, blir lagret personalisering utelatt. Den aktuelle brukerforespørselen behandles fortsatt av den konfigurerte AI-ruten; delingskontrollen gjelder lagret minne/historie og tilbakekaller ikke selve forespørselen.

Lokal sletting er ikke sletting av sikkerhetskopier, Discord-meldinger eller data som allerede er sendt til en provider. Sletting av andre brukere og fjernsletting inngår ikke i kommandoen. Mislykket vedvarende lokal lagring gir feil og beholder midlertidig kontekst. Fullstendige private eksportfiler behandles i I14; dagens eldre JSON-eksport er ikke en fullstendighetsgaranti.

Verifikasjon bruker bare syntetiske brukere, lokale midlertidige dokumenter og fake AI-adaptere. Den dekker opt-out, konkret dispatch-filter, reserve-rute, kjent/ukjent temaalder, global rydding, kopierte returverdier, egne versus andres poster og ærlig slettemelding.
