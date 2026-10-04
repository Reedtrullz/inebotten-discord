class ConsoleApp {
  constructor() {
    this.theme = localStorage.getItem("theme") || (
      window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
    );
    this.data = {};
    this.lastUpdated = null;
    this.isPolling = false;
    this.authExpired = false;
    this.pollingBackoff = {};
    this._focusTrapHandler = null;
    this._lastFocusedElement = null;
    this.openSection = null;
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
    this.requestTimeout = 15000;
    this.pollingEntries = Object.fromEntries(Object.entries(this.pollingConfig).map(([endpoint, config]) => [endpoint, {
      endpoint,
      interval: config.interval,
      timerId: null,
      deadlineId: null,
      controller: null,
      generation: 0,
      lastSuccess: null,
      status: "idle",
      deadline: null,
      timedOut: false,
    }]));
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
    document.querySelector('[data-log-pause]')?.addEventListener('click', () => {
      const entry = this.pollingEntries['/api/logs?lines=50'];
      this.pauseLogs(!entry.paused);
      if (!entry.paused) this.requestLogs();
    });
    document.querySelector('[data-log-older]')?.addEventListener('click', () => {
      this.pauseLogs(true);
      this.requestLogs(this.data.logs?.next_cursor);
    });
    ['[data-log-level]', '[data-log-component]'].forEach(selector => {
      document.querySelector(selector)?.addEventListener('change', () => this.requestLogs());
    });
    document.querySelector('[data-download-logs]')?.addEventListener('click', () => {
      const text = document.getElementById('log-container')?.innerText || '';
      const url = URL.createObjectURL(new Blob([text], {type:'text/plain;charset=utf-8'}));
      const link = document.createElement('a');
      link.href = url;
      link.download = 'inebotten-diagnostikk.txt';
      link.click();
      URL.revokeObjectURL(url);
    });
    document.querySelectorAll("[data-poll-retry]").forEach((button) => {
      button.addEventListener("click", () => this.retryEndpoint(button.dataset.pollRetry));
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
    const entries = Object.values(this.pollingEntries);
    const allFresh = entries.length > 0 && entries.every((entry) => entry.status === "fresh" && entry.lastSuccess !== null);
    const anyFailure = entries.some((entry) => entry.status === "error" || entry.status === "timeout");
    const anyPaused = entries.some((entry) => entry.status === "paused");
    this.lastUpdated = this.authExpired
      ? "Økta er utløpt"
      : !this.isPolling && anyPaused
        ? "Oppdatering satt på pause"
        : anyFailure
          ? "Noen data er utdaterte"
          : allFresh ? "Alle data oppdatert" : "Oppdaterer data";
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
    Object.keys(this.pollingEntries).forEach((endpoint) => {
      const entry = this.pollingEntries[endpoint];
      if (entry.paused || entry.timerId !== null || entry.controller !== null) return;
      this.pollEndpoint(endpoint, entry.generation);
    });
  }

  stopPolling() {
    this.isPolling = false;
    Object.values(this.pollingEntries).forEach((entry) => {
      entry.generation += 1;
      if (entry.timerId !== null) clearTimeout(entry.timerId);
      if (entry.deadlineId !== null) clearTimeout(entry.deadlineId);
      entry.timerId = null;
      entry.deadlineId = null;
      entry.deadline = null;
      entry.controller?.abort();
      entry.controller = null;
      entry.timedOut = false;
      entry.status = "paused";
      this.renderEndpointState(entry.endpoint);
    });
  }

  scheduleEndpoint(endpoint, delay, generation) {
    const entry = this.pollingEntries[endpoint];
    if (!this.isPolling || this.authExpired || entry.paused || entry.generation !== generation || entry.timerId !== null) return;
    entry.timerId = setTimeout(() => {
      if (entry.generation !== generation) return;
      entry.timerId = null;
      this.pollEndpoint(endpoint, generation);
    }, Math.max(0, delay));
  }

  retryEndpoint(endpoint) {
    const entry = this.pollingEntries[endpoint];
    if (!entry || this.authExpired) return;
    if (!this.isPolling) {
      if (document.visibilityState === "hidden") return;
      this.startPolling();
      return;
    }
    if (entry.timerId !== null) clearTimeout(entry.timerId);
    if (entry.deadlineId !== null) clearTimeout(entry.deadlineId);
    entry.timerId = null;
    entry.deadlineId = null;
    entry.controller?.abort();
    entry.controller = null;
    entry.generation += 1;
    this.pollingBackoff[endpoint] = 0;
    this.pollEndpoint(endpoint, entry.generation);
  }

  async pollEndpoint(endpoint, generation = this.pollingEntries[endpoint]?.generation) {
    const entry = this.pollingEntries[endpoint];
    if (!entry || !this.isPolling || this.authExpired || entry.generation !== generation || entry.controller !== null) return;
    const config = this.pollingConfig[endpoint];
    const controller = new AbortController();
    entry.controller = controller;
    entry.timedOut = false;
    entry.deadline = performance.now() + this.requestTimeout;
    entry.status = "loading";
    this.renderEndpointState(endpoint);
    entry.deadlineId = setTimeout(() => {
      if (entry.generation !== generation || entry.controller !== controller) return;
      entry.timedOut = true;
      controller.abort();
    }, this.requestTimeout);

    try {
      const response = await fetch(endpoint === '/api/logs?lines=50' ? this.logRequestUrl() : endpoint, {
        credentials: "same-origin",
        signal: controller.signal,
      });
      if (!this.isPolling || this.authExpired || entry.generation !== generation || entry.controller !== controller) return;
      if (controller.signal.aborted || performance.now() >= entry.deadline) {
        entry.timedOut = true;
        throw new DOMException('Deadline exceeded', 'AbortError');
      }
      if (response.status === 401) {
        this.authExpired = true;
        this.stopPolling();
        const banner = document.getElementById("auth-expired");
        if (banner) banner.hidden = false;
        this.touchUpdated();
        return;
      }
      if (endpoint === '/api/logs?lines=50' && response.status === 409) {
        this.logCursor = null;
        const status = document.querySelector('[data-log-page-status]');
        if (status) status.textContent = 'Loggen er rotert. Hent siste side på nytt.';
        this.data.logs.next_cursor = null;
        document.querySelector('[data-log-older]')?.setAttribute('disabled', '');
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const data = await response.json();
      if (!this.isPolling || this.authExpired || entry.generation !== generation || entry.controller !== controller) return;
      if (controller.signal.aborted || performance.now() >= entry.deadline) {
        entry.timedOut = true;
        throw new DOMException('Deadline exceeded', 'AbortError');
      }
      const key = endpoint.replace("/api/", "").replace("?lines=50", "");
      this.data[key] = data;
      this.pollingBackoff[endpoint] = 0;
      config.lastFetch = performance.now();
      entry.lastSuccess = performance.now();
      entry.status = "fresh";
      this.updateDashboard(key, data);
      this.renderEndpointState(endpoint);
    } catch (error) {
      if (this.isPolling && !this.authExpired && entry.generation === generation) {
        this.pollingBackoff[endpoint] = Math.min((this.pollingBackoff[endpoint] || 0) + config.interval, 60000);
        entry.status = entry.timedOut ? "timeout" : "error";
        this.renderEndpointState(endpoint);
        if (!entry.timedOut && error.name !== "AbortError") console.error(`Poll error for ${endpoint}:`, error);
      }
    } finally {
      if (entry.generation === generation && entry.controller === controller) {
        if (entry.deadlineId !== null) clearTimeout(entry.deadlineId);
        entry.deadlineId = null;
        entry.deadline = null;
        entry.controller = null;
      }
    }

    if (this.isPolling && !this.authExpired && entry.generation === generation) {
      this.scheduleEndpoint(endpoint, config.interval + (this.pollingBackoff[endpoint] || 0), generation);
    }
  }

  renderEndpointState(endpoint) {
    const entry = this.pollingEntries[endpoint];
    if (!entry) return;
    const age = entry.lastSuccess === null ? null : Math.max(0, Math.floor((performance.now() - entry.lastSuccess) / 1000));
    const lastSuccess = entry.lastSuccess === null ? "" : String(entry.lastSuccess);
    let label;
    if (entry.status === "fresh") label = age === 0 ? "Oppdatert nå" : `Oppdatert for ${age} sekunder siden`;
    else if (entry.status === "loading") label = age === null ? "Laster inn" : `Oppdaterer · sist oppdatert for ${age} sekunder siden`;
    else if (entry.status === "timeout") label = age === null ? "Tidsavbrudd · ingen vellykket oppdatering" : `Tidsavbrudd · utdatert, sist oppdatert for ${age} sekunder siden`;
    else if (entry.status === "error") label = age === null ? "Feil · ingen vellykket oppdatering" : `Feil · utdatert, sist oppdatert for ${age} sekunder siden`;
    else if (entry.status === "paused") label = age === null ? "Pausert · ingen vellykket oppdatering" : `Pausert · sist oppdatert for ${age} sekunder siden`;
    else label = "Venter på oppdatering";
    document.querySelectorAll("[data-poll-endpoint]").forEach((element) => {
      if (element.dataset.pollEndpoint !== endpoint) return;
      element.textContent = label;
      element.dataset.lastSuccess = lastSuccess;
      element.dataset.pollStatus = entry.status;
      element.classList.toggle("is-stale", entry.status === "error" || entry.status === "timeout");
    });
    this.touchUpdated();
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
        const bridgeReadiness = data.readiness?.components?.bridge;
        const bridgeDisabled = bridgeReadiness?.status === "disabled";
        setText("bridge.status", bridgeDisabled ? "Ikke nødvendig" : data.status);
        setText("bridge.lm_studio", bridgeDisabled ? "Ikke i bruk" : data.lm_studio);
        setText("bridge.requests", bridgeDisabled ? "–" : data.requests);
        setText("bridge.errors", bridgeDisabled ? "–" : data.errors);
        this.updateBridgeBadge(bridgeDisabled ? "disabled" : data.status);
        if (data.readiness) this.renderSection("readiness", data.readiness);
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
    this.renderSection(section, data);
  }

  renderSection(sectionName, sectionState) {
    if (!sectionState || typeof sectionState !== "object") return;
    this.data[sectionName] = sectionState;
    const setText = (selector, value) => {
      document.querySelectorAll(selector).forEach((element) => {
        element.textContent = value ?? "N/A";
      });
    };
    const make = (tag, className, text) => {
      const element = document.createElement(tag);
      if (className) element.className = className;
      if (text !== undefined) element.textContent = String(text);
      return element;
    };
    const empty = (message) => make("div", "empty-state", message);
    const rateLimits = sectionName === "rate-limits";
    const state = sectionState;

    if (sectionName === "readiness") {
      const container = document.querySelector("#readiness [data-readiness-list]");
      const badge = document.querySelector('#readiness [data-metric="readiness.status"]');
      const statusLabels = {
        ready: "Klar", degraded: "Svekket", unavailable: "Utilgjengelig",
        stale: "Utdatert", disabled: "Deaktivert",
      };
      const statusClass = {
        ready: "badge-online", degraded: "badge-warning", unavailable: "badge-error",
        stale: "badge-warning", disabled: "badge-neutral",
      };
      const labelFor = (value) => statusLabels[String(value || "").toLowerCase()] || "Ukjent";
      if (badge) {
        const status = String(state.status || "stale").toLowerCase();
        badge.className = `badge ${statusClass[status] || "badge-warning"}`;
        badge.textContent = labelFor(status);
      }
      if (container) {
        container.replaceChildren();
        const labels = {
          provider: "Valgt AI-provider", bridge: "Bridge", google_calendar: "Google Calendar",
          scheduler: "Påminnelsesplanlegger", store: "Konsolllager", calendar_sync: "Kalendersynkronisering",
        };
        const components = state.components && typeof state.components === "object" ? state.components : {};
        Object.entries(labels).forEach(([key, label]) => {
          const item = components[key];
          if (!item || typeof item !== "object") return;
          const row = make("div", "mini-row readiness-row");
          const summary = make("span");
          summary.append(make("strong", "", label));
          if (key === "provider") {
            const evidenceLabel = (value) => ({
              reachable: "tilkoblet", unavailable: "utilgjengelig", unverified: "ikke verifisert",
              catalog_reachable: "modelliste tilgjengelig",
              accepted: "inferens godkjent", not_observed: "inferens ikke observert", rejected: "inferens feilet",
            }[String(value || "").toLowerCase()] || "ikke verifisert");
            const evidence = make("small", "", `Transport: ${evidenceLabel(item.transport_status)} · modelliste: ${evidenceLabel(item.model_discovery_status)} · faktisk inferens: ${evidenceLabel(item.inference_acceptance_status)}`);
            summary.append(document.createElement("br"), evidence);
          }
          if (item.recovery_action) {
            summary.append(document.createElement("br"), make("small", "", item.recovery_action));
          }
          const status = String(item.status || "unavailable").toLowerCase();
          const statusLabel = key === "bridge" && status === "disabled" ? "Ikke nødvendig" : labelFor(status);
          const badge = make("strong", `badge ${statusClass[status] || "badge-warning"}`, statusLabel);
          row.append(summary, badge);
          container.append(row);
        });
        if (!container.childElementCount) container.append(empty("Venter på readiness-data."));
      }
    } else if (sectionName === "calendar") {
      const card = document.querySelector("#calendar .card-body");
      if (card) {
        card.querySelector(".mini-list, .empty-state")?.remove();
        const events = Array.isArray(state.upcoming_events) ? state.upcoming_events.slice(0, 3) : [];
        if (events.length) {
          const list = make("div", "mini-list");
          events.forEach((event) => {
            if (!event || typeof event !== "object") return;
            const row = make("div", "mini-row");
            const title = event.title || event.name || "Uten tittel";
            const date = event.date || event.when || event.start || "Ukjent tid";
            const when = event.time ? `${date} ${event.time}`.trim() : date;
            row.append(make("span", "", title), make("strong", "", when));
            list.append(row);
          });
          card.append(list);
        } else {
          card.append(empty("Ingen kommende kalenderhendelser."));
        }
      }
      setText("#calendar .card-header .badge", `${state.event_count ?? 0} hendelser`);
      const overviewCalendar = document.querySelector('[data-metric="overview.calendar"]');
      if (overviewCalendar) overviewCalendar.textContent = `${state.event_count ?? 0} / ${state.task_count ?? 0}`;
      this.renderCalendarScope(card, state, make);
    } else if (sectionName === "polls") {
      const body = document.querySelector("#polls .card-body");
      if (body) {
        body.replaceChildren();
        const polls = Array.isArray(state.polls) ? state.polls.slice(0, 5) : [];
        if (!polls.length) {
          body.append(empty("Ingen aktive avstemninger akkurat nå."));
        } else {
          const list = make("div", "mini-list");
          polls.forEach((poll) => {
            if (!poll || typeof poll !== "object") return;
            const item = make("div", "poll-detail");
            item.append(make("strong", "", poll.question || poll.title || "Uten spørsmål"));
            if (poll.votes && typeof poll.votes === "object" && !Array.isArray(poll.votes)) {
              const votes = Object.entries(poll.votes);
              const total = votes.reduce((sum, [, count]) => sum + (Number.isFinite(Number(count)) ? Number(count) : 0), 0);
              const bars = make("div", "poll-bars");
              votes.forEach(([option, rawCount]) => {
                const count = Number.isFinite(Number(rawCount)) ? Number(rawCount) : 0;
                const row = make("div", "poll-row");
                const track = make("div", "bar-track");
                const fill = make("div", "bar-fill");
                fill.style.width = `${total > 0 ? Math.max(0, Math.min(100, count / total * 100)) : 0}%`;
                track.append(fill);
                row.append(make("span", "", option), track, make("strong", "", count));
                bars.append(row);
              });
              item.append(bars);
            } else if (Number.isFinite(Number(poll.vote_count))) {
              item.append(make("span", "muted", `${Number(poll.vote_count)} stemmer`));
            }
            list.append(item);
          });
          body.append(list);
        }
      }
    } else if (rateLimits) {
      const body = document.querySelector("#rate-limits .card-body");
      if (body) {
        body.replaceChildren();
        const users = state.user_stats && typeof state.user_stats === "object" ? Object.entries(state.user_stats) : [];
        if (!users.length) {
          body.append(empty("Ingen rate-limit-data ennå."));
        } else {
          const counts = users.map(([user, raw]) => [user, typeof raw === "object" && raw !== null ? Number(raw.requests ?? raw.count ?? 0) || 0 : Number(raw) || 0]);
          const total = Math.max(...counts.map(([, count]) => count), 1);
          const shell = make("div", "table-shell");
          const table = make("table");
          const head = make("thead");
          const headRow = make("tr");
          ["Bruker", "Antall", "Bruk"].forEach((label) => headRow.append(make("th", "", label)));
          head.append(headRow);
          const tbody = make("tbody");
          counts.sort((a, b) => b[1] - a[1]).slice(0, 5).forEach(([user, count]) => {
            const row = make("tr");
            const usage = make("div", "usage-bar bar-track");
            const fill = make("div", "bar-fill");
            fill.style.width = `${Math.max(0, Math.min(100, count / total * 100))}%`;
            usage.append(fill);
            const usageCell = make("td");
            usageCell.append(usage);
            row.append(make("td", "", user), make("td", "", count), usageCell);
            tbody.append(row);
          });
          table.append(head, tbody);
          shell.append(table);
          body.append(shell);
        }
      }
    } else if (sectionName === "intents") {
      const body = document.querySelector("#intents .card-body");
      if (body) {
        body.replaceChildren();
        const intents = state.intent_counts && typeof state.intent_counts === "object" ? Object.entries(state.intent_counts) : [];
        if (!intents.length) {
          body.append(empty("Ingen intent-data ennå."));
        } else {
          const shell = make("div", "table-shell");
          const table = make("table");
          const head = make("thead");
          const headRow = make("tr");
          ["Intent", "Antall"].forEach((label) => headRow.append(make("th", "", label)));
          head.append(headRow);
          const bodyRows = make("tbody");
          intents.sort((a, b) => (Number(b[1]) || 0) - (Number(a[1]) || 0)).slice(0, 5).forEach(([intent, count]) => {
            const row = make("tr");
            row.append(make("td", "", intent), make("td", "", count));
            bodyRows.append(row);
          });
          table.append(head, bodyRows);
          shell.append(table);
          body.append(shell);
        }
      }
    } else if (sectionName === "logs") {
      this.data.logs = state;
      const older = document.querySelector('[data-log-older]');
      if (older) older.disabled = !state.next_cursor;
      const status = document.querySelector('[data-log-page-status]');
      if (status) status.textContent = state.truncated ? 'Avgrenset side. Eldre logger kan hentes separat.' : 'Ingen eldre logger i denne visningen.';
      const lines = Array.isArray(state.logs) ? state.logs.map((line) => String(line)) : [];
      const container = document.getElementById("log-container");
      if (container) {
        container.replaceChildren();
        if (lines.length) {
          const pre = make("pre");
          lines.forEach((line, index) => {
            if (index) pre.append(document.createTextNode("\n"));
            const upper = line.toUpperCase();
            const kind = upper.includes("ERROR") || upper.includes("CRITICAL") ? "log-error" : upper.includes("WARN") ? "log-warn" : upper.includes("INFO") ? "log-info" : "log-debug";
            pre.append(make("span", kind, line));
          });
          container.append(pre);
        } else {
          container.append(empty("Ingen logger tilgjengelig"));
        }
      }
      const activity = document.querySelector("#activity .activity-list");
      if (activity) {
        activity.replaceChildren();
        if (!lines.length) {
          activity.append(empty("Ingen aktivitet fanget ennå."));
        } else {
          lines.slice(-4).reverse().forEach((line) => {
            const upper = line.toUpperCase();
            const tone = upper.includes("ERROR") || upper.includes("CRITICAL") ? "log-error" : upper.includes("WARN") ? "log-warn" : upper.includes("INFO") ? "log-info" : "log-debug";
            const title = line.includes("]") ? line.split("]", 2)[1].trim() : line;
            const prefix = line.includes("[") ? line.split("[", 1)[0].trim() : "Nylig";
            const item = make("div", "activity-item");
            item.append(make("strong", tone, title.slice(0, 120)), make("span", "", prefix));
            activity.append(item);
          });
        }
      }
      setText('[data-metric="logs.count"]', lines.length);
    }

    if (this.openSection === sectionName && !document.getElementById("section-modal")?.hidden) {
      this.updateSectionModal(sectionName);
    }
    this.updateOverview();
  }

  pauseLogs(paused) {
    const entry = this.pollingEntries['/api/logs?lines=50'];
    entry.paused = paused;
    if (entry.timerId !== null) clearTimeout(entry.timerId);
    if (entry.deadlineId !== null) clearTimeout(entry.deadlineId);
    entry.timerId = entry.deadlineId = null;
    entry.controller?.abort();
    entry.controller = null;
    entry.generation += 1;
    const button = document.querySelector('[data-log-pause]');
    if (button) {
      button.textContent = paused ? 'Følg siste logger' : 'Sett på pause';
      button.setAttribute('aria-pressed', String(paused));
    }
  }

  logRequestUrl() {
    const query = new URLSearchParams('lines=50');
    const level = document.querySelector('[data-log-level]')?.value;
    const component = document.querySelector('[data-log-component]')?.value.trim();
    if (level) query.set('level', level);
    if (component) query.set('component', component);
    if (this.logCursor) query.set('cursor', this.logCursor);
    return '/api/logs?' + query.toString();
  }

  requestLogs(cursor = null) {
    this.logCursor = cursor;
    this.retryEndpoint('/api/logs?lines=50');
  }

  updateOverview() {
    const calendar = this.data.calendar || {};
    const polls = this.data.polls || {};
    const calendarMetric = document.querySelector('[data-metric="overview.calendar"]');
    if (calendarMetric) calendarMetric.textContent = `${calendar.event_count ?? 0} / ${calendar.task_count ?? 0}`;
    const pollMetric = document.querySelector('[data-metric="overview.polls"]');
    if (pollMetric) pollMetric.textContent = polls.active_polls ?? 0;
  }

  calendarScopeLines(state) {
    const lines = [];
    const display = (value) => Array.isArray(value)
      ? value.join(", ")
      : value === undefined || value === null || value === "" ? "Ingen" : String(value);
    if (state.access_summary) lines.push(`Tilgang: ${display(state.access_summary)}`);
    if (state.default_scope) lines.push(`Standardområde: ${display(state.default_scope)}`);
    if (Array.isArray(state.scope_policy)) {
      state.scope_policy.forEach((scope) => {
        if (!scope || typeof scope !== "object") return;
        lines.push(`Område: ${display(scope.scope_id)} (${display(scope.kind)})`);
        lines.push(`Eier: ${display(scope.owner_id)}`);
        lines.push(`Godkjente medlemmer: ${display(scope.collaborator_ids)}`);
        lines.push(`Kanaler: ${display(scope.channel_ids)}`);
        lines.push(`Lesetilgang: ${display(scope.read_policy)}`);
        lines.push(`Skrivetilgang: ${display(scope.write_policy)}`);
      });
    }
    if (state.sync_states && typeof state.sync_states === "object") {
      const labels = { pending: "Ventende", unknown: "Uavklart", failed: "Feilet", conflict: "Konflikt", synced: "Bekreftet" };
      lines.push("Google: " + Object.entries(labels).map(([key, label]) => `${label}: ${Number(state.sync_states[key]) || 0}`).join(", "));
    }
    const invocation = state.invocation_policy;
    if (invocation && typeof invocation === "object") {
      lines.push(`Kalleregel: ${display(invocation.mode)}`);
      lines.push(`Tillatte brukere: ${display(invocation.allowed_users)}`);
      lines.push(`Tillatte kanaler: ${display(invocation.allowed_channels)}`);
      lines.push(`Omvei for gruppedirektemeldinger: ${invocation.legacy_group_dm_bypass ? "Ja" : "Nei"}`);
      if (invocation.inherited_defaults) {
        lines.push(`Advarsel om arvede standarder: ${display(invocation.inherited_defaults)}`);
      }
    }
    return lines;
  }

  renderCalendarScope(card, state, make) {
    if (!card) return;
    card.querySelector("[data-calendar-scope]")?.remove();
    const lines = this.calendarScopeLines(state);
    if (!lines.length) return;
    const explanation = make("section", "calendar-scope");
    explanation.dataset.calendarScope = "";
    explanation.setAttribute("aria-label", "Tilgang og målgruppe");
    explanation.append(make("h4", "", "Tilgang og målgruppe"));
    explanation.append(make("p", "calendar-scope-summary", lines.join("\n")));
    card.append(explanation);
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
    if (s === "disabled") {
      badge.className = "badge badge-neutral";
      badge.textContent = "Ikke nødvendig";
      return;
    }
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
    this.openSection = section;
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
    this.openSection = null;
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
    this.openModal(section, { title: titles[section] || "Detaljer", content: this.sectionModalText(section, data) });
  }

  updateSectionModal(section) {
    const titles = {
      status: "Bot-status", bridge: "Bridge", calendar: "Kalender", polls: "Avstemninger",
      "rate-limits": "Rate limits", intents: "Intents", memory: "Minne", logs: "Logger",
    };
    const data = section === "rate-limits"
      ? (this.data["rate-limits"] || this.data.rate_limits || {})
      : (this.data[section] || {});
    const title = document.getElementById("modal-title");
    const content = document.getElementById("modal-content");
    if (title) title.textContent = titles[section] || "Detaljer";
    if (content) content.textContent = this.sectionModalText(section, data);
  }

  sectionModalText(section, data) {
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
        add("Status", data.readiness?.components?.bridge?.status === "disabled" ? "Ikke nødvendig" : data.status || "N/A");
        add("LM Studio", data.readiness?.components?.bridge?.status === "disabled" ? "Ikke i bruk" : data.lm_studio || "N/A");
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
        } else {
          addBlank();
          lines.push("Kommende hendelser: Ingen kommende kalenderhendelser.");
        }
        const scopeLines = this.calendarScopeLines(data);
        if (scopeLines.length) {
          addBlank();
          lines.push("Tilgang og målgruppe:");
          lines.push(...scopeLines);
        }
        break;
      case "polls":
        add("Aktive avstemninger", data.active_polls ?? 0);
        if (Array.isArray(data.polls) && data.polls.length) {
          addBlank();
          data.polls.forEach((poll) => {
            lines.push(`${poll.question || poll.title || "Uten spørsmål"}`);
            if (poll.votes && typeof poll.votes === "object") {
              Object.entries(poll.votes).forEach(([option, count]) => lines.push(`- ${option}: ${count}`));
            } else if (Number.isFinite(Number(poll.vote_count))) {
              lines.push(`- Stemmer: ${Number(poll.vote_count)}`);
            }
          });
        } else {
          add("Detaljer", "Ingen aktive avstemninger akkurat nå.");
        }
        break;
      case "rate-limits":
        add("Totale forespørsler", data.summary?.total_requests ?? 0);
        Object.entries(data.user_stats || {}).forEach(([user, raw]) => {
          const count = typeof raw === "object" && raw !== null ? raw.requests ?? raw.count ?? "N/A" : raw;
          lines.push(`- ${user}: ${count}`);
        });
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
    return lines.join("\n");
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
