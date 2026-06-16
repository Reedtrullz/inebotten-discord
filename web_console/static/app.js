class ConsoleApp {
  constructor() {
    this.theme = localStorage.getItem("theme") || (
      window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
    );
    this.data = {};
    this.lastUpdated = null;
    this.isPolling = false;
    this.authExpired = false;
    this.pollingControllers = {};
    this.pollingBackoff = {};
    this._focusTrapHandler = null;
    this._lastFocusedElement = null;
    this.isDemo = document.body.classList.contains("demo-mode");
    this.pollingConfig = {
      "/api/status": { interval: 5000, lastFetch: 0 },
      "/api/bridge": { interval: 5000, lastFetch: 0 },
      "/api/calendar": { interval: 10000, lastFetch: 0 },
      "/api/polls": { interval: 10000, lastFetch: 0 },
      "/api/rate-limits": { interval: 10000, lastFetch: 0 },
      "/api/intents": { interval: 10000, lastFetch: 0 },
      "/api/memory": { interval: 10000, lastFetch: 0 },
      "/api/logs?lines=50": { interval: 30000, lastFetch: 0 },
    };
  }

  init() {
    this.applyTheme();
    this.bindShell();
    this.bindModalButtons();
    this.initData();
    this.updateShellStatus();
    if (!this.isDemo) {
      this.startPolling();
    }
    document.addEventListener("visibilitychange", () => {
      if (this.isDemo) return;
      if (document.visibilityState === "hidden") {
        this.stopPolling();
      } else {
        this.startPolling();
      }
    });
  }

  bindShell() {
    document.getElementById("theme-toggle")?.addEventListener("click", () => this.toggleTheme());

    const menuButton = document.getElementById("mobile-menu-toggle");
    const nav = document.getElementById("primary-nav");
    menuButton?.addEventListener("click", () => {
      const open = !nav?.classList.contains("is-open");
      nav?.classList.toggle("is-open", open);
      menuButton.setAttribute("aria-expanded", open ? "true" : "false");
      menuButton.querySelector(".menu-icon-open")?.toggleAttribute("hidden", open);
      menuButton.querySelector(".menu-icon-close")?.toggleAttribute("hidden", !open);
    });

    nav?.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => {
        nav.classList.remove("is-open");
        menuButton?.setAttribute("aria-expanded", "false");
        menuButton?.querySelector(".menu-icon-open")?.removeAttribute("hidden");
        menuButton?.querySelector(".menu-icon-close")?.setAttribute("hidden", "");
      });
    });

    document.querySelectorAll("[data-close-modal]").forEach((button) => {
      button.addEventListener("click", () => this.closeModal());
    });
    document.querySelectorAll("[data-copy-logs]").forEach((button) => {
      button.addEventListener("click", () => copyLogs());
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") this.closeModal();
    });
  }

  bindModalButtons() {
    document.querySelectorAll("[data-section-modal]").forEach((button) => {
      button.addEventListener("click", () => {
        this.showSectionModal(button.getAttribute("data-section-modal"));
      });
    });
  }

  toggleTheme() {
    this.theme = this.theme === "dark" ? "light" : "dark";
    localStorage.setItem("theme", this.theme);
    this.applyTheme();
  }

  applyTheme() {
    document.documentElement.classList.remove("dark", "light");
    document.documentElement.classList.add(this.theme);
    const icon = document.querySelector("[data-theme-icon]");
    if (icon) icon.textContent = this.theme === "dark" ? "Lys" : "Mørk";
  }

  initData() {
    const script = document.getElementById("initial-data");
    if (!script) return;
    try {
      this.data = JSON.parse(script.textContent || "{}");
      this.touchUpdated();
    } catch (error) {
      console.error("Failed to parse initial data:", error);
    }
  }

  touchUpdated() {
    this.lastUpdated = new Date().toLocaleTimeString("no-NO", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    const wrapper = document.getElementById("last-updated");
    const value = document.querySelector("[data-last-updated-time]");
    if (wrapper && value) {
      value.textContent = this.lastUpdated;
      wrapper.hidden = false;
    }
  }

  startPolling() {
    if (this.isPolling || this.authExpired) return;
    this.isPolling = true;
    Object.keys(this.pollingConfig).forEach((endpoint) => {
      this.pollEndpoint(endpoint);
    });
  }

  stopPolling() {
    this.isPolling = false;
    Object.values(this.pollingControllers).forEach((controller) => controller.abort());
    this.pollingControllers = {};
  }

  async pollEndpoint(endpoint) {
    if (!this.isPolling || this.authExpired) return;
    const config = this.pollingConfig[endpoint];
    const now = Date.now();
    const backoff = this.pollingBackoff[endpoint] || 0;
    const interval = config.interval + backoff;

    if (now - config.lastFetch < interval) {
      setTimeout(() => this.pollEndpoint(endpoint), interval - (now - config.lastFetch));
      return;
    }

    this.pollingControllers[endpoint]?.abort();
    const controller = new AbortController();
    this.pollingControllers[endpoint] = controller;

    try {
      const response = await fetch(endpoint, {
        credentials: "same-origin",
        signal: controller.signal,
      });
      if (response.status === 401) {
        this.authExpired = true;
        this.stopPolling();
        const banner = document.getElementById("auth-expired");
        if (banner) banner.hidden = false;
        return;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const data = await response.json();
      const key = endpoint.replace("/api/", "").replace("?lines=50", "");
      this.data[key] = data;
      this.pollingBackoff[endpoint] = 0;
      config.lastFetch = now;
      this.touchUpdated();
      this.updateDashboard(key, data);
    } catch (error) {
      if (error.name !== "AbortError") {
        this.pollingBackoff[endpoint] = Math.min((this.pollingBackoff[endpoint] || 0) + config.interval, 60000);
        console.error(`Poll error for ${endpoint}:`, error);
      }
    } finally {
      delete this.pollingControllers[endpoint];
    }

    if (this.isPolling && !this.authExpired) {
      setTimeout(() => this.pollEndpoint(endpoint), config.interval + (this.pollingBackoff[endpoint] || 0));
    }
  }

  updateDashboard(section, data) {
    if (!data) return;

    const setText = (key, value) => {
      document.querySelectorAll(`[data-metric="${key}"]`).forEach((el) => {
        el.textContent = value ?? "N/A";
      });
    };

    switch (section) {
      case "status": {
        setText("status.uptime", this.formatUptime(data.uptime_seconds));
        setText("status.guilds", data.guilds);
        setText("status.users", data.users);
        setText("status.discord", data.discord_connected ? "Ja" : "Nei");
        this.updateStatusBadge("#status .badge", data.status);
        this.updateShellStatus();
        break;
      }
      case "bridge": {
        setText("bridge.status", data.status);
        setText("bridge.lm_studio", data.lm_studio);
        setText("bridge.requests", data.requests);
        setText("bridge.errors", data.errors);
        this.updateBridgeBadge(data.status);
        break;
      }
      case "calendar":
        setText("calendar.events", data.event_count);
        setText("calendar.tasks", data.task_count);
        break;
      case "polls":
        setText("polls.active", data.active_polls);
        break;
      case "rate-limits":
        setText("rate_limits.total", data.summary?.total_requests ?? 0);
        break;
      case "intents":
        setText("intents.fallback", data.fallback_count);
        break;
      case "memory":
        setText("memory.users", data.user_count);
        setText("memory.conversations", data.conversation_count);
        break;
      case "logs":
        setText("logs.count", Array.isArray(data.logs) ? data.logs.length : 0);
        break;
    }
  }

  updateShellStatus() {
    const status = this.data?.status?.status || "online";
    this.updateStatusBadge("#shell-status", status);
  }

  updateStatusBadge(selector, status) {
    const badge = document.querySelector(selector);
    if (!badge) return;
    const online = String(status || "").toLowerCase() === "online";
    badge.className = `badge ${online ? "badge-online" : "badge-warning"}`;
    badge.textContent = online ? "Online" : "Sjekk";
  }

  updateBridgeBadge(status) {
    const badge = document.querySelector("#bridge .badge");
    if (!badge) return;
    const s = String(status || "").toLowerCase();
    const ok = ["online", "connected", "ok", "healthy", "running", "active", "true", "yes"];
    const err = ["offline", "disconnected", "error", "unhealthy", "stopped", "inactive", "false", "no"];
    if (ok.includes(s)) {
      badge.className = "badge badge-online";
      badge.textContent = "Tilkoblet";
    } else if (err.includes(s)) {
      badge.className = "badge badge-error";
      badge.textContent = "Frakoblet";
    } else {
      badge.className = "badge badge-warning";
      badge.textContent = "Ukjent";
    }
  }

  formatUptime(seconds) {
    if (seconds === undefined || seconds === null || seconds < 0) return "N/A";
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    const parts = [];
    if (days) parts.push(`${days}d`);
    if (hours) parts.push(`${hours}t`);
    if (mins) parts.push(`${mins}m`);
    if (secs || !parts.length) parts.push(`${secs}s`);
    return parts.join(" ");
  }

  openModal(section, data = {}) {
    this._lastFocusedElement = document.activeElement;
    const modal = document.getElementById("section-modal");
    const title = document.getElementById("modal-title");
    const content = document.getElementById("modal-content");
    if (!modal || !title || !content) return;
    title.textContent = data.title || "Detaljer";
    content.textContent = data.content || "";
    modal.hidden = false;
    document.body.classList.add("modal-open");
    this._trapFocus(modal);
    modal.querySelector('[role="dialog"]')?.focus();
  }

  closeModal() {
    const modal = document.getElementById("section-modal");
    if (!modal || modal.hidden) return;
    modal.hidden = true;
    document.body.classList.remove("modal-open");
    this._untrapFocus();
    this._lastFocusedElement?.focus();
    this._lastFocusedElement = null;
  }

  _trapFocus(modal) {
    const dialog = modal.querySelector('[role="dialog"]');
    if (!dialog) return;
    const focusableSelectors = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
    this._focusTrapHandler = (event) => {
      if (event.key !== "Tab") return;
      const focusable = Array.from(dialog.querySelectorAll(focusableSelectors));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", this._focusTrapHandler);
  }

  _untrapFocus() {
    if (this._focusTrapHandler) {
      document.removeEventListener("keydown", this._focusTrapHandler);
      this._focusTrapHandler = null;
    }
  }

  showSectionModal(section) {
    const titles = {
      status: "Bot-status",
      bridge: "Bridge",
      calendar: "Kalender",
      polls: "Avstemninger",
      "rate-limits": "Rate limits",
      intents: "Intents",
      memory: "Minne",
      logs: "Logger",
    };
    const data = section === "rate-limits"
      ? (this.data["rate-limits"] || this.data.rate_limits || {})
      : (this.data[section] || {});
    const lines = [];
    const add = (label, value) => lines.push(`${label}: ${value ?? "N/A"}`);
    const addBlank = () => lines.push("");

    switch (section) {
      case "status":
        add("Status", data.status || "N/A");
        add("Oppetid", this.formatUptime(data.uptime_seconds));
        add("Servere", data.guilds ?? "N/A");
        add("Brukere", data.users ?? "N/A");
        add("Discord-tilkobling", data.discord_connected ? "Ja" : "Nei");
        break;
      case "bridge":
        add("Status", data.status || "N/A");
        add("LM Studio", data.lm_studio || "N/A");
        add("Forespørsler", data.requests ?? 0);
        add("Feil", data.errors ?? 0);
        break;
      case "calendar":
        add("Hendelser", data.event_count ?? 0);
        add("Oppgaver", data.task_count ?? 0);
        if (Array.isArray(data.upcoming_events) && data.upcoming_events.length) {
          addBlank();
          lines.push("Kommende hendelser:");
          data.upcoming_events.slice(0, 10).forEach((event) => {
            const title = event.title || event.name || "Uten tittel";
            const when = event.when || event.start || event.date || "Ukjent tid";
            lines.push(`- ${title} — ${when}`);
          });
        }
        break;
      case "polls":
        add("Aktive avstemninger", data.active_polls ?? 0);
        break;
      case "rate-limits":
        add("Totale forespørsler", data.summary?.total_requests ?? 0);
        break;
      case "intents":
        add("Fallbacks", data.fallback_count ?? 0);
        if (data.intent_counts && Object.keys(data.intent_counts).length) {
          addBlank();
          lines.push("Intent-tellinger:");
          Object.entries(data.intent_counts)
            .sort((a, b) => (b[1] || 0) - (a[1] || 0))
            .forEach(([intent, count]) => lines.push(`- ${intent}: ${count}`));
        }
        break;
      case "memory":
        add("Brukere i minne", data.user_count ?? 0);
        add("Samtaler", data.conversation_count ?? 0);
        break;
      case "logs":
        if (Array.isArray(data.logs) && data.logs.length) {
          lines.push(...data.logs.map((line) => String(line)));
        } else {
          lines.push("Ingen logger tilgjengelig");
        }
        break;
      default:
        lines.push("Ingen detaljer tilgjengelig");
    }

    this.openModal(section, { title: titles[section] || "Detaljer", content: lines.join("\n") });
  }
}

document.addEventListener("DOMContentLoaded", () => {
  window.consoleApp = new ConsoleApp();
  window.consoleApp.init();
});

function copyLogs() {
  const el = document.getElementById("log-container");
  if (!el) return;
  const text = el.innerText;
  navigator.clipboard.writeText(text).then(() => {
    const btn = document.querySelector('#logs button[data-copy-logs]');
    if (!btn) return;
    const original = btn.textContent;
    btn.textContent = "Kopiert";
    setTimeout(() => { btn.textContent = original; }, 1500);
  }).catch(() => {
    const btn = document.querySelector('#logs button[data-copy-logs]');
    if (!btn) return;
    const original = btn.textContent;
    btn.textContent = "Feilet";
    setTimeout(() => { btn.textContent = original; }, 1500);
  });
}
