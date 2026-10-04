# AI-utfall og utkast

Begge leverandører returnerer AIResult med success, busy, cancelled, auth_error, retryable eller unavailable. Hver tilkobling tillater høyst to samtidige forespørsler uten ventekø. Fristen bruker monotontid. Svar etter fristen blir ikke publisert; arbeid som motsetter seg avbrudd beholder plassen til det avsluttes. HTTP-konvolutten begrenses til 128 KiB før JSON tolkes, og svarteksten til 20 000 tegn. Ugyldig JSON eller tom tekst er ikke et vellykket AI-svar.

Lokalt valg eskalerer ikke til skyen. Bare eksplisitt deklarert OpenRouter-til-lokal reserve støttes av fabrikkgrensesnittet; vanlig konfigurasjon aktiverer ingen reserve automatisk. Autorisasjonsfeil og avbrudd utløser ikke reserve. Et reservesvar merkes med faktisk leverandør og modell. Modellisting dokumenterer bare tilgjengelig API, ikke vellykket inferens.

Modellens kalenderhandlinger er avgrensede, tillatte utkast. De skriver ikke til kalenderen eller kjører verktøy; brukeren må sende den viste kalenderkommandoen, som valideres av kalenderens vanlige parser og datomodell. Feil i en domenekommando gir kommandofeil i stedet for generisk AI-chat.

Verifikasjonen bruker syntetiske svar og offline tester. Ingen ekstern inferens eller endring av konto-/tjenesteoppsett er utført.
