"""Dashboard rendering for the Inebotten web console."""

import json
from html import escape
from pathlib import Path
from typing import Any


_TEMPLATE_DIR = Path(__file__).with_name("templates")
_BASE_TEMPLATE = (_TEMPLATE_DIR / "base.html").read_text(encoding="utf-8")
_LOGIN_TEMPLATE = (_TEMPLATE_DIR / "login_base.html").read_text(encoding="utf-8")


def _safe(data: Any, *keys: str, default: str = "N/A") -> str:
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


def _safe_int(data: Any, *keys: str, default: int = 0) -> int:
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


def _status_badge(status: object) -> str:
    if isinstance(status, bool):
        return "ok" if status else "error"
    s = str(status or "").lower()
    if s in ("online", "connected", "ok", "healthy", "running", "active", "true", "yes"):
        return "ok"
    if s in ("offline", "disconnected", "error", "unhealthy", "stopped", "inactive", "false", "no"):
        return "error"
    return "warn"


def _render_badge(value: object) -> str:
    if isinstance(value, bool):
        text = "Ja" if value else "Nei"
    else:
        text = escape(str(value))
    return f'<span class="badge {_status_badge(value)}">{text}</span>'


def _render_row(label: str, value: object) -> str:
    return f"<tr><td>{escape(label)}</td><td>{value}</td></tr>"


def _render_table(headers: tuple[str, ...], rows: list[str], empty_message: str, *, style: str = "") -> str:
    if rows:
        body = "\n".join(rows)
    else:
        body = f'<tr><td colspan="{len(headers)}" class="empty">{escape(empty_message)}</td></tr>'
    header_html = "".join(f"<th>{escape(header)}</th>" for header in headers)
    style_attr = f' style="{escape(style)}"' if style else ""
    return f"<table{style_attr}><thead><tr>{header_html}</tr></thead><tbody>{body}</tbody></table>"


def _render_pairs(mapping: object, empty_message: str) -> list[str]:
    if not isinstance(mapping, dict) or not mapping:
        return []

    def _sort_value(value: Any) -> tuple[int, object]:
        if isinstance(value, (int, float)):
            return (0, value)
        try:
            return (0, float(value))
        except (TypeError, ValueError):
            return (1, str(value))

    rows: list[str] = []
    for key, value in sorted(mapping.items(), key=lambda item: _sort_value(item[1]), reverse=True):
        rows.append(_render_row(str(key), escape(str(value))))
    return rows


def _render_event_rows(upcoming: object) -> list[str]:
    rows: list[str] = []
    if not isinstance(upcoming, list):
        return rows
    for event in upcoming:
        if not isinstance(event, dict):
            continue
        title = escape(str(event.get("title") or event.get("name") or "Uten tittel"))
        when = escape(str(event.get("when") or event.get("start") or event.get("date") or "Ukjent tid"))
        rows.append(f"<tr><td>{title}</td><td>{when}</td></tr>")
    return rows


def _render_poll_rows(polls: object) -> list[str]:
    rows: list[str] = []
    if not isinstance(polls, list):
        return rows
    for poll in polls:
        if not isinstance(poll, dict):
            continue
        question = escape(str(poll.get("question") or poll.get("title") or "Uten spørsmål"))
        votes = poll.get("votes") or {}
        total = sum(v for v in votes.values() if isinstance(v, int)) if isinstance(votes, dict) else 0
        rows.append(f"<tr><td>{question}</td><td>{total}</td></tr>")
    return rows


def _render_log_block(log_lines: object) -> str:
    if not isinstance(log_lines, list) or not log_lines:
        return '<p class="text-sm text-[var(--text-muted)] text-center py-4">Ingen logger tilgjengelig</p>'

    def _colorize_log(line: str) -> str:
        upper = line.upper()
        if "ERROR" in upper or "CRITICAL" in upper:
            return f'<span class="text-red-500">{escape(line)}</span>'
        elif "WARN" in upper:
            return f'<span class="text-yellow-500">{escape(line)}</span>'
        elif "INFO" in upper:
            return f'<span class="text-slate-400">{escape(line)}</span>'
        else:
            return f'<span class="text-slate-500">{escape(line)}</span>'

    colored_logs = "\n".join(_colorize_log(str(line)) for line in log_lines)
    return f'<pre class="whitespace-pre-wrap break-words">{colored_logs}</pre>'


