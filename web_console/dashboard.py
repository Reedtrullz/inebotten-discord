"""Dashboard rendering for the Inebotten web console."""


def _safe(data: dict, *keys: str, default: str = "N/A") -> str:
    try:
        for key in keys:
            if data is None:
                return default
            data = data[key]
        if data is None:
            return default
        return str(data)
    except (KeyError, TypeError):
        return default


def _safe_int(data: dict, *keys: str, default: int = 0) -> int:
    try:
        for key in keys:
            if data is None:
                return default
            data = data[key]
        if data is None:
            return default
        return int(data)
    except (KeyError, TypeError, ValueError):
        return default


def _uptime_fmt(seconds: int) -> str:
    if seconds < 0:
        return "N/A"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}t")
    if mins:
        parts.append(f"{mins}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def _status_badge(status: str) -> str:
    s = (status or "").lower()
    if s in ("online", "connected", "ok", "healthy"):
        return "ok"
    if s in ("offline", "disconnected", "error", "unhealthy"):
        return "error"
    return "warn"


def render_login_page(error: str | None = None) -> str:
    error_html = f'<div class="error">{error}</div>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="no">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Inebotten Console - Logg inn</title>
<style>
  :root {{
    --bg: #1a1a2e;
    --bg-card: #16213e;
    --text: #e0e0e0;
    --text-muted: #a0a0b0;
    --accent: #e94560;
    --accent-secondary: #0f3460;
    --border: #2a2a4a;
    --radius: 8px;
    --font: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    line-height: 1.5;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    padding: 1.5rem;
  }}
  .login-card {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 2rem;
    width: 100%;
    max-width: 400px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.3);
  }}
  .login-card h1 {{
    font-size: 1.5rem;
    font-weight: 700;
    margin-bottom: 0.5rem;
    color: var(--accent);
  }}
  .login-card p {{
    color: var(--text-muted);
    font-size: 0.875rem;
    margin-bottom: 1.5rem;
  }}
  label {{
    display: block;
    font-size: 0.875rem;
    font-weight: 600;
    margin-bottom: 0.5rem;
    color: var(--text-muted);
  }}
  input[type="password"] {{
    width: 100%;
    padding: 0.75rem 1rem;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text);
    font-size: 1rem;
    font-family: var(--font);
    margin-bottom: 1rem;
  }}
  input[type="password"]:focus {{
    outline: none;
    border-color: var(--accent);
  }}
  button {{
    width: 100%;
    padding: 0.75rem 1rem;
    background: var(--accent);
    border: none;
    border-radius: var(--radius);
    color: #fff;
    font-size: 1rem;
    font-weight: 600;
    font-family: var(--font);
    cursor: pointer;
    transition: opacity 0.2s;
  }}
  button:hover {{ opacity: 0.9; }}
  .error {{
    background: rgba(231, 76, 60, 0.15);
    color: #e74c3c;
    padding: 0.75rem 1rem;
    border-radius: var(--radius);
    font-size: 0.875rem;
    margin-bottom: 1rem;
  }}
  .hint {{
    margin-top: 1rem;
    font-size: 0.75rem;
    color: var(--text-muted);
    text-align: center;
  }}
</style>
</head>
<body>
<div class="login-card">
  <h1>Inebotten Console</h1>
  <p>Skriv inn API-nøkkelen for å fortsette</p>
  {error_html}
  <form method="POST" action="/api/login">
    <label for="api_key">API-nøkkel</label>
    <input type="password" id="api_key" name="api_key" placeholder="API-nøkkel" required autofocus>
    <button type="submit">Logg inn</button>
  </form>
  <p class="hint">Nøkkelen finner du i serverloggen eller som miljøvariabel <code>CONSOLE_API_KEY</code></p>
