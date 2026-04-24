#!/usr/bin/env python3
"""
Natural Language Parser for Inebotten
Understands flexible Norwegian and English event descriptions
"""

import re
from datetime import datetime, timedelta


class NaturalLanguageParser:
    """
    Parses natural language event descriptions into structured data
    """
    
    def __init__(self):
        self.setup_patterns()
    
    def setup_patterns(self):
        """Setup regex patterns for natural language parsing"""
        
        # Date indicators in Norwegian (Bokmål/Nynorsk) and English
        self.date_words = {
            'i dag': 0, 'today': 0, 'idag': 0, 'i dag': 0,
            'i morgen': 1, 'imorgen': 1, 'imårra': 1, 'imorra': 1, 'i morgon': 1, 'tomorrow': 1,
            'i overmorgen': 2, 'overmorgen': 2, 'i overmorgon': 2,
        }

        # Day names (Bokmål + Nynorsk variants)
        self.days = {
            'mandag': 0, 'måndag': 0, 'monday': 0,
            'tirsdag': 1, 'tuesday': 1,
            'onsdag': 2, 'wednesday': 2,
            'torsdag': 3, 'thursday': 3,
            'fredag': 4, 'friday': 4,
            'lørdag': 5, 'laurdag': 5, 'saturday': 5,
            'søndag': 6, 'sundag': 6, 'sunday': 6,
        }
        
        # Time words
        self.time_words = {
            'i morges': 'morning',
            'i formiddag': 'morning',
            'på formiddagen': 'morning',
            'i ettermiddag': 'afternoon',
            'på ettermiddagen': 'afternoon',
            'i kveld': 'evening',
            'på kvelden': 'evening',
            'i natt': 'night',
            'på natten': 'night',
            'midnatt': '00:00',
        }
        
        # Common prefixes to strip (from beginning of content)
        self.prefixes = [
            'husk at', 'husk', 'remember that', 'remember',
            'det er', 'there is', 'there\'s',
            'arrangement', 'event', 'fest', 'party',
            'ikke glem', 'don\'t forget',
            'vi har', 'we have', 'we\'re having',
            'minn meg på', 'minn meg om', 'påminn meg', 'remind me',
        ]
        
        # Task/obligation indicators (personal tasks) - Bokmål + Nynorsk + English
        self.task_indicators = [
            # Bokmål
            'jeg må', 'jeg skal', 'jeg trenger å', 'jeg bør',
            'jeg har lovet å', 'jeg har tenkt å', 'jeg vil',
            # Nynorsk
            'eg må', 'eg skal', 'eg treng å', 'eg bør',
            'eg har lova å', 'eg har tenkt å', 'eg vil',
            # Both
            'husk', 'husk å', 'ikkje gløym å', 'ikke glem å', 'må hugse å',
            'minn meg på', 'minn meg om', 'påminn meg',
            # English
            'i need to', 'i have to', 'i should', 'i must',
            'remember to', 'don\'t forget to', 'need to', 'remind me',
        ]
        
        # Event/social indicators (group gatherings)
        self.event_indicators = [
            'arrangement', 'event', 'fest', 'party', 'selskap',
            'møte', 'meeting', 'treff', 'gathering', 'grillfest',
            'vi har', 'we have', 'we\'re having', 'vi skal ha',
        ]
        
        # Recurrence continuation patterns (e.g., "og annenhver lørdag deretter")
        self.recurrence_continuation = [
            'og', 'deretter', 'etter det', 'så', 'then', 'and then', 'and',
        ]
        
        # Recurrence patterns
        self.recurrence_patterns = {
            # Bokmål + Nynorsk
            'hver uke': 'weekly',
            'kvar veke': 'weekly',
            'ukentlig': 'weekly',
            'ukent': 'weekly',
            'weekly': 'weekly',
            'hver andre uke': 'biweekly',
            'annenhver uke': 'biweekly',
            'kvar andre veke': 'biweekly',
            'biweekly': 'biweekly',
            'hver måned': 'monthly',
            'kvar månad': 'monthly',
            'månedlig': 'monthly',
            'monthly': 'monthly',
            'hvert år': 'yearly',
            'kvart år': 'yearly',
            'årlig': 'yearly',
            'yearly': 'yearly',
            'hver dag': 'daily',
            'kvar dag': 'daily',
            'daglig': 'daily',
            'daily': 'daily',
        }

        # Day-specific recurrence patterns (e.g., "hver mandag", "annenhver tirsdag")
        self.day_recurrence_patterns = {
            'hver': 'weekly',
            'kvar': 'weekly',
            'annenhver': 'biweekly',
            'kvar andre': 'biweekly',
            'hver andre': 'biweekly',
        }

        # Day name mappings for RRULE (Bokmål + Nynorsk)
        self.day_name_to_rrule = {
            'mandag': 'MO',
            'måndag': 'MO',
            'tirsdag': 'TU',
            'onsdag': 'WE',
            'torsdag': 'TH',
            'fredag': 'FR',
            'lørdag': 'SA',
            'laurdag': 'SA',
            'søndag': 'SU',
            'sundag': 'SU',
            'monday': 'MO',
            'tuesday': 'TU',
            'wednesday': 'WE',
            'thursday': 'TH',
            'friday': 'FR',
            'saturday': 'SA',
            'sunday': 'SU',
        }
    
    def parse_event(self, message_content):
        """
        Parse natural language event description
        
        Returns:
            dict with title, date, time or None
        """
        # Remove @inebotten mention and Discord user mentions
        content = message_content
        content = re.sub(r'<@!?\d+>', '', content)  # Remove Discord mentions like <@123456> or <@!123456>
        content = re.sub(r'@inebotten\s*', '', content, flags=re.IGNORECASE).strip()
        
        # Check if it looks like an event (has time indicator or date)
        if not self._has_time_indicator(content):
            return None
        
        # Extract date
        date_str, days_offset = self._extract_date(content)
        
        # If no date found but recurrence is present, default to today
        recurrence_data = self._extract_recurrence(content)
        if not date_str and days_offset is None:
            if recurrence_data:
                # Default to today for recurrence-only patterns like "regninger hver måned"
                from datetime import datetime
                today = datetime.now()
                date_str = today.strftime('%d.%m.%Y')
                days_offset = 0
            else:
                return None
        
        # Extract time
        time_str = self._extract_time(content)
        
        # Extract title by removing date/time/recurrence parts
        title = self._extract_title(content, date_str, time_str, recurrence_data)
        
        if not title or len(title) < 2:
            return None
        
        # Determine item type based on content indicators
        item_type = self._determine_item_type(content)
        
        result = {
            'type': item_type,  # 'event' or 'task'
            'title': title,
            'date': date_str,
            'time': time_str,
            'days_offset': days_offset,
        }
        
        # Add recurrence info
        if recurrence_data:
            result['recurrence'] = recurrence_data['type']
            if 'day' in recurrence_data:
                result['recurrence_day'] = recurrence_data['day']
                result['rrule_day'] = recurrence_data['rrule_day']
        
        return result
    
    def _determine_item_type(self, content):
        """
        Determine if content describes an event or a task
        based on language patterns
        """
        content_lower = content.lower()
        
        # Check for explicit event command
        if content_lower.startswith('arrangement'):
            return 'event'
        
        # Check for task indicators
        for indicator in self.task_indicators:
            if indicator in content_lower:
                return 'task'
        
        # Check for event indicators
        for indicator in self.event_indicators:
            if indicator in content_lower:
                return 'event'
        
        # Default to event for most time-based items (backwards compatible)
        return 'event'
    
    def parse_task_with_recurrence(self, message_content):
        """
        Parse natural language task descriptions with specific dates and recurrence
        
        Handles patterns like:
        - "Jeg må sende meldekort på lørdag 4.April og annenhver lørdag deretter"
        - "Jeg skal trene på mandag 1.juni og hver mandag etter det"
        - "Minn meg på at jeg må sende Meldekort kl 10:00 Lørdag 4.april og deretter annenhver lørdag"
        
        Returns:
            dict with task_text, start_date, time, recurrence, recurrence_day or None
        """
        # Remove @inebotten mention and Discord user mentions
        content = message_content
        content = re.sub(r'<@!?\d+>', '', content)
        content = re.sub(r'@inebotten\s*', '', content, flags=re.IGNORECASE).strip()
        
        # Check for task indicators or reminder phrases
        has_task_indicator = False
        matched_indicator = None
        for indicator in self.task_indicators:
            if indicator in content.lower():
                has_task_indicator = True
                matched_indicator = indicator
                break
        
        # Also check for "minn meg på" style reminders
        if not has_task_indicator:
            reminder_phrases = ['minn meg på', 'minn meg om', 'påminn meg', 'remind me']
            for phrase in reminder_phrases:
                if phrase in content.lower():
                    has_task_indicator = True
                    matched_indicator = phrase
                    break
        
        if not has_task_indicator:
            return None
        
        # Step 1: Get text after the indicator
        # Find the indicator in the original case content
        idx = content.lower().find(matched_indicator)
        remaining = content[idx + len(matched_indicator):].strip()
        
        # Clean up common particles after indicator
        remaining = re.sub(r'^(å|at|om|på)\s+', '', remaining, flags=re.IGNORECASE)
        
        # Step 2: Look for date with day name
        # Try multiple patterns to be flexible with word order
        
        # Pattern 1: "[day] [number].[month]" (e.g., "Lørdag 4.april")
        day_names_pattern = '|'.join(self.days.keys())
        date_match = re.search(
            r'(' + day_names_pattern + r')\s+(\d{1,2})[.\s]+([a-zæøå]+)(?:\s+(\d{4}))?',
            remaining,
            re.IGNORECASE
        )
        
        # Pattern 2: "[number].[month]" without day name
        if not date_match:
            date_match = re.search(
                r'(\d{1,2})[.\s]+([a-zæøå]+)(?:\s+(\d{4}))?',
                remaining,
                re.IGNORECASE
            )
            if date_match:
                day_num = date_match.group(1)
                month_name = date_match.group(2).lower()
                year = date_match.group(3) if date_match.lastindex >= 3 and date_match.group(3) else str(datetime.now().year)
                day_name = None
        else:
            day_name = date_match.group(1).lower()
            day_num = date_match.group(2)
            month_name = date_match.group(3).lower()
            year = date_match.group(4) if date_match.lastindex >= 4 and date_match.group(4) else str(datetime.now().year)
        
        if not date_match:
            return None
        
        # Convert month name to number
        month_map = {
            'januar': 1, 'january': 1, 'jan': 1,
            'februar': 2, 'february': 2, 'feb': 2,
            'mars': 3, 'march': 3, 'mar': 3,
            'april': 4, 'apr': 4,
            'mai': 5, 'may': 5,
            'juni': 6, 'june': 6, 'jun': 6,
            'juli': 7, 'july': 7, 'jul': 7,
            'august': 8, 'aug': 8,
            'september': 9, 'sep': 9, 'sept': 9,
            'oktober': 10, 'october': 10, 'okt': 10, 'oct': 10,
            'november': 11, 'nov': 11,
            'desember': 12, 'december': 12, 'des': 12, 'dec': 12,
        }
        
        month_num = month_map.get(month_name.lower())
        if not month_num:
            return None
        
        start_date = f"{day_num}.{month_num}.{year}"
        
        # Step 3: Extract time if present (look for "kl" or "klokken" before the date)
        time_str = None
        time_match = re.search(r'kl\.?\s*(\d{1,2})(?::(\d{2}))?', remaining[:date_match.start()], re.IGNORECASE)
        if time_match:
            hour = time_match.group(1)
            minute = time_match.group(2) if time_match.group(2) else '00'
            time_str = f"{hour}:{minute}"
        
        # Step 4: Extract task text (everything before date/time indicators)
        # Find where the task text ends (before time or date)
        task_end = date_match.start()
        if time_match:
            task_end = min(task_end, time_match.start())
        
        task_text = remaining[:task_end].strip()
        
        # Clean up task text - remove common prepositions at start and end
        task_text = re.sub(r'^(å|at|om|på)\s+', '', task_text, flags=re.IGNORECASE)
        task_text = re.sub(r'\s+(på|om|å|at)$', '', task_text, flags=re.IGNORECASE)
        task_text = re.sub(r'\s+', ' ', task_text).strip()
        
        if not task_text or len(task_text) < 2:
            return None
        
        # Step 5: Look for recurrence pattern after the date
        remaining_after_date = remaining[date_match.end():]
        
        # Check for continuation words + recurrence
        recurrence_data = None
        for cont in self.recurrence_continuation:
            if cont in remaining_after_date.lower():
                # Look for recurrence pattern
                recurrence_data = self._extract_recurrence(remaining_after_date)
                break
        
        # Also check for recurrence without continuation words (e.g., "og annenhver lørdag")
        if not recurrence_data:
            recurrence_data = self._extract_recurrence(remaining_after_date)
        
        result = {
            'type': 'task',  # Unified type
            'title': task_text,
            'date': start_date,
        }
        
        if time_str:
            result['time'] = time_str
        if recurrence_data:
            result['recurrence'] = recurrence_data['type']
            if 'day' in recurrence_data:
                result['recurrence_day'] = recurrence_data['day']
                result['rrule_day'] = recurrence_data['rrule_day']
        
        return result
    
    def _get_month_number(self, month_name):
        """Convert Norwegian or English month name to month number (1-12)"""
        month_map = {
            # Norwegian
            'januar': 1, 'jan': 1,
            'februar': 2, 'feb': 2,
            'mars': 3, 'mar': 3,
            'april': 4, 'apr': 4,
            'mai': 5,
            'juni': 6, 'jun': 6,
            'juli': 7, 'jul': 7,
            'august': 8, 'aug': 8,
            'september': 9, 'sep': 9,
            'oktober': 10, 'okt': 10,
            'november': 11, 'nov': 11,
            'desember': 12, 'des': 12,
            # English
            'january': 1,
            'february': 2,
            'march': 3,
            'april': 4,
            'may': 5,
            'june': 6,
            'july': 7,
            'august': 8,
            'september': 9,
            'october': 10,
            'november': 11,
            'december': 12,
        }
        return month_map.get(month_name.lower())

    def _has_time_indicator(self, content):
        """
        Check if content has strong time/date indicators that suggest a calendar command.

        This method is conservative - it requires multiple indicators OR explicit
        calendar keywords to avoid misinterpreting casual conversation.
        """
        content_lower = content.lower()

        # Strong indicators that almost certainly mean calendar command
        strong_indicators = 0

        # 1. Explicit calendar keywords (very strong signal)
        calendar_keywords = [
            'møte', 'meeting', 'treff', 'avtale', 'appointment',
            'arrangement', 'event', 'fest', 'party', 'selskap',
            'kurs', 'seminar', 'konferanse', 'workshop',
            'legetime', 'tannlege', 'hårtime', 'time', 'appointment',
            'konfirmasjon', 'bryllup', 'bursdag', 'jubileum',
            'frist', 'deadline', 'innlevering', 'eksamen',
            'trening', 'økt', 'øvelse', 'prøve', 'øving',
        ]
        for keyword in calendar_keywords:
            if keyword in content_lower:
                strong_indicators += 2  # Calendar keywords are strong signals

        # 2. Task indicators (husk, jeg må, etc.)
        for indicator in self.task_indicators:
            if indicator in content_lower:
                strong_indicators += 2

        # 3. Explicit time patterns (kl 14, 14:00)
        if re.search(r'(?:kl\.?|klokken)\s*\d{1,2}', content_lower):
            strong_indicators += 2
        if re.search(r'\b\d{1,2}:\d{2}\b', content):
            strong_indicators += 2

        # 4. Numeric dates (DD.MM.YYYY or DD.MM)
        if re.search(r'\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?', content):
            strong_indicators += 2

        # 4b. Month name dates (15. mai, 20 desember)
        month_pattern = r'\d{1,2}\s*[.-]?\s*(?:januar|februar|mars|april|mai|juni|juli|august|september|oktober|november|desember|jan|feb|mar|apr|jun|jul|aug|sep|okt|nov|des|january|february|march|may|june|july|august|september|october|november|december)'
        if re.search(month_pattern, content_lower):
            strong_indicators += 2

        # 4c. "den X" pattern (den 5., den 15. mai)
        den_pattern = r'den\s*\d{1,2}\s*\.?(?:\s*(?:januar|februar|mars|april|mai|juni|juli|august|september|oktober|november|desember|jan|feb|mar|apr|jun|jul|aug|sep|okt|nov|des))?'
        if re.search(den_pattern, content_lower):
            strong_indicators += 2

        # 5. Recurrence patterns (hver uke, etc.)
        for pattern in self.recurrence_patterns:
            if pattern in content_lower:
                strong_indicators += 2

        # If we have strong indicators, it's likely a calendar command
        if strong_indicators >= 2:
            return True

        # Weak indicators (date words like "i dag", "i morgen")
        # These alone are NOT enough - they're too common in conversation
        weak_indicators = 0

        for word in self.date_words:
            if word in content_lower:
                weak_indicators += 1

        for day in self.days:
            if day in content_lower:
                weak_indicators += 1

        # Only accept weak indicators if we have multiple AND the message is short
        # (short messages with date words are more likely to be calendar commands)
        word_count = len(content.split())
        if weak_indicators >= 1 and word_count <= 5:
            return True

        return False
    
    def _format_date(self, day: int, month: int, year: int) -> str:
        """Format as DD.MM.YYYY with leading zeros"""
        return f"{day:02d}.{month:02d}.{year}"
    
    def _extract_date(self, content):
        """
        Extract date from content
        Returns: (date_string, days_offset) or (None, None)
        """
        content_lower = content.lower()
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        # 1. Check for explicit DD.MM.YYYY or DD.MM
        date_match = re.search(r'(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?', content)
        if date_match:
            day, month, year = date_match.groups()
            if year:
                if len(year) == 2:
                    year = '20' + year
                date_str = f"{day}.{month}.{year}"
            else:
                date_str = f"{day}.{month}.{today.year}"
            return date_str, None

        # 2. NEW: Check for month name date format (e.g., "15. mai", "20 desember")
        # Pattern: one or two digits, optional dot/dash/space, month name, optional year
        month_date_match = re.search(
            r'(\d{1,2})\s*[.-]?\s*([a-zæøå]+)(?:\s+(\d{4}))?',
            content_lower
        )
        if month_date_match:
            day_str, month_name, year_str = month_date_match.groups()
            month_num = self._get_month_number(month_name)
            if month_num:
                year = year_str if year_str else str(today.year)
                # Handle two-digit years
                if len(year) == 2:
                    year = '20' + year
                date_str = f"{day_str}.{month_num}.{year}"
                return date_str, None

        # 3. NEW: Check for "den X." pattern (e.g., "den 5.", "den 15. mai")
        # Only match valid Norwegian/English month names
        valid_months = 'januar|februar|mars|april|mai|juni|juli|august|september|oktober|november|desember|jan|feb|mar|apr|jun|jul|aug|sep|okt|nov|des|january|february|march|may|june|july|august|september|october|november|december'
        den_match = re.search(
            rf'den\s*(\d{{1,2}})\s*[.]?\s*(?:({valid_months}))?(?:\s+(\d{{4}}))?',
            content_lower
        )
        if den_match:
            day_str, month_name, year_str = den_match.groups()
            if month_name:  # "den 15. mai"
                month_num = self._get_month_number(month_name.lower())
                if month_num:
                    year = year_str if year_str else str(today.year)
                    if len(year) == 2:
                        year = '20' + year
                    date_str = f"{day_str}.{month_num}.{year}"
                    return date_str, None
            else:  # "den 5." - day only, use current month
                year = year_str if year_str else str(today.year)
                if len(year) == 2:
                    year = '20' + year
                date_str = f"{day_str}.{today.month}.{year}"
                return date_str, None

        # 4. Check for "i dag", "i morgen", etc.
        for word, offset in self.date_words.items():
            if word in content_lower:
                target_date = today + timedelta(days=offset)
                return target_date.strftime('%d.%m.%Y'), offset

        # 5. Check for day names ("på lørdag", "til lørdag", etc.)
        for day_name, day_num in self.days.items():
            # Match patterns like "på lørdag", "til lørdag", "lørdag"
            pattern = r'(?:på|til|neste)?\s*' + day_name
            if re.search(pattern, content_lower):
                days_ahead = day_num - today.weekday()
                if days_ahead <= 0:  # Target day already happened this week
                    days_ahead += 7
                target_date = today + timedelta(days=days_ahead)
                return target_date.strftime('%d.%m.%Y'), days_ahead

        # 6. If we have time indicators like "i kveld" but no date, assume today
        for time_word in ['i kveld', 'i natt', 'i dag']:
            if time_word in content_lower:
                return today.strftime('%d.%m.%Y'), 0

        return None, None
    
    def _extract_time(self, content):
        """Extract time from content"""
        content_lower = content.lower()
        
        # Check for explicit time with "kl" or "klokken"
        time_match = re.search(r'(?:kl\.?|klokken)\s*(\d{1,2})(?::(\d{2}))?', content_lower)
        if time_match:
            hour = time_match.group(1)
            minute = time_match.group(2) if time_match.group(2) else '00'
            return f"{hour}:{minute}"
        
        # Check for HH:MM format
        time_match = re.search(r'\b(\d{1,2}):(\d{2})\b', content)
        if time_match:
            return f"{time_match.group(1)}:{time_match.group(2)}"
        
        # Check for time words
        for word, meaning in self.time_words.items():
            if word in content_lower:
                if meaning == 'morning':
                    return '10:00'
                elif meaning == 'afternoon':
                    return '14:00'
                elif meaning == 'evening':
                    return '19:00'
                elif meaning == 'night':
                    return '22:00'
                elif ':' in meaning:
                    return meaning
        
        return None
    
    def _extract_title(self, content, date_str, time_str, recurrence_data=None):
        """
        Extract event title by removing date/time indicators
        """
        title = content
        
        # Remove recurrence patterns first
        if recurrence_data:
            # Remove day-specific pattern if present - sort by longest prefix first
            if 'day' in recurrence_data:
                for prefix in sorted(self.day_recurrence_patterns.keys(), key=len, reverse=True):
                    pattern = f"{prefix} {recurrence_data['day']}"
                    title = re.sub(pattern, '', title, flags=re.IGNORECASE)
        # Remove general recurrence patterns
        for pattern in self.recurrence_patterns:
            title = re.sub(pattern, '', title, flags=re.IGNORECASE)
        
        # Remove any remaining Discord mentions
        title = re.sub(r'<@!?\d+>', '', title)
        
        # Remove prefixes and task indicators from start of title
        all_prefixes = self.prefixes + self.task_indicators
        for prefix in sorted(all_prefixes, key=len, reverse=True):  # Longer prefixes first
            # Match at start with optional leading whitespace, followed by space or end
            pattern = f'^\\s*{re.escape(prefix)}(?:\\s|$)'
            new_title = re.sub(pattern, '', title, flags=re.IGNORECASE, count=1)
            if new_title != title:
                title = new_title
                break  # Only remove one prefix
        
        # Remove date patterns
        if date_str:
            # Remove various date formats
            title = re.sub(r'\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?', '', title)
            
            # Remove date words
            for word in self.date_words:
                title = re.sub(word, '', title, flags=re.IGNORECASE)
            
            # Remove day names
            for day in self.days:
                title = re.sub(day, '', title, flags=re.IGNORECASE)
        
        # Remove time patterns
        if time_str:
            title = re.sub(r'(?:kl\.?|klokken)\s*\d{1,2}(?::\d{2})?', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\b\d{1,2}:\d{2}\b', '', title)
            
            # Remove time words
            for word in self.time_words:
                title = re.sub(word, '', title, flags=re.IGNORECASE)
        
        # Remove recurrence patterns from title
        for pattern in self.recurrence_patterns:
            title = re.sub(pattern, '', title, flags=re.IGNORECASE)
        
        # Remove day-specific recurrence patterns from title
        for prefix in self.day_recurrence_patterns:
            for day in self.day_name_to_rrule:
                pattern = f"{prefix} {day}"
                title = re.sub(pattern, '', title, flags=re.IGNORECASE)
        
        # Remove standalone recurrence prefixes (e.g., "hver", "annenhver" left over)
        for prefix in sorted(self.day_recurrence_patterns.keys(), key=len, reverse=True):
            title = re.sub(prefix, '', title, flags=re.IGNORECASE)
        
        # Remove trailing prepositions that weren't followed by their expected objects
        title = re.sub(r'\s+(på|om|å)\s*$', '', title, flags=re.IGNORECASE)
        
        # Clean up
        title = re.sub(r'\s+', ' ', title).strip()
        title = re.sub(r'^[-–—\s]+', '', title)
        title = re.sub(r'[-–—\s]+$', '', title)
        
        # If title is empty or too short after processing, use first word of original content
        if not title or len(title) < 2:
            # Get first word of original content (before any processing)
            original_words = content.split()
            for word in original_words:
                # Skip date/time words and find first meaningful word
                word_lower = word.lower()
                if (word_lower not in self.date_words and 
                    word_lower not in self.days and
                    word_lower not in ['kl', 'kl.'] and
                    not re.match(r'\d{1,2}:\d{2}', word) and
                    not re.match(r'\d{1,2}[./]', word)):
                    title = word
                    break
        
        # Capitalize first letter
        if title:
            title = title[0].upper() + title[1:]
        
        return title
    
    def _extract_recurrence(self, content):
        """
        Extract recurrence pattern from content
        Returns: dict with 'type' and optional 'day' or simple string
        """
        content_lower = content.lower()
        
        # Check for day-specific patterns first (e.g., "hver mandag", "annenhver tirsdag")
        for pattern_prefix in sorted(self.day_recurrence_patterns.keys(), key=len, reverse=True):
            if pattern_prefix in content_lower:
                # Check if a day name follows
                for day_name, rrule_day in self.day_name_to_rrule.items():
                    # Check for patterns like "hver mandag", "annenhver tirsdag"
                    full_pattern = f"{pattern_prefix} {day_name}"
                    if full_pattern in content_lower:
                        return {
                            'type': self.day_recurrence_patterns[pattern_prefix],
                            'day': day_name,
                            'rrule_day': rrule_day
                        }
        
        # Check for general recurrence patterns
        for pattern in sorted(self.recurrence_patterns.keys(), key=len, reverse=True):
            if pattern in content_lower:
                return {'type': self.recurrence_patterns[pattern]}
        
        return None


def parse_natural_event(message_content):
    """
    Convenience function to parse natural language event
    
    Examples that should work:
    - "@inebotten husk at det er kamp mellom bodø glimt og sporting i kveld kl 18:45"
    - "@inebotten arrangement 17.03.2026 Sporting-vs-Glimt kl 18:45"
    - "@inebotten det er bursdagsfest på lørdag kl 20:00"
    - "@inebotten husk møte i morgen kl 09:00"
    """
    parser = NaturalLanguageParser()
    return parser.parse_event(message_content)


if __name__ == "__main__":
    # Test the natural language parser
    print("=== Natural Language Parser Test ===\n")
    
    test_cases = [
        "@inebotten husk at det er kamp mellom bodø glimt og sporting i kveld kl 18:45",
        "@inebotten arrangement 17.03.2026 Sporting-vs-Glimt kl 18:45",
        "@inebotten det er bursdagsfest på lørdag kl 20:00",
        "@inebotten husk møte i morgen kl 09:00",
        "@inebotten i dag er det lunsj kl 12:00",
        "@inebotten på tirsdag har vi workshop",
        "@inebotten neste fredag kl 16:00 - etterarbeid",
        "@inebotten 25.12.2025 Julemiddag kl 17:00",
    ]
    
    parser = NaturalLanguageParser()
    
    for test in test_cases:
        result = parser.parse_event(test)
        print(f"Input: {test}")
        if result:
            print(f"  Title: {result['title']}")
            print(f"  Date: {result['date']}")
            print(f"  Time: {result['time']}")
        else:
            print(f"  Could not parse")
        print()
