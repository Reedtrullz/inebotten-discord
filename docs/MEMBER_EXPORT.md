# Manuell lokal medlemseksport

Eieren valgte 5. oktober 2026 å beholde det eksisterende verktøyet som en herdet, manuell lokal funksjon. Originalfilene i den primære arbeidskopien og eksisterende data er bevart. Dette er ingen botkommando, abonnement eller bakgrunnsjobb.

Kjøring krever eksplisitt forventet konto-ID, én tilgjengelig guild (ID anbefales), privat POSIX-utdatamappe, `.csv`-sti, radgrense, samlet utbytegrense og tidsbudsjett. Maksimum er 100 000 rader, 16 MiB og 300 sekunder. Autentisering importeres først etter argumentkontroll. Kontoidentiteten må samsvare før innhenting; tvetydige guildnavn avvises. Ingen invite-/join-funksjon finnes. Verktøyet trenger den eksisterende brukerkonto-profilen; den separate botprofilen støtter ikke denne funksjonen.

```sh
python scripts/export_members.py --guild-id REVIEWED_GUILD_ID \
  --account-id EXPECTED_ACCOUNT_ID --out /private/reviewed-export/members.csv \
  --max-rows 1000 --max-bytes 1048576 --timeout 30
```

REST-paginering bruker eksisterende klient og dens Retry-After-håndtering, et samlet deadline og maksimalt fem sidekall per sekund. Gjentatt/ikke-økende cursor, ugyldig side, rad-/bytegrense og feil avslutter med synlig årsak. `coverage=complete` betyr terminal REST-side og samsvar med guildobjektets rapporterte medlemstall; dette sertifiserer ikke en uavhengig folketelling eller tilgang til skjulte medlemmer. Avvik er `partial` eller `unknown`. `--allow-partial` er nødvendig før ufullstendige rader kan skrives. `--allow-cached-fallback` kan bruke allerede mellomlagrede medlemmer etter REST-feil; den utfører aldri gateway-scraping og merkes alltid ufullstendig.

JSON bevarer råverdier og inkluderer kilde, scope, coverage, count og truncation_reason. CSV og søsken-JSON opprettes eksklusivt med modus 0600 i en privat, symlinkfri mappe. Begge filene bindes til en åpnet mappeidentitet; eksisterende stier avvises. `.json` som hovedsti avvises. Ved en kollisjon/skrivefeil bevares eventuelle nye delvise filer som privat feilevidens; ingen fil slettes eller overskrives.

CSV prefikser ID-er med apostrof for å unngå bevisst numerisk konvertering av Discord-snowflakes. Formellignende tekst og innledende tab/linjeskift får også et tekstprefiks. Syntetisk CSV-lesing bekrefter prefikset og JSONs råverdier. Dette er **ikke** verifikasjon av Excel/Numbers/LibreOffice-import eller alle formelvarianter. Velg tekstkolonner ved import og bruk JSON som tapsfri kilde. Aksept i valgte regnearklesere gjenstår.

Fixturetester dekker identitetsavvik, navnetvetydighet, gjentatt cursor, deadline, REST-feil/cache, rad-/bytegrenser, private filer, eksisterende/symlink-kollisjoner, samme utvidelse og formellignende tekst. Ingen ekte guild, medlemseksport, token, kontoendring eller installasjon ble brukt.