</div>
</body>
</html>"""


def render_dashboard(data: dict | None) -> str:
    if data is None:
        data = {}

    bot_status = _safe(data, "status", "status", default="ukjent")
    uptime_sec = _safe_int(data, "status", "uptime_seconds", default=-1)
    guilds = _safe(data, "status", "guilds")
    users = _safe(data, "status", "users")
    discord_connected = _safe(data, "status", "discord_connected")

    lm_status = _safe(data, "bridge", "lm_studio")
    bridge_reqs = _safe(data, "bridge", "requests")
    bridge_errs = _safe(data, "bridge", "errors")

    event_count = _safe(data, "calendar", "event_count")
    upcoming = data.get("calendar", {}).get("upcoming_events") if isinstance(data.get("calendar"), dict) else None
    task_count = _safe(data, "calendar", "task_count")

    active_polls = _safe(data, "polls", "active_polls")
    polls_list = data.get("polls", {}).get("polls") if isinstance(data.get("polls"), dict) else None

    rate_stats = data.get("rate_limits", {}).get("user_stats") if isinstance(data.get("rate_limits"), dict) else None

    intent_counts = data.get("intents", {}).get("intent_counts") if isinstance(data.get("intents"), dict) else None
    fallback_count = _safe(data, "intents", "fallback_count")

    mem_users = _safe(data, "memory", "user_count")
    mem_convs = _safe(data, "memory", "conversation_count")

    log_lines = data.get("logs", {}).get("logs", []) if isinstance(data.get("logs"), dict) else []
    logs_html = ""
    if isinstance(log_lines, list) and log_lines:
        logs_text = "\n".join(str(line) for line in log_lines)
        logs_html = f'<pre>{logs_text}</pre>'
    else:
        logs_html = '<p class="empty">Ingen logger tilgjengelig</p>'

    upcoming_rows = ""
    if isinstance(upcoming, list) and upcoming:
        for ev in upcoming:
            if not isinstance(ev, dict):
                continue
            title = ev.get("title") or ev.get("name") or "Uten tittel"
            when = ev.get("when") or ev.get("start") or ev.get("date") or "Ukjent tid"
            upcoming_rows += f"""<tr><td>{title}</td><td>{when}</td></tr>\n"""
    else:
        upcoming_rows = '<tr><td colspan="2" class="empty">Ingen kommende hendelser</td></tr>\n'

    polls_rows = ""
    if isinstance(polls_list, list) and polls_list:
        for p in polls_list:
            if not isinstance(p, dict):
                continue
            question = p.get("question") or p.get("title") or "Uten spørsmål"
            total = sum(v for v in (p.get("votes") or {}).values() if isinstance(v, int))
            polls_rows += f"""<tr><td>{question}</td><td>{total}</td></tr>\n"""
    else:
        polls_rows = '<tr><td colspan="2" class="empty">Ingen aktive avstemninger</td></tr>\n'

    rate_rows = ""
    if isinstance(rate_stats, dict) and rate_stats:
        for user, count in sorted(rate_stats.items(), key=lambda x: x[1], reverse=True):
            rate_rows += f"""<tr><td>{user}</td><td>{count}</td></tr>\n"""
    else:
        rate_rows = '<tr><td colspan="2" class="empty">Ingen rate-limit-data</td></tr>\n'

    intent_rows = ""
    if isinstance(intent_counts, dict) and intent_counts:
        for intent, count in sorted(intent_counts.items(), key=lambda x: x[1], reverse=True):
            intent_rows += f"""<tr><td>{intent}</td><td>{count}</td></tr>\n"""
    else:
        intent_rows = '<tr><td colspan="2" class="empty">Ingen intent-data</td></tr>\n'

    return f"""<!DOCTYPE html>
<html lang="no">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="30">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Inebotten Console</title>
<style>
  :root {{
    --bg: #1a1a2e;
    --bg-card: #16213e;
    --bg-table-head: #0f3460;
    --text: #e0e0e0;
    --text-muted: #a0a0b0;
    --accent: #e94560;
    --accent-secondary: #0f3460;
    --ok: #2ecc71;
    --warn: #f1c40f;
    --error: #e74c3c;
    --border: #2a2a4a;
    --radius: 8px;
    --font: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    line-height: 1.5;
    padding: 1.5rem;
  }}
  header {{
    margin-bottom: 1.5rem;
  }}
  header h1 {{
    font-size: 1.75rem;
    font-weight: 700;
    letter-spacing: -0.02em;
  }}
  header p {{
    color: var(--text-muted);
    font-size: 0.875rem;
    margin-top: 0.25rem;
  }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 1rem;
  }}
  .card {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1rem;
  }}
  .card h2 {{
    font-size: 1rem;
    font-weight: 600;
    margin-bottom: 0.75rem;
    color: var(--accent);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;
  }}
  th, td {{
    padding: 0.5rem 0.75rem;
    text-align: left;
  }}
  thead th {{
    background: var(--bg-table-head);
    font-weight: 600;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-muted);
  }}
  tbody tr:nth-child(even) {{ background: rgba(255,255,255,0.03); }}
  tbody tr:hover {{ background: rgba(255,255,255,0.06); }}
  .badge {{
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
  }}
  .badge.ok {{ background: rgba(46, 204, 113, 0.15); color: var(--ok); }}
  .badge.warn {{ background: rgba(241, 196, 15, 0.15); color: var(--warn); }}
  .badge.error {{ background: rgba(231, 76, 60, 0.15); color: var(--error); }}
  .empty {{ color: var(--text-muted); font-style: italic; }}
  .log-card {{ grid-column: 1 / -1; }}
  .log-card pre {{
    background: #0d1117;
    color: #c9d1d9;
    padding: 0.75rem;
    border-radius: var(--radius);
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
    font-size: 0.8125rem;
    line-height: 1.4;
    max-height: 400px;
    overflow: auto;
    white-space: pre-wrap;
    word-break: break-word;
  }}
  footer {{
    margin-top: 1.5rem;
    text-align: center;
    font-size: 0.75rem;
    color: var(--text-muted);
  }}
