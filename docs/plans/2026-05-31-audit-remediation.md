# Inebotten Discord Audit Remediation Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Fix the deployment blockers, red tests, and security/reliability gaps found in the 2026-05-31 audit of `inebotten-discord`.

**Architecture:** Keep the current layered architecture: Discord messages enter `core/message_monitor.py`, dispatch into `features/*Handler`, mutate manager classes in `cal_system/`, and render monitoring data through `web_console/`. Fixes should be narrow and test-first: do not change intent routing, calendar storage shape, or selfbot startup semantics unless a task explicitly says so.

**Tech Stack:** Python 3.12+, pytest/pytest-asyncio, discord.py-self, Alpine.js static frontend, Docker Compose, Ansible, PyInstaller launchers.

---

## Safety and Architecture Notes

Architecture docs read before planning:
- `AGENTS.md`
- `docs/ARCHITECTURE.md`
- `docs/SECURITY.md`
- `web_console/AGENTS.md`
- `cal_system/AGENTS.md`

Runtime heartbeat chain:
- Bot startup: `scripts/run_both.py` → `core/selfbot_runner.py` → `SelfbotClient.setup_hook()` → `MessageMonitor.setup()` → handler registration / GCal sync / console persistence / reminder checker.
- Message handling: `MessageMonitor.handle_message()` → `IntentRouter.route()` → `MessageMonitor._handle_intent()` → `features/*Handler` → managers in `cal_system/`, `features/`, `memory/`.
- Web console: `ConsoleServer.handle_request()` → `_is_authenticated()` → `StateCollector`/collector functions → `templates/base.html` + `static/app.js`.

Silent degradation risks:
- Background tasks created with `asyncio.create_task()` can fail without a visible crash.
- The web console can look healthy while auth/XSS issues remain exploitable.
- The Ansible deploy can currently continue after git-pull failure and deploy stale code.

General implementation rules:
- Use strict TDD for every code change: RED → GREEN → refactor.
- Keep one task to one small behavioral change.
- Do not run the live bot or networked application code during these tasks. Pytest/static checks only.
- Use this dependency/test wrapper unless a task states otherwise:

Plan review history:
- First static review found blockers in desktop PyInstaller path handling, web-console Secure-cookie localhost behavior, modal function naming, GCal channel backfill, and non-root Docker data migration.
- Patched those blockers, then re-reviewed.
- Final focused static review verdict: PASS. No remaining blockers in the patched sections.

```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest <target> -q
```

Final full local gate after all tasks:

```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m compileall ai cal_system core features memory utils web_console scripts mac_app windows_app
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m flake8 . --select=E9,F63,F7,F82
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest -q
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m bandit -r setup.py web_console cal_system features utils -ll
```

---

### Task 1: Make comprehensive calendar tests date-stable

**Objective:** Remove the date-sensitive failures in `tests/test_comprehensive.py` without changing production calendar behavior.

**Files:**
- Modify: `tests/test_comprehensive.py:25-26`
- Modify: `tests/test_comprehensive.py:644-722`
- Modify: `tests/test_comprehensive.py:1940-2080`

**Step 1: Verify the current RED state**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest \
  tests/test_comprehensive.py::TestCalendarNLP::test_41_calendar_crud_list \
  tests/test_comprehensive.py::TestCommandRoutingExtras::test_136_edit_event_oppdater \
  -q
```

Expected: FAIL because fixed `15.05.2026` is no longer within the `days=30` upcoming window.

**Step 2: Add a future-date helper**

Add near the imports/helpers at the top of `tests/test_comprehensive.py`:

```python
def _future_date(days_ahead: int = 14) -> str:
    return (datetime.now() + timedelta(days=days_ahead)).strftime("%d.%m.%Y")
```

**Step 3: Replace date-brittle test event dates**

Replace the `date_str="15.05.2026"` values in the calendar CRUD/list/delete blocks and command-routing-extra calendar blocks with:

```python
date_str=_future_date(14),
```

Do not replace parser tests that intentionally validate a literal date string.

**Step 4: Run targeted tests**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest \
  tests/test_comprehensive.py::TestCalendarNLP::test_40_calendar_crud_add \
  tests/test_comprehensive.py::TestCalendarNLP::test_41_calendar_crud_list \
  tests/test_comprehensive.py::TestCalendarNLP::test_42_calendar_crud_complete \
  tests/test_comprehensive.py::TestCalendarNLP::test_43_calendar_crud_delete \
  tests/test_comprehensive.py::TestCommandRoutingExtras::test_136_edit_event_oppdater \
  -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_comprehensive.py
git commit -m "test: make calendar comprehensive dates stable"
```

---

### Task 2: Fix the local test runner path

**Objective:** Make `scripts/run_tests.sh` run the real pytest suite from repo root.

**Files:**
- Modify: `scripts/run_tests.sh:5-14`

**Step 1: Verify current RED state**

Run:
```bash
bash scripts/run_tests.sh
```

Expected before fix: FAIL with `can't open file .../scripts/test_selfbot_comprehensive.py`.

**Step 2: Replace the runner body**

Replace lines 5-14 with:

```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "=========================================="
echo "INEBOTTEN AUTOMATED TEST SUITE"
echo "=========================================="
echo ""
echo "Running pytest suite..."
echo ""

python3 -m pytest tests/test_comprehensive.py -q
```

Keep the existing exit-code reporting at lines 16-25.

**Step 3: Run the runner**

Run:
```bash
bash scripts/run_tests.sh
```

Expected: it invokes pytest from repo root and exits with pytest's real status.

**Step 4: Commit**

```bash
git add scripts/run_tests.sh
git commit -m "test: fix local test runner path"
```

---

### Task 3: Add desktop launcher path regression tests

**Objective:** Prove both desktop launchers point at `scripts/run_both.py`, and PyInstaller bundles include `scripts/`.

**Files:**
- Create: `tests/test_desktop_launcher_paths.py`
- Later modify: `mac_app/launcher.py:307-322`
- Later modify: `windows_app/launcher.py:313-329`
- Later modify: `mac_app/build.sh:51-70`
- Later modify: `windows_app/build.py:42-66`

**Step 1: Create the failing test file**

Create `tests/test_desktop_launcher_paths.py`:

