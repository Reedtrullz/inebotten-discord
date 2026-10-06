#!/usr/bin/env python3
"""
Conversation Context Manager for Inebotten
Maintains conversation threads and detects intent
"""

import re
import copy
from collections import defaultdict
from datetime import datetime, timedelta


class ConversationContext:
    """
    Manages conversation history and intent detection
    """
    
    # Keywords that indicate user wants dashboard/info
    DASHBOARD_KEYWORDS = [
        'vær', 'været', 'værmelding', 'weather',
        'kalender', 'kalenderen', 'calendar', 'plan', 'planer',
        'hva skjer', 'hva skal', 'hva har jeg',
        'oversikt', 'status', 'dashboard',
        'påminnelse', 'påminnelser', 'huskeliste', 'gjøremål',
        'navnedag', 'navnedager'
    ]
    
    # Small talk patterns
    SMALL_TALK_PATTERNS = [
        r'^hei\b', r'^hallo\b', r'^halla\b', r'^yo\b',
        r'^god (morgen|dag|kveld|natt)',
        r'^morn\b', r'^kvelden\b', r'^heisann\b',
        r'hvordan går det', r'how are you',
        r'hva (gjør|driver) du',
        r'takk', r'bra',
        r'\?$',  # Ends with question mark
        r'hva (synes|mener) du',
        r'forklar', r'fortell',
        # Norwegian dialect expressions
        r'\bkjekt\b', r'\btøft\b', r'\brått\b',
        r'\bskikkelig\b', r'\bkult\b', r'\bstilig\b',
        r'\bkempe', r'\bsupert\b', r'\bflott\b',
        r'\bskal\b', r'\bvil\b', r'\bblir\b', r'\bønsker\b',
        r'\bhva skjer\b', r'\bhva driver\b',
    ]
    
    def __init__(self, max_history=10, expiry_minutes=30, *, wall=None):
        if type(max_history) is not int or not 1 <= max_history <= 100 or type(expiry_minutes) is not int or not 1 <= expiry_minutes <= 1440:
            raise ValueError('invalid_context_limits')
        self.wall = wall or datetime.now
        self.max_history = max_history
        self.max_channels = 256
        self.expiry_minutes = expiry_minutes
        self.threads = defaultdict(list)  # channel_id -> messages
        self.last_bot_message = {}  # channel_id -> timestamp
    
    def add_message(self, channel_id, user_id, username, content, is_bot=False, *, source_user_id=None):
        """
        Add a message to the conversation thread
        """
        # Clean old messages first
        self.prune()
        
        entry = {
            'user_id': user_id,
            'username': str(username)[:256],
            'content': str(content)[:4000],
            'is_bot': is_bot,
            'timestamp': self.wall(),
            'source_user_id': source_user_id,
        }
        
        self.threads[channel_id].append(entry)
        
        self.prune()
        # Keep only last N messages
        if len(self.threads[channel_id]) > self.max_history:
            self.threads[channel_id] = self.threads[channel_id][-self.max_history:]
        
        if is_bot:
            self.last_bot_message[channel_id] = self.wall()
    
    def _clean_old_messages(self, channel_id):
        """Remove messages older than expiry time"""
        cutoff = self.wall() - timedelta(minutes=self.expiry_minutes)
        if channel_id in self.threads:
            self.threads[channel_id] = [
                m for m in self.threads[channel_id]
                if m['timestamp'] > cutoff
            ]
    
    def prune(self):
        for channel_id in list(self.threads):
            self._clean_old_messages(channel_id)
            if not self.threads[channel_id]:
                self.threads.pop(channel_id, None)
                self.last_bot_message.pop(channel_id, None)
        while len(self.threads) > self.max_channels:
            oldest = min(self.threads, key=lambda key: self.threads[key][-1]['timestamp'])
            self.threads.pop(oldest, None)
            self.last_bot_message.pop(oldest, None)

    def delete_user(self, user_id):
        count = 0
        for channel_id, messages in list(self.threads.items()):
            kept = [message for message in messages if str(message.get('user_id')) != str(user_id)
                and str(message.get('source_user_id')) != str(user_id)]
            count += len(messages) - len(kept)
            self.threads[channel_id] = kept
        self.prune()
        return count

    def get_context(self, channel_id, limit=5):
        """
        Get recent conversation context as formatted string
        """
        self.prune()
        if channel_id not in self.threads:
            return ""
        
        messages = self.threads[channel_id][-limit:]
        lines = []
        
        for msg in messages:
            name = "Bot" if msg['is_bot'] else msg.get('username', 'User')
            lines.append(f"{name}: {msg['content']}")
        
        return "\n".join(lines)

    def get_channel_messages(self, channel_id, limit=6):
        """Get recent messages for a specific channel."""
        self.prune()
        if channel_id not in self.threads:
            return []
        return copy.deepcopy(self.threads[channel_id][-limit:])
    
    def wants_dashboard(self, content):
        """
        Check if message implies user wants dashboard/info
        """
        content_lower = content.lower()
        
        # Un-match explicit questions that use "hva er" unless they specifically ask for weather/status
        if re.search(r'\bhva er\b', content_lower) and not re.search(r'\b(været|status|værmelding)\b', content_lower):
            return False

        # Extract precise words to prevent substring matching (e.g. "værnes" matching "vær")
        words = set(re.findall(r'\b\w+\b', content_lower))
        
        for keyword in self.DASHBOARD_KEYWORDS:
            if ' ' in keyword:
                if keyword in content_lower:
                    return True
            else:
                if keyword in words:
                    return True
        
        return False
    
    def is_small_talk(self, content):
        """
        Check if message is small talk (not requesting info)
        """
        # If it explicitly asks for info, it's not small talk
        if self.wants_dashboard(content):
            return False
        
        content_lower = content.lower().strip()
        
        # Check against small talk patterns
        for pattern in self.SMALL_TALK_PATTERNS:
            if re.search(pattern, content_lower):
                return True
        
        # Short greetings
        if len(content_lower) < 15:
            if any(word in content_lower for word in ['hei', 'hallo', 'halla', 'morn', 'kveld']):
                return True
        
        return False
    
    def should_show_dashboard(self, content, channel_id):
        """
        Determine if we should show dashboard or just chat
        
        Returns:
            (show_dashboard, reason)
        """
        # If they explicitly ask for info, always show
        if self.wants_dashboard(content):
            return True, "explicit_request"
        
        # If it's small talk, don't show
        if self.is_small_talk(content):
            return False, "small_talk"
        
        # If there's been recent conversation, continue chatting
        if channel_id in self.threads:
            recent_msgs = [m for m in self.threads[channel_id] 
                          if not m['is_bot'] and 
                          m['timestamp'] > self.wall() - timedelta(minutes=10)]
            if len(recent_msgs) > 1:
                return False, "ongoing_conversation"
        
        # Default: chat instead of showing dashboard
        return False, "default"
    
    def get_conversation_summary(self, channel_id, *, user_id=None):
        """
        Get a summary of what was discussed recently
        """
        self.prune()
        if channel_id not in self.threads:
            return None
        
        # Get last few user messages
        user_msgs = [m for m in self.threads[channel_id] if not m['is_bot'] and
            (user_id is None or str(m['user_id']) == str(user_id))][-3:]
        
        if not user_msgs:
            return None
        
        topics = []
        for msg in user_msgs:
            content = msg['content'].lower()
            # Extract potential topics (nouns, proper nouns)
            # This is simplified - could use NLP
            if 'rbk' in content or 'rosenborg' in content:
                topics.append('RBK')
            if 'vær' in content:
                topics.append('været')
            if 'kalender' in content or 'plan' in content:
                topics.append('planer')
        
        return list(set(topics)) if topics else None


# Singleton
_context_manager = None

def get_context_manager():
    """Get or create singleton ConversationContext instance"""
    global _context_manager
    if _context_manager is None:
        _context_manager = ConversationContext()
    return _context_manager


if __name__ == "__main__":
    ctx = ConversationContext()
    
    test_messages = [
        ("Hei!", "small_talk"),
        ("Hvordan går det?", "small_talk"),
        ("Hva er været i dag?", "dashboard"),
        ("Vis meg kalenderen", "dashboard"),
        ("Hva synes du om RBK?", "small_talk"),
        ("Takk for hjelpen!", "small_talk"),
    ]
    
    print("Intent detection tests:")
    for msg, expected in test_messages:
        is_small = ctx.is_small_talk(msg)
        wants_dash = ctx.wants_dashboard(msg)
        result = "small_talk" if is_small else ("dashboard" if wants_dash else "other")
        status = "✓" if result == expected else "✗"
        print(f"{status} '{msg}' -> {result} (expected: {expected})")
