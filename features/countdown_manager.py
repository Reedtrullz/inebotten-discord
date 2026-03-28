#!/usr/bin/env python3
"""
Countdown Manager for Inebotten
Handles "how long until..." queries and countdowns to events
Supports both Norwegian and English
"""

import re
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import random


class CountdownManager:
    """
    Manages countdowns to holidays, events, and custom dates
    """
    
    def __init__(self):
        # Important dates with both Norwegian and English names
        self.important_dates = {
            # Norwegian names
            '17. mai': (2026, 5, 17), 'grunnlovsdagen': (2026, 5, 17),
            'jul': (2026, 12, 25), 'julaften': (2026, 12, 24),
            'nyttår': (2026, 1, 1), 'nyttårsaften': (2025, 12, 31),
            'påske': (2026, 4, 5),
            'sommerferie': (2026, 6, 20),
            'vinterferie': (2026, 2, 23),
            'høstferie': (2025, 10, 6),
            'halloween': (2025, 10, 31),
            'allehelgensdag': (2025, 11, 1),
            'valentines': (2026, 2, 14), 'valentinsdagen': (2026, 2, 14),
            'morsdag': (2026, 2, 8),
            'farsdag': (2025, 11, 9),
            'sankthans': (2025, 6, 23),
            # English names
            '17 may': (2026, 5, 17), 'constitution day': (2026, 5, 17),
            'christmas': (2026, 12, 25), 'xmas': (2026, 12, 25),
            'christmas eve': (2026, 12, 24),
            'new year': (2026, 1, 1), 'new years': (2026, 1, 1),
            'new years eve': (2025, 12, 31),
            'easter': (2026, 4, 5),
            'summer holiday': (2026, 6, 20), 'summer vacation': (2026, 6, 20),
            'winter holiday': (2026, 2, 23),
            'autumn holiday': (2025, 10, 6), 'fall break': (2025, 10, 6),
            'all saints day': (2025, 11, 1),
            'valentines day': (2026, 2, 14),
            'mothers day': (2026, 2, 8),
            'fathers day': (2025, 11, 9),
            'midsummer': (2025, 6, 23), 'st hans': (2025, 6, 23),
        }
        
        # Emojis for events
        self.event_emojis = {
            '17. mai': '🇳🇴', 'grunnlovsdagen': '🇳🇴', '17 may': '🇳🇴', 'constitution day': '🇳🇴',
            'jul': '🎄', 'julaften': '🎁', 'christmas': '🎄', 'christmas eve': '🎁', 'xmas': '🎄',
            'nyttår': '🎆', 'nyttårsaften': '🎇', 'new year': '🎆', 'new years eve': '🎇',
            'påske': '🐰', 'easter': '🐰',
            'sommerferie': '🏖️', 'summer holiday': '🏖️', 'summer vacation': '🏖️',
            'vinterferie': '⛷️', 'winter holiday': '⛷️',
            'høstferie': '🍂', 'halloween': '🎃', 'autumn holiday': '🍂', 'fall break': '🍂',
            'valentines': '❤️', 'valentinsdagen': '❤️', 'valentines day': '❤️',
            'morsdag': '💐', 'farsdag': '👔', 'mothers day': '💐', 'fathers day': '👔',
            'sankthans': '🔥', 'midsummer': '🔥', 'st hans': '🔥',
        }
    
    def parse_countdown_query(self, message_content):
        """
        Parse countdown queries in Norwegian or English
        """
        content_lower = message_content.lower()
        
        # Remove @inebotten
        content_lower = content_lower.replace('@inebotten', '').strip()
        
        # Patterns to match (Norwegian and English)
        patterns = [
            # Norwegian
            r'(?:hvor lenge|hvor mange dager|nedtelling)\s+(?:til|før)\s+(.+)',
            r'når er\s+(.+)',
            r'dager til\s+(.+)',
            # English
            r'(?:how long|how many days|countdown)\s+(?:to|until|till)\s+(.+)',
            r'when is\s+(.+)',
            r'days until\s+(.+)',
            r'days to\s+(.+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content_lower)
            if match:
                query = match.group(1).strip()
                return self._find_date(query)
        
        return None
    
    def _find_date(self, query):
        """Find date for a query and return structured data"""
        query_lower = query.lower().strip()
        
        # Check against known holidays
        for holiday_name, date_tuple in self.important_dates.items():
            if holiday_name in query_lower:
                target_date = datetime(date_tuple[0], date_tuple[1], date_tuple[2])
                return self._calculate_countdown(target_date, holiday_name)
        
        # Try to parse DD.MM.YYYY or DD.MM (Norwegian)
        date_match = re.search(r'(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?', query_lower)
        if date_match:
            day, month, year = date_match.groups()
            day, month = int(day), int(month)
            year = int(year) if year else datetime.now().year
            
            try:
                target_date = datetime(year, month, day)
                if target_date < datetime.now():
                    target_date = datetime(year + 1, month, day)
                return self._calculate_countdown(target_date, query)
            except:
                pass
        
        # Try to parse MM/DD/YYYY or MM/DD (US format)
        date_match = re.search(r'(\d{1,2})/(\d{1,2})(?:/(\d{4}))?', query_lower)
        if date_match:
            month, day, year = date_match.groups()
            month, day = int(month), int(day)
            year = int(year) if year else datetime.now().year
            
            try:
                target_date = datetime(year, month, day)
                if target_date < datetime.now():
                    target_date = datetime(year + 1, month, day)
                return self._calculate_countdown(target_date, query)
            except:
                pass
        
        return None
    
    def _calculate_countdown(self, target_date, event_name):
        """Calculate countdown and return structured data"""
        now = datetime.now()
        diff = target_date - now
        
        days = diff.days
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60
        
        # Find emoji
        emoji = '📅'
        for key, em in self.event_emojis.items():
            if key in event_name.lower():
                emoji = em
                break
        
        return {
            'event': event_name.title(),
            'days': days,
            'hours': hours,
            'minutes': minutes,
            'target_date': target_date,
            'emoji': emoji,
            'is_today': days == 0,
            'is_tomorrow': days == 1,
            'is_past': days < 0
        }
    
    def format_response(self, countdown_data, lang='no'):
        """Format countdown response in specified language"""
        if not countdown_data:
            return None
        
        event = countdown_data['event']
        days = countdown_data['days']
        hours = countdown_data['hours']
        emoji = countdown_data['emoji']
        
        if countdown_data['is_past']:
            if lang == 'no':
                return f"📅 **{event}** var for {abs(days)} dager siden {emoji}"
            else:
                return f"📅 **{event}** was {abs(days)} days ago {emoji}"
        
        if countdown_data['is_today']:
            if lang == 'no':
                return f"🎉 **{event}** er i dag! {emoji}"
            else:
                return f"🎉 **{event}** is today! {emoji}"
        
        if countdown_data['is_tomorrow']:
            if lang == 'no':
                return f"📅 **{event}** er i morgen! {emoji}"
            else:
                return f"📅 **{event}** is tomorrow! {emoji}"
        
        # Format based on how close
        if days < 7:
            if lang == 'no':
                return f"⏰ **{event}** om **{days}** dager! {emoji}"
            else:
                return f"⏰ **{event}** in **{days}** days! {emoji}"
        elif days < 30:
            weeks = days // 7
            remaining_days = days % 7
            if lang == 'no':
                if remaining_days > 0:
                    return f"📅 **{event}** om {weeks} uker og {remaining_days} dager! {emoji}"
                else:
                    return f"📅 **{event}** om {weeks} uker! {emoji}"
            else:
                if remaining_days > 0:
                    return f"📅 **{event}** in {weeks} weeks and {remaining_days} days! {emoji}"
                else:
                    return f"📅 **{event}** in {weeks} weeks! {emoji}"
        elif days < 365:
            months = days // 30
            if lang == 'no':
                return f"📅 **{event}** om ~{months} måneder ({days} dager) {emoji}"
            else:
                return f"📅 **{event}** in ~{months} months ({days} days) {emoji}"
        else:
            years = days // 365
            remaining_days = days % 365
            if lang == 'no':
                return f"📅 **{event}** om {years} år og {remaining_days} dager {emoji}"
            else:
                return f"📅 **{event}** in {years} years and {remaining_days} days {emoji}"


# Quick test
if __name__ == "__main__":
    manager = CountdownManager()
    
    test_queries = [
        ("@inebotten hvor lenge til 17. mai", 'no'),
        ("@inebotten countdown to christmas", 'en'),
        ("@inebotten nedtelling til jul", 'no'),
        ("@inebotten how many days to easter", 'en'),
    ]
    
    for query, lang in test_queries:
        result = manager.parse_countdown_query(query)
        if result:
            formatted = manager.format_response(result, lang)
            print(f"'{query}' → {formatted}")
        else:
            print(f"'{query}' → No match")
