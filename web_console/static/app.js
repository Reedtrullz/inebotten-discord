const _registerConsoleApp = () => {
  Alpine.data('consoleApp', () => ({
    theme: localStorage.getItem('theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'),
    mobileMenuOpen: false,

    init() {
      document.documentElement.classList.remove('dark', 'light');
      document.documentElement.classList.add(this.theme);

      this.$watch('theme', (value) => {
        localStorage.setItem('theme', value);
        document.documentElement.classList.remove('dark', 'light');
        document.documentElement.classList.add(value);
      });

      this.initData();
      this.startPolling();

      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') {
          this.stopPolling();
        } else {
          this.startPolling();
        }
      });
    },

    toggleTheme() {
      this.theme = this.theme === 'dark' ? 'light' : 'dark';
    },

    activeModal: null,
    modalData: {},
    _focusTrapHandler: null,
    _lastFocusedElement: null,

    openModal(name, data = {}) {
      this._lastFocusedElement = document.activeElement;
      this.activeModal = name;
      this.modalData = data;
      this.$nextTick(() => {
        this._trapFocus();
        const modalContent = document.querySelector('[role="dialog"]');
        if (modalContent) {
          modalContent.focus();
        }
      });
    },

    closeModal() {
      this.activeModal = null;
      this.modalData = {};
      this._untrapFocus();
      if (this._lastFocusedElement) {
        this.$nextTick(() => {
          this._lastFocusedElement.focus();
          this._lastFocusedElement = null;
        });
      }
    },

    _trapFocus() {
      const modal = document.querySelector('[role="dialog"]');
      if (!modal) return;

      const focusableSelectors = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

      this._focusTrapHandler = (e) => {
        if (e.key !== 'Tab') return;

        const focusableElements = Array.from(modal.querySelectorAll(focusableSelectors));
        const first = focusableElements[0];
        const last = focusableElements[focusableElements.length - 1];

        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      };

      document.addEventListener('keydown', this._focusTrapHandler);
    },

    _untrapFocus() {
      if (this._focusTrapHandler) {
        document.removeEventListener('keydown', this._focusTrapHandler);
        this._focusTrapHandler = null;
      }
    },

    lastUpdated: null,
    data: {},

    pollingConfig: {
      '/api/status': { interval: 5000, lastFetch: 0 },
      '/api/bridge': { interval: 5000, lastFetch: 0 },
      '/api/calendar': { interval: 10000, lastFetch: 0 },
      '/api/polls': { interval: 10000, lastFetch: 0 },
      '/api/rate-limits': { interval: 10000, lastFetch: 0 },
      '/api/intents': { interval: 10000, lastFetch: 0 },
      '/api/memory': { interval: 10000, lastFetch: 0 },
      '/api/logs?lines=50': { interval: 30000, lastFetch: 0 },
    },
    pollingControllers: {},
    pollingBackoff: {},
    isPolling: false,
    authExpired: false,

    initData() {
      const script = document.getElementById('initial-data');
      if (script) {
        try {
          this.data = JSON.parse(script.textContent);
          this.lastUpdated = new Date().toLocaleTimeString('no-NO', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        } catch (e) {
          console.error('Failed to parse initial data:', e);
        }
      }
    },

    startPolling() {
      if (this.isPolling || this.authExpired) return;
      this.isPolling = true;

      Object.keys(this.pollingConfig).forEach(endpoint => {
        this.pollEndpoint(endpoint);
      });
    },

    stopPolling() {
      this.isPolling = false;
      Object.values(this.pollingControllers).forEach(controller => {
        controller.abort();
      });
      this.pollingControllers = {};
    },

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

      if (this.pollingControllers[endpoint]) {
        this.pollingControllers[endpoint].abort();
      }

      const controller = new AbortController();
      this.pollingControllers[endpoint] = controller;

      try {
        const response = await fetch(endpoint, {
          credentials: 'same-origin',
          signal: controller.signal,
        });

        if (response.status === 401) {
          this.authExpired = true;
          this.stopPolling();
          console.warn('Session expired. Please refresh to log in again.');
          return;
        }

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        const key = endpoint.replace('/api/', '').replace('?lines=50', '');
        this.data[key] = data;

        this.pollingBackoff[endpoint] = 0;
        config.lastFetch = now;
        this.lastUpdated = new Date().toLocaleTimeString('no-NO', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        this.updateDashboard(key, data);

      } catch (error) {
        if (error.name === 'AbortError') {
          return;
        }

        this.pollingBackoff[endpoint] = Math.min((this.pollingBackoff[endpoint] || 0) + config.interval, 60000);
        console.error(`Poll error for ${endpoint}:`, error);
      } finally {
        delete this.pollingControllers[endpoint];
      }

      if (this.isPolling && !this.authExpired) {
        const nextInterval = config.interval + (this.pollingBackoff[endpoint] || 0);
        setTimeout(() => this.pollEndpoint(endpoint), nextInterval);
      }
    },

    updateDashboard(section, data) {
      if (!data) return;

      const setText = (key, value) => {
        const el = document.querySelector(`[data-metric="${key}"]`);
        if (el) el.textContent = value ?? 'N/A';
      };

      switch (section) {
        case 'status': {
          setText('status.uptime', this.formatUptime(data.uptime_seconds));
          setText('status.guilds', data.guilds);
          setText('status.users', data.users);
          setText('status.discord', data.discord_connected ? 'Ja' : 'Nei');
          const badge = document.querySelector('#status .badge');
          if (badge && data.status) {
            const online = String(data.status).toLowerCase() === 'online';
            badge.className = `badge ${online ? 'badge-online' : 'badge-error'}`;
            badge.textContent = online ? 'Online' : 'Offline';
          }
          break;
        }
        case 'bridge': {
          setText('bridge.lm_studio', data.lm_studio);
          setText('bridge.requests', data.requests);
          setText('bridge.errors', data.errors);
          const badge = document.querySelector('#bridge .badge');
          if (badge && data.status) {
            const s = String(data.status).toLowerCase();
            let cls = 'badge-warning';
            let text = 'Ukjent';
            const ok = ['online', 'connected', 'ok', 'healthy', 'running', 'active', 'true', 'yes'];
            const err = ['offline', 'disconnected', 'error', 'unhealthy', 'stopped', 'inactive', 'false', 'no'];
            if (ok.includes(s)) { cls = 'badge-online'; text = 'Tilkoblet'; }
            else if (err.includes(s)) { cls = 'badge-error'; text = 'Frakoblet'; }
            badge.className = `badge ${cls}`;
            badge.textContent = text;
          }
          const errEl = document.querySelector('[data-metric="bridge.errors"]');
          if (errEl) {
            const errVal = parseInt(data.errors, 10) || 0;
            errEl.className = `text-xl font-bold ${errVal > 0 ? 'text-[var(--status-error)]' : 'text-[var(--text-primary)]'}`;
          }
          break;
        }
        case 'calendar': {
          setText('calendar.events', data.event_count);
          setText('calendar.tasks', data.task_count);
          const badge = document.querySelector('#calendar .badge');
          if (badge && typeof data.event_count !== 'undefined') {
            badge.textContent = `${data.event_count} hendelser`;
          }
          break;
        }
        case 'polls': {
          setText('polls.active', data.active_polls);
          const badge = document.querySelector('#polls .badge');
          if (badge && typeof data.active_polls !== 'undefined') {
            badge.textContent = `${data.active_polls} aktive`;
          }
          break;
        }
        case 'rate-limits': {
          const total = data.summary?.total_requests ?? 0;
          setText('rate_limits.total', total);
          const headerText = document.querySelector('#rate-limits .text-sm.text-\\[var\\(--text-muted\\)\\]');
          if (headerText) {
            headerText.textContent = `${total} forespørsler totalt`;
          }
          break;
        }
        case 'intents': {
          setText('intents.fallback', data.fallback_count);
          const badge = document.querySelector('#intents .badge');
          if (badge && typeof data.fallback_count !== 'undefined') {
            const err = (data.fallback_count || 0) > 5;
            badge.className = `badge ${err ? 'badge-error' : 'badge-info'}`;
            badge.textContent = `Fallbacks: ${data.fallback_count}`;
          }
          break;
        }
        case 'memory': {
          setText('memory.users', data.user_count);
          setText('memory.conversations', data.conversation_count);
          break;
        }
        case 'logs': {
          const lines = Array.isArray(data.logs) ? data.logs.length : 0;
          setText('logs.count', lines);
          const headerText = document.querySelector('#logs .text-sm.text-\\[var\\(--text-muted\\)\\]');
          if (headerText) {
            headerText.textContent = `Siste ${lines} linjer`;
          }
          break;
        }
      }
    },

    formatUptime(seconds) {
      if (seconds === undefined || seconds === null || seconds < 0) return 'N/A';
      const days = Math.floor(seconds / 86400);
      const hours = Math.floor((seconds % 86400) / 3600);
      const mins = Math.floor((seconds % 3600) / 60);
      const secs = seconds % 60;
      const parts = [];
      if (days) parts.push(`${days}d`);
      if (hours) parts.push(`${hours}t`);
      if (mins) parts.push(`${mins}m`);
      if (secs || !parts.length) parts.push(`${secs}s`);
      return parts.join(' ');
    },

    showSectionModal(section) {
      const titles = {
        status: 'Bot Status',
        bridge: 'Bridge',
        calendar: 'Kalender',
        polls: 'Avstemninger',
        'rate-limits': 'Rate Limits',
        intents: 'Intents',
        memory: 'Minne',
        logs: 'Logger',
      };
      const data = this.data[section] || {};
      let content = '';
      switch (section) {
        case 'status':
          content = `<table class="w-full text-sm"><tbody>
            <tr class="border-b border-[var(--border-color)]"><td class="py-2 font-medium">Status</td><td class="py-2">${data.status || 'N/A'}</td></tr>
            <tr class="border-b border-[var(--border-color)]"><td class="py-2 font-medium">Oppetid</td><td class="py-2">${this.formatUptime(data.uptime_seconds)}</td></tr>
            <tr class="border-b border-[var(--border-color)]"><td class="py-2 font-medium">Servere</td><td class="py-2">${data.guilds ?? 'N/A'}</td></tr>
            <tr class="border-b border-[var(--border-color)]"><td class="py-2 font-medium">Brukere</td><td class="py-2">${data.users ?? 'N/A'}</td></tr>
            <tr><td class="py-2 font-medium">Discord-tilkobling</td><td class="py-2">${data.discord_connected ? 'Ja' : 'Nei'}</td></tr>
          </tbody></table>`;
          break;
        case 'bridge':
          content = `<table class="w-full text-sm"><tbody>
            <tr class="border-b border-[var(--border-color)]"><td class="py-2 font-medium">Status</td><td class="py-2">${data.status || 'N/A'}</td></tr>
            <tr class="border-b border-[var(--border-color)]"><td class="py-2 font-medium">LM Studio</td><td class="py-2">${data.lm_studio || 'N/A'}</td></tr>
            <tr class="border-b border-[var(--border-color)]"><td class="py-2 font-medium">Forespørsler</td><td class="py-2">${data.requests ?? 0}</td></tr>
            <tr><td class="py-2 font-medium">Feil</td><td class="py-2">${data.errors ?? 0}</td></tr>
          </tbody></table>`;
          break;
        case 'calendar':
          content = `<table class="w-full text-sm"><tbody>
            <tr class="border-b border-[var(--border-color)]"><td class="py-2 font-medium">Hendelser</td><td class="py-2">${data.event_count ?? 0}</td></tr>
            <tr><td class="py-2 font-medium">Oppgaver</td><td class="py-2">${data.task_count ?? 0}</td></tr>
          </tbody></table>`;
          if (Array.isArray(data.upcoming_events) && data.upcoming_events.length) {
            content += `<div class="mt-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">Kommende hendelser</div>`;
            data.upcoming_events.slice(0, 10).forEach(ev => {
              const title = ev.title || ev.name || 'Uten tittel';
              const when = ev.when || ev.start || ev.date || 'Ukjent tid';
              content += `<div class="flex items-center justify-between py-2 border-b border-[var(--border-color)] last:border-0"><span>${title}</span><span class="text-[var(--text-muted)]">${when}</span></div>`;
            });
          }
          break;
        case 'polls':
          content = `<div class="text-sm">Aktive avstemninger: <strong>${data.active_polls ?? 0}</strong></div>`;
          break;
        case 'rate-limits':
          content = `<div class="text-sm">Totale forespørsler: <strong>${data.summary?.total_requests ?? 0}</strong></div>`;
          break;
        case 'intents':
          content = `<div class="text-sm">Fallbacks: <strong>${data.fallback_count ?? 0}</strong></div>`;
          if (data.intent_counts && Object.keys(data.intent_counts).length) {
            content += `<table class="w-full text-sm mt-4"><thead><tr class="border-b border-[var(--border-color)]"><th class="py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">Intent</th><th class="py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">Antall</th></tr></thead><tbody>`;
            Object.entries(data.intent_counts).sort((a, b) => (b[1] || 0) - (a[1] || 0)).forEach(([intent, count]) => {
              content += `<tr class="border-b border-[var(--border-color)]"><td class="py-2">${intent}</td><td class="py-2">${count}</td></tr>`;
            });
            content += `</tbody></table>`;
          }
          break;
        case 'memory':
          content = `<table class="w-full text-sm"><tbody>
            <tr class="border-b border-[var(--border-color)]"><td class="py-2 font-medium">Brukere i minne</td><td class="py-2">${data.user_count ?? 0}</td></tr>
            <tr><td class="py-2 font-medium">Samtaler</td><td class="py-2">${data.conversation_count ?? 0}</td></tr>
          </tbody></table>`;
          break;
        case 'logs':
          if (Array.isArray(data.logs) && data.logs.length) {
            content = `<pre class="whitespace-pre-wrap break-words text-sm">` + data.logs.map(line => {
              const upper = String(line).toUpperCase();
              if (upper.includes('ERROR') || upper.includes('CRITICAL')) return `<span class="text-red-500">${line}</span>`;
              if (upper.includes('WARN')) return `<span class="text-yellow-500">${line}</span>`;
              if (upper.includes('INFO')) return `<span class="text-slate-400">${line}</span>`;
              return `<span class="text-slate-500">${line}</span>`;
            }).join('\n') + `</pre>`;
          } else {
            content = '<p class="text-sm text-[var(--text-muted)] text-center py-4">Ingen logger tilgjengelig</p>';
          }
          break;
      }
      this.openModal(section, { title: titles[section] || 'Detaljer', content });
    },
  }));
};

if (window.Alpine) {
  _registerConsoleApp();
} else {
  document.addEventListener('alpine:init', _registerConsoleApp);
}

setTimeout(() => {
  if (typeof window.Alpine !== 'undefined' && typeof Alpine.data('consoleApp') === 'undefined') {
    _registerConsoleApp();
  }
}, 50);
