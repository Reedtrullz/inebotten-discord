import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from cal_system.google_calendar_manager import GoogleCalendarManager

def test_gcal_creators():
    print("=== Testing GCal Creator Info ===\n")
    gcal = GoogleCalendarManager()
    if not gcal.is_configured():
        print("GCal not configured.")
        return
        
    events = gcal.list_upcoming_events(days=30)
    if not events:
        print("No events found.")
        return
        
    for event in events:
        summary = event.get('summary', 'No Title')
        creator = event.get('creator', {})
        organizer = event.get('organizer', {})
        print(f"Event: {summary}")
        print(f"  Creator: {creator.get('displayName')} ({creator.get('email')})")
        print(f"  Organizer: {organizer.get('displayName')} ({organizer.get('email')})")
        print("-" * 20)

if __name__ == "__main__":
    test_gcal_creators()