def _initial_data_script(data: Any) -> str:
    payload = json.dumps(data or {}, ensure_ascii=False, separators=(",", ":"), default=str)
    payload = payload.replace("<", "\\u003c")
    return f'<script id="initial-data" type="application/json">{payload}</script>'


def _dashboard_header() -> str:
    return ""


def _dashboard_footer() -> str:
    return "Inebotten &middot; Norsk Discord-selfbot"


def _render_status_section(data: dict[str, Any]) -> str:
    bot_status = _safe(data, "status", "status", default="ukjent")
    uptime_sec = _safe_int(data, "status", "uptime_seconds", default=-1)
    guilds = _safe(data, "status", "guilds")
    users = _safe(data, "status", "users")
    discord_connected = _safe(data, "status", "discord_connected")

    status_lower = str(bot_status).lower()
    if status_lower == "online":
        badge_class = "badge-online"
        badge_text = "Online"
    else:
        badge_class = "badge-error"
        badge_text = "Offline"

    dc_text = "Ja" if discord_connected in (True, "true", "yes", "ja", "connected") else "Nei"

    return f"""<section class="card" id="status">
  <div class="flex items-center justify-between mb-4">
    <h2 class="text-lg font-semibold">Bot Status</h2>
    <span class="badge {badge_class}">{badge_text}</span>
  </div>
  <div class="card-body">
    <div class="grid grid-cols-2 gap-4">
      <div class="metric">
        <div class="text-sm text-[var(--text-muted)]">Oppetid</div>
        <div class="text-xl font-bold text-[var(--text-primary)]" data-metric="status.uptime">{escape(_uptime_fmt(uptime_sec))}</div>
      </div>
      <div class="metric">
        <div class="text-sm text-[var(--text-muted)]">Servere</div>
        <div class="text-xl font-bold text-[var(--text-primary)]" data-metric="status.guilds">{escape(guilds)}</div>
      </div>
      <div class="metric">
        <div class="text-sm text-[var(--text-muted)]">Brukere</div>
        <div class="text-xl font-bold text-[var(--text-primary)]" data-metric="status.users">{escape(users)}</div>
      </div>
      <div class="metric">
        <div class="text-sm text-[var(--text-muted)]">Discord</div>
        <div class="text-xl font-bold text-[var(--text-primary)]" data-metric="status.discord">{dc_text}</div>
      </div>
    </div>
  </div>
  <div class="card-footer">
    <button class="btn text-xs py-1 px-3" @click="showSectionModal('status')">Detaljer</button>
  </div>
</section>"""


def _render_bridge_section(data: dict[str, Any]) -> str:
    bridge_status = _safe(data, "bridge", "status", default="ukjent")
    lm_status = _safe(data, "bridge", "lm_studio")
    bridge_reqs = _safe(data, "bridge", "requests")
    bridge_errs = _safe(data, "bridge", "errors")

    status_lower = str(bridge_status).lower()
    if status_lower in ("online", "connected", "ok", "healthy", "running", "active", "true", "yes"):
        badge_class = "badge-online"
        badge_text = "Tilkoblet"
    elif status_lower in ("offline", "disconnected", "error", "unhealthy", "stopped", "inactive", "false", "no"):
        badge_class = "badge-error"
        badge_text = "Frakoblet"
    else:
        badge_class = "badge-warning"
        badge_text = "Ukjent"

    err_val = _safe_int(data, "bridge", "errors", default=0)
    err_class = "text-[var(--status-error)]" if err_val > 0 else "text-[var(--text-primary)]"

    return f"""<section class="card" id="bridge">
  <div class="flex items-center justify-between mb-4">
    <h2 class="text-lg font-semibold">Bridge</h2>
    <span class="badge {badge_class}">{badge_text}</span>
  </div>
  <div class="card-body">
    <div class="grid grid-cols-2 gap-4">
      <div class="metric">
        <div class="text-sm text-[var(--text-muted)]">Status</div>
        <div class="text-lg font-bold text-[var(--text-primary)] truncate">{escape(str(bridge_status))}</div>
      </div>
      <div class="metric">
        <div class="text-sm text-[var(--text-muted)]">LM Studio</div>
        <div class="text-lg font-bold text-[var(--text-primary)] truncate" data-metric="bridge.lm_studio">{escape(str(lm_status))}</div>
      </div>
      <div class="metric">
        <div class="text-sm text-[var(--text-muted)]">Forespørsler</div>
        <div class="text-lg font-bold text-[var(--text-primary)]" data-metric="bridge.requests">{escape(bridge_reqs)}</div>
      </div>
      <div class="metric">
        <div class="text-sm text-[var(--text-muted)]">Feil</div>
        <div class="text-lg font-bold {err_class}" data-metric="bridge.errors">{escape(bridge_errs)}</div>
      </div>
    </div>
  </div>
  <div class="card-footer">
    <button class="btn text-xs py-1 px-3" @click="showSectionModal('bridge')">Detaljer</button>
  </div>
</section>"""


