"""Dashboard rendering for the Inebotten web console."""

import json
from html import escape
from pathlib import Path
from typing import Any

from core.help_registry import HelpCategory, HelpExample, catalog_sections


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
        return "badge-online" if status else "badge-error"
    s = str(status or "").lower()
    if s in ("online", "connected", "ok", "healthy", "running", "active", "true", "yes"):
        return "badge-online"
    if s in ("offline", "disconnected", "error", "unhealthy", "stopped", "inactive", "false", "no"):
        return "badge-error"
    return "badge-warning"


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
        return '<p class="empty-state">Ingen logger tilgjengelig</p>'

    def _colorize_log(line: str) -> str:
        upper = line.upper()
        if "ERROR" in upper or "CRITICAL" in upper:
            return f'<span class="log-error">{escape(line)}</span>'
        elif "WARN" in upper:
            return f'<span class="log-warn">{escape(line)}</span>'
        elif "INFO" in upper:
            return f'<span class="log-info">{escape(line)}</span>'
        else:
            return f'<span class="log-debug">{escape(line)}</span>'

    colored_logs = "\n".join(_colorize_log(str(line)) for line in log_lines)
    return f"<pre>{colored_logs}</pre>"


def _initial_data_script(data: Any) -> str:
    payload = json.dumps(data or {}, ensure_ascii=False, separators=(",", ":"), default=str)
    payload = payload.replace("<", "\\u003c")
    return f'<script id="initial-data" type="application/json">{payload}</script>'


def _dashboard_header() -> str:
    return ""


def _dashboard_footer() -> str:
    return "Inebotten &middot; Norsk Discord-selfbot"


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _rate_request_count(value: object) -> int:
    if isinstance(value, dict):
        for key in ("requests", "count", "total"):
            raw = value.get(key)
            if isinstance(raw, (int, float)):
                return int(raw)
        return sum(int(raw) for raw in value.values() if isinstance(raw, (int, float)))
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _log_counts(log_lines: object) -> dict[str, int]:
    counts = {"error": 0, "warn": 0, "info": 0, "debug": 0}
    if not isinstance(log_lines, list):
        return counts
    for line in log_lines:
        upper = str(line).upper()
        if "ERROR" in upper or "CRITICAL" in upper:
            counts["error"] += 1
        elif "WARN" in upper:
            counts["warn"] += 1
        elif "INFO" in upper:
            counts["info"] += 1
        else:
            counts["debug"] += 1
    return counts


def _badge_text(value: object, *, ok: str = "OK", warn: str = "Sjekk", error: str = "Feil") -> str:
    badge = _status_badge(value)
    if badge == "badge-online":
        return ok
    if badge == "badge-error":
        return error
    return warn


def _modal_button(section: str, label: str = "Detaljer") -> str:
    return (
        f'<button type="button" class="btn btn-secondary" '
        f'data-section-modal="{escape(section)}">{escape(label)}</button>'
    )


def _metric_tile(label: str, value: object, *, metric: str | None = None) -> str:
    metric_attr = f' data-metric="{escape(metric)}"' if metric else ""
    return (
        '<div class="metric">'
        f"<span>{escape(label)}</span>"
        f"<strong{metric_attr}>{escape(str(value))}</strong>"
        "</div>"
    )


def _signal_card(tone: str, symbol: str, title: str, detail: str, value: object) -> str:
    return f"""<div class="signal-card signal-{escape(tone)}">
  <span class="signal-icon" aria-hidden="true">{escape(symbol)}</span>
  <div>
    <strong>{escape(title)}</strong>
    <span>{escape(detail)}</span>
  </div>
  <span class="signal-value">{escape(str(value))}</span>
</div>"""


