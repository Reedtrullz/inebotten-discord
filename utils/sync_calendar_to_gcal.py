#!/usr/bin/env python3
"""
One-time script to sync existing calendar items to Google Calendar
"""

import json
from pathlib import Path
from datetime import datetime

# Load existing calendar data
calendar_path = Path.home() / '.hermes' / 'discord' / 'data' / 'calendar.json'

if not calendar_path.exists():
    print("No calendar data found!")
    exit(1)

with open(calendar_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

# Initialize Google Calendar
from cal_system.google_calendar_manager import GoogleCalendarManager
gcal = GoogleCalendarManager()

if not gcal.enabled:
    print("Google Calendar not configured!")
    exit(1)

print(f"Found {sum(len(items) for items in data.values())} total items")
print("Syncing to Google Calendar...\n")

synced_count = 0
failed_count = 0

for guild_id, items in data.items():
    for item in items:
        # Skip if already synced
        if item.get('gcal_event_id'):
            print(f"⏭️  Already synced: {item['title']}")
            continue
        
        # Skip completed items
        if item.get('completed'):
            print(f"⏭️  Skipping completed: {item['title']}")
            continue
        
        try:
            event_data = {
                'title': item['title'],
                'start_date': item['date'],
                'start_time': item.get('time', '09:00'),
                'end_time': f"{int(item.get('time', '09:00').split(':')[0]) + 1:02d}:{item.get('time', '09:00').split(':')[1] if ':' in item.get('time', '09:00') else '00'}",
                'description': item.get('title'),
            }
            
            if item.get('recurrence'):
                event_data['recurrence'] = item['recurrence']
                if item.get('rrule_day'):
                    event_data['rrule_day'] = item['rrule_day']
            
            result = gcal.create_event(
                title=event_data['title'],
                start_time=f"{event_data['start_date'].split('.')[2]}-{event_data['start_date'].split('.')[1].zfill(2)}-{event_data['start_date'].split('.')[0].zfill(2)}T{event_data['start_time']}:00",
                end_time=f"{event_data['start_date'].split('.')[2]}-{event_data['start_date'].split('.')[1].zfill(2)}-{event_data['start_date'].split('.')[0].zfill(2)}T{event_data['end_time']}:00",
                description=event_data.get('description'),
                recurrence=event_data.get('recurrence'),
                rrule_day=event_data.get('rrule_day')
            )
            
            if result:
                item['gcal_event_id'] = result.get('id')
                item['gcal_link'] = result.get('htmlLink')
                synced_count += 1
                print(f"✅ Synced: {item['title']} -> {result.get('htmlLink')}")
            else:
                failed_count += 1
                print(f"❌ Failed: {item['title']}")
                
        except Exception as e:
            failed_count += 1
            print(f"❌ Error syncing {item['title']}: {e}")

# Save updated data
with open(calendar_path, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"\n{'='*50}")
print(f"Done! Synced: {synced_count}, Failed: {failed_count}")
print(f"{'='*50}")
