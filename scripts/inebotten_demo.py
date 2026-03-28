#!/usr/bin/env python3
"""
Standalone @inebotten Response Demo
Shows exactly what the selfbot would reply with
No external dependencies required
"""

import os
from datetime import datetime, timedelta

def get_weather():
    """Simulated weather data - in real bot this comes from API"""
    return f"\n🌤️  **Weather:**\n   Sunny, {random.randint(50, 80)}°F. High tomorrow: {random.randint(60, 90)}°, Low: {random.randint(35, 55)}°"

def get_holidays():
    """Simulated holiday info - in real bot this queries calendar API"""
    today = datetime.now().strftime("%m-%d")
    holidays = [
        {'name': 'Pumpkin Spice Day', 'date': '09-13'},
        {'name': 'National Pizza Day', 'date': '10-09'},
        {'name': 'Fall Equinox', 'date': '09-22'},
    ]
    
    today_holiday = next((h for h in holidays if h['date'] == today), None)
    upcoming = [h for h in holidays if h['date'] > today and (datetime.strptime(h['date'], "%m-%d") - datetime.now()).days <= 7]
    
    response_parts = []
    
    if today_holiday:
        response_parts.append(f"   Today is {today_holiday['name']}! 🎉")
    
    for holiday in upcoming[:3]:
        days_until = (datetime.strptime(holiday['date'], "%m-%d") - datetime.now()).days
        if days_until <= 7:
            response_parts.append(f"   • {holiday['name']} ({holiday['date']})")
    
    return '\n'.join(response_parts)

def get_calendar():
    """Simulated calendar reminders - in real bot this pulls from Google Calendar API"""
    events = [
        "10:00 AM - Team Standup",
        "2:00 PM - Deadline for project proposal",
        "4:30 PM - Sunset yoga class",
    ]
    
    reminders = []
    for event in events:
        reminders.append(f"   • {event}")
    
    return '\n'.join(reminders)

def get_almanac():
    """Simulated almanac data - in real bot this queries astronomy API"""
    sunrise = f"{datetime.now().hour + 6:02d}:{datetime.now().minute:02d}"
    sunset = f"{datetime.now().hour + 18:02d}:{datetime.now().minute:02d}"
    
    return f"\n🌙 **ALMANAC**:\n   Moon Phase: 🌓 Waxing Crescent\n   • Sunrise: {sunrise}, Sunset: {sunset}\n   • Daylight: ~10h 30m"

def generate_inebotten_response(message=None):
    """
    Generate the response @inebotten would send
    This is what actually happens when you mention him!
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    parts = []
    
    # Header
    parts.append(f"📅 **Calendar & Almanac Update**\n*{timestamp}*\n\n")
    
    # Weather (simulated)
    weather = get_weather()
    if 'not configured' not in weather.lower():
        parts.append(weather + "\n")
    else:
        parts.append("🌤️  **Weather**: API not configured\n")
    
    # Holidays
    holiday_info = get_holidays()
    if holiday_info:
        parts.append(f"🎉 **Holidays**:\n{holiday_info}\n")
    else:
        parts.append("🎉 **Holidays**: No upcoming holidays this week\n")
    
    # Calendar
    reminders = get_calendar()
    parts.append(f"📝 **Reminders**:\n{reminders}\n")
    
    # Almanac
    almanac = get_almanac()
    parts.append(almanac + "\n")
    
    # Footer
    parts.append("— *Check back for updates!")
    
    return '\n'.join(parts)

def run_demo():
    print("="*70)
    print("  @inebotten RESPONSE SIMULATION")
    print("="*70)
    
    # Simulate a message you sent
    incoming_message = "Hey @inebotten, what's the weather like today and are there any holidays?"
    
    print(f"\n📥 YOU SENT: \"{incoming_message}\"")
    
    # What @inebotten would respond with
    response_text = generate_inebotten_response(incoming_message)
    
    print("\n" + "─"*70)
    print("📤 @inebotten's RESPONSE:")
    print("─" * 70)
    
    # Format and display response
    lines = response_text.split('\n')
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if '✗' in line or 'not configured' in line.lower():
            print(f"   {line}")
            continue
        
        # Add proper formatting
        stripped = line.strip()
        indent = "   " if i > 0 else ""
        
        # Smart indentation for different content types
        if '•' in stripped and not stripped.startswith('•'):
            print(f"{indent}• {stripped}")
        elif ':' in stripped or '☕' in stripped:
            print(f"{indent}{stripped}")
        else:
            print(f"{indent}{stripped}" if i > 0 else stripped)
    
    print("\n" + "="*70)
    print("  DEMO COMPLETE")
    print("="*70)
    
    stats = {
        'input_length': len(incoming_message),
        'response_length': len(response_text),
        'time_to_generate': 'instant (cached responses)',
    }
    
    print(f"\nStatistics:")
    print(f"  • Input: {stats['input_length']} chars")
    print(f"  • Response: {stats['response_length']} chars")
    print(f"  • Generation time: {stats['time_to_generate']}")

if __name__ == "__main__":
    import random  # Needed for weather simulation
    run_demo()
