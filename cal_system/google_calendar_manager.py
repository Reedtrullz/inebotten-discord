#!/usr/bin/env python3
"""
Google Calendar Manager for Inebotten
Integrates with Google Calendar API to sync events
"""

import json
import os
import sys
import subprocess
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    # Fallback for Python < 3.9
    try:
        from backports.zoneinfo import ZoneInfo
    except ImportError:
        # Last resort: simplified mock or dateutil
        from dateutil.tz import gettz
        class ZoneInfo:
            def __new__(cls, name):
                return gettz(name)

# Suppress requests/urllib3 version warnings
warnings.filterwarnings("ignore", category=UserWarning, module="requests")

# Add the google-workspace skill scripts to path
SKILL_PATH = (
    Path.home() / ".hermes" / "skills" / "productivity" / "google-workspace" / "scripts"
)
if str(SKILL_PATH) not in sys.path:
    sys.path.insert(0, str(SKILL_PATH))

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_hermes_home() -> Path:
    """Return the base directory for Inebotten's persistent local state."""
    return Path(os.getenv("HERMES_HOME", Path.home() / ".hermes")).expanduser()


def _configured_path(env_name: str) -> Path | None:
    raw_path = os.getenv(env_name)
    if not raw_path:
        return None
    return Path(raw_path).expanduser()


def get_google_token_path() -> Path:
    """Return the OAuth token path, preserving the historical fallback path."""
    configured = _configured_path("GCAL_TOKEN_PATH")
    if configured:
        return configured

    token_path = get_hermes_home() / "google_token.json"
    if token_path.exists():
        return token_path

    # Backwards compatibility for very old local setups that placed the token
    # next to the project checkout instead of under HERMES_HOME.
    alt_path = Path(__file__).parent.parent.parent.parent / "google_token.json"
    if alt_path.exists():
        return alt_path
    return token_path


def get_google_credentials_path() -> Path:
    """Return the OAuth client secrets path used to start new auth flows."""
    configured = _configured_path("GCAL_CREDENTIALS_PATH")
    if configured:
        return configured
    return get_hermes_home() / "credentials.json"


# Kept for compatibility with older imports/tests; manager instances resolve
# these paths dynamically so env changes and Docker mounts are respected.
HERMES_HOME = get_hermes_home()
TOKEN_PATH = get_google_token_path()
CREDENTIALS_PATH = get_google_credentials_path()


