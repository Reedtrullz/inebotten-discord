# Avstemninger: frist, stemmer og endringer

`vote` sjekker lukket/utløpt tilstand i domenet, også ved direkte kall og etter restart. Nye frister har UTC-offset; gamle naive frister bevarer legacy-fortolkningen. Eksakt utløpstid er ikke åpen for nye stemmer. Lukkede resultater kan leses i samme guild/DM-område med `@inebotten poll resultater`/`poll results`; dette åpner ikke et annet område eller anonymiserer deltakelsen.

Hvert valg har stabil ID og hver avstemning en revisjon. `@inebotten endre poll N etikett OPTION_ID: Nytt navn` endrer bare etiketten og beholder tilhørende stemmer. Valg-ID-er vises med alternativene. Spørsmålsendring beholder stemmer. `valg: A/B` er en erstatning av alternativer: hvis listen endres, må stemmene nullstilles, også ved samme antall alternativer. Domenet antar ikke at Pizza → Fisk er en harmløs navneendring. Den eldre interne `edit_poll(options=...)` med samme antall er en dokumentert posisjonell etikettadapter; Discord bruker den eksplisitte ID-operasjonen.

Reset-forhåndsvisninger viser nye valg og effekten. Bekreft med `@inebotten bekreft poll endring TOKEN reset`. Tokenet gjelder bare samme aktør, poll, område og revisjon; enhver ny stemme/close gjør den gammel. Tokenet varer fem minutter, maksimalt 128 beholdes i minnet, og restart krever ny forhåndsvisning. Eierkontroll og eldre username-fallback er bevart. Ingen nye anonyme stemmegarantier eller statistiske påstander.

Poll-filen bruker samme schema-1-envelope, preserving legacy-backup, kopi/snapshot og samarbeidsbaserte prosesslås som I04/I05. Uleselig/nyere data er skrivebeskyttet, ikke en frisk tom avstemningsliste. Svar om stemmer/opprettelse/endring krever vellykket commit; write-feil bevarer forrige post/revisjon. Konsollen leser envelopen og utelater utløpte aktive poster. Pollmanageren eier domenedata; direkte mutasjon av et returnert dict endrer ikke lagret tilstand. I24 kobler `close_storage` til full shutdown.

Dette er prøvd med syntetiske data, fake clock, eierlås- og snapshot-prober og offline routing. Ingen eksisterende live-avstemning er endret eller nullstilt.