def _render_overview_section(data: dict[str, Any]) -> str:
    status = _section(data, "status")
    bridge = _section(data, "bridge")
    intents = _section(data, "intents")
    logs = _section(data, "logs")
    calendar = _section(data, "calendar")
    polls = _section(data, "polls")

    bot_status = status.get("status", "ukjent")
    bridge_status = bridge.get("status", "ukjent")
    bridge_errors = _safe_int(bridge, "errors", default=0)
    fallback_count = _safe_int(intents, "fallback_count", default=0)
    log_lines = logs.get("logs", [])
    log_counts = _log_counts(log_lines)
    active_polls = _safe_int(polls, "active_polls", default=0)
    event_count = _safe_int(calendar, "event_count", default=0)
    task_count = _safe_int(calendar, "task_count", default=0)

    has_attention = (
        _status_badge(bot_status) != "badge-online"
        or _status_badge(bridge_status) == "badge-error"
        or bridge_errors > 0
        or log_counts["error"] > 0
    )

    if has_attention:
        headline = "Inebotten trenger et blikk"
        subline = "Det meste er samlet her: helsesignal, siste aktivitet og de raskeste stedene å undersøke når noe skurrer."
        badge = '<span class="badge badge-warning">Oppmerksomhet</span>'
    elif str(bot_status).lower() == "starting":
        headline = "Inebotten starter opp"
        subline = "Konsollen viser hva som er klart, hva som mangler monitor, og hvor langt botten har kommet."
        badge = '<span class="badge badge-neutral">Starter</span>'
    else:
        headline = "Inebotten er våken"
        subline = "En rask oversikt over hva botten gjør nå, hvor mye som skjer, og hva som fortjener neste klikk."
        badge = '<span class="badge badge-online">Klar</span>'

    hero_stats = "\n".join(
        [
            f'<div class="hero-stat"><span>Oppetid</span><strong data-metric="status.uptime">{escape(_uptime_fmt(_safe_int(status, "uptime_seconds", default=-1)))}</strong></div>',
            f'<div class="hero-stat"><span>Servere</span><strong data-metric="status.guilds">{escape(str(status.get("guilds", "N/A")))}</strong></div>',
            f'<div class="hero-stat"><span>Kalender</span><strong>{event_count} / {task_count}</strong></div>',
            f'<div class="hero-stat"><span>Avstemninger</span><strong data-metric="polls.active">{active_polls}</strong></div>',
        ]
    )

    bridge_tone = "ok" if _status_badge(bridge_status) == "badge-online" and bridge_errors == 0 else "warn"
    if _status_badge(bridge_status) == "badge-error":
        bridge_tone = "error"
    fallback_tone = "warn" if fallback_count > 5 else "ok"
    log_tone = "error" if log_counts["error"] else ("warn" if log_counts["warn"] else "ok")

    signals = "\n".join(
        [
            _signal_card("ok" if _status_badge(bot_status) == "badge-online" else "warn", "OK", "Bot", f"Status: {bot_status}", _badge_text(bot_status, ok="Online")),
            _signal_card(bridge_tone, "AI", "Bridge", f"LM Studio: {bridge.get('lm_studio', 'ukjent')}", _badge_text(bridge_status, ok="Tilkoblet", error="Nede")),
            _signal_card(fallback_tone, "?", "Fallbacks", "Lav trygghet eller AI-chat-ruting", fallback_count),
            _signal_card(log_tone, "!", "Logger", f"{log_counts['warn']} varsler, {log_counts['error']} feil", len(log_lines) if isinstance(log_lines, list) else 0),
        ]
    )

    return f"""<section class="panel overview-panel" id="overview">
  <div class="overview-layout">
    <div class="overview-copy">
      <div class="section-heading">
        <div>
          <div class="eyebrow">Inebotten Console</div>
          <h1>{escape(headline)}</h1>
        </div>
        {badge}
      </div>
      <p>{escape(subline)}</p>
      <div class="status-strip">{hero_stats}</div>
      <div class="next-actions">
        <a class="next-action" href="#logs"><strong>Les siste logger</strong><span>Se hva botten nettopp gjorde.</span></a>
        <a class="next-action" href="#calendar"><strong>Sjekk køen</strong><span>Kalender, oppgaver og avstemninger.</span></a>
        <a class="next-action" href="#diagnostics"><strong>Åpne diagnostikk</strong><span>Bridge, intents og rate limits.</span></a>
      </div>
    </div>
    <div class="overview-side">{signals}</div>
  </div>
</section>"""


def _render_status_section(data: dict[str, Any]) -> str:
    status = _section(data, "status")
    bot_status = status.get("status", "ukjent")
    uptime_sec = _safe_int(status, "uptime_seconds", default=-1)
    dc_text = "Ja" if status.get("discord_connected") in (True, "true", "yes", "ja", "connected") else "Nei"
    metrics = "\n".join(
        [
            _metric_tile("Oppetid", _uptime_fmt(uptime_sec), metric="status.uptime"),
            _metric_tile("Servere", status.get("guilds", "N/A"), metric="status.guilds"),
            _metric_tile("Brukere", status.get("users", "N/A"), metric="status.users"),
            _metric_tile("Discord", dc_text, metric="status.discord"),
        ]
    )
    return f"""<section class="card span-4" id="status">
  <div class="card-header">
    <div><h3>Nå</h3><p class="muted">Bot, Discord og oppetid.</p></div>
    <span class="badge {_status_badge(bot_status)}">{escape(_badge_text(bot_status, ok="Online", error="Offline"))}</span>
  </div>
  <div class="card-body"><div class="metric-grid">{metrics}</div></div>
  <div class="card-footer">{_modal_button("status")}</div>
</section>"""


