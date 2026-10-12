# Daglige gjøremål

Konsollens «I dag» viser egne påminnelser i valgt kalenderområde og avstemninger i konsollens valgte kanal. Opprett, rediger, fullfør eller slett med forhåndsvisning; stem på et alternativ eller lukk en egen avstemning. Konsollavstemninger opprettes lokalt. Publiserte Discord-meldinger oppdateres ikke av disse konsollendringene.

Konsollen bruker eksisterende `CONSOLE_ACTOR_USER_ID` og `CONSOLE_ACTOR_CHANNEL_ID`. Velg et Discord-kanal-ID som allerede er godkjent for aktøren og kalenderområdet for kanalens avstemninger og varsler. Standardkanalen `console` viser egne oppgaver i området og kan pause varsler; en godkjent destinasjon eller eksisterende varselprofil kreves for å aktivere dem. Private områder sender fortsatt bare til eierens verifiserte direktemelding. Ingen tillatelser eller private innstillinger endres automatisk.

Vanlige påminnelser får ett fristvarsel. Etterfrist er et bevisst valg, fra 5 til 1440 minutter, via konsollen eller `@inebotten varsler etterfrist 30`. `@inebotten varsler etterfrist av` slår det av. Stille timer flytter varsler til neste tillatte tidspunkt og samler sammenfallende varsler. Neste varselplan viser tidssone og destinasjon, inkludert slumring. Dato uten tid bruker kl. 09:00 i Europe/Oslo.

Kvitteringer og planlagte påminnelser inneholder kopierbare Fullfør-, Slumre- og Rediger-kommandoer for én bestemt oppføring. Slumre utsetter denne forekomsten ti minutter; stille timer gjelder fortsatt. Valgene krever samme bruker og kanal, korrekt område og uendret oppføring. De varer opptil 24 timer og utløper ved omstart.

Lokale påminnelse- og avstemningsendringer kan angres med valget i konsollen eller kommandoen i kvitteringen. Angre varer fem minutter, krever samme aktør og uendret lager og gjenoppretter bare den valgte oppføringen. Det tilbys ikke for Google-koblede eller planleggingsstyrte oppføringer. Sendte varsler, publiserte meldinger og leveringshistorikk beholdes. Oppdater listen og velg på nytt etter utløp eller en samtidig endring.

Kalendereditoren starter med tittel, dato og tid. «Avansert» viser tidssone, type, varighet og beskrivelse. Ved høstens klokkeomstilling vises valget før eller etter at klokken stilles tilbake når tidspunktet er tvetydig. Verdiene bevares under valideringen. Gjentakelser krever fortsatt et uttrykkelig omfang.

`@inebotten hjelp varsler` viser varselkontrollene. Påminnelse- og avstemningslister viser bare sider som finnes, med Forrige og Neste når de er tilgjengelige.
