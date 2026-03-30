#!/usr/bin/env python3
"""
Conversation Context Manager for Inebotten
Maintains conversation threads and detects intent
"""

import re
from collections import defaultdict
from datetime import datetime, timedelta


class ConversationContext:
    """
    Manages conversation history and intent detection
    """
    
    # Keywords that indicate user wants dashboard/info
    DASHBOARD_KEYWORDS = [
        'vær', 'været', 'weather',
        'kalender', 'calendar', 'plan',
        'hva skjer', 'hva skal', 'hva har jeg',
        'oversikt', 'status', 'dashboard',
        'påminnelse', 'huskeliste', 'gjøremål',
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
    ]
    
    def __init__(self, max_history=10, expiry_minutes=30):
        self.max_history = max_history
        self.expiry_minutes = expiry_minutes
        self.threads = defaultdict(list)  # channel_id -> messages
        self.last_bot_message = {}  # channel_id -> timestamp
    
    def add_message(self, channel_id, user_id, username, content, is_bot=False):
        """
        Add a message to the conversation thread
        """
        # Clean old messages first
        self._clean_old_messages(channel_id)
        
        entry = {
            'user_id': user_id,
            'username': username,
            'content': content,
            'is_bot': is_bot,
            'timestamp': datetime.now(),
        }
        
        self.threads[channel_id].append(entry)
        
        # Keep only last N messages
        if len(self.threads[channel_id]) > self.max_history:
            self.threads[channel_id] = self.threads[channel_id][-self.max_history:]
        
        if is_bot:
            self.last_bot_message[channel_id] = datetime.now()
    
    def _clean_old_messages(self, channel_id):
        """Remove messages older than expiry time"""
        cutoff = datetime.now() - timedelta(minutes=self.expiry_minutes)
        if channel_id in self.threads:
            self.threads[channel_id] = [
                m for m in self.threads[channel_id]
                if m['timestamp'] > cutoff
            ]
    
    def get_context(self, channel_id, limit=5):
        """
        Get recent conversation context as formatted string
        """
        if channel_id not in self.threads:
            return ""
        
        messages = self.threads[channel_id][-limit:]
        lines = []
        
        for msg in messages:
            name = "Bot" if msg['is_bot'] else msg.get('username', 'User')
            lines.append(f"{name}: {msg['content']}")
        
        return "\n".join(lines)
    
    def wants_dashboard(self, content):
        """
        Check if message implies user wants dashboard/info
        """
        content_lower = content.lower()
        
        for keyword in self.DASHBOARD_KEYWORDS:
            if keyword in content_lower:
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
                          m['timestamp'] > datetime.now() - timedelta(minutes=10)]
            if len(recent_msgs) > 1:
                return False, "ongoing_conversation"
        
        # Default: show dashboard for unknown intent (backwards compatible)
        return True, "default"
    
    def get_conversation_summary(self, channel_id):
        """
        Get a summary of what was discussed recently
        """
        if channel_id not in self.threads:
            return None
        
        # Get last few user messages
        user_msgs = [m for m in self.threads[channel_id] if not m['is_bot']][-3:]
        
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