```python
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _install_tkinter_stub(monkeypatch):
    tk = types.ModuleType("tkinter")
    ttk = types.ModuleType("tkinter.ttk")
    messagebox = types.ModuleType("tkinter.messagebox")
    scrolledtext = types.ModuleType("tkinter.scrolledtext")
    tk.Tk = object
    tk.StringVar = object
    tk.BooleanVar = object
    tk.END = "end"
    tk.ttk = ttk
    tk.messagebox = messagebox
    tk.scrolledtext = scrolledtext
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setitem(sys.modules, "tkinter.messagebox", messagebox)
    monkeypatch.setitem(sys.modules, "tkinter.scrolledtext", scrolledtext)


def _load_module(path: Path, name: str, monkeypatch):
    _install_tkinter_stub(monkeypatch)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_bundle_root(tmp_path: Path) -> Path:
    bundle_root = tmp_path / "_MEIPASS"
    scripts_dir = bundle_root / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "run_both.py").write_text("print('ok')\n", encoding="utf-8")
    return bundle_root


def test_mac_launcher_targets_scripts_run_both_in_source_tree(monkeypatch):
    module = _load_module(ROOT / "mac_app" / "launcher.py", "mac_launcher_under_test", monkeypatch)
    assert module.get_run_both_path() == ROOT / "scripts" / "run_both.py"
    assert module.get_run_both_path().exists()


def test_windows_launcher_targets_scripts_run_both_in_source_tree(monkeypatch):
    module = _load_module(ROOT / "windows_app" / "launcher.py", "windows_launcher_under_test", monkeypatch)
    assert module.get_run_both_path() == ROOT / "scripts" / "run_both.py"
    assert module.get_run_both_path().exists()


def test_mac_launcher_targets_scripts_run_both_inside_pyinstaller_bundle(monkeypatch, tmp_path):
    module = _load_module(ROOT / "mac_app" / "launcher.py", "mac_launcher_bundle_under_test", monkeypatch)
    bundle_root = _make_bundle_root(tmp_path)
    monkeypatch.setattr(module.sys, "_MEIPASS", str(bundle_root), raising=False)
    assert module.get_run_both_path() == bundle_root / "scripts" / "run_both.py"


def test_windows_launcher_targets_scripts_run_both_inside_pyinstaller_bundle(monkeypatch, tmp_path):
    module = _load_module(ROOT / "windows_app" / "launcher.py", "windows_launcher_bundle_under_test", monkeypatch)
    bundle_root = _make_bundle_root(tmp_path)
    monkeypatch.setattr(module.sys, "_MEIPASS", str(bundle_root), raising=False)
    assert module.get_run_both_path() == bundle_root / "scripts" / "run_both.py"


def test_mac_launcher_uses_self_command_when_frozen(monkeypatch, tmp_path):
    module = _load_module(ROOT / "mac_app" / "launcher.py", "mac_launcher_frozen_under_test", monkeypatch)
    bundle_root = _make_bundle_root(tmp_path)
    monkeypatch.setattr(module.sys, "_MEIPASS", str(bundle_root), raising=False)
    monkeypatch.setattr(module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(module.sys, "executable", "/tmp/Inebotten", raising=False)
    assert module.get_bot_command() == ["/tmp/Inebotten", "--run-bot"]


def test_windows_launcher_uses_self_command_when_frozen(monkeypatch, tmp_path):
    module = _load_module(ROOT / "windows_app" / "launcher.py", "windows_launcher_frozen_under_test", monkeypatch)
    bundle_root = _make_bundle_root(tmp_path)
    monkeypatch.setattr(module.sys, "_MEIPASS", str(bundle_root), raising=False)
    monkeypatch.setattr(module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(module.sys, "executable", "C:/tmp/Inebotten.exe", raising=False)
    assert module.get_bot_command() == ["C:/tmp/Inebotten.exe", "--run-bot"]


def test_mac_pyinstaller_build_bundles_scripts_directory():
    build_script = (ROOT / "mac_app" / "build.sh").read_text(encoding="utf-8")
    assert '--add-data="../scripts:scripts"' in build_script
    assert "--hidden-import=scripts" in build_script


def test_windows_pyinstaller_build_bundles_scripts_directory():
    build_script = (ROOT / "windows_app" / "build.py").read_text(encoding="utf-8")
    assert "--add-data=../scripts;scripts" in build_script
    assert "--hidden-import=scripts" in build_script
```

**Step 2: Run test to verify failure**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_desktop_launcher_paths.py -q
```

Expected: FAIL because `get_run_both_path()`/`get_bot_command()` do not exist, PyInstaller `_MEIPASS` is not handled, frozen launchers would recursively spawn themselves incorrectly, and `scripts/` is not bundled.

**Step 3: Commit only the failing test**

```bash
git add tests/test_desktop_launcher_paths.py
git commit -m "test: cover desktop launcher bot entrypoint path"
```

---

### Task 4: Fix desktop launcher runtime entrypoint helpers

**Objective:** Make both launchers resolve `scripts/run_both.py` in source and PyInstaller layouts, and avoid recursively spawning the frozen GUI executable as if it were Python.

**Files:**
- Modify: `mac_app/launcher.py:307-322`
- Modify: `windows_app/launcher.py:313-329`
- Test: `tests/test_desktop_launcher_paths.py`

**Step 1: Add helper functions to both launchers**

Add this near the imports/top-level class definitions in both `mac_app/launcher.py` and `windows_app/launcher.py`:

```python
def get_project_root() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root)
    return Path(__file__).resolve().parent.parent


def get_run_both_path() -> Path:
    return get_project_root() / "scripts" / "run_both.py"


def get_bot_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--run-bot"]
    return [sys.executable, str(get_run_both_path())]


def run_bundled_bot() -> None:
    import runpy

    run_both_path = get_run_both_path()
    if not run_both_path.exists():
        raise FileNotFoundError(f"Bot entrypoint not found: {run_both_path}")
    runpy.run_path(str(run_both_path), run_name="__main__")
```

**Step 2: Update `_run_bot()` in both launchers**

Replace:

```python
script_dir = Path(__file__).parent.parent