def _render_bridge_section(data: dict[str, Any]) -> str:
    bridge = _section(data, "bridge")
    bridge_status = bridge.get("status", "ukjent")
    err_val = _safe_int(data, "bridge", "errors", default=0)
    metrics = "\n".join(
        [
            _metric_tile("Status", bridge_status, metric="bridge.status"),
            _metric_tile("LM Studio", bridge.get("lm_studio", "N/A"), metric="bridge.lm_studio"),
            _metric_tile("Forespørsler", bridge.get("requests", 0), metric="bridge.requests"),
            _metric_tile("Feil", err_val, metric="bridge.errors"),
        ]
    )
    return f"""<article class="card" id="bridge">
  <div class="card-header">
    <div><h3>Bridge</h3><p class="muted">AI-broen og LM Studio-kontakten.</p></div>
    <span class="badge {_status_badge(bridge_status)}">{escape(_badge_text(bridge_status, ok="Tilkoblet", error="Frakoblet"))}</span>
  </div>
  <div class="card-body"><div class="metric-grid">{metrics}</div></div>
  <div class="card-footer">{_modal_button("bridge")}</div>
</article>"""


def _render_calendar_section(data: dict[str, Any]) -> str:
    calendar = _section(data, "calendar")
    event_count = calendar.get("event_count", 0)
    task_count = calendar.get("task_count", 0)
    upcoming = calendar.get("upcoming_events")

    if isinstance(upcoming, list) and upcoming:
        items = []
        for event in upcoming[:3]:
            if not isinstance(event, dict):
                continue
            title = escape(str(event.get("title") or event.get("name") or "Uten tittel"))
            date = event.get("date") or event.get("when") or event.get("start") or "Ukjent tid"
            time = event.get("time")
            when = escape(f"{date} {time}".strip() if time else str(date))
            items.append(f'<div class="mini-row"><span>{title}</span><strong>{when}</strong></div>')
        upcoming_html = f'<div class="mini-list">{"".join(items)}</div>'
    else:
        upcoming_html = '<div class="empty-state">Ingen kommende kalenderhendelser.</div>'

    metrics = "\n".join(
        [
            _metric_tile("Hendelser", event_count, metric="calendar.events"),
            _metric_tile("Oppgaver", task_count, metric="calendar.tasks"),
        ]
    )
    return f"""<section class="card span-4" id="calendar">
  <div class="card-header">
    <div><h3>Kalender</h3><p class="muted">Neste hendelser og oppgaver.</p></div>
    <span class="badge badge-neutral">{escape(str(event_count))} hendelser</span>
  </div>
  <div class="card-body">
    <div class="metric-grid">{metrics}</div>
    {upcoming_html}
  </div>
  <div class="card-footer">
    <a href="/gcal-auth" class="btn btn-secondary">Google-oppsett</a>
    {_modal_button("calendar", "Vis alle")}
  </div>
</section>"""


def _render_polls_section(data: dict[str, Any]) -> str:
    polls = _section(data, "polls")
    active_polls = polls.get("active_polls", 0)
    polls_list = polls.get("polls")

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
                        f"""<div class="poll-row">
  <span>{escape(str(option))}</span>
  <div class="bar-track"><div class="bar-fill" style="width:{pct:.1f}%"></div></div>
  <strong>{escape(str(count))}</strong>
</div>"""
                    )
                poll_items.append(
                    f"""<div>
  <strong>{question}</strong>
  <div class="poll-bars">{''.join(bars)}</div>
</div>"""
                )
            else:
                poll_items.append(f"<strong>{question}</strong>")
        polls_html = f'<div class="mini-list">{"".join(poll_items)}</div>'
    else:
        polls_html = '<div class="empty-state">Ingen aktive avstemninger akkurat nå.</div>'

    return f"""<section class="card span-4" id="polls">
  <div class="card-header">
    <div><h3>Avstemninger</h3><p class="muted">Aktive valg i Discord.</p></div>
    <span class="badge badge-neutral"><span data-metric="polls.active">{escape(str(active_polls))}</span> aktive</span>
  </div>
  <div class="card-body">{polls_html}</div>
  <div class="card-footer">{_modal_button("polls", "Vis alle")}</div>
</section>"""


