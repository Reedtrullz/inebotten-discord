#!/usr/bin/env python3
"""
Simple Calendar Manager for Inebotten
Everything is just a calendar item with a date
"""

import json
from datetime import datetime, timedelta
from pathlib import Path


class CalendarManager:
    """
    Manages calendar items - everything is just something happening on a date
    """
    
    def __init__(self, storage_path=None):
        if storage_path is None:
            storage_path = Path.home() / '.hermes' / 'discord' / 'data' / 'calendar.json'
        
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.items = self._load_items()
        
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
                print("[CALENDAR] Google Calendar integration enabled")
        except Exception as e:
            print(f"[CALENDAR] Google Calendar not available: {e}")
    
    def _load_items(self):
        """Load calendar items from storage"""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save_items(self):
        """Save calendar items to storage"""
        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(self.items, f, ensure_ascii=False, indent=2)
    
    def add_item(self, guild_id, user_id, username, title,
                 date_str=None, time_str=None, description=None,
                 recurrence=None, recurrence_day=None, rrule_day=None,
                 gcal_event_id=None, gcal_link=None):
        """
        Add a new calendar item
        
        Args:
            guild_id: Discord guild ID
            user_id: User who created it
            username: Display name
            title: Item title
            date_str: Date in DD.MM.YYYY format
            time_str: Time in HH:MM format (optional)
            description: Optional description
            recurrence: Optional recurrence type ('weekly', 'biweekly', etc.)
            recurrence_day: Optional day name (e.g., 'lørdag')
            rrule_day: Optional RRULE day code (e.g., 'SA')
            gcal_event_id: Optional GCal event ID
            gcal_link: Optional GCal link
        
        Returns:
            item dict
        """
        guild_key = str(guild_id)
        item_id = f"cal_{guild_id}_{int(datetime.now().timestamp())}"
        
        if guild_key not in self.items:
            self.items[guild_key] = []
        
        item = {
            'id': item_id,
            'user_id': str(user_id),
            'username': username,
            'title': title,
            'date': date_str,
            'time': time_str,
            'description': description,
            'recurrence': recurrence,
            'recurrence_day': recurrence_day,
            'rrule_day': rrule_day,
            'gcal_event_id': gcal_event_id,
            'gcal_link': gcal_link,
            'created_at': datetime.now().isoformat(),
            'completed': False,
            'completed_at': None,
            'completed_count': 0,
        }
        
        self.items[guild_key].append(item)
        self._save_items()
        
        return item
    
    def complete_item(self, guild_id, item_num=None, item_id=None):
        """
        Mark a calendar item as completed
        For recurring items, advances the date instead
        
        Returns:
            (success, item_title, next_date)
        """
        guild_key = str(guild_id)
        
        if guild_key not in self.items:
            return False, None, None
        
        # Get incomplete items
        incomplete = [i for i in self.items[guild_key] if not i.get('completed')]
        incomplete.sort(key=lambda x: datetime.strptime(x['date'], '%d.%m.%Y') if x.get('date') else datetime.max)
        
        target_item = None
        
        if item_num is not None:
            idx = item_num - 1
            if 0 <= idx < len(incomplete):
                target_item = incomplete[idx]
        elif item_id:
            for item in self.items[guild_key]:
                if item['id'] == item_id and not item['completed']:
                    target_item = item
                    break
        
        if not target_item:
            return False, None, None
        
        # Check if recurring
        if target_item.get('recurrence') and target_item.get('date'):
            next_date = self._calculate_next_date(
                target_item['date'],
                target_item['recurrence']
            )
            if next_date:
                target_item['date'] = next_date
                target_item['completed_count'] = target_item.get('completed_count', 0) + 1
                self._save_items()
                return True, target_item['title'], next_date
        
        # Non-recurring - mark complete
        target_item['completed'] = True
        target_item['completed_at'] = datetime.now().isoformat()
        self._save_items()
        return True, target_item['title'], None
    
    def _calculate_next_date(self, current_date_str, recurrence):
        """Calculate next occurrence date"""
        try:
            current = datetime.strptime(current_date_str, '%d.%m.%Y')
            
            if recurrence == 'weekly':
                next_date = current + timedelta(weeks=1)
            elif recurrence == 'biweekly':
                next_date = current + timedelta(weeks=2)
            elif recurrence == 'monthly':
                if current.month == 12:
                    next_date = current.replace(year=current.year + 1, month=1)
                else:
                    next_date = current.replace(month=current.month + 1)
            elif recurrence == 'yearly':
                next_date = current.replace(year=current.year + 1)
            else:
                return None
            
            return next_date.strftime('%d.%m.%Y')
        except:
            return None
    
    def delete_item(self, guild_id, item_num):
        """
        Delete a calendar item by its number in the list
        
        Returns:
            (success, item_title)
        """
        guild_key = str(guild_id)
        
        if guild_key not in self.items:
            return False, None
        
        # Get items to display (same order as format_calendar)
        items = self.get_upcoming(guild_id, days=365, include_completed=False)
        
        idx = item_num - 1
        if 0 <= idx < len(items):
            item = items[idx]
            item_id = item['id']
            
            # Find and remove from storage
            for i, stored_item in enumerate(self.items[guild_key]):
                if stored_item['id'] == item_id:
                    title = stored_item['title']
                    self.items[guild_key].pop(i)
                    self._save_items()
                    return True, title
        
        return False, None
    
    def get_upcoming(self, guild_id, days=30, include_completed=False):
        """
        Get upcoming calendar items
        
        Args:
            guild_id: Discord guild ID
            days: Number of days to look ahead
            include_completed: Whether to include completed items
        
        Returns:
            List of item dicts sorted by date
        """
        guild_key = str(guild_id)
        
        if guild_key not in self.items:
            return []
        
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = today + timedelta(days=days)
        
        upcoming = []
        for item in self.items[guild_key]:
            if not include_completed and item.get('completed'):
                continue
            
            if item.get('date'):
                try:
                    item_date = datetime.strptime(item['date'], '%d.%m.%Y')
                    if include_completed or (today <= item_date <= cutoff):
                        upcoming.append(item)
                except:
                    continue
        
        # Sort by date
        upcoming.sort(key=lambda x: datetime.strptime(x['date'], '%d.%m.%Y'))
        return upcoming
    
    def format_list(self, guild_id, days=90, show_completed=False):
        """
        Format calendar items for display
        Shows next 3 months by default to capture future events
        """
        items = self.get_upcoming(guild_id, days=days, include_completed=False)
        
        if not items:
            return None
        
        lines = ["📅 **Kalender:**"]
        
        for i, item in enumerate(items[:10], 1):
            time_str = f" kl. {item['time']}" if item.get('time') else ""
            
            # Status indicator: 📅 = GCal synced, 📌 = local only, ✓ = completed
            if item.get('completed'):
                status_indicator = "✓"
            elif item.get('gcal_event_id') or item.get('gcal_link'):
                status_indicator = "📅"
            else:
                status_indicator = "📌"
            
            # Recurrence indicator
            recurrence_str = ""
            if item.get('recurrence'):
                labels = {'weekly': 'uke', 'biweekly': '2uker', 'monthly': 'mnd', 'yearly': 'år'}
                if item.get('recurrence_day'):
                    recurrence_str = f" 🔄 {item['recurrence_day'][:3].lower()} {labels.get(item['recurrence'], '')}"
                else:
                    recurrence_str = f" 🔄 {labels.get(item['recurrence'], '')}"
            
            # Strike through completed items
            title_display = f"~~{item['title']}~~" if item.get('completed') else item['title']
            
            lines.append(f"{status_indicator} **{i}.** {title_display} - {item['date']}{time_str}{recurrence_str}")
        
        # Show recently completed if requested
        if show_completed:
            all_items = self.items.get(str(guild_id), [])
            completed = [i for i in all_items if i.get('completed')][:3]
            if completed:
                lines.append("\n✅ **Nylig fullført:**")
                for item in completed:
                    lines.append(f"  ✓ ~~{item['title']}~~")
        
        lines.append("\n— *`@inebotten ferdig [nummer]` for å fullføre*")
        return "\n".join(lines)
    
    def format_single_item(self, item):
        """Format a single item for display"""
        time_str = f" kl. {item['time']}" if item.get('time') else ""
        
        lines = [
            f"✅ **Lagt til i kalenderen!**",
            "",
            f"📌 **{item['title']}**",
            f"📅 {item['date']}{time_str}",
        ]
        
        if item.get('recurrence'):
            labels = {'weekly': 'hver uke', 'biweekly': 'annenhver uke', 'monthly': 'hver måned', 'yearly': 'hvert år'}
            if item.get('recurrence_day'):
                lines.append(f"🔄 Gjentas hver {item['recurrence_day']} ({labels.get(item['recurrence'], item['recurrence'])})")
            else:
                lines.append(f"🔄 Gjentas {labels.get(item['recurrence'], item['recurrence'])}")
        
        if item.get('gcal_link'):
            lines.append("")
            lines.append(f"📅 Synkronisert med Google Calendar")
            lines.append(f"🔗 {item['gcal_link']}")
        
        lines.append("")
        lines.append("— *Bruk `@inebotten kalender` for å se alt*")
        
        return "\n".join(lines)


