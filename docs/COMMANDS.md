# Kommandoer

## Faktasjekk av kalenderoppføringer

Inebotten kan starte en lesebasert faktasjekk når du uttrykker en konkret
bekymring om dato eller klokkeslett for en kjent kalenderoppføring:

- `@inebotten jeg tror tidspunktet for Møte med Ola er feil`
- `@inebotten eg trur tidspunktet for Møte med Ola er feil`
- `@inebotten I think the time for Møte med Ola is wrong`

Første svar viser kalenderens nåværende dato og klokkeslett. Du kan deretter
be boten undersøke offentlige kilder eller oppgi en konkret ny dato eller tid.
En eventuell endring vises alltid som en separat bekreftelse og utføres først
etter et eksplisitt `@inebotten ja`. `feil`, `wrong` eller `stemmer ikke` alene
autoriserer aldri en kalenderendring.