self.bot_process = subprocess.Popen(
    [sys.executable, str(script_dir / "run_both.py")],
```

with:

```python
script_dir = get_project_root()
run_both_path = get_run_both_path()
if not run_both_path.exists():
    raise FileNotFoundError(f"Bot entrypoint not found: {run_both_path}")

self.bot_process = subprocess.Popen(
    get_bot_command(),
```

Preserve the existing `stdout`, `stderr`, `cwd`, and Windows `creationflags` arguments. In source layout this executes `python scripts/run_both.py`; in a frozen PyInstaller app this executes the same frozen binary with `--run-bot`, which avoids treating the GUI executable as a Python interpreter.

**Step 3: Dispatch `--run-bot` before starting the GUI**

At the bottom of both launchers, replace:

```python
if __name__ == "__main__":
    main()
```

with:

```python
if __name__ == "__main__":
    if "--run-bot" in sys.argv:
        run_bundled_bot()
    else:
        main()
```

**Step 4: Run targeted tests**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest \
  tests/test_desktop_launcher_paths.py::test_mac_launcher_targets_scripts_run_both_in_source_tree \
  tests/test_desktop_launcher_paths.py::test_windows_launcher_targets_scripts_run_both_in_source_tree \
  tests/test_desktop_launcher_paths.py::test_mac_launcher_targets_scripts_run_both_inside_pyinstaller_bundle \
  tests/test_desktop_launcher_paths.py::test_windows_launcher_targets_scripts_run_both_inside_pyinstaller_bundle \
  tests/test_desktop_launcher_paths.py::test_mac_launcher_uses_self_command_when_frozen \
  tests/test_desktop_launcher_paths.py::test_windows_launcher_uses_self_command_when_frozen \
  -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add mac_app/launcher.py windows_app/launcher.py
git commit -m "fix: point desktop launchers at scripts run_both"
```

---

### Task 5: Bundle `scripts/` in desktop builds

**Objective:** Ensure PyInstaller packages the runtime entrypoint and support scripts.

**Files:**
- Modify: `mac_app/build.sh:51-70`
- Modify: `windows_app/build.py:42-66`
- Test: `tests/test_desktop_launcher_paths.py`

**Step 1: Update macOS PyInstaller data and hidden imports**

In `mac_app/build.sh`, add:

```bash
    --add-data="../scripts:scripts" \
```

after the existing `--add-data="../docs:docs" \` line, and add:

```bash
    --hidden-import=scripts \
```

after the existing `--hidden-import=docs \` line.

**Step 2: Update Windows PyInstaller data and hidden imports**

In `windows_app/build.py`, add these list entries:

```python
        "--add-data=../scripts;scripts",
```

and:

```python
        "--hidden-import=scripts",
```

near the existing `docs` entries.

**Step 3: Run the desktop path test file**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_desktop_launcher_paths.py -q
```

Expected: 8 passed.

**Step 4: Commit**

```bash
git add mac_app/build.sh windows_app/build.py tests/test_desktop_launcher_paths.py
git commit -m "fix: bundle scripts in desktop app builds"
```

---

### Task 6: Add web console auth hardening tests

**Objective:** Prove the console is never authenticated when `api_key` is missing, and that production/TLS mode marks login cookies Secure without breaking localhost HTTP tests.

**Files:**
- Modify: `tests/test_console_server.py:11-13`
- Modify: `tests/test_console_server.py:49-73`
- Modify later: `web_console/server.py:1-94`
- Modify later: `web_console/server.py:232-250`

**Step 1: Let the test helper request secure-cookie mode**

Update `start_server()` in `tests/test_console_server.py` from:

```python
async def start_server(monitor: object | None = None) -> tuple[ConsoleServer, asyncio.Task[None]]:
    server = ConsoleServer(host=HOST, port=PORT, api_key=API_KEY, monitor=monitor)
```

to:

```python
async def start_server(monitor: object | None = None, *, secure_cookies: bool | None = None) -> tuple[ConsoleServer, asyncio.Task[None]]:
    server = ConsoleServer(host=HOST, port=PORT, api_key=API_KEY, monitor=monitor, secure_cookies=secure_cookies)
```

**Step 2: Add tests**

Append to `tests/test_console_server.py` after `test_auth_valid_key`:

```python
def test_missing_console_api_key_never_authenticates():
    server = ConsoleServer(api_key=None)
    assert server._is_authenticated({}) is False
    assert server._is_authenticated({"x-api-key": ""}) is False
    assert server._is_authenticated({"cookie": "console_auth="}) is False


async def test_console_server_refuses_to_start_without_api_key():
    server = ConsoleServer(host=HOST, port=0, api_key=None)
    try:
        try:
            await server.start()
        except RuntimeError as exc:
            assert "api_key" in str(exc)
        else:
            raise AssertionError("ConsoleServer.start() accepted a missing api_key")
    finally:
        await server.stop()
```

Keep `test_api_login_valid_key` localhost-compatible, and add a separate production-cookie test after it:

```python
async def test_api_login_valid_key_sets_secure_cookie_when_enabled():
    server, task = await start_server(secure_cookies=True)
    try:
        body = b"api_key=test-key-123"
        response = await request("/api/login", method="POST", body=body)
        assert b"302" in response
        assert b"Set-Cookie: console_auth=" in response
        assert b"HttpOnly" in response
        assert b"SameSite=Strict" in response
        assert b"Secure" in response
    finally:
        await stop_server(server, task)
```

Do not assert `Secure` in the existing localhost-login test, because Playwright/local HTTP tests need browser cookies to round-trip on `http://127.0.0.1:<port>`.

**Step 3: Run tests to verify failure**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest \
  tests/test_console_server.py::test_missing_console_api_key_never_authenticates \
  tests/test_console_server.py::test_console_server_refuses_to_start_without_api_key \
  tests/test_console_server.py::test_api_login_valid_key_sets_secure_cookie_when_enabled \
  -q
```

Expected: FAIL because `ConsoleServer` lacks `secure_cookies`, still authenticates with missing keys, and does not emit Secure in explicit secure-cookie mode.

**Step 4: Commit only tests**

```bash
git add tests/test_console_server.py
git commit -m "test: cover web console auth hardening"
```

---

### Task 7: Harden ConsoleServer authentication and cookies

**Objective:** Remove the `None == None` auth bypass, use constant-time comparison, and set Secure cookies when explicitly enabled or when the console binds to a non-localhost interface.

**Files:**
- Modify: `web_console/server.py:1-94`
- Modify: `web_console/server.py:232-250`
- Test: `tests/test_console_server.py`

**Step 1: Add hmac import and stricter types**

At the top of `web_console/server.py`, add:

```python
import hmac
```

Change the class attributes and constructor signature from `object | None` to explicit auth/cookie fields:

```python
api_key: str | None
secure_cookies: bool


def __init__(
    self,
    host: str = "127.0.0.1",
    port: int = 8080,
    api_key: str | None = None,
    monitor: object | None = None,
    secure_cookies: bool | None = None,
):
    self.host = host
    self.port = port
    self.api_key = api_key.strip() if isinstance(api_key, str) and api_key.strip() else None
    self.secure_cookies = secure_cookies if secure_cookies is not None else host not in {"127.0.0.1", "localhost", "::1"}
    self.monitor = monitor
    self._server = None
```

**Step 2: Refuse startup without a configured key**

At the start of `start()` before `asyncio.start_server(...)`, add:

```python
        if self.api_key is None:
            raise RuntimeError("ConsoleServer requires a non-empty api_key")
```

**Step 3: Replace `_is_authenticated()`**

Replace `web_console/server.py:87-94` with:

```python
    def _candidate_matches_api_key(self, candidate: str | None) -> bool:
        if self.api_key is None or candidate is None:
            return False
        return hmac.compare_digest(candidate, self.api_key)

    def _is_authenticated(self, headers: dict[str, str]) -> bool:
        if self._candidate_matches_api_key(headers.get("x-api-key")):
            return True
        cookies = self._parse_cookies(headers.get("cookie"))
        return self._candidate_matches_api_key(cookies.get("console_auth"))
```

**Step 4: Use the helper in login and set cookie flags by mode**

Replace:

```python
                if submitted_key == self.api_key:
```

with:

```python
                if self._candidate_matches_api_key(submitted_key):
```

Before sending the response, build cookie attributes:

```python
                    cookie_attrs = "; Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000"
                    if self.secure_cookies:
                        cookie_attrs = "; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=2592000"
```

Replace the `Set-Cookie` header with:

```python
                            "Set-Cookie: console_auth=" + self.api_key + cookie_attrs,
```

`self.api_key` is non-None here because `_candidate_matches_api_key()` returned True. Localhost tests keep `secure_cookies=False` by default, while production/container hosts such as `0.0.0.0` default to Secure.

**Step 5: Run tests**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_console_server.py -q
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_console_frontend.py -q
```

Expected: PASS. The frontend test confirms localhost HTTP login still works because Secure cookies are not forced for `127.0.0.1`.

**Step 6: Commit**

```bash
git add web_console/server.py tests/test_console_server.py
git commit -m "fix: harden web console authentication"
```

---

### Task 8: Add web console modal XSS regression tests

**Objective:** Prove the Alpine modal no longer uses an HTML sink for untrusted data.

**Files:**
- Create: `tests/test_web_console_frontend_security.py`
- Modify later: `web_console/templates/base.html:120-128`
- Modify later: `web_console/static/app.js:330-402`

**Step 1: Create failing tests**

Create `tests/test_web_console_frontend_security.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_modal_template_does_not_use_x_html_sink():
    base = (ROOT / "web_console" / "templates" / "base.html").read_text(encoding="utf-8")
    assert "x-html" not in base
    assert "x-text=\"modalData.content || ''\"" in base


def test_modal_details_are_built_as_plain_text_not_html_strings():
    app_js = (ROOT / "web_console" / "static" / "app.js").read_text(encoding="utf-8")
    assert "showSectionModal(section)" in app_js
    assert "content += `<div" not in app_js
    assert "content = `<table" not in app_js
    assert "openModal(section, { title:" in app_js
```

**Step 2: Run tests to verify failure**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_web_console_frontend_security.py -q
```

Expected: FAIL because `base.html` contains `x-html` and `app.js` builds HTML strings.

**Step 3: Commit only tests**

```bash
git add tests/test_web_console_frontend_security.py
git commit -m "test: cover web console modal xss sink"
```

---

### Task 9: Replace the modal HTML sink with plain-text rendering

**Objective:** Remove the direct DOM-XSS sink while keeping useful modal details.

**Files:**
- Modify: `web_console/templates/base.html:120-128`
- Modify: `web_console/static/app.js:330-402`
- Test: `tests/test_web_console_frontend_security.py`

**Step 1: Replace modal body in `base.html`**

Replace:

```html
        <div class="p-6 max-h-[60vh] overflow-y-auto">
          <div x-html="modalData.content || ''"></div>
        </div>
```

with:

```html
        <div class="p-6 max-h-[60vh] overflow-y-auto">
          <pre class="whitespace-pre-wrap break-words text-sm leading-relaxed" x-text="modalData.content || ''"></pre>
        </div>
```

**Step 2: Replace `showSectionModal(section)` content building**

In `web_console/static/app.js`, replace the `showSectionModal(section)` function body with a plain-text builder:

```javascript
    showSectionModal(section) {
      const titles = {
        status: 'Bot-status',
        bridge: 'Bridge',
        calendar: 'Kalender',
        polls: 'Avstemninger',
        'rate-limits': 'Rate limits',
        intents: 'Intents',
        memory: 'Minne',
        logs: 'Logger',
      };
      const data = this.data[section] || {};
      const lines = [];
      const add = (label, value) => lines.push(`${label}: ${value ?? 'N/A'}`);
      const addBlank = () => lines.push('');

      switch (section) {
        case 'status':
          add('Status', data.status || 'N/A');
          add('Oppetid', this.formatUptime(data.uptime_seconds));
          add('Servere', data.guilds ?? 'N/A');
          add('Brukere', data.users ?? 'N/A');
          add('Discord-tilkobling', data.discord_connected ? 'Ja' : 'Nei');
          break;
        case 'bridge':
          add('Status', data.status || 'N/A');
          add('LM Studio', data.lm_studio || 'N/A');
          add('Forespørsler', data.requests ?? 0);
          add('Feil', data.errors ?? 0);
          break;
        case 'calendar':
          add('Hendelser', data.event_count ?? 0);
          add('Oppgaver', data.task_count ?? 0);
          if (Array.isArray(data.upcoming_events) && data.upcoming_events.length) {
            addBlank();
            lines.push('Kommende hendelser:');
            data.upcoming_events.slice(0, 10).forEach(ev => {
              const title = ev.title || ev.name || 'Uten tittel';
              const when = ev.when || ev.start || ev.date || 'Ukjent tid';
              lines.push(`- ${title} — ${when}`);
            });
          }
          break;
        case 'polls':
          add('Aktive avstemninger', data.active_polls ?? 0);
          break;
        case 'rate-limits':
          add('Totale forespørsler', data.summary?.total_requests ?? 0);
          break;
        case 'intents':
          add('Fallbacks', data.fallback_count ?? 0);
          if (data.intent_counts && Object.keys(data.intent_counts).length) {
            addBlank();
            lines.push('Intent-tellinger:');
            Object.entries(data.intent_counts)
              .sort((a, b) => (b[1] || 0) - (a[1] || 0))
              .forEach(([intent, count]) => lines.push(`- ${intent}: ${count}`));
          }
          break;
        case 'memory':
          add('Brukere i minne', data.user_count ?? 0);
          add('Samtaler', data.conversation_count ?? 0);
          break;
        case 'logs':
          if (Array.isArray(data.logs) && data.logs.length) {
            lines.push(...data.logs.map(line => String(line)));
          } else {
            lines.push('Ingen logger tilgjengelig');
          }
          break;
        default:
          lines.push('Ingen detaljer tilgjengelig');
      }

      this.openModal(section, { title: titles[section] || 'Detaljer', content: lines.join('\n') });
    },
```

**Step 3: Run frontend security tests**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_web_console_frontend_security.py -q
```

Expected: PASS.

**Step 4: Run console server tests**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_console_server.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add web_console/templates/base.html web_console/static/app.js tests/test_web_console_frontend_security.py
git commit -m "fix: remove web console modal html sink"
```

---

### Task 10: Add GCal sync channel routing regression tests

**Objective:** Prove imported Google Calendar items keep a usable Discord channel, and shared calendar digests do not crash on `int('shared')`.

**Files:**
- Create: `tests/test_gcal_reminder_routing.py`
- Modify later: `cal_system/calendar_manager.py:428-559`
- Modify later: `features/calendar_handler.py:495-510`
- Modify later: `cal_system/reminder_checker.py:360-367`

**Step 1: Create failing tests**

Create `tests/test_gcal_reminder_routing.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from cal_system.calendar_manager import CalendarManager
from cal_system.reminder_checker import ReminderChecker


class FakeGCal:
    def is_configured(self):
        return True

    def list_upcoming_events(self, days=30):
        start = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        return [
            {
                "id": "gcal-1",
                "summary": "GCal møte",
                "start": {"date": start},
                "creator": {"email": "reed@example.com"},
                "organizer": {"email": "reed@example.com"},
                "htmlLink": "https://calendar.google.com/event?eid=gcal-1",
            }
        ]


@pytest.mark.asyncio
async def test_sync_from_gcal_stores_default_channel_id_for_new_items():
    with TemporaryDirectory() as tmpdir:
        manager = CalendarManager(storage_path=Path(tmpdir) / "calendar.json", gcal_manager=FakeGCal())
        await manager.setup()

        count = await manager.sync_from_gcal(default_guild_id="123", default_channel_id="999")

        assert count == 1
        item = manager.items[manager.SHARED_KEY][0]
        assert item["gcal_event_id"] == "gcal-1"
        assert item["channel_id"] == "999"


@pytest.mark.asyncio
async def test_sync_from_gcal_backfills_channel_id_for_existing_items():
    with TemporaryDirectory() as tmpdir:
        manager = CalendarManager(storage_path=Path(tmpdir) / "calendar.json", gcal_manager=FakeGCal())
        await manager.setup()
        manager.add_item(
            guild_id="123",
            user_id="gcal_sync",
            username="Google Calendar",
            title="Old title",
            date_str=(datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y"),
            gcal_event_id="gcal-1",
            channel_id=None,
        )

        count = await manager.sync_from_gcal(default_guild_id="123", default_channel_id="999")

        assert count == 1
        item = manager.items[manager.SHARED_KEY][0]
        assert item["title"] == "GCal møte"
        assert item["channel_id"] == "999"


def test_find_digest_channel_returns_none_for_shared_without_channel_id():
    class CalendarStub:
        def get_upcoming(self, guild_id, days=1):
            return [{"title": "GCal møte", "channel_id": None}]

    checker = ReminderChecker(calendar_manager=CalendarStub())

    assert checker._find_digest_channel("shared") is None
```

**Step 2: Run tests to verify failure**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_gcal_reminder_routing.py -q
```

Expected: FAIL because `sync_from_gcal()` has no `default_channel_id` parameter and `_find_digest_channel('shared')` raises `ValueError`.

**Step 3: Commit only tests**

```bash
git add tests/test_gcal_reminder_routing.py
git commit -m "test: cover gcal reminder channel routing"
```

---

### Task 11: Preserve GCal sync channel IDs and avoid shared digest crash

**Objective:** Route GCal-imported reminders/digests to the channel that triggered sync, and safely skip items without a channel.

**Files:**
- Modify: `cal_system/calendar_manager.py:428-559`
- Modify: `features/calendar_handler.py:495-510`
- Modify: `cal_system/reminder_checker.py:360-367`
- Test: `tests/test_gcal_reminder_routing.py`

**Step 1: Extend `CalendarManager.sync_from_gcal()` signature**

Change:

```python
    async def sync_from_gcal(self, default_guild_id=None):
```

to:

```python
    async def sync_from_gcal(self, default_guild_id=None, default_channel_id=None):
```

Inside the method before the event loop, add:

```python
        fallback_channel_id = default_channel_id
```

Only store a real channel ID. Do not fall back to `default_guild_id`, because a guild snowflake is not a sendable text-channel snowflake.

**Step 2: Backfill channel_id on existing GCal items**

Inside the `if gcal_id in gcal_map:` update branch, after the existing user-id/username update checks and before completion handling, add:

```python
                if not item.get("channel_id") and fallback_channel_id is not None:
                    item["channel_id"] = str(fallback_channel_id)
                    changed = True
```

This repairs events imported before this fix.

**Step 3: Store channel_id on new GCal items**

In the `await self.add_item(...)` call for new GCal items, add:

```python
                    channel_id=fallback_channel_id,
```

**Step 4: Pass channel id from manual sync handler**

In `features/calendar_handler.py:498-510`, change:

```python
            guild_id = self.get_guild_id(message)
```

to:

```python
            guild_id = self.get_guild_id(message)
            channel_id = getattr(getattr(message, "channel", None), "id", None)
```

Change the sync call to:

```python
            count = await self.calendar.sync_from_gcal(default_guild_id=guild_id, default_channel_id=channel_id)
```

**Step 5: Make digest fallback safe**

Replace `ReminderChecker._find_digest_channel()` with:

```python
    def _find_digest_channel(self, guild_id):
        """Find a sensible channel_id for the morning digest."""
        items = self.calendar.get_upcoming(guild_id, days=1)
        for item in items:
            channel_id = item.get("channel_id")
            if channel_id:
                try:
                    return int(channel_id)
                except (TypeError, ValueError):
                    continue
        return None
```

**Step 6: Run tests**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_gcal_reminder_routing.py -q
```

Expected: PASS.

**Step 7: Commit**

```bash
git add cal_system/calendar_manager.py features/calendar_handler.py cal_system/reminder_checker.py tests/test_gcal_reminder_routing.py
git commit -m "fix: preserve gcal reminder channel routing"
```

---

### Task 12: Add URL shortener HTTPS regression test

**Objective:** Prove TinyURL API calls do not send user URLs over plaintext HTTP.

**Files:**
- Create: `tests/test_url_shortener_security.py`
- Modify later: `features/url_shortener.py:45-56`

**Step 1: Create failing test**

Create `tests/test_url_shortener_security.py`:

```python
from __future__ import annotations

import urllib.request

from features.url_shortener import URLShortener


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return b"https://tinyurl.com/example"


def test_tinyurl_api_uses_https(monkeypatch):
    requested_urls = []

    def fake_urlopen(url, timeout=10):
        requested_urls.append(url)
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = URLShortener().shorten_url("https://example.com/private?token=secret")

    assert result["short"] == "https://tinyurl.com/example"
    assert requested_urls
    assert requested_urls[0].startswith("https://tinyurl.com/api-create.php?")
```

**Step 2: Run test to verify failure**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_url_shortener_security.py -q
```

Expected: FAIL because current code uses `http://tinyurl.com/...`.

**Step 3: Commit only test**

```bash
git add tests/test_url_shortener_security.py
git commit -m "test: cover url shortener https transport"
```

---

### Task 13: Use HTTPS for TinyURL API calls

**Objective:** Stop exposing user URLs to plaintext network observers.

**Files:**
- Modify: `features/url_shortener.py:45-56`
- Test: `tests/test_url_shortener_security.py`

**Step 1: Change TinyURL endpoint**

Replace:

```python
            api_url = f"http://tinyurl.com/api-create.php?url={urllib.parse.quote(url)}"
```

with:

```python
            api_url = f"https://tinyurl.com/api-create.php?url={urllib.parse.quote(url, safe='')}"
```

**Step 2: Run tests**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_url_shortener_security.py -q
```

Expected: PASS.

**Step 3: Commit**

```bash
git add features/url_shortener.py tests/test_url_shortener_security.py
git commit -m "fix: use https for url shortener api"
```

---

### Task 14: Add sanitizer regression tests

**Objective:** Prove shared sanitizer helpers actually remove mentions, escape HTML, and block loopback/private URLs.

**Files:**
- Create: `tests/test_sanitizer_security.py`
- Modify later: `utils/sanitizer.py:7-9`
- Modify later: `utils/sanitizer.py:41-52`
- Modify later: `utils/sanitizer.py:132-161`
- Modify later: `utils/sanitizer.py:215-235`

**Step 1: Create failing tests**

Create `tests/test_sanitizer_security.py`:

```python
from utils.sanitizer import sanitize_discord_mention, sanitize_html, sanitize_url


def test_sanitize_discord_mention_removes_user_mentions():
    assert sanitize_discord_mention("hei <@123456> og <@!789>").strip() == "hei  og"


def test_sanitize_html_escapes_tags_and_quotes():
    assert sanitize_html('<img src=x onerror="alert(1)">') == "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"


def test_sanitize_url_blocks_loopback_and_private_hosts():
    assert sanitize_url("http://127.0.0.1:8080/secret") == ""
    assert sanitize_url("http://localhost:8080/secret") == ""
    assert sanitize_url("http://10.0.0.1/secret") == ""
    assert sanitize_url("http://192.168.1.10/secret") == ""
    assert sanitize_url("http://172.16.0.1/secret") == ""


def test_sanitize_url_allows_public_https_url():
    assert sanitize_url("https://example.com/path?q=1") == "https://example.com/path?q=1"
```

**Step 2: Run tests to verify failure**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_sanitizer_security.py -q
```

Expected: FAIL on mention regex, HTML escaping, and URL blocking.

**Step 3: Commit only tests**

```bash
git add tests/test_sanitizer_security.py
git commit -m "test: cover sanitizer security behavior"
```

---

### Task 15: Fix sanitizer helper behavior

**Objective:** Make `utils/sanitizer.py` match its security claims.

**Files:**
- Modify: `utils/sanitizer.py:7-9`
- Modify: `utils/sanitizer.py:41-52`
- Modify: `utils/sanitizer.py:132-161`
- Modify: `utils/sanitizer.py:215-235`
- Test: `tests/test_sanitizer_security.py`

**Step 1: Add imports**

At the top of `utils/sanitizer.py`, add:

```python
import html
import ipaddress
from urllib.parse import urlparse
```

**Step 2: Fix mention regex**

Replace:

```python
    return re.sub(r'<@!?\\d+>', '', text)
```

with:

```python
    return re.sub(r'<@!?\d+>', '', text)
```

**Step 3: Replace `sanitize_url()`**

Replace the full function with:

```python
def sanitize_url(url: str) -> str:
    """Sanitize URL to prevent SSRF attacks."""
    if not url:
        return ""

    url = url.strip()[:2048]
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return ""
    if not parsed.hostname:
        return ""

    host = parsed.hostname.lower()
    if host in {"localhost", "localhost.localdomain"}:
        return ""

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return url

    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return ""

    return url
```

**Step 4: Replace `sanitize_html()`**

Replace the function body with:

```python
    if not text:
        return ""
    return html.escape(text, quote=True)
```

**Step 5: Run tests**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_sanitizer_security.py -q
```

Expected: PASS.

**Step 6: Commit**

```bash
git add utils/sanitizer.py tests/test_sanitizer_security.py
git commit -m "fix: repair sanitizer security helpers"
```

---

### Task 16: Add setup clear-screen shell regression test

**Objective:** Prove `setup.py` no longer shells out through `os.system()` just to clear the screen.

**Files:**
- Create: `tests/test_setup_security.py`
- Modify later: `setup.py:31-32`

**Step 1: Create failing test**

Create `tests/test_setup_security.py`:

```python
from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_setup_module():
    spec = importlib.util.spec_from_file_location("inebotten_setup_under_test", ROOT / "setup.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_clear_screen_does_not_call_os_system(monkeypatch, capsys):
    setup_module = _load_setup_module()

    def forbidden_system(command):
        raise AssertionError(f"os.system must not be called: {command}")

    monkeypatch.setattr(setup_module.os, "system", forbidden_system)

    setup_module.clear_screen()

    captured = capsys.readouterr()
    assert captured.out
```

**Step 2: Run test to verify failure**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_setup_security.py -q
```

Expected: FAIL because `clear_screen()` calls `os.system(...)`.

**Step 3: Commit only test**

```bash
git add tests/test_setup_security.py
git commit -m "test: cover setup clear screen shell use"
```

---

### Task 17: Remove shell usage from setup clear-screen

**Objective:** Clear the terminal without invoking a shell command.

**Files:**
- Modify: `setup.py:31-32`
- Test: `tests/test_setup_security.py`

**Step 1: Replace `clear_screen()`**

Replace:

```python
def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')
```

with:

```python
def clear_screen():
    # ANSI clear-screen sequence; avoids shell execution for a cosmetic action.
    print("\033[2J\033[H", end="")
```

**Step 2: Run test and bandit target**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_setup_security.py -q
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m bandit setup.py -ll
```

Expected: pytest PASS; Bandit has no HIGH finding for `os.system` in `setup.py`.

**Step 3: Commit**

```bash
git add setup.py tests/test_setup_security.py
git commit -m "fix: avoid shell clear in setup script"
```

---

### Task 18: Add deploy and container hardening tests

**Objective:** Lock in deploy safety: no ignored git-pull failures, no `.git` in Docker context, no root runtime, writable non-root data directory, and bundled Caddy is opt-in.

**Files:**
- Create: `tests/test_deploy_hardening.py`
- Modify later: `deploy/ansible-playbook.yml:13-23`, `deploy/ansible-playbook.yml:67-76`
- Modify later: `.dockerignore:23-24`
- Modify later: `Dockerfile:34-49`
- Modify later: `docker-compose.yml:8-16`, `docker-compose.yml:28-43`

**Step 1: Create failing tests**

Create `tests/test_deploy_hardening.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ansible_git_pull_does_not_ignore_errors():
    playbook = (ROOT / "deploy" / "ansible-playbook.yml").read_text(encoding="utf-8")
    pull_task = playbook.split("- name: Pull latest source from origin", 1)[1].split("- name:", 1)[0]
    assert "ignore_errors" not in pull_task


def test_dockerignore_excludes_git_directory():
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ".git/" in lines


def test_dockerfile_runs_as_non_root_user():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "useradd" in dockerfile
    assert "--uid 10001" in dockerfile
    assert "USER inebotten" in dockerfile
    assert "/home/inebotten/.hermes" in dockerfile


def test_ansible_ensures_data_dir_is_writable_by_runtime_uid():
    playbook = (ROOT / "deploy" / "ansible-playbook.yml").read_text(encoding="utf-8")
    assert "{{ compose_dir }}/data" in playbook
    assert 'owner: "10001"' in playbook
    assert 'group: "10001"' in playbook
    assert "recurse: true" in playbook


def test_compose_mounts_non_root_home_and_caddy_is_opt_in():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "./data:/home/inebotten/.hermes" in compose
    assert 'user: "10001:10001"' in compose
    caddy_block = compose.split("  caddy:", 1)[1]
    assert "profiles:" in caddy_block
    assert "bundled-caddy" in caddy_block
```

**Step 2: Run tests to verify failure**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_deploy_hardening.py -q
```

Expected: FAIL on current deploy/container config.

**Step 3: Commit only tests**

```bash
git add tests/test_deploy_hardening.py
git commit -m "test: cover deploy and container hardening"
```

---

### Task 19: Make Ansible fail loudly on source sync errors

**Objective:** Prevent deployments from continuing with stale code after git pull failure.

**Files:**
- Modify: `deploy/ansible-playbook.yml:13-23`
- Test: `tests/test_deploy_hardening.py`

**Step 1: Remove ignored git errors**

Delete line 23:

```yaml
      ignore_errors: yes  # allow operating on an already-checked-out tree without origin access
```

Keep `register: source_pull`.

**Step 2: Run deploy hardening test subset**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_deploy_hardening.py::test_ansible_git_pull_does_not_ignore_errors -q
```

Expected: PASS.

**Step 3: Commit**

```bash
git add deploy/ansible-playbook.yml tests/test_deploy_hardening.py
git commit -m "fix: fail deploy on source sync errors"
```

---

### Task 20: Harden Docker context, runtime user, and Caddy profile

**Objective:** Keep Git history out of images, run the bot as a fixed non-root UID with writable persisted data, and avoid default port-80/443 conflicts.

**Files:**
- Modify: `deploy/ansible-playbook.yml:67-76`
- Modify: `.dockerignore:23-24`
- Modify: `Dockerfile:34-49`
- Modify: `docker-compose.yml:8-16`, `docker-compose.yml:28-43`
- Test: `tests/test_deploy_hardening.py`

**Step 1: Exclude `.git/` from Docker context**

In `.dockerignore`, under `# Git`, add:

```text
.git/
```

Keep `.gitignore` ignored too.

**Step 2: Update Dockerfile for non-root runtime**

Replace lines 34-49 with:

```dockerfile
# Create a fixed-UID non-root runtime user and its persistent data directory
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin inebotten
ENV HOME=/home/inebotten

# Copy the rest of the application code into the container
COPY . .

# Bake the current git commit hash into the image at build time
RUN python scripts/write_version.py || echo "warning: could not write commit_hash.txt"

# The bot stores data in ~/.hermes, now under the non-root user's home
RUN mkdir -p /home/inebotten/.hermes \
    && chown -R inebotten:inebotten /app /home/inebotten

USER inebotten

# Expose the bridge port (if needed for external access, though run_both uses localhost)
EXPOSE 3000
EXPOSE 8080

# Run the bot
CMD ["python", "scripts/run_both.py"]
```

**Step 3: Update Compose mount path and runtime UID**

In `docker-compose.yml`, replace:

```yaml
      - ./data:/root/.hermes
```

with:

```yaml
      - ./data:/home/inebotten/.hermes
```

Under the `inebotten:` service, also add:

```yaml
    user: "10001:10001"
```

**Step 4: Ensure deployed bind mount is owned by the runtime UID**

In `deploy/ansible-playbook.yml`, add this task before `Build (or rebuild) the inebotten image`:

```yaml
    - name: Ensure persistent data directory is writable by the non-root container user
      ansible.builtin.file:
        path: "{{ compose_dir }}/data"
        state: directory
        owner: "10001"
        group: "10001"
        mode: "0700"
        recurse: true
      become: true
```

This also migrates an existing root-owned `./data` directory on the VPS.

**Step 5: Put bundled Caddy behind an opt-in profile**

Under the `caddy:` service in `docker-compose.yml`, add:

```yaml
    profiles:
      - bundled-caddy
```

Do not change the Ansible override in this task.

**Step 6: Run tests**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_deploy_hardening.py -q
```

Expected: PASS.

If Docker is installed on the implementer's machine, also run:

```bash
docker compose config >/tmp/inebotten-compose-config.yml
docker compose build inebotten
mkdir -p data && printf old > data/existing-write-test.txt
docker compose run --rm --entrypoint python inebotten -c "from pathlib import Path; p=Path.home()/'.hermes'/'existing-write-test.txt'; p.write_text(p.read_text()+'-ok'); print(p.read_text())"
```

Expected: exit 0 and the write-test command prints `old-ok`. If Docker is unavailable locally, mark this verification as blocked and run it in CI/VPS before claiming container hardening complete. On the VPS, also verify the Ansible `recurse: true` task changed ownership of pre-existing files under `{{ compose_dir }}/data`.

**Step 7: Commit**

```bash
git add deploy/ansible-playbook.yml .dockerignore Dockerfile docker-compose.yml tests/test_deploy_hardening.py
git commit -m "fix: harden docker runtime and compose defaults"
```

---

### Task 21: Add per-send rate limit tests for BaseHandler

**Objective:** Prove every actual handler send checks the rate limiter, not just the initial message dispatch.

**Files:**
- Create: `tests/test_base_handler_rate_limit.py`
- Modify later: `features/base_handler.py:42-84`

**Step 1: Create failing tests**

Create `tests/test_base_handler_rate_limit.py`:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from features.base_handler import BaseHandler


class FakeHandler(BaseHandler):
    pass


@pytest.mark.asyncio
async def test_send_response_drops_when_rate_limiter_says_no():
    rate_limiter = SimpleNamespace(
        can_send=Mock(return_value=(False, "daily quota")),
        wait_if_needed=AsyncMock(return_value=True),
        record_sent=Mock(),
        record_failure=Mock(),
        record_dropped=Mock(),
    )
    monitor = SimpleNamespace(rate_limiter=rate_limiter, loc=object(), client=object())
    handler = FakeHandler(monitor)
    message = SimpleNamespace(channel=object(), reply=AsyncMock())

    result = await handler.send_response(message, "hei")

    assert result is None
    message.reply.assert_not_awaited()
    rate_limiter.record_dropped.assert_called_once()
    rate_limiter.record_sent.assert_not_called()


@pytest.mark.asyncio
async def test_send_response_waits_before_sending():
    rate_limiter = SimpleNamespace(
        can_send=Mock(return_value=(True, None)),
        wait_if_needed=AsyncMock(return_value=True),
        record_sent=Mock(),
        record_failure=Mock(),
    )
    monitor = SimpleNamespace(rate_limiter=rate_limiter, loc=object(), client=object(), response_count=0)
    handler = FakeHandler(monitor)
    sent = object()
    message = SimpleNamespace(channel=object(), reply=AsyncMock(return_value=sent))

    result = await handler.send_response(message, "hei")

    assert result is sent
    rate_limiter.wait_if_needed.assert_awaited_once()
    rate_limiter.record_sent.assert_called_once()
    assert monitor.response_count == 1
```

**Step 2: Run tests to verify failure**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_base_handler_rate_limit.py -q
```

Expected: FAIL because `send_response()` sends without checking `can_send()`/`wait_if_needed()`.

**Step 3: Commit only tests**

```bash
git add tests/test_base_handler_rate_limit.py
git commit -m "test: cover per-send handler rate limiting"
```

---

### Task 22: Enforce rate limits inside BaseHandler.send_response

**Objective:** Ensure multi-response handlers cannot bypass rate limits after the first precheck.

**Files:**
- Modify: `features/base_handler.py:42-84`
- Test: `tests/test_base_handler_rate_limit.py`

**Step 1: Add a guard at the top of `send_response()`**

Inside `BaseHandler.send_response()`, immediately after the docstring and before sending, add:

```python
        can_send, reason = self.rate_limiter.can_send()
        if not can_send:
            self.logger.warning("Rate limited: cannot send response (%s)", reason)
            if hasattr(self.rate_limiter, "record_dropped"):
                self.rate_limiter.record_dropped()
            return None

        if not await self.rate_limiter.wait_if_needed():
            self.logger.warning("Rate limited: wait_if_needed refused send")
            if hasattr(self.rate_limiter, "record_dropped"):
                self.rate_limiter.record_dropped()
            return None
```

Do not remove existing `record_sent()` or exception handling.

**Step 2: Run targeted tests**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_base_handler_rate_limit.py -q
```

Expected: PASS.

**Step 3: Run calendar handler tests that mock rate limiting**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_calendar_edit.py tests/test_reminder_crud.py -q
```

Expected: PASS. If mocks are missing `record_dropped`, keep the `hasattr` guard.

**Step 4: Commit**

```bash
git add features/base_handler.py tests/test_base_handler_rate_limit.py
git commit -m "fix: enforce rate limits for every handler send"
```

---

### Task 23: Add Google token permission tests

**Objective:** Prove OAuth token writes use private file permissions.

**Files:**
- Create: `tests/test_gcal_token_permissions.py`
- Modify later: `scripts/auth_gcal.py:79-83`
- Modify later: `cal_system/google_calendar_manager.py:85-90`

**Step 1: Create tests**

Create `tests/test_gcal_token_permissions.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_auth_gcal_sets_private_permissions_when_writing_token():
    source = (ROOT / "scripts" / "auth_gcal.py").read_text(encoding="utf-8")
    assert "os.open" in source
    assert "0o600" in source


def test_google_calendar_manager_sets_private_permissions_when_saving_token():
    source = (ROOT / "cal_system" / "google_calendar_manager.py").read_text(encoding="utf-8")
    assert "os.open" in source
    assert "0o600" in source
```

**Step 2: Run tests to verify failure**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_gcal_token_permissions.py -q
```

Expected: FAIL because both files use normal `open(..., "w")`.

**Step 3: Commit only tests**

```bash
git add tests/test_gcal_token_permissions.py
git commit -m "test: cover google token file permissions"
```

---

### Task 24: Write Google OAuth tokens with 0600 permissions

**Objective:** Prevent permissive umask/shared systems from exposing refresh tokens.

**Files:**
- Modify: `scripts/auth_gcal.py:79-83`
- Modify: `cal_system/google_calendar_manager.py:85-90`
- Test: `tests/test_gcal_token_permissions.py`

**Step 1: Update `scripts/auth_gcal.py` token write**

Add `import os` if it is not already present.

Replace:

```python
        HERMES_HOME.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())
```

with:

```python
        HERMES_HOME.mkdir(parents=True, exist_ok=True)
        HERMES_HOME.chmod(0o700)
        fd = os.open(TOKEN_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as token:
            token.write(creds.to_json())
```

**Step 2: Update `GoogleCalendarManager._save_credentials()`**

Add `import os` to `cal_system/google_calendar_manager.py` if needed.

Replace:

```python
            with open(TOKEN_PATH, "w") as token:
                token.write(creds.to_json())
```

with:

```python
            HERMES_HOME.mkdir(parents=True, exist_ok=True)
            HERMES_HOME.chmod(0o700)
            fd = os.open(TOKEN_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as token:
                token.write(creds.to_json())
```

**Step 3: Run tests**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest tests/test_gcal_token_permissions.py -q
```

Expected: PASS.

**Step 4: Commit**

```bash
git add scripts/auth_gcal.py cal_system/google_calendar_manager.py tests/test_gcal_token_permissions.py
git commit -m "fix: store google oauth tokens with private permissions"
```

---

### Task 25: Final integration gate and post-implementation audit

**Objective:** Verify the full remediation set and catch integration mistakes that targeted tests miss.

**Files:**
- Read/audit every file modified by Tasks 1-24.
- No production code changes unless this audit finds a bug; if it finds a bug, add a new failing test first.

**Step 1: Run full local gates**

Run:
```bash
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m compileall ai cal_system core features memory utils web_console scripts mac_app windows_app
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m flake8 . --select=E9,F63,F7,F82
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m pytest -q
uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt python -m bandit -r setup.py web_console cal_system features utils -ll
```

Expected:
- compileall: success
- flake8 subset: 0 issues
- pytest: all pass
- bandit target: no HIGH findings; investigate any remaining MEDIUM findings before reporting done

**Step 2: Run post-implementation audit checklist**

Use `subagent-driven-development/references/post-implementation-audit.md` as checklist. Audit specifically:
- Did secure cookie behavior break localhost login expectations? If yes, document or add a dev-mode toggle with tests.
- Did removing `x-html` make modal content safe but unusable? If too degraded, add a follow-up safe structured modal renderer with tests.
- Did non-root Docker runtime still write to mounted `./data`? If Docker is installed, verify with `docker compose config`; otherwise record that Docker runtime verification was blocked locally.
- Did BaseHandler rate-limit checks require new mocks in handler tests?
- Did GCal sync still preserve existing event updates and not duplicate imported events?

**Step 3: Review git history and diff**

Run:
```bash
git status --short
git log --oneline --decorate -10
git diff --stat origin/master..HEAD
```

Expected:
- clean working tree
- one small commit per task
- diff only touches planned files

**Step 4: Do not claim CI/deploy success unless actually verified**

If pushing to GitHub later, verify exact SHA:

```bash
gh run list --json databaseId,headSha,status,conclusion,workflowName,createdAt --limit 10
```

Only report CI success after the run for the pushed SHA shows `status=completed` and `conclusion=success`.

**Step 5: Final commit if audit-only docs changed**

```bash
git add docs/plans/2026-05-31-audit-remediation.md
git commit -m "docs: add audit remediation implementation plan"
```

---

## Follow-up Items Not Included in This First Remediation Pass

These are real audit findings but should be separate plans after the high-impact fixes above are green:

1. Track and cancel background tasks cleanly in `MessageMonitor`/`SelfbotClient.close()`.
2. Extend `GoogleCalendarManager.update_event()` so local calendar edit date/time changes sync back to GCal, not just title/completion.
3. Normalize or remove email/password auth mode from `core/config.py`, `core/auth_handler.py`, and setup docs.
4. Fix cumulative web-console stats inflation by storing snapshots or deltas explicitly in `web_console/console_store.py`.
5. Consolidate the two GitHub release workflows so tag pushes cannot race release creation.
6. Add CI jobs for Docker Compose config, Docker build smoke, Ansible syntax/lint with dummy vars, shellcheck, and a Bandit policy/baseline.

Each follow-up should get its own TDD plan before implementation.