def _render_rate_limits_section(data: dict[str, Any]) -> str:
    rate_limits = _section(data, "rate_limits")
    user_stats = rate_limits.get("user_stats")
    total_requests = _safe_int(rate_limits, "summary", "total_requests", default=0)

    if isinstance(user_stats, dict) and user_stats:
        counts = {str(user): _rate_request_count(raw) for user, raw in user_stats.items()}
        if total_requests <= 0:
            total_requests = sum(counts.values())
        max_count = max(counts.values()) if counts else 1
        user_rows_html: list[str] = []
        for user, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:5]:
            pct = min((count / max_count) * 100, 100) if max_count else 0
            user_rows_html.append(
                f"<tr><td>{escape(str(user))}</td><td>{count}</td>"
                f'<td><div class="usage-bar bar-track"><div class="bar-fill" style="width:{pct:.0f}%"></div></div></td></tr>'
            )
        table_html = f"""<div class="table-shell">
  <table>
    <thead><tr><th>Bruker</th><th>Antall</th><th>Bruk</th></tr></thead>
    <tbody>{''.join(user_rows_html)}</tbody>
  </table>
</div>"""
    else:
        table_html = '<div class="empty-state">Ingen rate-limit-data ennå.</div>'

    return f"""<article class="card" id="rate-limits">
  <div class="card-header">
    <div><h3>Rate Limits</h3><p class="muted">Hvem som bruker botten mest.</p></div>
    <span class="badge badge-neutral"><span data-metric="rate_limits.total">{total_requests}</span> totalt</span>
  </div>
  <div class="card-body">{table_html}</div>
  <div class="card-footer">{_modal_button("rate-limits")}</div>
</article>"""


def _render_intents_section(data: dict[str, Any]) -> str:
    intents = _section(data, "intents")
    intent_counts = intents.get("intent_counts")
    fallback_count = _safe_int(data, "intents", "fallback_count", default=0)
    fallback_badge_class = "badge-warning" if fallback_count > 5 else "badge-neutral"

    if isinstance(intent_counts, dict) and intent_counts:
        intent_rows_html: list[str] = []
        for intent, count in sorted(intent_counts.items(), key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0, reverse=True)[:5]:
            intent_rows_html.append(f"<tr><td>{escape(str(intent))}</td><td>{escape(str(count))}</td></tr>")
        table_html = f"""<div class="table-shell">
  <table>
    <thead><tr><th>Intent</th><th>Antall</th></tr></thead>
    <tbody>{''.join(intent_rows_html)}</tbody>
  </table>
</div>"""
    else:
        table_html = '<div class="empty-state">Ingen intent-data ennå.</div>'

    return f"""<article class="card" id="intents">
  <div class="card-header">
    <div><h3>Intents</h3><p class="muted">Hvordan meldinger rutes.</p></div>
    <span class="badge {fallback_badge_class}">Fallbacks: <span data-metric="intents.fallback">{fallback_count}</span></span>
  </div>
  <div class="card-body">{table_html}</div>
  <div class="card-footer">{_modal_button("intents")}</div>
</article>"""


def _render_memory_section(data: dict[str, Any]) -> str:
    mem_users = _safe_int(data, "memory", "user_count", default=0)
    mem_convs = _safe_int(data, "memory", "conversation_count", default=0)
    metrics = "\n".join(
        [
            _metric_tile("Brukere", mem_users, metric="memory.users"),
            _metric_tile("Samtaler", mem_convs, metric="memory.conversations"),
        ]
    )

    return f"""<section class="card span-4" id="memory">
  <div class="card-header">
    <div><h3>Minne</h3><p class="muted">Hva botten husker på tvers av samtaler.</p></div>
  </div>
  <div class="card-body"><div class="metric-grid">{metrics}</div></div>
  <div class="card-footer">{_modal_button("memory")}</div>
</section>"""


