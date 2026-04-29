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
            return f'<span class="text-[var(--status-error)]">{escape(line)}</span>'
        elif "WARN" in upper:
            return f'<span class="text-[var(--status-warning)]">{escape(line)}</span>'
        elif "INFO" in upper:
            return f'<span class="text-[var(--log-text-info)]">{escape(line)}</span>'
        else:
            return f'<span class="text-[var(--log-text-debug)]">{escape(line)}</span>'

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
    mem_users = _safe_int(data, "memory", "user_count", default=0)
    mem_convs = _safe_int(data, "memory", "conversation_count", default=0)

    status_lower = str(bot_status).lower()
    if status_lower == "online":
        badge_class = "badge-online"
        badge_text = "Online"
    else:
        badge_class = "badge-error"
        badge_text = "Offline"

    dc_text = "Ja" if discord_connected in (True, "true", "yes", "ja", "connected") else "Nei"

    return f"""<section class="card xl:col-span-2 scroll-mt-24" id="status">
  <div class="flex items-center justify-between gap-3 mb-4">
    <h2 class="text-lg font-semibold">Bot Status</h2>
    <span class="badge {badge_class}">{badge_text}</span>
  </div>
  <div class="card-body">
    <div class="grid grid-cols-3 gap-4">
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
      <div class="metric">
        <div class="text-sm text-[var(--text-muted)]">Minne brukere</div>
        <div class="text-xl font-bold text-[var(--accent)]" data-metric="memory.users">{mem_users}</div>
      </div>
      <div class="metric">
        <div class="text-sm text-[var(--text-muted)]">Samtaler</div>
        <div class="text-xl font-bold text-[var(--accent)]" data-metric="memory.conversations">{mem_convs}</div>
      </div>
    </div>
  </div>
  <div class="card-footer flex justify-end">
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

    return f"""<section class="card xl:col-span-2 scroll-mt-24" id="bridge">
  <div class="flex items-center justify-between gap-3 mb-4">
    <h2 class="text-lg font-semibold">Bridge</h2>
    <span class="badge {badge_class}">{badge_text}</span>
  </div>
  <div class="card-body">
    <div class="grid grid-cols-2 gap-5">
      <div class="metric">
        <div class="text-sm text-[var(--text-muted)]">Status</div>
        <div class="text-2xl font-bold text-[var(--text-primary)] break-words">{escape(str(bridge_status))}</div>
      </div>
      <div class="metric">
        <div class="text-sm text-[var(--text-muted)]">LM Studio</div>
        <div class="text-2xl font-bold text-[var(--text-primary)] break-words" data-metric="bridge.lm_studio">{escape(str(lm_status))}</div>
      </div>
      <div class="metric">
        <div class="text-sm text-[var(--text-muted)]">Forespørsler</div>
        <div class="text-2xl font-bold text-[var(--text-primary)]" data-metric="bridge.requests">{escape(bridge_reqs)}</div>
      </div>
      <div class="metric">
        <div class="text-sm text-[var(--text-muted)]">Feil</div>
        <div class="text-2xl font-bold {err_class}" data-metric="bridge.errors">{escape(bridge_errs)}</div>
      </div>
    </div>
  </div>
  <div class="card-footer flex justify-end">
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
      <div class="text-sm font-medium text-[var(--text-muted)] mb-1">Kommende</div>
{chr(10).join(items)}
    </div>"""

    return f"""<section class="card scroll-mt-24" id="calendar">
  <div class="flex items-center justify-between gap-3 mb-4">
    <h2 class="text-lg font-semibold">Kalender</h2>
    <span class="badge badge-info">{escape(event_count)} hendelser</span>
  </div>
  <div class="card-body">
    <div class="grid grid-cols-2 gap-4">
      <div class="metric">
        <div class="text-sm text-[var(--text-muted)]">Hendelser</div>
        <div class="text-2xl font-bold text-[var(--text-primary)]" data-metric="calendar.events">{escape(event_count)}</div>
      </div>
      <div class="metric">
        <div class="text-sm text-[var(--text-muted)]">Oppgaver</div>
        <div class="text-2xl font-bold text-[var(--text-primary)]" data-metric="calendar.tasks">{escape(task_count)}</div>
      </div>
    </div>
{upcoming_html}
  </div>
  <div class="card-footer flex justify-end">
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
                        f"""            <div class="grid grid-cols-[3rem_1fr_auto] gap-2 items-center mt-1">
              <span class="text-xs text-[var(--text-secondary)] truncate">{escape(str(option))}</span>
              <div class="h-1.5 rounded-full" style="background:var(--bg-tertiary)">
                <div class="h-1.5 rounded-full transition-all duration-500" style="width:{pct:.1f}%;background:var(--accent)"></div>
              </div>
              <span class="text-xs text-[var(--text-muted)] whitespace-nowrap">{count}</span>
            </div>"""
                    )
                poll_items.append(
                    f"""        <div class="py-2 border-b border-[var(--border-color)] last:border-0">
          <div class="text-sm font-medium text-[var(--text-primary)]">{question}</div>
          <div class="mt-1">{''.join(bars)}</div>
        </div>"""
                )
            else:
                poll_items.append(
                    f"""        <div class="py-2 border-b border-[var(--border-color)] last:border-0">
          <div class="text-sm font-medium text-[var(--text-primary)]">{question}</div>
        </div>"""
                )
        polls_html = f"""    <div class="mt-2">
{chr(10).join(poll_items)}
    </div>"""
    else:
        polls_html = '    <div class="mt-2 text-sm text-[var(--text-muted)]">Ingen aktive avstemninger</div>'

    return f"""<section class="card scroll-mt-24" id="polls">
  <div class="flex items-center justify-between gap-3 mb-4">
    <h2 class="text-lg font-semibold">Avstemninger</h2>
    <span class="badge badge-info"><span data-metric="polls.active">{escape(active_polls)}</span> aktive</span>
  </div>
  <div class="card-body">
{polls_html}
  </div>
  <div class="card-footer flex justify-end">
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
        table_html = f"""<div class="overflow-x-auto rounded-lg border border-[var(--border-color)]">
      <table class="w-full border-collapse text-sm">
        <thead>
          <tr class="border-b border-[var(--border-color)] bg-[var(--bg-secondary)]">
            <th class="py-2 px-4 text-left text-sm font-medium text-[var(--text-secondary)]">Bruker</th>
            <th class="py-2 px-4 text-left text-sm font-medium text-[var(--text-secondary)]">Antall</th>
            <th class="py-2 px-4 text-left text-sm font-medium text-[var(--text-secondary)]">Bruk</th>
          </tr>
        </thead>
        <tbody>{''.join(user_rows_html)}</tbody>
      </table>
    </div>"""
    else:
        table_html = '<div class="py-8 text-center text-sm text-[var(--text-muted)]">Ingen rate-limit-data</div>'

    return f"""<section class="card scroll-mt-24" id="rate-limits">
  <div class="flex items-center justify-between gap-3 mb-4">
    <h2 class="text-lg font-semibold text-[var(--text-primary)]">Rate Limits</h2>
    <span class="badge badge-info whitespace-nowrap gap-1"><span data-metric="rate_limits.total">{total_requests}</span><span>totalt</span></span>
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
        table_html = f"""<div class="overflow-x-auto rounded-lg border border-[var(--border-color)]">
      <table class="w-full border-collapse text-sm">
        <thead>
          <tr class="border-b border-[var(--border-color)] bg-[var(--bg-secondary)]">
            <th class="py-2 px-4 text-left text-sm font-medium text-[var(--text-secondary)]">Intent</th>
            <th class="py-2 px-4 text-left text-sm font-medium text-[var(--text-secondary)]">Antall</th>
          </tr>
        </thead>
        <tbody>{''.join(intent_rows_html)}</tbody>
      </table>
    </div>"""
    else:
        table_html = '<div class="py-8 text-center text-sm text-[var(--text-muted)]">Ingen intent-data</div>'

    return f"""<section class="card scroll-mt-24" id="intents">
  <div class="flex items-center justify-between gap-3 mb-4">
    <h2 class="text-lg font-semibold text-[var(--text-primary)]">Intents</h2>
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

    return f"""<section class="card xl:col-span-2 scroll-mt-24" id="memory">
  <div class="flex items-center justify-between gap-3 mb-4">
    <h2 class="text-lg font-semibold text-[var(--text-primary)]">Minne</h2>
  </div>
  <div class="card-body">
    <div class="grid grid-cols-2 gap-4">
      <div class="bg-[var(--bg-secondary)] rounded-lg p-4 text-center border border-[var(--border-color)]">
        <div class="text-3xl font-bold text-[var(--accent)]" data-metric="memory.users">{mem_users}</div>
        <div class="text-sm text-[var(--text-muted)] mt-2">Brukere</div>
      </div>
      <div class="bg-[var(--bg-secondary)] rounded-lg p-4 text-center border border-[var(--border-color)]">
        <div class="text-3xl font-bold text-[var(--accent)]" data-metric="memory.conversations">{mem_convs}</div>
        <div class="text-sm text-[var(--text-muted)] mt-2">Samtaler</div>
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
    return f"""<section class="card md:col-span-2 xl:col-span-4 scroll-mt-24" id="logs">
  <div class="flex items-center justify-between gap-3 mb-4">
    <h2 class="text-lg font-semibold text-[var(--text-primary)]">Logger</h2>
    <span class="badge badge-info gap-1"><span>Siste</span><span data-metric="logs.count">{line_count}</span><span>linjer</span></span>
  </div>
  <div class="card-body">
    <div id="log-container" class="max-h-80 overflow-y-auto font-mono text-sm bg-[var(--bg-secondary)] rounded-lg p-5 border border-[var(--border-color)]">
      {_render_log_block(log_lines)}
    </div>
  </div>
  <div class="card-footer flex justify-end gap-2">
    <button class="btn text-xs px-3 py-1.5" onclick="copyLogs()">Kopier</button>
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


def render_commands_page() -> str:
    sections = [
        (
            "💬 Samtale & AI",
            "Naturlige samtaler og AI-assisterte svar.",
            [
                ("@inebotten Hei! Hvordan går det?", "Generell AI-samtale"),
                ("@inebotten Hva synes du om RBK?", "AI-chat med kontekst"),
                ("@inebotten Fortell en vits", "Be om kreativt innhold"),
                ("@inebotten Hva er meningen med livet?", "Filosofiske spørsmål"),
            ],
        ),
        (
            "📅 Kalender",
            "Opprett, administrer og synkroniser hendelser.",
            [
                ("@inebotten møte med Ola i morgen kl 14", "Opprett hendelse med naturlig språk"),
                ("@inebotten lunsj hver fredag kl 12", "Opprett gjentagende hendelse"),
                ("@inebotten bursdag til mamma 15.05 hvert år", "Årlig gjentagelse"),
                ("@inebotten kalender", "Vis alle kommende hendelser (90 dager)"),
                ("@inebotten søk møte", "Søk etter hendelser"),
                ("@inebotten endre 1 tittel: Ny tittel dato: 15.05 kl 14", "Rediger hendelse"),
                ("@inebotten slett 2", "Slett hendelse etter nummer"),
                ("@inebotten slett spaghetti", "Slett etter delvis tittel"),
                ("@inebotten slett alle spaghetti", "Slett alle treff"),
                ("@inebotten slett alt", "Slett alt (krever bekreftelse)"),
                ("@inebotten ferdig 2", "Marker som fullført"),
                ("@inebotten ferdig meldekort", "Fullfør etter tittel"),
                ("@inebotten synk", "Synkroniser med Google Calendar"),
            ],
        ),
        (
            "🔔 Påminnelser",
            "Opprett og administrer påminnelser.",
            [
                ("@inebotten påminnelse Ring lege om 2 timer", "Opprett påminnelse"),
                ("@inebotten påminnelser", "Vis aktive påminnelser"),
                ("@inebotten endre påminnelse 1 om 1 time", "Rediger påminnelse"),
                ("@inebotten slett påminnelse 1", "Slett påminnelse"),
                ("@inebotten søk påminnelse lege", "Søk etter påminnelse"),
            ],
        ),
        (
            "📊 Avstemninger",
            "Opprett, stem og administrer avstemninger.",
            [
                ("@inebotten avstemning Pizza eller burger? Pepperoni, Margherita, Kebab", "Opprett avstemning"),
                ("@inebotten stem 1", "Stem på alternativ"),
                ("@inebotten polls", "Vis aktive avstemninger"),
                ("@inebotten endre poll 1", "Rediger avstemning"),
                ("@inebotten slett poll 1", "Slett avstemning"),
                ("@inebotten lukk poll 1", "Lukk avstemning"),
            ],
        ),
        (
            "💬 Sitater",
            "Inspirerende sitater og administrasjon.",
            [
                ("@inebotten sitat", "Tilfeldig sitat"),
                ("@inebotten sitater", "Vis alle sitater"),
                ("@inebotten endre sitat 1 tekst: Ny tekst forfatter: Ola", "Rediger sitat"),
                ("@inebotten slett sitat 1", "Slett sitat"),
            ],
        ),
        (
            "📺 Watchlist",
            "Spor kryptovaluta og aksjer.",
            [
                ("@inebotten watchlist", "Vis watchlist"),
                ("@inebotten watchlist AAPL", "Legg til ticker"),
                ("@inebotten endre watchlist 1 TSLA", "Endre ticker"),
                ("@inebotten fjern watchlist 1", "Fjern ticker"),
            ],
        ),
        (
            "🎂 Bursdager",
            "Husk bursdager med automatisk daglig oppsummering.",
            [
                ("@inebotten bursdag Ola 15.05", "Legg til bursdag"),
                ("@inebotten endre bursdag Ola 20.05", "Endre bursdag"),
                ("@inebotten bursdager", "Vis alle bursdager"),
            ],
        ),
        (
            "🌦️ Vær",
            "Værmeldinger og lokasjonslagring.",
            [
                ("@inebotten vær", "Værmelding for din lokasjon"),
                ("@inebotten været i Trondheim", "Vær for spesifikt sted"),
                ("@inebotten Jeg bor i Trondheim", "Lagre faste lokasjon"),
            ],
        ),
        (
            "💰 Krypto & Priser",
            "Sjekk kryptovaluta-priser.",
            [
                ("@inebotten pris BTC", "Sjekk kryptopris"),
                ("@inebotten pris ETH", "Støttede symboler: BTC, ETH, SOL, ADA, XRP, DOGE, m.fl."),
            ],
        ),
        (
            "🧮 Kalkulator",
            "Utfør matematiske beregninger.",
            [
                ("@inebotten kalk (100 * 1.25) / 2", "Regn ut uttrykk"),
            ],
        ),
        (
            "🔗 URL-forkorter",
            "Forkort lenker.",
            [
                ("@inebotten shorten https://example.com", "Forkort URL"),
            ],
        ),
        (
            "🔮 Horoskop",
            "Daglig horoskop.",
            [
                ("@inebotten horoskop væren", "Daglig horoskop"),
            ],
        ),
        (
            "💕 Komplimenter",
            "Send et kompliment.",
            [
                ("@inebotten kompliment", "Tilfeldig kompliment"),
            ],
        ),
        (
            "🌌 Nordlys",
            "Nordlysvarsel for ditt område.",
            [
                ("@inebotten nordlys", "Sjekk nordlysutsikter"),
            ],
        ),
        (
            "📖 Dagens ord",
            "Lær et nytt norsk ord.",
            [
                ("@inebotten dagens ord", "Norsk ord med definisjon"),
            ],
        ),
        (
            "📰 Daglig oppsummering",
            "Omfattende morgenbrief.",
            [
                ("@inebotten daglig oppsummering", "Vær, marked, kalender og bursdager"),
            ],
        ),
        (
            "⏱️ Nedtelling",
            "Nedtelling til hendelser.",
            [
                ("@inebotten nedtelling til 17. mai", "Nedtelling til dato"),
                ("@inebotten nedtelling til julaften", "Nedtelling til høytid"),
            ],
        ),
        (
            "🔍 Søk & Nettleser",
            "Søk på nettet og les artikler.",
            [
                ("@inebotten søk [spørring]", "Søk på nettet"),
                ("@inebotten les [URL]", "Hent artikkelinnhold"),
            ],
        ),
        (
            "👤 Profil",
            "Endre din Discord-status og aktivitet.",
            [
                ("@inebotten status", "Vis bot-helse"),
                ("@inebotten status dnd", "online, idle, dnd, invisible"),
                ("@inebotten spiller CS2", "Endre aktivitet"),
                ("@inebotten ser på Netflix", "Endre aktivitet"),
            ],
        ),
        (
            "🩺 Drift",
            "Bot-drift og diagnostikk.",
            [
                ("@inebotten bot status", "Uptime, AI-status, handlers, rate-limit"),
                ("@inebotten health", "Kort helsesjekk"),
            ],
        ),
        (
            "❓ Hjelp",
            "Få hjelp med botten.",
            [
                ("@inebotten hjelp", "Vis hjelpemelding"),
                ("@inebotten hva kan du gjøre", "Funksjonsoversikt"),
            ],
        ),
    ]

    def _render_cmd_section(title: str, description: str, commands: list[tuple[str, str]]) -> str:
        rows = "\n".join(
            f"<tr><td><code>{escape(cmd)}</code></td><td>{escape(desc)}</td></tr>"
            for cmd, desc in commands
        )
        return f"""<section class="card scroll-mt-24">
  <h2 class="text-lg font-semibold mb-2">{escape(title)}</h2>
  <p class="text-sm text-[var(--text-muted)] mb-4">{escape(description)}</p>
  <table>
    <thead><tr><th>Kommando</th><th>Beskrivelse</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>"""

    main_content = "\n".join(_render_cmd_section(t, d, c) for t, d, c in sections)

    return _BASE_TEMPLATE.format(
        title="Inebotten - Kommandoer",
        header_content="",
        main_content=main_content,
        footer_content="Inebotten &middot; Norsk Discord-selfbot",
        body_class="commands-page",
        refresh_meta="",
        initial_data_script="",
    )
