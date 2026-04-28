# web_console/ — Web Dashboard

HTTP console for bot monitoring: status, bridge health, calendar, polls, rate limits, intents, memory, and live logs.

## Web Console Architecture (Redesigned)

### Frontend
- Tailwind CSS + Alpine.js (vendored in `static/`)
- Dark/light theme with CSS custom properties
- Smart polling with per-endpoint intervals
- Modal system with focus trap
- Responsive design (mobile-first)

### Static Assets
- `static/main.css` — Design system
- `static/app.js` — Alpine.js application
- `static/alpinejs.min.js` — Alpine.js library
- `static/tailwindcss.min.js` — Tailwind CSS CDN build

### Templates
- `templates/base.html` — Dashboard base template
- `templates/login_base.html` — Login base template

### Polling Intervals
- Status/Bridge: 5s
- Calendar/Polls/Rate Limits/Intents/Memory: 10s
- Logs: 30s

## STRUCTURE

```
web_console/
├── server.py           # ConsoleServer — asyncio HTTP server
├── dashboard.py        # render_dashboard() + render_login_page() — Python HTML templates
├── state_collector.py  # Collects bot state for the dashboard
├── templates/          # Base templates (dashboard + login)
├── static/             # CSS, JS, and vendored libraries
└── __init__.py
```

## WHERE TO LOOK

| Task | File |
|------|------|
| Add new dashboard card | `dashboard.py` + `state_collector.py` |
| Add new API endpoint | `server.py` — `handle_request()` |
| Change auth behavior | `server.py` — `_is_authenticated()`, `/api/login` |
| Change data collection | `state_collector.py` |
| Change styling | `static/main.css` + `templates/base.html` |
| Change frontend behavior | `static/app.js` |

## CONVENTIONS

- Python string templates loaded at runtime from `dashboard.py`
- Auth: `X-API-Key` header for API clients, cookie session (`console_auth`) for browsers
- `ConsoleServer` receives `monitor=None` initially, updated after `on_ready()`
- `/health` is auth-exempt
- Login form posts to `/api/login` which validates key and sets HttpOnly cookie
- All dashboard cards use `data-metric` attributes for client-side updates
- Initial state delivered via `<script id="initial-data" type="application/json">`

## ANTI-PATTERNS

- **Do not** serve the dashboard without auth — always check `_is_authenticated()`
- **Do not** forget to update `self.console_server.monitor` in `start_console()` after `on_ready()`
- **Do not** add inline JavaScript in templates — use `static/app.js`

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
