# Inebotten - Utviklerguide

> Guide for utviklere som vil bidra til eller utvide Inebotten

---

## 📋 Innholdsfortegnelse

1. [Komme i Gang](#komme-i-gang)
2. [Legge til ny funksjon](#legge-til-ny-funksjon)
3. [Kode-stil](#kode-stil)
4. [Test](#test)
5. [Vanlige Mønstre](#vanlige-mønstre)
6. [Debug-tips](#debug-tips)
7. [Git-workflow](#git-workflow)
8. [Nyttige Kommandoer](#nyttige-kommandoer)

---

## Komme i Gang

### Utviklingsmiljø

```bash
# 1. Klon repoet
git clone https://github.com/Reedtrullz/inebotten-discord.git
cd inebotten-discord

# 2. Lag virtuelt miljø
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Installer avhengigheter
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 4. Kopier og konfigurer miljø
cp .env.example .env
# Rediger .env med dine verdier

# 5. Verifiser oppsett
python3 -m py_compile *.py
python3 tests/test_selfbot.py
```

### Prosjektstruktur

```
inebotten-discord/
├── ai/                     # AI-komponenter
│   ├── hermes_bridge_server.py
│   ├── hermes_connector.py
│   └── response_generator.py
├── cal_system/             # Kalendersystem
│   ├── calendar_manager.py
│   ├── natural_language_parser.py
│   └── google_calendar_manager.py
├── core/                   # Kjernekomponenter
│   ├── message_monitor.py
│   ├── rate_limiter.py
│   └── config.py
├── features/               # Funksjons-managers
│   ├── weather_api.py
│   ├── poll_manager.py
│   └── ...
├── memory/                 # Personlighetssystem
│   ├── user_memory.py
│   └── conversation_context.py
├── docs/                   # Dokumentasjon
└── tests/                  # Tester
```

---

## Legge til ny funksjon

### Steg-for-steg-guide

#### Steg 1: Lag funksjonsmanager

Opprett `features/my_feature_manager.py`:

```python
#!/usr/bin/env python3
"""
MyFeature-manager - [beskrivelse av funksjonen]
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Tuple, Optional, Dict, Any


class MyFeatureManager:
    """
    Manager for [funksjon].
    
    Ansvar:
    - [Ansvar 1]
    - [Ansvar 2]
    - [Ansvar 3]
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        """
        Initialiser MyFeatureManager.
        
        Args:
            storage_path: Sti til lagringsfil. Standard: ~/.hermes/discord/data/my_feature.json
        """
        if storage_path is None:
            storage_path = Path.home() / '.hermes' / 'discord' / 'data' / 'my_feature.json'
        
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load_data()
    
    def _load_data(self) -> Dict[str, Any]:
        """Last data fra lagring."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"[MYFEATURE] Advarsel: Kunne ikke laste data: {e}")
                return {}
        return {}
    
    def _save_data(self) -> None:
        """Lagre data til disk."""
        try:
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except IOError as e:
            print(f"[MYFEATURE] Feil: Kunne ikke lagre data: {e}")
    
    def add_item(self, guild_id: str, user_id: str, content: str) -> Tuple[bool, str]:
        """
        Legg til nytt element.
        
        Args:
            guild_id: Discord guild ID
            user_id: Discord bruker ID
            content: Innhold å legge til
        
        Returns:
            (suksess: bool, melding: str)
        """
        guild_key = str(guild_id)
        
        if guild_key not in self.data:
            self.data[guild_key] = []
        
        item = {
            "id": len(self.data[guild_key]) + 1,
            "content": content,
            "created_by": user_id,
            "created_at": datetime.now().isoformat()
        }
        
        self.data[guild_key].append(item)
        self._save_data()
        
        return True, f"Lagt til: {content}"
    
    def list_items(self, guild_id: str) -> str:
        """
        Formater liste for visning.
        
        Args:
            guild_id: Discord guild ID
        
        Returns:
            Formatert streng for Discord
        """
        guild_key = str(guild_id)
        
        if guild_key not in self.data or not self.data[guild_key]:
            return "📋 **Min Feature**\nIngen elementer funnet."
        
        lines = ["📋 **Min Feature:**"]
        for item in self.data[guild_key][:10]:
            lines.append(f"{item['id']}. {item['content']}")
        
        return "\n".join(lines)


def parse_my_feature_command(content: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Parse feature-kommando fra melding.
    
    Args:
        content: Meldingsinnhold (uten bot mention)
    
    Returns:
        (handling, parametere) eller None hvis ikke match
    """
    content_lower = content.lower().strip()
    
    # Match mønstre som "myfeature add ...", "myfeature list", etc.
    if content_lower.startswith('myfeature '):
        parts = content_lower.split(maxsplit=2)
        
        if len(parts) < 2:
            return None
        
        action = parts[1]  # "add", "list", "remove", etc.
        rest = parts[2] if len(parts) > 2 else ""
        
        return action, {"content": rest}
    
    return None


# Singleton instans
_my_feature_manager: Optional[MyFeatureManager] = None


def get_my_feature_manager() -> MyFeatureManager:
    """Hent eller opprett singleton MyFeatureManager instans."""
    global _my_feature_manager
    if _my_feature_manager is None:
        _my_feature_manager = MyFeatureManager()
    return _my_feature_manager
```

#### Steg 2: Lag Handler (Ny Arkitektur)

Opprett `features/my_feature_handler.py`:

```python
#!/usr/bin/env python3
"""
MyFeatureHandler - Håndterer myfeature-kommandoer
"""

from typing import Optional, Dict, Any, Tuple
from features.base_handler import BaseHandler
from features.my_feature_manager import MyFeatureManager, parse_my_feature_command


class MyFeatureHandler(BaseHandler):
    """
    Handler for myfeature-kommandoer.
    
    Arver fra BaseHandler for å få:
    - send_response(): Unified DM/Group/Guild replies
    - get_guild_id(): DM-safe guild ID extraction
    - extract_number(): Parse numbers fra meldinger
    - log(): Structured logging
    """
    
    def __init__(self, monitor):
        super().__init__(monitor)
        self.my_feature = MyFeatureManager()
        self.parse_my_feature_command = parse_my_feature_command
    
    async def handle_my_feature(self, message, parsed: Tuple[str, Dict[str, Any]]) -> None:
        """
        Håndter myfeature-kommandoer.
        
        Args:
            message: Discord meldingsobjekt
            parsed: (handling, parametere) tuple fra parser
        """
        try:
            action, params = parsed
            guild_id = self.get_guild_id(message)  # DM-safe!
            
            if action == 'add':
                if not params.get('content', '').strip():
                    await self.send_response(
                        message,
                        "❌ Du må skrive noe å legge til.\n"
                        "Bruk: `@inebotten myfeature add [tekst]`"
                    )
                    return
                
                success, result = self.my_feature.add_item(
                    guild_id,
                    message.author.id,
                    params['content']
                )
                
                if success:
                    await self.send_response(message, f"✅ {result}")
                else:
                    await self.send_response(message, f"❌ {result}")
            
            elif action == 'list':
                output = self.my_feature.list_items(guild_id)
                await self.send_response(message, output)
            
            else:
                await self.send_response(
                    message,
                    "❌ Ukjent kommando.\n"
                    "Bruk: `@inebotten myfeature [add/list]`"
                )
        
        except Exception as e:
            self.log(f"Kommando feil: {e}")
            await self.send_response(
                message,
                "❌ Noe gikk galt. Prøv igjen senere."
            )
```

**2.1. Registrer handler i MessageMonitor:**

I `core/message_monitor.py`, legg til i `_register_handlers()`:

```python
from features.my_feature_handler import MyFeatureHandler

self.handlers = {
    # ... eksisterende handlers ...
    "my_feature": MyFeatureHandler(self),
}
```

**2.2. Legg til intent-regel:**

Nye prompt-regler skal normalt legges i `core/intent_router.py`, ikke som en ny hardkodet sjekk i `MessageMonitor`. Routeren skal returnere én `IntentResult` med intent, confidence, payload og reason.

```python
if "myfeature" in content_lower:
    return IntentResult(
        intent=BotIntent.UTILITY,
        confidence=0.9,
        payload={"feature": "my_feature"},
        reason="Eksplisitt myfeature-kommando",
    )
```

Deretter lar `MessageMonitor` kalle riktig handler basert på router-resultatet.

**Fordeler med ny arkitektur:**
- ✅ **send_response()** håndterer automatisk DM/Group/Guild kanaler
- ✅ **Rate limiting** skjer automatisk
- ✅ **Feilhåndtering** er konsistent på tvers av alle handlere
- ✅ **Enklere testing** - kan mocke BaseHandler
- ✅ **Mindre kode** - ingen duplisert respons-håndtering
- ✅ **Strammere intent-ruting** - falske positive kan testes ett sted

#### Steg 3: Oppdater Dokumentasjon

**3.1. Legg til i `docs/DOCUMENTATION.md`:**

Finn funksjonstabellen og legg til:

```markdown
| **MyFeature** | `features/my_feature_manager.py` | `@inebotten myfeature [add/list]` |
```

**3.2. Legg til i `docs/QUICK_REFERENCE.md`:**

Finn "Andre kommandoer"-tabellen og legg til:

```markdown
| MyFeature | `@inebotten myfeature add [tekst]` |
```

#### Steg 4: Test

```bash
# Syntaks-sjekk
python3 -m py_compile features/my_feature_manager.py
python3 -m py_compile core/message_monitor.py
python3 -m py_compile core/intent_router.py

# Enhetstest
python3 -c "
from features.my_feature_manager import MyFeatureManager, parse_my_feature_command
import tempfile

# Test parser
result = parse_my_feature_command('myfeature add test data')
assert result is not None
assert result[0] == 'add'
print('✓ Parser test passed')

# Test manager
with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
    temp_path = f.name

fm = MyFeatureManager(temp_path)
success, msg = fm.add_item('guild1', 'user1', 'test')
assert success
print('✓ Manager test passed')

print('\n✅ All tests passed!')
"

# Integrasjonstest
python3 run_both.py
# I Discord: "@inebotten myfeature add test"
```

Legg også inn minst én positiv og én negativ case i `tests/test_intent_router.py`.

#### BaseHandler Referanse

**Tilgjengelige metoder i alle handlers:**

| Metode | Beskrivelse | Eksempel |
|--------|-------------|----------|
| `send_response(message, content)` | Send svar (håndterer DM/Group/Guild) | `await self.send_response(msg, "Hei!")` |
| `get_guild_id(message)` | Hent guild ID (DM-safe) | `guild_id = self.get_guild_id(msg)` |
| `extract_number(content)` | Hent første tall fra melding | `num = self.extract_number(msg.content)` |
| `check_rate_limit()` | Sjekk rate limit | `can_send, reason = await self.check_rate_limit()` |
| `wait_if_needed()` | Vent på rate limit | `await self.wait_if_needed()` |
| `get_channel_type(channel)` | Hent kanaltype | `ch_type = self.get_channel_type(msg.channel)` |
| `log(message)` | Logg med handler-navn | `self.log("Behandlet kommando")` |

---

## Kode-stil

### Navngiving

| Type | Konvensjon | Eksempel |
|------|------------|----------|
| Klasser | PascalCase | `CalendarManager` |
| Funksjoner | snake_case | `parse_event` |
| Konstanter | UPPER_CASE | `MAX_ITEMS` |
| Private | _leading_underscore | `_load_data` |
| Type hints | Alltid bruk | `def func(x: str) -> int:` |

### Dokumentasjon

```python
def calculate_next_occurrence(
    date_str: str,
    recurrence: str,
    recurrence_day: Optional[str] = None
) -> Optional[str]:
    """
    Beregn neste forekomst av et gjentagende event.
    
    Args:
        date_str: Dato på formatet "DD.MM.YYYY"
        recurrence: Gjentagelsestype ("weekly", "monthly", "yearly")
        recurrence_day: Ukedag for ukentlige events ("Monday", etc.)
    
    Returns:
        Neste dato som "DD.MM.YYYY" eller None hvis ugyldig
    
    Raises:
        ValueError: Hvis datoformat er ugyldig
    
    Example:
        >>> calculate_next_occurrence("25.03.2026", "weekly", "Monday")
        "30.03.2026"
    """
```

### Feilhåndtering

```python
try:
    result = risky_operation()
except SpecificError as e:
    print(f"[FEATURE] Spesifikk feil: {e}")
    return False, "Bruker-vennlig feilmelding"
except Exception as e:
    print(f"[FEATURE] Uventet feil: {e}")
    import traceback
    traceback.print_exc()
    return False, "Noe gikk galt"
```

### Norsk Tekst

> Botten snakker norsk til brukere, men kode er på engelsk:

```python
# ✅ Godt
error_message = "Fant ikke noe med det nummeret."  # Bruker ser norsk

# ❌ Dårlig
error_message = "Item not found with that number."  # Blanding av språk
```

---

## Test

### Enhetstest-mal

```python
#!/usr/bin/env python3
"""Tester for my_feature_manager.py"""

import sys
import os
import tempfile
from pathlib import Path

# Legg til foreldremappe i path
sys.path.insert(0, str(Path(__file__).parent.parent))

from features.my_feature_manager import MyFeatureManager, parse_my_feature_command


def test_parse_command():
    """Test kommando-parsing."""
    # Skal matche
    result = parse_my_feature_command("myfeature add test data")
    assert result is not None, "Skal matche 'myfeature add ...'"
    assert result[0] == "add"
    assert result[1]["content"] == "test data"
    
    # Skal ikke matche
    result = parse_my_feature_command("noe annet")
    assert result is None, "Skal ikke matche 'noe annet'"
    
    print("✓ parse_my_feature_command tester bestått")


def test_manager():
    """Test feature manager operasjoner."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_path = f.name
    
    try:
        fm = MyFeatureManager(temp_path)
        
        # Test legg til
        success, result = fm.add_item("guild1", "user1", "test data")
        assert success is True, "Legg til skal lykkes"
        assert "test data" in result
        
        # Test formatering
        output = fm.list_items("guild1")
        assert "test data" in output, "Data skal vises i liste"
        
        print("✓ MyFeatureManager tester bestått")
    
    finally:
        os.remove(temp_path)


def test_edge_cases():
    """Test grensetilfeller."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_path = f.name
    
    try:
        fm = MyFeatureManager(temp_path)
        
        # Tom liste
        output = fm.list_items("guild1")
        assert "Ingen elementer" in output
        
        # Tomt innhold
        success, result = fm.add_item("guild1", "user1", "")
        assert success is True  # Aksepterer tomt, men sjekk i handler
        
        print("✓ Edge case tester bestått")
    
    finally:
        os.remove(temp_path)


if __name__ == "__main__":
    test_parse_command()
    test_manager()
    test_edge_cases()
    print("\n🎉 Alle tester bestått!")
```

### Kjøre Tester

```bash
# Kjør alle tester
python3 tests/test_selfbot.py

# Kjør spesifikk test
python3 tests/test_my_feature.py

# Med pytest
pytest tests/ -v

# Coverage
pytest tests/ --cov=. --cov-report=html
```

---

## Vanlige Mønstre

### Singleton Pattern

```python
_manager: Optional[Manager] = None

def get_manager() -> Manager:
    global _manager
    if _manager is None:
        _manager = Manager()
    return _manager
```

### Lagringsmønster

```python
def _load(self) -> Dict:
    """Last data fra fil."""
    if self.path.exists():
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}

def _save(self) -> None:
    """Lagre data til fil."""
    try:
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
    except IOError as e:
        print(f"[ERROR] Kunne ikke lagre: {e}")
```

### Kommando Handler Pattern

```python
async def _handle_command(self, message: discord.Message):
    """Håndter kommando med standard feilhåndtering."""
    try:
        guild_id = message.guild.id if message.guild else message.channel.id
        content = message.content
        
        # Parse kommando
        parsed = parse_command(content)
        if not parsed:
            return
        
        # Utfør
        success, result = self.manager.action(guild_id, parsed)
        
        # Svar
        if success:
            await message.reply(f"✅ {result}", mention_author=False)
        else:
            await message.reply(f"❌ {result}", mention_author=False)
    
    except Exception as e:
        print(f"[ERROR] {e}")
        await message.reply("❌ Feil", mention_author=False)
```

### Modular Handler Pattern (Anbefalt)

Prosjektet bruker nå et modulært handler-mønster. Hver feature har sin egen Handler-klasse:

**Struktur:**
```
features/
├── _base.py           # BaseCog (arv for fremtidig bruk)
├── _loader.py         # Cog loader (reservert)
├── *_handler.py       # Handler-klasser (10 stk)
└── *_manager.py      # Manager-klasser (20+ stk)
```

**Eksempel - Legge til ny Handler:**

1. Opprett `features/my_handler.py`:

```python
class MyHandler:
    def __init__(self, monitor):
        self.monitor = monitor
        self.my_manager = monitor.my_manager
        self.loc = monitor.loc
    
    async def handle_my_command(self, message, parsed):
        try:
            result = self.my_manager.do_something(parsed)
            await message.reply(f"✅ {result}", mention_author=False)
            self.monitor.rate_limiter.record_sent()
            self.monitor.response_count += 1
        except Exception as e:
            print(f"[MY_HANDLER] Error: {e}")
```

2. Registrer i `message_monitor.py` `_register_handlers()`:

```python
def _register_handlers(self):
    from features.my_handler import MyHandler
    self.handlers["my_feature"] = MyHandler(self)
```

3. Kall i `handle_message()` med hasattr-mønster:

```python
my_handler = self.handlers.get("my_feature")
if my_handler:
    await my_handler.handle_my_command(message, parsed)
else:
    await self._handle_my_command(message, parsed)  # fallback
```

**Eksisterende Handlers:**
| Handler | Fil | Metoder |
|---------|------|---------|
| FunHandler | fun_handler.py | word_of_day, quote, horoscope, compliment |
| UtilityHandler | utility_handler.py | calculator, price, shorten |
| CountdownHandler | countdown_manager.py | countdown |
| PollsHandler | polls_handler.py | poll, vote |
| CalendarHandler | calendar_handler.py | calendar_item, list, delete, complete, edit |
| WatchlistHandler | watchlist_manager.py | watchlist |
| AuroraHandler | aurora_forecast.py | aurora |
| SchoolHolidaysHandler | school_holidays.py | school_holidays |
| HelpHandler | help_handler.py | help |
| DailyDigestHandler | daily_digest_manager.py | daily_digest |

---

## Debug-tips

### 1. Enable Debug Logging

```python
# I din feature
print(f"[MYFEATURE] Debug: variable={value}")
```

### 2. Test i Isolasjon

```python
# Test kun din feature
python3 -c "
from features.my_feature_manager import MyFeatureManager
fm = MyFeatureManager('/tmp/test.json')
print(fm.add_item('g1', 'u1', 'test'))
"
```

### 3. Sjekk Lagring

```bash
# Vis lagrede data
cat ~/.hermes/discord/data/my_feature.json | python3 -m json.tool

# Sjekk filrettigheter
ls -la ~/.hermes/discord/data/
```

### 4. Trace Meldingsflyt

Se konsoll-output:
```
[MONITOR] Mention detected...
[MONITOR] Matched: myfeature command
[MONITOR] MyFeature command error: ...
```

### 5. Bruk Python Debugger

```python
# Sett breakpoint
import pdb; pdb.set_trace()

# Eller bruk breakpoint() i Python 3.7+
breakpoint()
```

---

## Git-workflow

```bash
# Før du gjør endringer
git status
git diff

# Lag ny branch
git checkout -b feature/my-new-feature

# Gjør endringer
# ... rediger filer ...

# Test
python3 -m py_compile features/my_feature_manager.py
python3 -m py_compile features/my_feature_handler.py
python3 test_my_feature.py

# Commit
git add features/my_feature_manager.py features/my_feature_handler.py core/message_monitor.py
git commit -m "Add feature: My Feature

- Kan gjøre X
- Kan gjøre Y
- Oppdatert dokumentasjon"

# Push og lag PR
git push -u origin feature/my-new-feature
# Lag PR på GitHub
```

---

## Nyttige Kommandoer

```bash
# Finn alle TODOs
grep -r "TODO" features/ core/ ai/

# Sjekk filstørrelser
ls -lh features/*.py core/*.py

# Tell kodelinjer
wc -l features/*.py core/*.py

# Finn imports
grep "^import\|^from" core/message_monitor.py

# Test all syntaks
for f in features/*.py core/*.py; do
    python3 -m py_compile "$f" && echo "✓ $f"
done

# Formater JSON
cat data/calendar.json | python3 -m json.tool

# Sjekk for hardkodede tokens
grep -r "MTQ3\|discord_token" --include="*.py" .

# Se endringer
git diff --stat
git log --oneline -10
```

---

## Beste praksis

### ✅ Gjør

- Skriv tester for ny funksjonalitet
- Oppdater dokumentasjon
- Bruk type hints
- Håndter feil graceful
- Logg viktige hendelser
- Følg eksisterende mønstre
- Test i Discord før commit

### ❌ Ikke Gjør

- Hardkod tokens eller passord
- Break eksisterende funksjonalitet
- Ignorer feilmeldinger
- Gjør for store endringer i én commit
- Glem å oppdatere dokumentasjon
- Bruk engelsk i brukervendte meldinger

---

## Få Hjelp

- 📖 [Komplett Dokumentasjon](DOCUMENTATION.md)
- 🏗️ [Systemarkitektur](ARCHITECTURE.md)
- 📋 [Hurtigreferanse](QUICK_REFERENCE.md)
- 💬 [GitHub Discussions](../../discussions)
- 🐛 [Rapporter Bug](../../issues/new?template=bug_report.md)

---

<p align="center">
  <a href="DOCUMENTATION.md">📖 Dokumentasjon</a> &nbsp;•&nbsp;
  <a href="ARCHITECTURE.md">🏗️ Arkitektur</a> &nbsp;•&nbsp;
  <a href="QUICK_REFERENCE.md">📋 Hurtigreferanse</a> &nbsp;•&nbsp;
  <a href="../README.md">⬅️ Tilbake til README</a>
</p>
