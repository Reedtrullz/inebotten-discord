# Privat eksport av brukerminne

`eksporter minnet mitt` i en direktemelding sender hele den lagrede,
gjeldende brukerminneposten som `inebotten-minne.json` i UTF-8. Eksporten
inneholder bare avsenderens post, inkludert lagrede minnekontroller. Utløpte
tema følger den eksisterende oppryddingsregelen. Midlertidig samtalekontekst,
andre brukere, sikkerhetskopier og tidligere provider-data inngår ikke.

I en server eller gruppe gir kommandoen instruksjoner uten å hente eller
publisere minneposten. `eksporter minnet mitt privat` velger uttrykkelig en
direktemelding til avsenderen. Manglende eller feil privat mottaker nekter
eksport; det finnes ingen offentlig reservelevering.

Applikasjonsgrensen er **1 MiB totalt**, målt i ferdige UTF-8-byte. For store
eksporter avvises hele; JSON blir aldri forkortet. Denne konservative grensen
er uavhengig av kontoens abonnement: Discords
[vedleggs-FAQ](https://support.discord.com/hc/en-us/articles/25444343291031-File-Attachments-FAQ)
oppgir 20 MB, mens
[kontogrensene](https://support.discord.com/hc/en-us/articles/33694251638295-Discord-Account-Caps-Server-Caps-and-More)
oppgir 10 MB for standardkontoer (kildene kontrollert 5. oktober 2026).
Gjeldende grense for en faktisk konto er ikke verifisert gjennom opplasting.

Vedlegg bruker samme `OutboundSender`, kvoter og monotone frist som tekst.
Vedleggsbyte og navn inngår i identiteten som hindrer duplikater. Et uttrykkelig
429-avslag kan prøves én gang med en ny lesestrøm; timeout eller manglende
meldingskvittering får status `unknown` og blir ikke automatisk prøvd igjen.
Lesestrømmer lukkes etter hvert forsøk. Kvitteringsbufferen lagrer ingen
eksportbyte. Ingen eksportfil skrives til disk av leveringskoden.

De lokale testene bruker syntetiske minneposter og falske transportmottakere.
De verifiserer komplette parserbare byte, størrelse, selv-avgrensning,
privat destinasjon, kvoter og feilkvitteringer. Faktisk Discord-opplasting og
mottakerens aksept er separate, ikke gjennomførte kontotester.