def _render_calendar_section(data: dict[str, Any]) -> str:
    event_count = _safe(data, "calendar", "event_count")
    task_count = _safe(data, "calendar", "task_count")
    upcoming = data.get("calendar", {}).get("upcoming_events") if isinstance(data.get("calendar"), dict) else None

    upcoming_html = ""
    if isinstance(upcoming, list) and upcoming:
        items = []
        for event in upcoming[:3]:
            if not isinstance(event, dict):
                continue
            title = escape(str(event.get("title") or event.get("name") or "Uten tittel"))
            when = escape(str(event.get("when") or event.get("start") or event.get("date") or "Ukjent tid"))
            items.append(
                f"""        <div class="flex items-center gap-2 py-1.5 border-b border-[var(--border-color)] last:border-0">
          <span class="text-sm text-[var(--text-primary)] truncate flex-1 min-w-0">{title}</span>
          <span class="text-xs text-[var(--text-muted)] whitespace-nowrap">{when}</span>
        </div>"""
            )
        upcoming_html = f"""    <div class="mt-3">
      <div class="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-1">Kommende</div>
{chr(10).join(items)}
    </div>"""

    return f"""<section class="card" id="calendar">
  <div class="flex items-center justify-between mb-4">
    <h2 class="text-lg font-semibold">Kalender</h2>
    <span class="badge badge-info">{escape(event_count)} hendelser</span>
  </div>
  <div class="card-body">
    <div class="grid grid-cols-2 gap-4">
      <div class="metric">
        <div class="text-sm text-[var(--text-muted)]">Hendelser</div>
        <div class="text-xl font-bold text-[var(--text-primary)]" data-metric="calendar.events">{escape(event_count)}</div>
      </div>
      <div class="metric">
        <div class="text-sm text-[var(--text-muted)]">Oppgaver</div>
        <div class="text-xl font-bold text-[var(--text-primary)]" data-metric="calendar.tasks">{escape(task_count)}</div>
      </div>
    </div>
{upcoming_html}
  </div>
  <div class="card-footer">
    <button class="btn text-xs py-1 px-3" @click="showSectionModal('calendar')">Vis alle</button>
  </div>
</section>"""


