#!/usr/bin/env python3
"""
Birthday Manager for Inebotten
Tracks birthdays for Discord group members with Google Calendar sync
"""

import json
import warnings
from datetime import datetime, timedelta
from pathlib import Path

# Suppress requests/urllib3 version warnings
warnings.filterwarnings('ignore', category=UserWarning, module='requests')


class BirthdayManager:
    """
    Manages birthdays for Discord group members with Google Calendar sync
    """
    
    def __init__(self, storage_path=None):
        if storage_path is None:
            storage_path = Path.home() / '.hermes' / 'discord' / 'birthdays.json'
        
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.birthdays = self._load_birthdays()
        
        # Initialize Google Calendar integration
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
                print("[BIRTHDAY] Google Calendar integration enabled")
        except Exception as e:
            print(f"[BIRTHDAY] Google Calendar not available: {e}")
    
    def _load_birthdays(self):
        """Load birthdays from storage"""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save_birthdays(self):
        """Save birthdays to storage"""
        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(self.birthdays, f, ensure_ascii=False, indent=2)
    
    def add_birthday(self, guild_id, user_id, username, day, month, year=None):
        """
        Add a birthday for a user
        
        Args:
            guild_id: Discord guild ID
            user_id: Discord user ID
            username: Display name
            day: Day of month (1-31)
            month: Month (1-12)
            year: Optional birth year
        
        Returns:
            True if successful
        """
        try:
            guild_key = str(guild_id)
            user_key = str(user_id)
            
            if guild_key not in self.birthdays:
                self.birthdays[guild_key] = {}
            
            birthday_data = {
                'username': username,
                'day': day,
                'month': month,
                'year': year,
                'added_at': datetime.now().isoformat(),
                'gcal_event_id': None
            }
            
            # Sync to Google Calendar if enabled
            if self.gcal_enabled:
                try:
                    gcal_result = self._sync_birthday_to_gcal(username, day, month, year)
                    if gcal_result:
                        birthday_data['gcal_event_id'] = gcal_result.get('id')
                        print(f"[BIRTHDAY] Synced to Google Calendar: {gcal_result.get('htmlLink', '')}")
                except Exception as e:
                    print(f"[BIRTHDAY] Failed to sync to Google Calendar: {e}")
            
            self.birthdays[guild_key][user_key] = birthday_data
            self._save_birthdays()
            return True
            
        except Exception as e:
            print(f"[BIRTHDAY] Error adding birthday: {e}")
            return False
    
    def _sync_birthday_to_gcal(self, username, day, month, year=None):
        """
        Create a recurring yearly birthday event in Google Calendar
        
        Args:
            username: Name of the person
            day: Day of month
            month: Month (1-12)
            year: Optional birth year
            
        Returns:
            Google Calendar event dict or None
        """
        if not self.gcal or not self.gcal_enabled:
            return None
        
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        
        current_year = datetime.now().year
        
        # Create the birthday event for this year (or next if passed)
        try:
            birthday_this_year = datetime(current_year, month, day, 9, 0, 0, tzinfo=ZoneInfo('Europe/Oslo'))
            if birthday_this_year < datetime.now(ZoneInfo('Europe/Oslo')):
                # Birthday already passed this year, start from next year
                birthday_this_year = datetime(current_year + 1, month, day, 9, 0, 0, tzinfo=ZoneInfo('Europe/Oslo'))
        except:
            return None
        
        # End time (all-day event or specific time)
        end_time = birthday_this_year.replace(hour=23, minute=59)
        
        # Build description
        description = f"🎂 Bursdag for {username}"
        if year:
            age = current_year - year
            if (datetime.now().month, datetime.now().day) < (month, day):
                age -= 1
            description += f"\nBlir {age + 1} år gammel!"
        
        # Create the event using the calendar API directly for recurring events
        import subprocess
        import json
        import sys
        from pathlib import Path
        
        SKILL_PATH = Path.home() / '.hermes' / 'skills' / 'productivity' / 'google-workspace' / 'scripts'
        script_path = SKILL_PATH / "google_api.py"
        
        # Build event with recurrence (yearly)
        # RRULE:FREQ=YEARLY means repeat every year
        event_data = {
            "summary": f"🎂 {username}",
            "description": description,
            "start": {
                "dateTime": birthday_this_year.isoformat(),
                "timeZone": "Europe/Oslo"
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": "Europe/Oslo"
            },
            "recurrence": ["RRULE:FREQ=YEARLY"],
            "transparency": "transparent",  # Show as free/busy
            "visibility": "default"
        }
        
        # For now, use the basic create method (recurrence needs direct API call)
        # We'll create a simple event for this year
        result = self.gcal.create_event(
            title=f"🎂 {username}",
            start_time=birthday_this_year.isoformat(),
            end_time=end_time.isoformat(),
            description=description
        )
        
        return result
    
    def remove_birthday(self, guild_id, user_id):
        """Remove a user's birthday"""
        try:
            guild_key = str(guild_id)
            user_key = str(user_id)
            
            if guild_key in self.birthdays and user_key in self.birthdays[guild_key]:
                birthday_data = self.birthdays[guild_key][user_key]
                
                # Also remove from Google Calendar if synced
                if self.gcal_enabled and birthday_data.get('gcal_event_id'):
                    try:
                        self.gcal.delete_event(birthday_data['gcal_event_id'])
                        print(f"[BIRTHDAY] Deleted from Google Calendar: {birthday_data['gcal_event_id']}")
                    except Exception as e:
                        print(f"[BIRTHDAY] Failed to delete from Google Calendar: {e}")
                
                del self.birthdays[guild_key][user_key]
                self._save_birthdays()
                return True
            
            return False
            
        except Exception as e:
            print(f"[BIRTHDAY] Error removing birthday: {e}")
            return False
    
    def get_todays_birthdays(self, guild_id):
        """
        Get birthdays for today
        
        Returns:
            List of (username, age) tuples
        """
        today = datetime.now()
        return self._get_birthdays_for_date(guild_id, today.month, today.day)
    
    def get_upcoming_birthdays(self, guild_id, days=30):
        """
        Get upcoming birthdays within N days
        
        Returns:
            List of dicts with birthday info
        """
        today = datetime.now()
        upcoming = []
        
        guild_key = str(guild_id)
        if guild_key not in self.birthdays:
            return upcoming
        
        for user_id, data in self.birthdays[guild_key].items():
            birthday_date = datetime(today.year, data['month'], data['day'])
            
            # If birthday passed this year, check next year
            if birthday_date < today:
                birthday_date = datetime(today.year + 1, data['month'], data['day'])
            
            days_until = (birthday_date - today).days
            
            if 0 <= days_until <= days:
                age = None
                if data.get('year'):
                    age = today.year - data['year']
                    if (today.month, today.day) < (data['month'], data['day']):
                        age -= 1
                
                upcoming.append({
                    'username': data['username'],
                    'day': data['day'],
                    'month': data['month'],
                    'days_until': days_until,
                    'age': age,
                    'turning': age + 1 if age else None
                })
        
        # Sort by days until
        upcoming.sort(key=lambda x: x['days_until'])
        return upcoming
    
    def _get_birthdays_for_date(self, guild_id, month, day):
        """Get birthdays for a specific date"""
        guild_key = str(guild_id)
        
        if guild_key not in self.birthdays:
            return []
        
        matches = []
        today = datetime.now()
        
        for user_id, data in self.birthdays[guild_key].items():
            if data['month'] == month and data['day'] == day:
                age = None
                if data.get('year'):
                    age = today.year - data['year']
                    if (today.month, today.day) < (data['month'], data['day']):
                        age -= 1
                
                matches.append((data['username'], age))
        
        return matches
    
    def format_birthday_greeting(self, username, age=None):
        """Format a birthday greeting"""
        import random
        
        greetings = [
            "Gratulerer med dagen! 🎉",
            "Hurra for deg! 🎂",
            "God bursdag! 🎈",
            "Tillykke med fødselsdagen! 🎁",
            "Ha en fin bursdag! 🎊"
        ]
        
        greeting = random.choice(greetings)
        
        lines = [
            f"🎂 **Bursdag i dag!**",
            "",
            f"{greeting}",
            f"**{username}** feirer bursdag i dag!"
        ]
        
        if age:
            lines.append(f"🎉 {age} år! 🎉")
        
        lines.append("")
        lines.append("— *🎈🎁🎂*")
        
        return "\n".join(lines)
    
    def format_upcoming_birthdays(self, guild_id, days=30):
        """Format upcoming birthdays list"""
        upcoming = self.get_upcoming_birthdays(guild_id, days)
        
        if not upcoming:
            return "🎂 **Kommende bursdager**\n\nIngen bursdager de neste 30 dagene."
        
        lines = ["🎂 **Kommende bursdager**", ""]
        
        months = ['', 'januar', 'februar', 'mars', 'april', 'mai', 'juni',
                  'juli', 'august', 'september', 'oktober', 'november', 'desember']
        
        for b in upcoming[:10]:
            date_str = f"{b['day']}. {months[b['month']]}"
            
            if b['days_until'] == 0:
                when = "I dag! 🎉"
            elif b['days_until'] == 1:
                when = "I morgen"
            else:
                when = f"Om {b['days_until']} dager"
            
            age_str = f" (blir {b['turning']})" if b['turning'] else ""
            
            lines.append(f"• **{b['username']}**{age_str} - {date_str} ({when})")
        
        return "\n".join(lines)
    
    def format_birthday_list(self, guild_id):
        """Format all registered birthdays"""
        guild_key = str(guild_id)
        
        if guild_key not in self.birthdays or not self.birthdays[guild_key]:
            return "🎂 **Bursdager**\n\nIngen bursdager registrert.\n\nBruk: `@inebotten bursdag DD.MM [år]`"
        
        months = ['', 'januar', 'februar', 'mars', 'april', 'mai', 'juni',
                  'juli', 'august', 'september', 'oktober', 'november', 'desember']
        
        lines = ["🎂 **Registrerte bursdager**", ""]
        
        # Sort by month/day
        sorted_birthdays = sorted(
            self.birthdays[guild_key].items(),
            key=lambda x: (x[1]['month'], x[1]['day'])
        )
        
        for user_id, data in sorted_birthdays:
            date_str = f"{data['day']}. {months[data['month']]}"
            year_str = f" ({data['year']})" if data.get('year') else ""
            lines.append(f"• **{data['username']}**{year_str} - {date_str}")
        
        return "\n".join(lines)


