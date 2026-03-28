#!/usr/bin/env python3
"""
Event Manager for Inebotten
Handles creating, storing, and retrieving events
Stores events in JSON file with optional Google Calendar sync
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path


class EventManager:
    """
    Manages events for Discord groups
    Stores events in a JSON file with seamless Google Calendar integration
    """
    
    def __init__(self, storage_path=None):
        if storage_path is None:
            storage_path = Path.home() / '.hermes' / 'discord' / 'events.json'
        
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.events = self._load_events()
        
        # Initialize Google Calendar integration (optional)
        self._init_gcal()
    
    def _init_gcal(self):
        """Initialize Google Calendar manager if available"""
        self.gcal = None
        self.gcal_enabled = False
        try:
            from cal_system.google_calendar_manager import GoogleCalendarManager
            self.gcal = GoogleCalendarManager()
            self.gcal_enabled = self.gcal.is_configured()
            if self.gcal_enabled:
                print("[EVENT] Google Calendar integration enabled")
        except Exception as e:
            print(f"[EVENT] Google Calendar not available: {e}")
    
    def _load_events(self):
        """Load events from storage file"""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save_events(self):
        """Save events to storage file"""
        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(self.events, f, ensure_ascii=False, indent=2)
    
    def create_event(self, guild_id, title, date_str, time_str=None, 
                     description=None, created_by=None, recurrence=None):
        """
        Create a new event
        
        Args:
            guild_id: Discord guild/server ID
            title: Event title
            date_str: Date in format DD.MM.YYYY or "today", "tomorrow", "Saturday"
            time_str: Optional time (e.g., "18:00")
            description: Optional description
            created_by: User who created the event
            recurrence: Optional recurrence rule ('weekly', 'biweekly', 'monthly', 'yearly')
        
        Returns:
            Event dict or None if error
        """
        try:
            # Parse date
            parsed_date = self._parse_date(date_str)
            if not parsed_date:
                return None
            
            # Create event ID
            event_id = f"{guild_id}_{int(datetime.now().timestamp())}"
            
            event = {
                'id': event_id,
                'guild_id': str(guild_id),
                'title': title,
                'date': parsed_date.strftime('%d.%m.%Y'),
                'time': time_str,
                'description': description,
                'created_by': created_by,
                'created_at': datetime.now().isoformat(),
                'attendees': [],
                'status': 'active',
                'recurrence': recurrence,  # Store recurrence rule
                'gcal_event_id': None,  # Will be populated if GCal sync succeeds
                'gcal_link': None
            }
            
            # Sync to Google Calendar if enabled
            if self.gcal_enabled:
                try:
                    gcal_result = self.gcal.sync_local_event(event)
                    if gcal_result:
                        event['gcal_event_id'] = gcal_result.get('id')
                        event['gcal_link'] = gcal_result.get('htmlLink')
                        print(f"[EVENT] Synced to Google Calendar: {gcal_result.get('htmlLink')}")
                except Exception as e:
                    print(f"[EVENT] Failed to sync to Google Calendar: {e}")
            
            # Store event locally
            if str(guild_id) not in self.events:
                self.events[str(guild_id)] = []
            
            self.events[str(guild_id)].append(event)
            self._save_events()
            
            return event
            
        except Exception as e:
            print(f"[EVENT] Error creating event: {e}")
            return None
    
    def _parse_date(self, date_str):
        """
        Parse various date formats
        Supports: DD.MM.YYYY, today, tomorrow, day names
        """
        date_str = date_str.lower().strip()
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Handle special words
        if date_str in ['today', 'i dag', 'idag']:
            return today
        
        if date_str in ['tomorrow', 'i morgen', 'imorgen']:
            return today + timedelta(days=1)
        
        # Handle day names
        days = {
            'monday': 0, 'mandag': 0,
            'tuesday': 1, 'tirsdag': 1,
            'wednesday': 2, 'onsdag': 2,
            'thursday': 3, 'torsdag': 3,
            'friday': 4, 'fredag': 4,
            'saturday': 5, 'lørdag': 5,
            'sunday': 6, 'søndag': 6
        }
        
        if date_str in days:
            target_day = days[date_str]
            days_ahead = target_day - today.weekday()
            if days_ahead <= 0:  # Target day already happened this week
                days_ahead += 7
            return today + timedelta(days=days_ahead)
        
        # Try parsing DD.MM.YYYY
        try:
            return datetime.strptime(date_str, '%d.%m.%Y')
        except:
            pass
        
        # Try parsing DD/MM/YYYY
        try:
            return datetime.strptime(date_str, '%d/%m/%Y')
        except:
            pass
        
        return None
    
    def get_upcoming_events(self, guild_id, days=30, include_gcal=True):
        """
        Get upcoming events for a guild
        
        Args:
            guild_id: Discord guild ID
            days: How many days ahead to look
            include_gcal: Whether to include Google Calendar events (if enabled)
        
        Returns:
            List of events
        """
        now = datetime.now()
        today = now.date()  # Just the date part
        cutoff = now + timedelta(days=days)
        upcoming = []
        gcal_event_ids = set()  # Track GCal events to avoid duplicates
        
        # Fetch from Google Calendar first (source of truth)
        if include_gcal and self.gcal_enabled:
            try:
                gcal_events = self.gcal.list_upcoming_events(days=days)
                if gcal_events:
                    for gcal_event in gcal_events:
                        gcal_id = gcal_event.get('id')
                        gcal_event_ids.add(gcal_id)
                        
                        # Convert GCal event to local format
                        event = self._convert_gcal_to_local(gcal_event)
                        if event:
                            upcoming.append(event)
            except Exception as e:
                print(f"[EVENT] Failed to fetch from Google Calendar: {e}")
        
        # Add local events that aren't already synced to GCal
        local_events = []
        if str(guild_id) in self.events:
            local_events = self.events[str(guild_id)]
        else:
            # Search all guilds for DMs/group chats
            for gid, events in self.events.items():
                local_events.extend(events)
        
        for event in local_events:
            try:
                # Skip if already synced to GCal (avoid duplicates)
                if event.get('gcal_event_id') and event['gcal_event_id'] in gcal_event_ids:
                    continue
                
                event_date = datetime.strptime(event['date'], '%d.%m.%Y').date()
                if today <= event_date <= cutoff.date() and event['status'] == 'active':
                    upcoming.append(event)
            except:
                continue
        
        # Sort by date
        upcoming.sort(key=lambda x: datetime.strptime(x['date'], '%d.%m.%Y').date())
        return upcoming
    
    def _convert_gcal_to_local(self, gcal_event):
        """Convert a Google Calendar event to local event format"""
        try:
            # Ensure gcal_event is a dict
            if not isinstance(gcal_event, dict):
                print(f"[EVENT] Invalid GCal event type: {type(gcal_event)}")
                return None
                
            summary = gcal_event.get('summary', '(ingen tittel)')
            start = gcal_event.get('start')
            
            if not start:
                print(f"[EVENT] GCal event has no start: {gcal_event.get('id')}")
                return None
            
            from zoneinfo import ZoneInfo
            
            # The Google Calendar API returns start as either:
            # - A string (ISO 8601 datetime): "2026-03-25T18:00:00+01:00"
            # - A dict with 'date' or 'dateTime' key
            
            if isinstance(start, str):
                # ISO 8601 datetime string
                start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                start_local = start_dt.astimezone(ZoneInfo('Europe/Oslo'))
                date_str = start_local.strftime('%d.%m.%Y')
                time_str = start_local.strftime('%H:%M')
            elif isinstance(start, dict):
                # Dict format
                if 'dateTime' in start:
                    # Has time
                    start_dt = datetime.fromisoformat(start['dateTime'].replace('Z', '+00:00'))
                    start_local = start_dt.astimezone(ZoneInfo('Europe/Oslo'))
                    date_str = start_local.strftime('%d.%m.%Y')
                    time_str = start_local.strftime('%H:%M')
                else:
                    # Date only
                    date_str = start.get('date', '')
                    if not date_str:
                        print(f"[EVENT] GCal event has no date: {gcal_event.get('id')}")
                        return None
                    
                    # Convert from YYYY-MM-DD to DD.MM.YYYY
                    parts = date_str.split('-')
                    if len(parts) == 3:
                        date_str = f"{parts[2]}.{parts[1]}.{parts[0]}"
                    time_str = None
            else:
                print(f"[EVENT] Unknown start type: {type(start)}")
                return None
            
            return {
                'id': f"gcal_{gcal_event.get('id', '')}",
                'title': summary,
                'date': date_str,
                'time': time_str,
                'description': gcal_event.get('description', ''),
                'location': gcal_event.get('location', ''),
                'gcal_event_id': gcal_event.get('id'),
                'gcal_link': gcal_event.get('htmlLink', ''),
                'status': 'active',
                'is_gcal_event': True  # Flag to identify GCal events
            }
        except Exception as e:
            print(f"[EVENT] Error converting GCal event: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def get_todays_events(self, guild_id):
        """Get events for today"""
        today = datetime.now().strftime('%d.%m.%Y')
        todays = []
        
        # Try specific guild first
        if str(guild_id) in self.events:
            todays = [e for e in self.events[str(guild_id)] 
                    if e['date'] == today and e['status'] == 'active']
        
        # If no events, search all guilds
        if not todays:
            for gid, events in self.events.items():
                for e in events:
                    if e['date'] == today and e['status'] == 'active':
                        todays.append(e)
        
        return todays
    
    def delete_event(self, guild_id, event_id):
        """Delete an event by ID (searches all guilds if not found in specified)"""
        deleted_event = None
        gcal_event_id = None
        
        # Check if this is a Google Calendar event (ID starts with 'gcal_')
        if event_id.startswith('gcal_'):
            # Extract the actual GCal event ID
            gcal_event_id = event_id[5:]  # Remove 'gcal_' prefix
            print(f"[EVENT] Deleting Google Calendar event: {gcal_event_id}")
        else:
            # Try to find in local storage
            # Try specific guild first
            if str(guild_id) in self.events:
                for i, event in enumerate(self.events[str(guild_id)]):
                    if event['id'] == event_id:
                        deleted_event = self.events[str(guild_id)].pop(i)
                        gcal_event_id = deleted_event.get('gcal_event_id')
                        self._save_events()
                        break
            
            # Search all guilds if not found
            if not deleted_event:
                for gid, events in self.events.items():
                    for i, event in enumerate(events):
                        if event['id'] == event_id:
                            deleted_event = events.pop(i)
                            gcal_event_id = deleted_event.get('gcal_event_id')
                            self._save_events()
                            break
                    if deleted_event:
                        break
        
        # Also delete from Google Calendar if applicable
        if self.gcal_enabled and gcal_event_id:
            try:
                self.gcal.delete_event(gcal_event_id)
                print(f"[EVENT] Deleted from Google Calendar: {gcal_event_id}")
            except Exception as e:
                print(f"[EVENT] Failed to delete from Google Calendar: {e}")
        
        return deleted_event is not None or gcal_event_id is not None
    
    def format_event_list(self, events, title="Kommende arrangementer"):
        """
        Format a list of events for display
        """
        if not events:
            return f"🗓️ **{title}**\nIngen arrangementer planlagt."
        
        lines = [f"🗓️ **{title}**", ""]
        
        for i, event in enumerate(events[:10], 1):  # Show max 10, numbered
            time_str = f" kl. {event['time']}" if event['time'] else ""
            
            # Show Google Calendar indicator for synced events
            gcal_indicator = "📅" if event.get('gcal_event_id') or event.get('is_gcal_event') else "📌"
            
            # Add recurrence indicator
            recurrence_str = ""
            if event.get('recurrence'):
                recurrence_labels = {
                    'weekly': 'uke',
                    'biweekly': '2uker',
                    'monthly': 'mnd',
                    'yearly': 'år'
                }
                # Show day name if specified
                if event.get('recurrence_day'):
                    day_abbr = event['recurrence_day'][:3].lower()
                    recurrence_str = f" 🔄 {day_abbr} {recurrence_labels.get(event['recurrence'], '')}"
                else:
                    recurrence_str = f" 🔄 {recurrence_labels.get(event['recurrence'], '')}"
            
            lines.append(f"{gcal_indicator} **{event['title']}** - {event['date']}{time_str}{recurrence_str}")
            
            if event.get('description'):
                lines.append(f"   📝 {event['description']}")
            
            if event.get('location'):
                lines.append(f"   📍 {event['location']}")
            
            attendees = len(event.get('attendees', []))
            if attendees > 0:
                lines.append(f"   👥 {attendees} deltakere")
            
            # Add Google Calendar link if available
            if event.get('gcal_link'):
                lines.append(f"   🔗 [Åpne i Google Calendar]({event['gcal_link']})")
            
            lines.append("")
        
        return "\n".join(lines)
    
    def format_single_event(self, event):
        """Format a single event for display"""
        time_str = f" kl. {event['time']}" if event['time'] else ""
        
        lines = [
            f"✅ **Arrangement opprettet!**",
            "",
            f"📌 **{event['title']}**",
            f"📅 {event['date']}{time_str}",
        ]
        
        if event.get('description'):
            lines.append(f"📝 {event['description']}")
        
        # Show recurrence info
        if event.get('recurrence'):
            recurrence_labels = {
                'weekly': 'hver uke',
                'biweekly': 'annenhver uke',
                'monthly': 'hver måned',
                'yearly': 'hvert år'
            }
            if event.get('recurrence_day'):
                lines.append(f"🔄 Gjentas hver {event['recurrence_day']} ({recurrence_labels.get(event['recurrence'], event['recurrence'])})")
            else:
                lines.append(f"🔄 Gjentas {recurrence_labels.get(event['recurrence'], event['recurrence'])}")
        
        # Show Google Calendar sync status
        if event.get('gcal_link'):
            lines.append("")
            lines.append(f"📅 **Synkronisert med Google Calendar**")
            lines.append(f"🔗 {event['gcal_link']}")
        
        lines.append("")
        lines.append("— *Bruk @inebotten arrangementer for å se alle arrangementer*")
        
        return "\n".join(lines)


# Parse natural language event commands
def parse_event_command(message_content):
    """
    Parse event creation command from message
    
    Expected formats:
    - "@inebotten arrangement lørdag Grillfest"
    - "@inebotten arrangement 20.03.2025 Julebord kl 18:00"
    - "@inebotten arrangement i morgen Lunsj"
    - "@inebotten arrangement hver uke Møte"
    
    Returns:
        dict with title, date, time, recurrence or None
    """
    import re
    content = message_content.lower()
    
    # Remove Discord mentions and @inebotten
    content = re.sub(r'<@!?\d+>', '', content)  # Remove Discord mentions
    content = content.replace('@inebotten', '').strip()
    
    # Check if it's an event command
    if not content.startswith('arrangement'):
        return None
    
    # Remove command word
    content = content.replace('arrangement', '', 1).strip()
    
    # Common Norwegian date words
    date_indicators = [
        'i dag', 'idag', 'today',
        'i morgen', 'imorgen', 'tomorrow',
        'mandag', 'tirsdag', 'onsdag', 'torsdag', 'fredag', 'lørdag', 'søndag',
        'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'
    ]
    
    # Recurrence patterns
    recurrence_patterns = {
        'hver uke': 'weekly',
        'ukentlig': 'weekly',
        'weekly': 'weekly',
        'hver andre uke': 'biweekly',
        'annenhver uke': 'biweekly',
        'biweekly': 'biweekly',
        'hver måned': 'monthly',
        'månedlig': 'monthly',
        'monthly': 'monthly',
        'hvert år': 'yearly',
        'årlig': 'yearly',
        'yearly': 'yearly',
    }
    
    # Day-specific recurrence patterns
    day_recurrence_patterns = {
        'hver': 'weekly',
        'annenhver': 'biweekly',
        'hver andre': 'biweekly',
    }
    
    day_names = ['mandag', 'tirsdag', 'onsdag', 'torsdag', 'fredag', 'lørdag', 'søndag',
                 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    
    # Try to find day-specific recurrence first (e.g., "hver mandag", "annenhver tirsdag")
    recurrence = None
    recurrence_day = None
    rrule_day = None
    
    for prefix in sorted(day_recurrence_patterns.keys(), key=len, reverse=True):
        if prefix in content:
            for day in day_names:
                pattern = f"{prefix} {day}"
                if pattern in content:
                    recurrence = day_recurrence_patterns[prefix]
                    recurrence_day = day
                    # Map to RRULE day
                    day_map = {
                        'mandag': 'MO', 'monday': 'MO',
                        'tirsdag': 'TU', 'tuesday': 'TU',
                        'onsdag': 'WE', 'wednesday': 'WE',
                        'torsdag': 'TH', 'thursday': 'TH',
                        'fredag': 'FR', 'friday': 'FR',
                        'lørdag': 'SA', 'saturday': 'SA',
                        'søndag': 'SU', 'sunday': 'SU',
                    }
                    rrule_day = day_map.get(day)
                    content = content.replace(pattern, '').strip()
                    break
            if recurrence:
                break
    
    # If no day-specific recurrence, try general patterns
    if not recurrence:
        for pattern in sorted(recurrence_patterns.keys(), key=len, reverse=True):
            if pattern in content:
                recurrence = recurrence_patterns[pattern]
                content = content.replace(pattern, '').strip()
                break
    
    # Try to find date
    date_str = None
    remaining = content
    
    # Check for DD.MM.YYYY format
    import re
    date_match = re.search(r'(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?', content)
    if date_match:
        day, month, year = date_match.groups()
        if year:
            if len(year) == 2:
                year = '20' + year
            date_str = f"{day}.{month}.{year}"
        else:
            date_str = f"{day}.{month}.{datetime.now().year}"
        remaining = content[date_match.end():].strip()
    else:
        # Check for day names or special words
        for indicator in date_indicators:
            if content.startswith(indicator):
                date_str = indicator.replace(' ', '')
                remaining = content[len(indicator):].strip()
                break
    
    # If no date found but we have recurrence, default to today
    if not date_str and recurrence:
        from datetime import datetime
        date_str = datetime.now().strftime('%d.%m.%Y')
        remaining = content
    
    if not date_str:
        return None
    
    # Try to find time (HH:MM)
    time_str = None
    time_match = re.search(r'kl\.?\s*(\d{1,2}):(\d{2})', remaining)
    if time_match:
        time_str = f"{time_match.group(1)}:{time_match.group(2)}"
        remaining = remaining[:time_match.start()] + remaining[time_match.end():]
        remaining = remaining.strip()
    
    # Everything else is the title
    title = remaining.strip()
    if not title:
        return None
    
    # Capitalize first letter of title
    title = title[0].upper() + title[1:] if title else title
    
    result = {
        'title': title,
        'date': date_str,
        'time': time_str
    }
    
    if recurrence:
        result['recurrence'] = recurrence
    if recurrence_day:
        result['recurrence_day'] = recurrence_day
    if rrule_day:
        result['rrule_day'] = rrule_day
    
    return result


if __name__ == "__main__":
    # Test the event manager
    print("=== Event Manager Test ===\n")
    
    manager = EventManager(storage_path='/tmp/test_events.json')
    
    # Test creating events
    test_guild = "123456789"
    
    event1 = manager.create_event(
        test_guild,
        "Grillfest",
        "lørdag",
        "18:00",
        "Sommerens første grillfest!",
        "TestUser"
    )
    
    if event1:
        print("Created event:")
        print(manager.format_single_event(event1))
        print()
    
    # Test listing events
    upcoming = manager.get_upcoming_events(test_guild)
    print(manager.format_event_list(upcoming))
    
    # Cleanup
    if manager.storage_path.exists():
        manager.storage_path.unlink()