if __name__ == "__main__":
    # Test
    print("=== Calendar Manager Test ===\n")
    
    manager = CalendarManager(storage_path='/tmp/test_calendar_simple.json')
    
    # Add various items
    manager.add_item(
        guild_id='test',
        user_id='user1',
        username='Ola',
        title='Grillfest',
        date_str='28.03.2026',
        time_str='18:00'
    )
    print("Added: Grillfest")
    
    manager.add_item(
        guild_id='test',
        user_id='user1',
        username='Ola',
        title='Sende meldekort',
        date_str='04.04.2026',
        time_str='10:00',
        recurrence='biweekly',
        recurrence_day='lørdag'
    )
    print("Added: Sende meldekort (recurring)")
    
    manager.add_item(
        guild_id='test',
        user_id='user1',
        username='Ola',
        title='Kjøpe melk',
        date_str='29.03.2026'
    )
    print("Added: Kjøpe melk")
    
    print("\n--- Calendar ---")
    print(manager.format_list('test'))
    
    print("\n--- Complete item #2 ---")
    success, title, next_date = manager.complete_item('test', item_num=2)
    print(f"Completed: {title}, next: {next_date}")
    
    print("\n--- Calendar after ---")
    print(manager.format_list('test'))
    
    # Cleanup
    import os
    os.remove('/tmp/test_calendar_simple.json')
