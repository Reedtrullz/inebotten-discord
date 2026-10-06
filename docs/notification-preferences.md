# Egne varsler og oversiktskort

Uten egen profil beholdes eksisterende legacy-varsler i opprinnelig kanal:
30 minutter før, ved start/frist og like etter start/frist, samt kalenderens
morgenoversikt i 09–10-vinduet. Ingen nye abonnenter opprettes automatisk.
En egen profil erstatter disse varslene for den aktuelle brukeren og området.
En pauset profil stopper også brukerens legacy-varsler.

Valg gjøres med en vanlig autorisert invokasjon og gjelder avsenderen i det
aktuelle kalenderområdet. `varsler på` velger uttrykkelig denne kanalen;
annen mottaker eller kanal-ID kan ikke settes i kommandoen. Privat område
krever direktemelding til riktig bruker. Gruppens medlemskap og godkjente
kanaler kontrolleres på nytt når bakgrunnsjobben kjører. Destinasjon som
forsvinner gir ingen offentlig reservelevering eller provider-kall for digest.

- `varsler på`, `varsler av`, `varsler status`
- `varsler forvarsel 30,10,0 minutter` (maks åtte verdier, 0–1440)
- `varsler stille 22:00-07:00`, `varsler stille av`
- `varsler morgen 09:00`, `varsler morgen av`
- `varsler tidssone Europe/Oslo` (gyldig IANA-navn)
- `varsler kort kalender,vær` (dato, kalender, vær, bursdager, marked, nordlys, vaktliste)
- `slumre #<ID> 10 minutter` (egen aktiv oppføring, 1–1440 minutter)

Nye profiler er pauset til et uttrykkelig `varsler på`. Et lagret morgenvalg
starter ikke et abonnement alene. Profiler beholdes per bruker/område,
slumring beholder oppførings-ID, forekomstidentitet og et UTC-tidspunkt.
Flyttet/avsluttet/slettet forekomst blir ikke erstattet med en annen oppføring.
Mislykket lagring gir ingen bekreftelse. Ukjent transportaksept beholdes uten
automatisk ny sending; bekreftet slumring fjernes først etter meldingskvittering.
Pause/endret profil under provider- eller kvoteventing kontrolleres før sending.

Stille timer tolkes i profilens IANA-tidssone (standard Europe/Oslo), også
over midnatt. Slutten på en manglende DST-time flyttes til første reelle minutt;
ved gjentatt time velges første slutt som fortsatt er fremtidig. Forvarsel
utsatt til etter hendelsesstart hoppes over. Slumring kan leveres etter start.
Profiljobben har en samlet monoton frist på ti sekunder, delte sendekvoter og
et femminutters leveringsvindu. Store klokkehopp eller lang nedetid gir ingen
oppsamlet masseutsending av gamle varsler. Eksisterende legacy-vinduer beholdes.

En hendelse merkes «ferdig» bare når en kjent varighet faktisk har utløpt.
Ukjent slutt gir «starttidspunktet er passert», og en påminnelse sier «fristen
er passert» uten å påstå at oppgaven er fullført.

Forespurt og profilens morgenoversikt bruker samme kortkode. Bare valgte
providers kalles; et utilgjengelig kort bevarer de øvrige kortene. Lokal
kalender/bursdagsliste/vaktliste merkes som lokale. Vær og nordlys beholder
eksisterende kilde-/gyldighetsmerking. Marked er CoinGecko og oppgir at hentet/
gyldig tidspunkt ikke er dokumentert. Lagret privat sted brukes bare i egen
direktemelding, ellers brukes det offentlige standardstedet Oslo. En digest er
en begrenset oversikt, ikke en komplett dataeksport. Uten eget kortvalg beholdes
forespurt oversikts eksisterende korttyper. Private eller gruppeområder får
ikke automatisk omklassifisert legacy-data.

Testene bruker syntetiske lagre, falske kvitteringer og eksplisitte klokker.
Ingen ekte abonnement, Discord-sending eller brukerlager er endret. Eierens
valg av tider, kanal og kort samt faktisk transport er fortsatt manuell aksept.