def _render_polls_section(data: dict[str, Any]) -> str:
    active_polls = _safe(data, "polls", "active_polls")
    polls_list = data.get("polls", {}).get("polls") if isinstance(data.get("polls"), dict) else None

    polls_html = ""
    if isinstance(polls_list, list) and polls_list:
        poll_items = []
        for poll in polls_list[:1]:
            if not isinstance(poll, dict):
                continue
            question = escape(str(poll.get("question") or poll.get("title") or "Uten spørsmål"))
            votes = poll.get("votes") or {}
            if isinstance(votes, dict):
                total = sum(v for v in votes.values() if isinstance(v, (int, float)))
                bars = []
                for option, count in votes.items():
                    pct = (count / total * 100) if total > 0 else 0
                    bars.append(
                        f"""            <div class="mt-1">
              <div class="flex items-center justify-between text-xs">
                <span class="text-[var(--text-secondary)]">{escape(str(option))}</span>
                <span class="text-[var(--text-muted)]">{count} ({pct:.0f}%)</span>
              </div>
              <div class="w-full h-2 rounded-full mt-1" style="background:var(--bg-tertiary)">
                <div class="h-2 rounded-full transition-all duration-500" style="width:{pct:.1f}%;background:var(--accent)"></div>
              </div>
            </div>"""
                    )
                poll_items.append(
                    f"""        <div class="py-3 border-b border-[var(--border-color)] last:border-0">
          <div class="text-sm font-medium text-[var(--text-primary)]">{question}</div>
          <div class="mt-2">{''.join(bars)}</div>
        </div>"""
                )
            else:
                poll_items.append(
                    f"""        <div class="py-3 border-b border-[var(--border-color)] last:border-0">
          <div class="text-sm font-medium text-[var(--text-primary)]">{question}</div>
        </div>"""
                )
        polls_html = f"""    <div class="mt-4">
      <div class="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">Aktive avstemninger</div>
{chr(10).join(poll_items)}
    </div>"""
    else:
        polls_html = '    <div class="mt-4 text-sm text-[var(--text-muted)]">Ingen aktive avstemninger</div>'

    return f"""<section class="card" id="polls">
  <div class="flex items-center justify-between mb-4">
    <h2 class="text-lg font-semibold">Avstemninger</h2>
    <span class="badge badge-info"><span data-metric="polls.active">{escape(active_polls)}</span> aktive</span>
  </div>
  <div class="card-body">
{polls_html}
  </div>
  <div class="card-footer">
    <button class="btn text-xs py-1 px-3" @click="showSectionModal('polls')">Vis alle</button>
  </div>
</section>"""


def _render_rate_limits_section(data: dict[str, Any]) -> str:
    rate_limits = data.get("rate_limits", {}) if isinstance(data.get("rate_limits"), dict) else {}
    summary = rate_limits.get("summary") if isinstance(rate_limits, dict) else None
    user_stats = rate_limits.get("user_stats") if isinstance(rate_limits, dict) else None
    total_requests = _safe_int(rate_limits, "summary", "total_requests", default=0)

    table_html = ""
    if isinstance(user_stats, dict) and user_stats:
        numeric_values = [v for v in user_stats.values() if isinstance(v, (int, float))]
        max_count = max(numeric_values) if numeric_values else 1
        user_rows_html: list[str] = []
        for user, count in sorted(user_stats.items(), key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0, reverse=True)[:5]:
            pct = min((count / max_count) * 100, 100) if max_count else 0
            user_rows_html.append(
                f'<tr class="border-b border-[var(--border-color)] hover:bg-[var(--bg-hover)]">'
                + f'<td class="py-2 px-4 text-sm text-[var(--text-primary)]">{escape(str(user))}</td>'
                + f'<td class="py-2 px-4 text-sm text-[var(--text-secondary)]">{escape(str(count))}</td>'
                + f'<td class="py-2 px-4 w-24">'
                + f'<div class="w-full bg-gray-700 rounded h-1.5">'
                + f'<div class="bg-blue-500 h-1.5 rounded" style="width: {pct:.0f}%"></div>'
                + f'</div>'
                + f'</td>'
                + f'</tr>'
            )
        table_html = f"""<div class="overflow-x-auto">
      <table class="w-full border-collapse text-sm">
        <thead>
          <tr class="border-b border-[var(--border-color)]">
            <th class="py-2 px-4 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">Bruker</th>
            <th class="py-2 px-4 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">Antall</th>
            <th class="py-2 px-4 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">Bruk</th>
          </tr>
        </thead>
        <tbody>{''.join(user_rows_html)}</tbody>
      </table>
    </div>"""
    else:
        table_html = '<div class="text-sm text-[var(--text-muted)] text-center py-6">Ingen rate-limit-data</div>'

    return f"""<section class="card" id="rate-limits">
  <div class="flex items-center justify-between gap-2 mb-4">
    <h2 class="text-lg font-semibold text-[var(--text-primary)] truncate">Rate Limits</h2>
    <span class="text-sm text-[var(--text-muted)] whitespace-nowrap"><span data-metric="rate_limits.total">{total_requests}</span> totalt</span>
  </div>
  <div class="card-body">
    {table_html}
  </div>
  <div class="card-footer flex justify-end">
    <button class="btn text-xs px-3 py-1.5" @click="showSectionModal('rate-limits')">Detaljer</button>
  </div>
</section>"""


