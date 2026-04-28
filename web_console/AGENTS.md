# web_console/ — Web Dashboard

HTTP console for bot monitoring: status, bridge health, calendar, polls, rate limits, intents, memory, and live logs.

## STRUCTURE

```
web_console/
├── server.py           # ConsoleServer — asyncio HTTP server
├── dashboard.py        # render_dashboard() + render_login_page() — pure Python HTML
├── state_collector.py  # Collects bot state for the dashboard
└── __init__.py
```

## WHERE TO LOOK

| Task | File |
|------|------|
| Add new dashboard card | `dashboard.py` + `state_collector.py` |
| Add new API endpoint | `server.py` — `handle_request()` |
| Change auth behavior | `server.py` — `_is_authenticated()`, `/api/login` |
| Change data collection | `state_collector.py` |
| Change styling | `dashboard.py` — inline CSS in `render_dashboard()` |

## CONVENTIONS

- Pure Python HTML — no templating engine
- Auth: `X-API-Key` header for API clients, cookie session (`console_auth`) for browsers
- `ConsoleServer` receives `monitor=None` initially, updated after `on_ready()`
- `/health` is auth-exempt
- Login form posts to `/api/login` which validates key and sets HttpOnly cookie

## ANTI-PATTERNS

- **Do not** serve the dashboard without auth — always check `_is_authenticated()`
- **Do not** forget to update `self.console_server.monitor` in `start_console()` after `on_ready()`

## ENDPOINTS

| Path | Auth | Description |
|------|------|-------------|
| `/` | Yes | Dashboard HTML |
| `/login` | No | Login page |
| `/health` | No | Health check JSON |
| `/api/login` | No | POST: validate key, set cookie |
| `/api/status` | Yes | Bot status JSON |
| `/api/bridge` | Yes | Bridge health JSON |
| `/api/calendar` | Yes | Calendar data JSON |
| `/api/polls` | Yes | Polls JSON |
| `/api/rate-limits` | Yes | Rate limit stats JSON |
| `/api/intents` | Yes | Intent stats JSON |
| `/api/memory` | Yes | Memory stats JSON |
| `/api/logs` | Yes | Log lines JSON (`?lines=N`) |