def _render_logs_section(data: dict[str, Any]) -> str:
    log_lines = data.get("logs", {}).get("logs", []) if isinstance(data.get("logs"), dict) else []
    line_count = len(log_lines) if isinstance(log_lines, list) else 0
    return f"""<section class="card span-12" id="logs">
  <div class="card-header">
    <div><h3>Logger</h3><p class="muted">Siste driftsspor fra prosessen.</p></div>
    <span class="badge badge-neutral">Siste <span data-metric="logs.count">{line_count}</span> linjer</span>
  </div>
  <div class="card-body">
    <div id="log-container" class="log-console">{_render_log_block(log_lines)}</div>
  </div>
  <div class="card-footer">
    <button type="button" class="btn btn-secondary" data-copy-logs>Kopier</button>
    {_modal_button("logs", "Vis alle")}
  </div>
</section>"""


def _render_activity_section(data: dict[str, Any]) -> str:
    log_lines = data.get("logs", {}).get("logs", []) if isinstance(data.get("logs"), dict) else []
    if not isinstance(log_lines, list) or not log_lines:
        items = '<div class="empty-state">Ingen aktivitet fanget ennå.</div>'
    else:
        cards = []
        for raw in log_lines[-4:][::-1]:
            line = str(raw)
            upper = line.upper()
            tone = "log-error" if "ERROR" in upper or "CRITICAL" in upper else "log-warn" if "WARN" in upper else "log-info" if "INFO" in upper else "log-debug"
            title = line.split("]", 1)[1].strip() if "]" in line else line
            prefix = line.split("[", 1)[0].strip() if "[" in line else "Nylig"
            cards.append(f'<div class="activity-item"><strong class="{tone}">{escape(title[:120])}</strong><span>{escape(prefix)}</span></div>')
        items = "".join(cards)
    return f"""<section class="section-band span-12" id="activity">
  <div class="section-heading">
    <div>
      <h2>Siste aktivitet</h2>
      <p>De nyeste signalene før du dykker ned i tabeller og logger.</p>
    </div>
  </div>
  <div class="activity-list">{items}</div>
</section>"""


def _render_diagnostics_section(data: dict[str, Any]) -> str:
    return f"""<section class="section-band span-12" id="diagnostics">
  <div class="section-heading">
    <div>
      <h2>Diagnostikk</h2>
      <p>AI-bro, trafikk og intent-ruting samlet på ett sted.</p>
    </div>
  </div>
  <div class="diagnostics-grid">
    {_render_bridge_section(data)}
    {_render_rate_limits_section(data)}
    {_render_intents_section(data)}
    {_render_memory_section(data)}
  </div>
</section>"""


def render_login_page(error: str | None = None) -> str:
    error_html = f'<div class="badge badge-error" role="alert">{escape(error)}</div>' if error else ""
    main_content = f"""<div class="panel auth-card">
  <button type="button" id="login-theme-toggle" class="theme-toggle auth-theme" aria-label="Bytt tema">
    <span id="theme-icon">Lys</span>
  </button>
  <div class="auth-brand">
    <div class="brand-icon" aria-hidden="true">I</div>
    <div>
      <h1>Inebotten Console</h1>
      <p class="muted">Norsk Discord-selfbot</p>
    </div>
  </div>
  <p class="muted">Skriv inn API-nøkkelen for å fortsette.</p>
  {error_html}
  <form method="POST" action="/api/login" class="form-stack">
    <div class="field-stack">
      <label for="api_key">API-nøkkel</label>
      <input type="password" id="api_key" name="api_key" placeholder="API-nøkkel" required autofocus class="input">
    </div>
    <button type="submit" class="btn">Logg inn</button>
  </form>
  <p class="auth-link">
    <a href="/demo">Se demo uten innlogging</a>
  </p>
</div>"""
    return _LOGIN_TEMPLATE.format(
        title="Inebotten Console - Logg inn",
        header_content="",
        main_content=main_content,
        footer_content='<p class="hint">Nøkkelen settes med <code>CONSOLE_API_KEY</code> eller lagres i <code>~/.hermes/discord/data/console/api_key.txt</code></p>',
        body_class="auth-page",
        refresh_meta="",
        initial_data_script="",
    )


def render_dashboard(data: dict[str, Any] | None, *, is_demo: bool = False) -> str:
    if data is None:
        data = {}

    main_content = "\n".join(
        [
            _render_overview_section(data),
            _render_status_section(data),
            _render_calendar_section(data),
            _render_polls_section(data),
            _render_activity_section(data),
            _render_diagnostics_section(data),
            _render_logs_section(data),
        ]
    )

    body_class = "dashboard-page demo-mode" if is_demo else "dashboard-page"

    return _BASE_TEMPLATE.format(
        title="Inebotten Console",
        header_content=_dashboard_header(),
        main_content=main_content,
        footer_content=_dashboard_footer(),
        body_class=body_class,
        refresh_meta="",
        initial_data_script=_initial_data_script(data),
    )