def _render_intents_section(data: dict[str, Any]) -> str:
    intent_counts = data.get("intents", {}).get("intent_counts") if isinstance(data.get("intents"), dict) else None
    fallback_count = _safe_int(data, "intents", "fallback_count", default=0)
    fallback_badge_class = "badge-error" if fallback_count > 5 else "badge-info"

    table_html = ""
    if isinstance(intent_counts, dict) and intent_counts:
        intent_rows_html: list[str] = []
        for intent, count in sorted(intent_counts.items(), key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0, reverse=True)[:5]:
            intent_rows_html.append(
                f'<tr class="border-b border-[var(--border-color)] hover:bg-[var(--bg-hover)]">'
                + f'<td class="py-2 px-4 text-sm text-[var(--text-primary)]">{escape(str(intent))}</td>'
                + f'<td class="py-2 px-4 text-sm text-[var(--text-secondary)]">{escape(str(count))}</td>'
                + f'</tr>'
            )
        table_html = f"""<div class="overflow-x-auto">
      <table class="w-full border-collapse text-sm">
        <thead>
          <tr class="border-b border-[var(--border-color)]">
            <th class="py-2 px-4 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">Intent</th>
            <th class="py-2 px-4 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">Antall</th>
          </tr>
        </thead>
        <tbody>{''.join(intent_rows_html)}</tbody>
      </table>
    </div>"""
    else:
        table_html = '<div class="text-sm text-[var(--text-muted)] text-center py-6">Ingen intent-data</div>'

    return f"""<section class="card" id="intents">
  <div class="flex items-center justify-between gap-2 mb-4">
    <h2 class="text-lg font-semibold text-[var(--text-primary)] truncate">Intents</h2>
    <span class="badge {fallback_badge_class} whitespace-nowrap">Fallbacks: <span data-metric="intents.fallback">{fallback_count}</span></span>
  </div>
  <div class="card-body">
    {table_html}
  </div>
  <div class="card-footer flex justify-end">
    <button class="btn text-xs px-3 py-1.5" @click="showSectionModal('intents')">Detaljer</button>
  </div>
</section>"""


def _render_memory_section(data: dict[str, Any]) -> str:
    mem_users = _safe_int(data, "memory", "user_count", default=0)
    mem_convs = _safe_int(data, "memory", "conversation_count", default=0)

    return f"""<section class="card" id="memory">
  <div class="flex items-center justify-between mb-4">
    <h2 class="text-lg font-semibold text-[var(--text-primary)]">Minne</h2>
  </div>
  <div class="card-body">
    <div class="grid grid-cols-2 gap-4">
      <div class="bg-[var(--bg-secondary)] rounded-lg p-4 text-center border border-[var(--border-color)]">
        <div class="text-2xl font-bold text-[var(--accent)]" data-metric="memory.users">{mem_users}</div>
        <div class="text-sm text-[var(--text-muted)] mt-1">Brukere</div>
      </div>
      <div class="bg-[var(--bg-secondary)] rounded-lg p-4 text-center border border-[var(--border-color)]">
        <div class="text-2xl font-bold text-[var(--accent)]" data-metric="memory.conversations">{mem_convs}</div>
        <div class="text-sm text-[var(--text-muted)] mt-1">Samtaler</div>
      </div>
    </div>
  </div>
  <div class="card-footer flex justify-end">
    <button class="btn text-xs px-3 py-1.5" @click="showSectionModal('memory')">Detaljer</button>
  </div>
</section>"""