class GoogleCalendarManager:
    """
    Manages Google Calendar integration for the Discord bot
    """

    def __init__(self):
        self.calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
        self.hermes_home = get_hermes_home()
        self.token_path = get_google_token_path()
        self.credentials_path = get_google_credentials_path()
        self.enabled = self._check_auth()

    def _token_path(self) -> Path:
        if hasattr(self, "token_path"):
            return self.token_path
        return get_google_token_path()

    def _credentials_path(self) -> Path:
        if hasattr(self, "credentials_path"):
            return self.credentials_path
        return get_google_credentials_path()

    def _check_auth(self):
        """Check if Google authentication is set up and actually works"""
        token_path = self._token_path()
        if not token_path.exists():
            return False
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request

            creds = Credentials.from_authorized_user_file(
                str(token_path), SCOPES
            )
            # If token is valid right now, we're good
            if creds.valid:
                return True
            # If expired but we have a refresh token, try to refresh now
            # to catch revoked tokens early
            if creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    self._save_credentials(creds)
                    return True
                except Exception as e:
                    print(f"[GCAL] Refresh failed (token revoked): {e}")
                    return False
            return False
        except Exception as e:
            print(f"[GCAL] Auth check failed: {e}")
            return False

    def _save_credentials(self, creds):
        """Persist credentials back to disk (e.g. after token refresh)"""
        try:
            token_path = self._token_path()
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.parent.chmod(0o700)
            fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as token:
                token.write(creds.to_json())
            token_path.chmod(0o600)
        except Exception as e:
            print(f"[GCAL] Failed to save token: {e}")

    def is_configured(self):
        """Return True if Google Calendar is configured and ready"""
        return self.enabled

    def get_auth_url(self):
        """Generate an OAuth authorization URL for the user to visit"""
        from google_auth_oauthlib.flow import InstalledAppFlow
        client_secrets_file = self._credentials_path()
        
        if not client_secrets_file.exists():
            return False, (
                f"Fant ikke `credentials.json` i {client_secrets_file.parent}. "
                "Last ned OAuth 2.0 Client ID for 'Desktop app' fra Google Cloud "
                "Platform, døp filen til `credentials.json`, og legg den der. "
                "I Docker/VPS skal filen ligge i den monterte data-mappen."
            )
            
        try:
            self._auth_flow = InstalledAppFlow.from_client_secrets_file(
                str(client_secrets_file),
                SCOPES,
            )
            # Use localhost as redirect URI (OOB is deprecated)
            self._auth_flow.redirect_uri = "http://localhost:8080"
            auth_url, _ = self._auth_flow.authorization_url(
                prompt="consent", access_type="offline"
            )
            return True, auth_url
        except Exception as e:
            return False, f"Klarte ikke generere auth URL: {e}"

    def exchange_code(self, code):
        """Exchange the authorization code for a token"""
        if not getattr(self, '_auth_flow', None):
            return False, "Ingen aktiv påloggingsøkt funnet. Vennligst kjør `@inebotten kalender auth` først for å få en ny lenke, og prøv igjen med den nye koden."
            
        try:
            flow = self._auth_flow
            flow.fetch_token(code=code)
            
            creds = flow.credentials
            self._save_credentials(creds)
            self.enabled = True
            self._auth_flow = None # Clear flow after success
            return True, "Autentisering vellykket! Google Calendar er nå synkronisert og klar til bruk."
        except Exception as e:
            return False, f"Autentisering feilet: Sjekk at koden er riktig. ({e})"

    def _run_calendar_command(self, *args):
        """Run a calendar command via the google_api.py script"""
        script_path = SKILL_PATH / "google_api.py"
        cmd = [sys.executable, str(script_path), "calendar"] + list(args)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                print(f"[GCAL] Command failed: {result.stderr}")
                return None
            return json.loads(result.stdout) if result.stdout.strip() else None
        except Exception as e:
            print(f"[GCAL] Error running command: {e}")
            return None

    def list_upcoming_events(self, days=30):
        """
        List upcoming events from Google Calendar using direct API.

        Args:
            days: Number of days to look ahead

        Returns:
            List of event dicts or None if error
        """
        if not self.enabled:
            return None

        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from google.auth.transport.requests import Request

            creds = Credentials.from_authorized_user_file(
                str(self._token_path()), SCOPES
            )
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self._save_credentials(creds)

            service = build("calendar", "v3", credentials=creds)

            now = datetime.now(timezone.utc)
            end = now + timedelta(days=days)

            items = []
            page_token = None
            while True:
                events_result = service.events().list(
                    calendarId=self.calendar_id,
                    timeMin=now.isoformat(),
                    timeMax=end.isoformat(),
                    maxResults=2500,
                    singleEvents=True,
                    orderBy="startTime",
                    pageToken=page_token,
                ).execute()
                items.extend(events_result.get("items", []))
                page_token = events_result.get("nextPageToken")
                if not page_token:
                    break
            return items

        except Exception as e:
            print(f"[GCAL] Error listing events: {e}")
            return None

    def get_event(self, event_id):
        """Fetch a single event by ID; returns None if missing or unavailable."""
        if not self.enabled:
            return None

        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from google.auth.transport.requests import Request

            creds = Credentials.from_authorized_user_file(
                str(self._token_path()), SCOPES
            )
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self._save_credentials(creds)

            service = build("calendar", "v3", credentials=creds)
            return (
                service.events()
                .get(calendarId=self.calendar_id, eventId=event_id)
                .execute()
            )
        except Exception as e:
            print(f"[GCAL] Error fetching event {event_id}: {e}")
            return None

    def create_event(
        self,
        title,
        start_time,
        end_time=None,
        description=None,
        location=None,
        attendees=None,
        recurrence=None,
        rrule_day=None,
        discord_user_id=None,
        discord_username=None,
    ):
        """
        Create a new event in Google Calendar

        Args:
            title: Event title/summary
            start_time: ISO 8601 datetime string (with timezone)
            end_time: ISO 8601 datetime string (optional, defaults to 1 hour after start)
            description: Optional event description
            location: Optional location string
            attendees: Optional comma-separated list of email addresses
            recurrence: Optional recurrence rule ('weekly', 'biweekly', 'monthly', 'yearly')
            rrule_day: Optional specific day for weekly recurrence (e.g., 'MO', 'TU')

        Returns:
            Event dict with id and htmlLink, or None if error
        """
        if not self.enabled:
            return None

        # Calculate end time if not provided (default 1 hour duration)
        if end_time is None:
            try:
                start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                end_dt = start_dt + timedelta(hours=1)
                end_time = end_dt.isoformat()
            except Exception as e:
                print(f"[CALENDAR] GCal datetime parse error: {e}")
                return None

        # Build recurrence rule if specified
        rrule = None
        if recurrence:
            rrule = self._build_rrule(recurrence, rrule_day)

        # Use direct API for all events (ensures timezone support)
        return self._create_event_api(
            title=title,
            start_time=start_time,
            end_time=end_time,
            description=description,
            location=location,
            rrule=rrule,
            discord_user_id=discord_user_id,
            discord_username=discord_username,
        )

    def _create_event_api(
        self, title, start_time, end_time, description=None, location=None, rrule=None,
        discord_user_id=None, discord_username=None
    ):
        """
        Create an event using direct Google Calendar API (handles both recurring and non-recurring)
        """
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from google.auth.transport.requests import Request

            # Load credentials
            creds = Credentials.from_authorized_user_file(
                str(self._token_path()), SCOPES
            )
            # Refresh if expired
            if creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    print(f"[GCAL] Token refresh failed during event creation: {e}")
                    # Mark as disabled so we don't keep trying
                    self.enabled = False
                    return None
            elif not creds.valid:
                print("[GCAL] Credentials invalid (no refresh token)")
                self.enabled = False
                return None

            # Save back refreshed token
            self._save_credentials(creds)

            service = build("calendar", "v3", credentials=creds)

            # Build event body
            event_body = {
                "summary": title,
                "start": {"dateTime": start_time, "timeZone": "Europe/Oslo"},
                "end": {"dateTime": end_time, "timeZone": "Europe/Oslo"},
            }

            if description:
                event_body["description"] = description
            if location:
                event_body["location"] = location
            if rrule:
                event_body["recurrence"] = [rrule]
            
            # Add Discord metadata to extended properties
            if discord_user_id or discord_username:
                event_body["extendedProperties"] = {
                    "private": {
                        "discord_user_id": str(discord_user_id) if discord_user_id else "",
                        "discord_username": discord_username or ""
                    }
                }

            result = (
                service.events()
                .insert(calendarId=self.calendar_id, body=event_body)
                .execute()
            )

            return {
                "status": "created",
                "id": result["id"],
                "summary": result.get("summary", ""),
                "htmlLink": result.get("htmlLink", ""),
            }

        except Exception as e:
            print(f"[GCAL] Error creating event: {e}")
            return None

    def delete_event(self, event_id):
        """
        Delete an event from Google Calendar

        Args:
            event_id: The Google Calendar event ID

        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            return False

        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from google.auth.transport.requests import Request

            creds = Credentials.from_authorized_user_file(
                str(self._token_path()), SCOPES
            )
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self._save_credentials(creds)

            service = build("calendar", "v3", credentials=creds)
            service.events().delete(
                calendarId=self.calendar_id, eventId=event_id
            ).execute()
            return True
        except Exception as e:
            print(f"[GCAL] Error deleting event {event_id}: {e}")
            return False

    def _build_rrule(self, recurrence, rrule_day=None):
        if not recurrence:
            return None
        recurrence = recurrence.lower()
        if recurrence == "weekly":
            return f"RRULE:FREQ=WEEKLY;BYDAY={rrule_day}" if rrule_day else "RRULE:FREQ=WEEKLY"
        if recurrence == "biweekly":
            return f"RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY={rrule_day}" if rrule_day else "RRULE:FREQ=WEEKLY;INTERVAL=2"
        if recurrence == "monthly":
            return "RRULE:FREQ=MONTHLY"
        if recurrence == "yearly":
            return "RRULE:FREQ=YEARLY"
        return None

    def _local_event_times(self, date_str, time_str=None):
        day, month, year = date_str.split(".")
        hour, minute = (time_str or "12:00").split(":")
        local_tz = ZoneInfo("Europe/Oslo")
        start_dt = datetime(
            int(year), int(month), int(day), int(hour), int(minute), tzinfo=local_tz
        )
        end_dt = start_dt + timedelta(hours=1)
        return start_dt.isoformat(), end_dt.isoformat()

    def update_event(
        self,
        event_id,
        title=None,
        description=None,
        completed=False,
        date_str=None,
        time_str=None,
        recurrence=None,
        rrule_day=None,
    ):
        """
        Update an event in Google Calendar
        """
        if not self.enabled:
            return None

        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from google.auth.transport.requests import Request

            creds = Credentials.from_authorized_user_file(
                str(self._token_path()), SCOPES
            )
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self._save_credentials(creds)

            service = build("calendar", "v3", credentials=creds)

            # Get existing event
            event = (
                service.events()
                .get(calendarId=self.calendar_id, eventId=event_id)
                .execute()
            )

            # Update fields
            if title:
                event["summary"] = title
            
            if completed and not event["summary"].endswith(" [FERDIG]"):
                event["summary"] += " [FERDIG]"
            
            if description:
                event["description"] = description

            if date_str:
                start_iso, end_iso = self._local_event_times(date_str, time_str)
                event["start"] = {"dateTime": start_iso, "timeZone": "Europe/Oslo"}
                event["end"] = {"dateTime": end_iso, "timeZone": "Europe/Oslo"}

            if recurrence is not None:
                rrule = self._build_rrule(recurrence, rrule_day)
                if rrule:
                    event["recurrence"] = [rrule]
                else:
                    event.pop("recurrence", None)

            result = (
                service.events()
                .update(calendarId=self.calendar_id, eventId=event_id, body=event)
                .execute()
            )

            return result
        except Exception as e:
            print(f"[GCAL] Error updating event {event_id}: {e}")
            return None

    def sync_local_event(self, event_data):
        """
        Sync a local bot event to Google Calendar

        Args:
            event_data: Dict with title, date (DD.MM.YYYY), time (HH:MM), description

        Returns:
            Created event dict or None
        """
        if not self.enabled:
            return None

        try:
            # Parse date and time
            date_str = event_data.get("date", "")  # DD.MM.YYYY
            time_str = event_data.get("time") or "12:00"  # HH:MM

            # Parse date
            day, month, year = date_str.split(".")
            hour, minute = time_str.split(":")

            # Create datetime in local timezone (assume Europe/Oslo for Norway)
            from zoneinfo import ZoneInfo

            local_tz = ZoneInfo("Europe/Oslo")

            start_dt = datetime(
                int(year), int(month), int(day), int(hour), int(minute), tzinfo=local_tz
            )
            end_dt = start_dt + timedelta(hours=1)

            # Convert to ISO format with timezone
            start_iso = start_dt.isoformat()
            end_iso = end_dt.isoformat()

            return self.create_event(
                title=event_data.get("title", "Untitled"),
                start_time=start_iso,
                end_time=end_iso,
                description=event_data.get("description", ""),
                recurrence=event_data.get("recurrence"),
                rrule_day=event_data.get("rrule_day"),
                discord_user_id=event_data.get("user_id"),
                discord_username=event_data.get("username"),
            )

        except Exception as e:
            print(f"[GCAL] Error syncing event: {e}")
            return None

    def format_event_list(self, events, title="Google Calendar - Kommende"):
        """
        Format a list of Google Calendar events for display
        """
        if not events:
            return f"📅 **{title}**\nIngen arrangementer funnet."

        lines = [f"📅 **{title}**", ""]

        for event in events[:10]:  # Show max 10
            summary = event.get("summary", "(ingen tittel)")
            start = event.get("start", "")
            location = event.get("location", "")
            link = event.get("htmlLink", "")

            # Parse datetime - start can be a dict or string
            try:
                if isinstance(start, dict):
                    if "dateTime" in start:
                        dt = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
                        from zoneinfo import ZoneInfo
                        local_dt = dt.astimezone(ZoneInfo("Europe/Oslo"))
                        date_str = local_dt.strftime("%d.%m.%Y")
                        time_str = local_dt.strftime("%H:%M")
                        time_display = f" kl. {time_str}"
                    else:
                        date_str = start.get("date", start)
                        time_display = ""
                elif isinstance(start, str) and "T" in start:
                    dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    from zoneinfo import ZoneInfo
                    local_dt = dt.astimezone(ZoneInfo("Europe/Oslo"))
                    date_str = local_dt.strftime("%d.%m.%Y")
                    time_str = local_dt.strftime("%H:%M")
                    time_display = f" kl. {time_str}"
                else:
                    # date-only format
                    date_str = start
                    time_display = ""
            except Exception as e:
                print(f"[CALENDAR] GCal parse error: {e}")
                date_str = start
                time_display = ""

            lines.append(f"📌 **{summary}** - {date_str}{time_display}")

            if location:
                lines.append(f"   📍 {location}")

            if link:
                lines.append(f"   🔗 {link}")

            lines.append("")

        return "\n".join(lines)

    def get_setup_instructions(self):
        """Get instructions for setting up Google Calendar integration"""
        return """🔧 **Google Calendar-oppsett**

