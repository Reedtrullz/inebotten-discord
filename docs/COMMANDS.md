# Kommandooversikt

Tagg Inebotten for å kjøre en kommando. Eksemplene følger den sentrale katalogen.
Område og rettigheter kontrolleres ved faktisk kjøring; forhåndsvisning kjører ingen handler.

| Intent | Eksempler | Virkning | Område | Beskrivelse |
| --- | --- | --- | --- | --- |
| help | `hjelp` | read | invocation | Vis kommandohjelp |
| status | `bot status` | read | invocation | Vis drift og relevante avvik |
| profile | `status online` | write | controller | Endre egen Discord-profil |
| calendar_help | `hjelp kalender` | read | calendar | Vis kalenderhjelp |
| calendar_list | `kalender` | read | calendar | Vis kommende kalender med område og ID |
| calendar_sync | `synk`<br>`synk konflikt <ID> lokal`<br>`bekreft synk <ID>` | write | calendar | Synkroniser eller gjennomgå konflikt |
| calendar_delete | `slett #<ID> i kalender` | write | calendar | Forhåndsvis sletting av valgt ID |
| calendar_complete | `ferdig #<ID> i kalender` | write | calendar | Fullfør valgt kalenderpunkt |
| calendar_edit | `kalender endre #<ID> tittel: Ny tittel` | write | calendar | Endre valgt kalenderpunkt |
| calendar_search | `søk kalender møte` | read | calendar | Søk i tillatt kalenderområde |
| calendar_clear | `slett alt i kalender`<br>`bekreft kalender <token>`<br>`angre kalender <token>` | write | calendar | Forhåndsvis flere slettinger eller lokal angre |
| calendar_item | `møte i morgen kl 14` | write | calendar | Tolk og opprett kalenderpunkt |
| calendar_exchange | `kalender eksporter ics alle`<br>`kalender importer ics`<br>`bekreft ics <token>` | mixed | calendar | Eksporter ICS eller forhåndsvis en vedlagt import |
| workflow | `oppskrift ny forbered budsjett 10`<br>`oppskrift på <ID>`<br>`oppskrift pause <ID>`<br>`oppskrift vurder <ID> <KALENDER-ID>`<br>`oppskrift bekreft <token>`<br>`oppskrift historikk <ID>`<br>`oppskrift vis` | mixed | calendar | Tillatte oppskrifter med gjennomgang og eksplisitt bekreftelse |
| planning | `planlegg Film \| 04.01.2027 18:00 / 05.01.2027 18:00 \| 120`<br>`plan stem <ID> 1`<br>`plan vurder <ID>`<br>`plan velg <ID> 1 varsle her`<br>`plan bekreft <ID> <token>`<br>`plan rsvp <ID> ja synlighet arrangør`<br>`plan vis <ID>`<br>`plan avbryt <ID>` | mixed | calendar | Planlegg én gruppeaktivitet med arrangørbekreftelse |
| calendar_auth | `kalender auth` | write | controller | Start eller fullfør Google-innlogging |
| reminder_edit | `endre påminnelse 1 tekst: Ny tekst` | write | calendar | Endre påminnelse |
| reminder_delete | `slett påminnelse 1` | write | calendar | Slett påminnelse |
| reminder_search | `søk påminnelse handle` | read | calendar | Søk i påminnelser |
| reminder_create | `påminnelse kjøp melk` | write | calendar | Opprett påminnelse |
| reminder_list | `vis påminnelser` | read | calendar | Vis aktive påminnelser |
| reminder_complete | `ferdig påminnelse 1` | write | calendar | Fullfør påminnelse |
| poll_create | `poll Pizza / Burger` | write | channel | Opprett avstemning |
| poll_vote | `1` | write | channel | Stem i aktiv avstemning |
| poll_edit | `endre poll 1 spørsmål: Nytt spørsmål` | write | poll_owner | Rediger egen poll; bekreft stemmeresett |
| poll_delete | `slett poll 1` | write | poll_owner | Slett egen avstemning |
| poll_close | `lukk poll 1` | write | poll_owner | Lukk egen avstemning |
| poll_list | `vis poll`<br>`poll resultater` | read | channel | Vis aktive eller avsluttede resultater |
| countdown | `hvor lenge til jul` | read | invocation | Vis nedtelling |
| watchlist | `hva skal vi se` | mixed | channel | Administrer film- og serieliste |
| word_of_day | `dagens ord` | read | invocation | Vis dagens ord |
| quote | `sitat` | mixed | channel | Hent eller lagre sitat |
| quote_list | `vis sitater` | read | channel | Vis sitater |
| quote_edit | `endre sitat 1 Ny tekst` | write | channel | Endre eget sitat |
| quote_delete | `slett sitat 1` | write | channel | Slett eget sitat |
| aurora | `nordlys` | provider | invocation | Vis nordlysvarsel med alder og kilde |
| school_holidays | `skoleferie Trondheim 2026-2027` | read | invocation | Vis kildebelagt skolerute og dekning |
| price | `hva koster bitcoin` | provider | invocation | Vis markedsdata med kilde og alder |
| horoscope | `horoskop væren` | read | invocation | Vis horoskop |
| compliment | `kompliment` | read | invocation | Gi et kompliment |
| calculator | `2+2` | read | invocation | Beregn eller konverter med eksplisitt grunnlag |
| shorten_url | `forkort https://example.com/side` | provider | invocation | Forkort offentlig URL |
| daily_digest | `daglig oppsummering` | provider | invocation | Vis dagens valgte oversikt |
| birthday_edit | `endre bursdag Ola 15.05` | write | channel | Endre bursdagsoppføring |
| set_location | `jeg bor i Oslo` | write | self | Lagre eget stedsvalg |
| memory_view | `vis minnet mitt`<br>`minne læring på`<br>`minne del med ingen`<br>`minne private fakta av`<br>`minne behold tema 7 dager`<br>`minne kommune oslo`<br>`varsler på`<br>`varsler av`<br>`varsler status`<br>`varsler tidssone Europe/Oslo`<br>`varsler forvarsel 30,10,0 minutter`<br>`varsler stille 22:00-07:00`<br>`varsler morgen 09:00`<br>`varsler kort kalender,vær`<br>`slumre #<ID> 10 minutter` | mixed | self | Vis minne og velg egne varsler |
| memory_export | `eksporter minnet mitt`<br>`eksporter minnet mitt privat` | read | self | Eksporter eget minne privat som komplett JSON |
| memory_delete | `slett minnet mitt bekreft` | write | self | Bekreft lokal sletting av eget minne |
| search | `søk på nett Oslo` | provider | invocation | Søk offentlig informasjon |
| dashboard | `vis dashboard` | provider | invocation | Vis forespurt oversikt |
| ai_chat | `hei` | provider | invocation | Svar med konfigurert AI |
