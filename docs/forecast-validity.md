# Varsler med kilde og gyldighet

Dashbord og dagsoversikt deler monitorens `ForecastService`. Værvarselet viser MET Norway som kilde og en varseltid; feil vises som utilgjengelige data. Tidligere cache kan vises som utdatert ved en mislykket oppdatering, maksimalt én time fra vellykket henting. Manglende temperatur gjør svaret utilgjengelig. Manglende maksimum/minimum, fuktighet, vind og symbol blir ikke erstattet med gjetninger.

Steder velges fra de eksisterende norske byene, aliasene Tromso/Bodo/Alesund eller et navn med validerte koordinater. Et ukjent sted gir en konkret feilmelding; det erstattes ikke stille med Oslo. Uten valgt sted brukes eksisterende standard Oslo og navnet vises i svaret. Ingen ekstern geokoder er lagt til.

Cachealder beregnes med en monoton klokke. Kilde- og varseltider beholdes som tidssonebevisste verdier. METs tidsserie er UTC; hvert punkt og de oppgitte neste 1/6/12 timene tolkes separat. Kildeformat: [MET ForecastJSON](https://api.met.no/doc/ForecastJSON).

Nordlysadapteren godtar både tabellformat og objektformat fra [NOAAs Kp-produkt](https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json). Offsetløse `time_tag`-verdier i akkurat dette UTC-produktet tilordnes UTC, aldri maskinens lokale tid. Kp-intervallet er tre timer, som beskrevet i [NOAAs produktoversikt](https://www.spaceweather.gov/products/3-day-geomagnetic-forecast). Observed/estimated/predicted beholdes som kildekategori når oppgitt. En lokal synlighetsscore er merket heuristisk, ikke målt sannsynlighet; lokalt mørke og skydekke er ikke kjent.

Tjenesten eier klientene og har en idempotent `close()`. Full shutdown-integrasjon og endelige tellere inngår i I24. Verifikasjon her bruker syntetiske feil, cacheklokker, UTC/Oslo og DST-grenser. Ingen påstand om meteorologisk presisjon eller faktiske lokale observasjoner.
