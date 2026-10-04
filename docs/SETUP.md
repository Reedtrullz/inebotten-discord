# Local setup

Use Python 3.12 or newer in an isolated virtual environment. From the project directory:

```bash
python3 -m venv .venv312
.venv312/bin/python -m pip install -r requirements.txt
.venv312/bin/python setup.py
.venv312/bin/python scripts/run_both.py
```

On Windows, use `.venv312\Scripts\python.exe` in place of `.venv312/bin/python`. The legacy `utils/setup.py` entry point only prints this venv workflow; it no longer installs packages. The interactive wizard never installs packages into the active interpreter or suggests `--break-system-packages`.

The wizard hides Discord and OpenRouter credential input. Discord authentication supports `DISCORD_USER_TOKEN`; `DISCORD_EMAIL` and `DISCORD_PASSWORD` are rejected. Setup changes are validated before saving and update only the selected keys, preserving comments, unrelated settings, allowlists, console configuration, Google Calendar configuration, and credentials that were not changed.

When `HERMES_HOME` is set to a non-empty path, it is authoritative: setup reads or writes only `$HERMES_HOME/discord/.env`, including when the path contains spaces. It does not fall back to a project `.env` if that file is missing. With `HERMES_HOME` unset, the command-line wizard uses the project `.env`. Desktop launchers use the canonical Hermes settings file and start the bot with that Hermes home explicitly set.

The shared writer creates a same-directory temporary file with mode `0600` before writing, flushes it, and atomically replaces `.env`. On POSIX systems the settings directory is created with mode `0700`. If setup is interrupted before replacement, the previous `.env` remains intact; run setup again to complete the update. If interruption leaves a hidden `.env.*.tmp` file, stop setup and the bot before removing only that temporary file. A failure while writing reports a generic message and never prints submitted credentials.

The web console accepts settings updates at authenticated `POST /api/setup/settings`. Existing API-key, browser-session, and configured Cloudflare Access authentication checks apply. Invalid settings return field/reason errors without submitted values.

For offline checks, use the isolated runner with a Python 3.12 environment:

```bash
python scripts/run_offline_tests.py --python .venv312/bin/python -- tests/test_config_roundtrip.py -q
```


Verdier i `.env` behandles som bokstavelig tekst, også `${…}` i en nøkkel; oppsettet utfører ingen variabelinterpolering. Endring av ett felt bevarer andre felter, kommentarer og linjeskift. En valgt OpenRouter-provider beholdes selv når API-nøkkelen mangler; oppsett/status skal vise det manglende feltet, uten å bytte provider i skjul. URL-felt avviser ugyldige URL-er og innbakte brukernavn/passord uten å vise den innsendte verdien. Source-launcherne finner prosjektmodulene også når de startes fra en annen katalog. Faktisk Tk-visning, signerte bundles og macOS/Windows-prosesslivsløp krever egne I31/I22-prøver.


Kalenderområdet og invokasjonsmodus velges nå separat i CLI-oppsettet. Se [kalendertilgang](calendar-access.md) for felt, tom-listesemantikk, eier/medlemsregler og preview før flytting. Desktop viser samme forklaring i oppsettsloggen; bruk CLI eller den validerte settings-ruten for å endre disse feltene. Eksisterende delte data forblir delt også når et nytt privat område velges.