</style>
</head>
<body>
<header>
  <h1>Inebotten Console</h1>
  <p>Debug-oversikt &middot; Oppdateres hvert 30. sekund</p>
</header>
<main class="grid">
  <section class="card">
    <h2>Bot Status</h2>
    <table>
      <tbody>
        <tr><td>Status</td><td><span class="badge {_status_badge(bot_status)}">{bot_status}</span></td></tr>
        <tr><td>Oppetid</td><td>{_uptime_fmt(uptime_sec)}</td></tr>
        <tr><td>Servere</td><td>{guilds}</td></tr>
        <tr><td>Brukere</td><td>{users}</td></tr>
        <tr><td>Discord-tilkobling</td><td><span class="badge {_status_badge(discord_connected)}">{discord_connected}</span></td></tr>
      </tbody>
    </table>
  </section>

  <section class="card">
    <h2>Bridge</h2>
    <table>
      <tbody>
        <tr><td>LM Studio</td><td><span class="badge {_status_badge(lm_status)}">{lm_status}</span></td></tr>
        <tr><td>Forespørsler</td><td>{bridge_reqs}</td></tr>
        <tr><td>Feil</td><td>{bridge_errs}</td></tr>
      </tbody>
    </table>
  </section>

  <section class="card">
    <h2>Kalender</h2>
    <table>
      <tbody>
        <tr><td>Hendelser totalt</td><td>{event_count}</td></tr>
        <tr><td>Oppgaver</td><td>{task_count}</td></tr>
      </tbody>
    </table>
    <table style="margin-top:0.5rem">
      <thead><tr><th>Kommende hendelse</th><th>Tid</th></tr></thead>
      <tbody>
        {upcoming_rows}
      </tbody>
    </table>
  </section>

  <section class="card">
    <h2>Avstemninger</h2>
    <table>
      <tbody>
        <tr><td>Aktive avstemninger</td><td>{active_polls}</td></tr>
      </tbody>
    </table>
    <table style="margin-top:0.5rem">
      <thead><tr><th>Spørsmål</th><th>Stemmer</th></tr></thead>
      <tbody>
        {polls_rows}
      </tbody>
    </table>
  </section>

  <section class="card">
    <h2>Rate Limits</h2>
    <table>
      <thead><tr><th>Bruker</th><th>Antall</th></tr></thead>
      <tbody>
        {rate_rows}
      </tbody>
    </table>
  </section>

  <section class="card">
    <h2>Intents</h2>
    <table>
      <tbody>
        <tr><td>Fallbacks</td><td>{fallback_count}</td></tr>
      </tbody>
    </table>
    <table style="margin-top:0.5rem">
      <thead><tr><th>Intent</th><th>Antall</th></tr></thead>
      <tbody>
        {intent_rows}
      </tbody>
    </table>
  </section>

  <section class="card">
    <h2>Minne</h2>
    <table>
      <tbody>
        <tr><td>Brukere i minne</td><td>{mem_users}</td></tr>
        <tr><td>Samtaler</td><td>{mem_convs}</td></tr>
      </tbody>
    </table>
  </section>

  <section class="card log-card">
    <h2>Logger</h2>
    {logs_html}
  </section>
</main>
<footer>
  Inebotten &middot; Norsk Discord-selfbot &middot; Oppdatert nå
</footer>
</body>
</html>"""
