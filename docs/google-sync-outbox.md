# Google-synkronisering med bekreftet gjennomføring

Kalenderendringer og Google-intent lagres i samme lokale eierdokument før API-kallet. Lokal lagring er ikke en bekreftelse fra Google. Status er `pending`, `synced`, `unknown`, `conflict` eller `failed`; konsollen viser norske beskrivelser og bare antall i områder leseren har tilgang til. Hver oppføring beholder inntil åtte intensjoner. En full kø avviser nye endringer uten å forkaste uavklarte operasjoner.

Én delt provider-slot behandler kalenderen og den allerede initialiserte påminnelseseieren. Nettverksarbeid skjer i en tråd. En synkroniseringsrunde har en felles frist på 20 sekunder og behandler høyst åtte oppføringer per eier. En tråd som overskrider fristen beholder sloten til den faktisk avsluttes: Python kan ikke sikkert avbryte et vilkårlig synkront klientkall. Sene svar publiseres ikke som vellykkede lokale operasjoner. Stopp eller krasj etter ekstern gjennomføring etterlater en varig uavklart intensjon som undersøkes ved neste runde.

Nyopprettelser bruker en på forhånd lagret tilfeldig Google-ID og et privat operasjonsmerke. Uavklart opprettelse gjentas aldri blindt. En direkte kvittering eller etterfølgende lesing må vise samme ID, operasjonsmerke, versjon og redigerbare verdier før gjennomføring bekreftes. Dette er ikke en garanti om global «exactly once»: manglende eller motstridende bevis krever avklaring. Google-lesing ved en uklar 404 beviser ikke sletting.

Oppdatering og sletting krever en kjent Google-versjon, en forhåndslesing og `If-Match` på selve endringen. Samtidige endringer gir konflikt fremfor automatisk overskriving. Kjente rateavvisninger bruker ventetid og høyst seks forsøk. Manglende autorisasjon, ugyldige felt og brukt forsøksbudsjett stanser automatisk skriving. En feil må rettes og gjennomgås før en ny intensjon kan erstatte den; autorisasjon alene beviser ikke gjennomføring.

## Gjennomgå en konflikt

Bruk `@inebotten synk konflikt <operasjons-ID> lokal` eller `google`. Botten viser begge versjoner og ID-ene til ventende intensjoner valget erstatter. Bekreft deretter den viste koden med `@inebotten bekreft synk <kode>` innen fem minutter. For eldre koblede påminnelser brukes `synk konflikt påminnelse <ID> ...` og `bekreft synk påminnelse <kode>`. Valget er bundet til personen, samtalen, lokal revisjon, området og Google-versjonen. Endringer etter visning krever ny gjennomgang. For stor tekst åpner ingen bekreftelse i Discord.

«Lokal» kølegger den gjennomgåtte nåværende lokale versjonen, også en senere lokal sletting. «Google» bruker den gjennomgåtte versjonen lokalt. Ekstern gjennomføring av det lokale valget må fortsatt bekreftes av worker. Ingen automatisk siste-skriver-vinner. Konfliktbevis lagrer bare redigerbare kalenderfelt, egne operasjonsmerker, ID og versjon; deltakerlister og annen uvedkommende Google-metadata beholdes ikke i beviset. Lokal angre støtter ikke tilbakeføring av Google-operasjoner; nye revisjoner kan gjøre eldre angrekoder ugyldige. Uavklart ekstern aksept blokkerer lokal angre som ellers ville forkastet kvitteringsbevis. Redigering før første opprettelse kølegger en etterfølgende oppdatering av samme ID, ikke en ny opprettelse.

Påminnelser uten eksplisitt arrangementstid opprettes aldri som tidsbestemte Google-arrangementer. Eldre koblede påminnelser kan oppdatere tekst/fullføring eller slettes betinget. Endring av lokal frist eller gjentakelse stanser ekstern skriving og ber om eksplisitte arrangementsfelt. Ukjente Google-serieregler beholdes; full serie-/forekomstmodell er I10.

Innkommende data leses uten å holde den lokale skriverlåsen. En endret lokal revisjon avviser hele den innkommende anvendelsen. Ventende lokale endringer overskrives ikke av en pull. Listing er begrenset til 4096 hendelser og 16 sider; overskridelse behandles som utilgjengelig listing, aldri som bevis på at manglende lokale hendelser er slettet.

## Kildegrunnlag og lokal verifikasjon

Kontrollert 4. oktober 2026 mot Googles offisielle dokumentasjon:

- [Egendefinerte hendelses-ID-er](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert): base32hex-tegn og klientvalgt ID; tilfeldig UUID gir et gyldig ID-grunnlag.
- [Versjoner og betingede endringer](https://developers.google.com/workspace/calendar/api/guides/version-resources): ETag og If-Match, 412 ved versjonskonflikt.
- [Patch-semantikk](https://developers.google.com/workspace/calendar/api/v3/reference/events/patch): utelatte felt beholdes, angitte arrays erstattes. Påminnelser patcher bare egne støttede felt; tom recurrence-array fjerner uttrykkelig en regel.
- [Feilklassifisering](https://developers.google.com/workspace/calendar/api/guides/errors): avgrensede rateavvisninger, autorisasjon og versjonskonflikt.

Syntetiske tester dekker mislykket lokal commit, krasj etter ekstern aksept, stopp etter aksept, uavklart opprettelse uten gjentakelse, konflikt før/etter forhåndslesing, reviderte valg, full kø, sen pull, uavhengig event-loop-heartbeat og faktiske adapterforespørsler med mockede credentials. Ingen Google-konto, OAuth-token eller produksjonsdata ble brukt. Kontoaksept og full shutdown-integrasjon er egne porter.