def parse_birthday_command(message_content):
    """
    Parse birthday command
    
    Formats:
    - "@inebotten bursdag 15.05 1990" - set own birthday
    - "@inebotten bursdag @user 15.05" - set someone's birthday
    - "@inebotten bursdager" - list birthdays
    
    Returns:
        dict or None
    """
    import re
    
    content = message_content.lower()
    
    # Remove Discord mention formats and @inebotten text
    content = re.sub(r'<@!?\d+>', '', content)  # Remove Discord mentions like <@123> or <@!123>
    content = content.replace('@inebotten', '').strip()
    
    # Check if it's a birthday command
    if not (content.startswith('bursdag') or content.startswith('bursdager') or content.startswith('birthday')):
        return None
    
    # List command
    if content.startswith('bursdager') or content.startswith('birthdays'):
        return {'action': 'list'}
    
    # Remove command word
    content = content.replace('bursdag', '').replace('birthday', '').strip()
    
    # Try to parse DD.MM or DD.MM.YYYY or DD.MM.YY
    date_match = re.search(r'(\d{1,2})[.](\d{1,2})(?:[.](\d{2,4}))?', content)
    
    if not date_match:
        return None
    
    day = int(date_match.group(1))
    month = int(date_match.group(2))
    year_str = date_match.group(3)
    year = None
    
    if year_str:
        year = int(year_str)
        # Handle 2-digit years
        if year < 100:
            if year >= 50:
                year = 1900 + year  # 95 -> 1995
            else:
                year = 2000 + year  # 15 -> 2015
    
    return {
        'action': 'add',
        'day': day,
        'month': month,
        'year': year
    }


if __name__ == "__main__":
    # Test
    print("=== Birthday Manager Test ===\n")
    
    manager = BirthdayManager(storage_path='/tmp/test_birthdays.json')
    
    # Add test birthdays
    manager.add_birthday("guild1", "user1", "Ola Nordmann", 17, 3, 1990)
    manager.add_birthday("guild1", "user2", "Kari Nordmann", 20, 3)
    
    # Test today's birthdays
    print("Today's birthdays:")
    today_bdays = manager.get_todays_birthdays("guild1")
    for username, age in today_bdays:
        print(manager.format_birthday_greeting(username, age))
    
    print("\nUpcoming birthdays:")
    print(manager.format_upcoming_birthdays("guild1"))
    
    print("\nAll birthdays:")
    print(manager.format_birthday_list("guild1"))
    
    # Cleanup
    if manager.storage_path.exists():
        manager.storage_path.unlink()