def render_gcal_auth_page(
    status: dict[str, Any] | None,
    *,
    message: str | None = None,
    error: str | None = None,
) -> str:
    if status is None:
        status = {}

    configured = bool(status.get("configured"))
    path = escape(str(status.get("path") or "Ikke satt"))
    badge_class = "badge-online" if configured else "badge-warning"
    badge_text = "Konfigurert" if configured else "Mangler OAuth-klient"
    message_html = (
        f'<div class="badge badge-online setup-message" role="status">{escape(message)}</div>'
        if message
        else ""
    )
    error_html = (
        f'<div class="badge badge-error setup-message" role="alert">{escape(error)}</div>'
        if error
        else ""
    )

    main_content = f"""<section class="panel setup-panel span-12" id="gcal-auth">
  <div class="setup-header">
    <div>
      <p class="eyebrow">Google Calendar</p>
      <h1>OAuth-oppsett</h1>
      <p class="muted">Lagre Google OAuth-klienten her, og kjør deretter kalender-auth fra Discord.</p>
    </div>
    <span class="badge {badge_class}">{badge_text}</span>
  </div>

  <div class="setup-status">
    <span>Lagringssti</span>
    <code>{path}</code>
  </div>

  {message_html}
  {error_html}

  <form method="POST" action="/api/gcal/credentials" class="form-stack setup-form">
    <div class="field-stack">
      <label for="credentials_json">OAuth Client ID JSON</label>
      <textarea
        id="credentials_json"
        name="credentials_json"
        class="input credentials-input"
        spellcheck="false"
        autocomplete="off"
        required
        placeholder='{{"installed":{{"client_id":"...","client_secret":"..."}}}}'
      ></textarea>
    </div>
    <div class="setup-actions">
      <button type="submit" class="btn">Lagre OAuth-klient</button>
      <a href="/" class="btn btn-secondary">Tilbake</a>
    </div>
  </form>

  <div class="setup-note">
    <div class="setup-link-row">
      <a
        href="https://console.developers.google.com/auth/clients"
        class="btn btn-secondary"
        target="_blank"
        rel="noopener noreferrer"
      >Åpne Google Auth Clients</a>
      <a
        href="https://support.google.com/cloud/answer/15549257"
        class="btn btn-ghost"
        target="_blank"
        rel="noopener noreferrer"
      >Google-hjelp</a>
    </div>
    <p>I Google: velg <strong>CREATE CLIENT</strong>, application type <strong>Desktop app</strong>, last ned JSON-filen, og lim hele innholdet inn her.</p>
    <p>Innholdet lagres privat som <code>credentials.json</code>, og vises ikke tilbake etter lagring.</p>
    <p>Når den er lagret: kjør <code>@inebotten kalender auth</code>, åpne Google-lenken og send koden tilbake med <code>@inebotten kalender kode &lt;kode&gt;</code>.</p>
  </div>
</section>"""

    return _BASE_TEMPLATE.format(
        title="Inebotten - Google Calendar OAuth",
        header_content="",
        main_content=main_content,
        footer_content="Inebotten &middot; Google Calendar-oppsett",
        body_class="dashboard-page setup-page",
        refresh_meta="",
        initial_data_script="",
    )


def _render_cmd_section(
    category: HelpCategory,
    examples: tuple[HelpExample, ...],
) -> str:
    rows = "\n".join(
        "<tr><td><code>"
        f"{escape('@inebotten ' + example.display_phrase)}"
        "</code></td></tr>"
        for example in examples
    )
    return (
        '<section class="card scroll-mt-24">'
        f"<h2>{escape(category.title_no)}</h2>"
        f'<p class="muted">{escape(category.description_no)}</p>'
        "<table><thead><tr><th>Eksempel på formulering</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></section>"
    )


def render_commands_page() -> str:
    main_content = "\n".join(
        _render_cmd_section(category, examples)
        for category, examples in catalog_sections("nb")
    )

    return _BASE_TEMPLATE.format(
        title="Inebotten - Eksempler",
        header_content="",
        main_content=main_content,
        footer_content="Inebotten &middot; Norsk Discord-selfbot",
        body_class="commands-page",
        refresh_meta="",
        initial_data_script="",
    )