For å koble boten til Google Calendar:

1. Gå til https://console.cloud.google.com/apis/credentials
2. Opprett et prosjekt (eller bruk et eksisterende)
3. Klikk "Enable APIs" og skru på: Google Calendar API
4. Gå til Credentials → Create Credentials → OAuth 2.0 Client ID
5. Application type: "Desktop app" → Create
6. Last ned JSON-filen og gi meg filbanen

Deretter kjører vi setup-scriptet for å autorisere.
"""


def parse_google_calendar_command(message_content):
    """
    Parse Google Calendar commands from message

    Commands:
    - "google calendar" or "gcal" - list upcoming events
    - "sync til google" - sync local events to Google Calendar

    Returns:
        Command dict or None
    """
    content = message_content.lower()

    # Check for Google Calendar commands
    if any(
        phrase in content for phrase in ["google calendar", "gcal", "google kalender"]
    ):
        if any(word in content for word in ["sync", "synk", "oppdater", "push"]):
            return {"action": "sync"}
        elif any(word in content for word in ["slett", "delete", "fjern"]):
            return {"action": "delete"}
        else:
            return {"action": "list"}

    return None


if __name__ == "__main__":
    # Test the manager
    print("=== Google Calendar Manager Test ===\n")

    manager = GoogleCalendarManager()

    if not manager.is_configured():
        print("Google Calendar er ikke konfigurert ennå.")
        print(manager.get_setup_instructions())
    else:
        print("✅ Google Calendar er konfigurert!")
        print("\nHenter kommende arrangementer...\n")

        events = manager.list_upcoming_events(days=30)
        if events:
            print(manager.format_event_list(events))
        else:
            print("Ingen arrangementer funnet eller feil oppstod.")