def _render_logs_section(data: dict[str, Any]) -> str:
    log_lines = data.get("logs", {}).get("logs", []) if isinstance(data.get("logs"), dict) else []
    line_count = len(log_lines) if isinstance(log_lines, list) else 0
    return f"""<section class="card" id="logs">
  <div class="flex items-center justify-between mb-4">
    <h2 class="text-lg font-semibold text-[var(--text-primary)]">Logger</h2>
    <span class="text-sm text-[var(--text-muted)]">Siste <span data-metric="logs.count">{line_count}</span> linjer</span>
  </div>
  <div class="card-body">
    <div class="max-h-48 overflow-y-auto font-mono text-sm bg-[var(--bg-secondary)] rounded-lg p-4 border border-[var(--border-color)] log-fade">
      {_render_log_block(log_lines)}
    </div>
  </div>
  <div class="card-footer flex justify-end">
    <button class="btn text-xs px-3 py-1.5" @click="showSectionModal('logs')">Vis alle</button>
  </div>
</section>"""


def render_login_page(error: str | None = None) -> str:
    error_html = f'<div class="badge badge-error w-full justify-center mb-4" role="alert">{escape(error)}</div>' if error else ""
    main_content = f"""<div class="card relative">
  <button type="button" class="btn-secondary absolute top-4 right-4 px-2 py-1 text-lg" onclick="toggleTheme()" aria-label="Bytt tema">
    <span id="theme-icon">☀️</span>
  </button>
  <div class="flex items-center justify-center mb-6">
    <div class="w-12 h-12 rounded-full bg-[var(--accent)] flex items-center justify-center text-white text-xl font-bold mr-3" style="box-shadow: var(--shadow-glow)">
      🤖
    </div>
    <div>
      <h1 class="text-2xl font-bold text-[var(--text-primary)]">Inebotten Console</h1>
      <p class="text-sm text-[var(--text-secondary)]">Norsk Discord-selfbot</p>
    </div>
  </div>
  <p class="text-[var(--text-secondary)] mb-4 text-center">Skriv inn API-nøkkelen for å fortsette</p>
  {error_html}
  <form method="POST" action="/api/login" class="space-y-4">
    <div>
      <label for="api_key" class="block text-sm font-medium text-[var(--text-secondary)] mb-1">API-nøkkel</label>
      <input type="password" id="api_key" name="api_key" placeholder="API-nøkkel" required autofocus class="input">
    </div>
    <button type="submit" class="btn w-full">Logg inn</button>
  </form>
</div>
<script>
function toggleTheme() {{
  var html = document.documentElement;
  var isLight = html.classList.contains('light');
  var icon = document.getElementById('theme-icon');
  if (isLight) {{
    html.classList.remove('light');
    localStorage.setItem('theme', 'dark');
    if (icon) icon.textContent = '☀️';
  }} else {{
    html.classList.add('light');
    localStorage.setItem('theme', 'light');
    if (icon) icon.textContent = '🌙';
  }}
}}
(function() {{
  var html = document.documentElement;
  var isLight = html.classList.contains('light');
  var icon = document.getElementById('theme-icon');
  if (icon) icon.textContent = isLight ? '🌙' : '☀️';
}})();
</script>"""
    return _LOGIN_TEMPLATE.format(
        title="Inebotten Console - Logg inn",
        header_content="",
        main_content=main_content,
        footer_content='<p class="hint">Nøkkelen finner du i serverloggen eller som miljøvariabel <code>CONSOLE_API_KEY</code></p>',
        body_class="auth-page",
        refresh_meta="",
        initial_data_script="",
    )


def render_dashboard(data: dict[str, Any] | None) -> str:
    if data is None:
        data = {}

    main_content = "\n".join(
        [
            _render_status_section(data),
            _render_bridge_section(data),
            _render_calendar_section(data),
            _render_polls_section(data),
            _render_rate_limits_section(data),
            _render_intents_section(data),
            _render_memory_section(data),
            _render_logs_section(data),
        ]
    )

    return _BASE_TEMPLATE.format(
        title="Inebotten Console",
        header_content=_dashboard_header(),
        main_content=main_content,
        footer_content=_dashboard_footer(),
        body_class="dashboard-page",
        refresh_meta="",
        initial_data_script=_initial_data_script(data),
    )
