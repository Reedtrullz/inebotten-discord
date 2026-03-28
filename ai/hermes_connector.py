#!/usr/bin/env python3
"""
Hermes API Connector for Discord Selfbot
Handles communication with Hermes AI for intelligent responses
"""

import json
import asyncio
import aiohttp
from datetime import datetime
from urllib.parse import quote

class HermesConnector:
    """
    Connects to Hermes API for AI-powered response generation
    Uses GET /api/chat?data={payload}
    """
    
    def __init__(self, base_url="http://127.0.0.1:3000/api/chat"):
        self.base_url = base_url.rstrip('/')
        self.session = None
        self.request_count = 0
        self.error_count = 0
        self.last_error = None
    
    async def _get_session(self):
        """
        Get or create aiohttp session
        """
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={
                    'User-Agent': 'DiscordSelfbot/1.0 HermesConnector',
                    'Accept': 'application/json'
                }
            )
        return self.session
    
    async def close(self):
        """
        Close the HTTP session
        """
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None
    
    async def check_health(self):
        """
        Check if Hermes API is reachable
        Returns: (is_healthy, message)
        """
        try:
            session = await self._get_session()
            
            # Try a simple request to check connectivity
            # Some APIs have a status endpoint, others just need a test request
            test_payload = {
                "message": "health_check",
                "author_name": "selfbot",
                "channel_type": "health_check",
                "timestamp": datetime.now().isoformat(),
                "is_mention": False
            }
            
            url = f"{self.base_url}?data={quote(json.dumps(test_payload))}"
            
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                # Any response (even error) means the server is up
                return True, f"API reachable (status: {response.status})"
                
        except aiohttp.ClientConnectorError as e:
            return False, f"Cannot connect to Hermes API: {e}"
        except asyncio.TimeoutError:
            return False, "Connection timeout"
        except Exception as e:
            return False, f"Health check error: {e}"
    
    async def generate_response(self, message_content, author_name, channel_type, is_mention=True, system_prompt=None):
        """
        Send message to Hermes API and get AI-generated response
        
        Args:
            message_content: The message text
            author_name: Name of the message author
            channel_type: 'DM', 'GROUP_DM', or 'GUILD_TEXT'
            is_mention: Whether the bot was mentioned
            system_prompt: Optional custom system prompt for personality
        
        Returns:
            (success, response_text or error_message)
        """
        session = await self._get_session()
        
        # Build payload
        payload = {
            "message": message_content,
            "author_name": author_name,
            "channel_type": channel_type,
            "timestamp": datetime.now().isoformat(),
            "is_mention": is_mention
        }
        
        # Add system prompt if provided (for personality customization)
        if system_prompt:
            payload["system_prompt"] = system_prompt
        
        try:
            # Construct URL with encoded payload
            encoded_payload = quote(json.dumps(payload))
            url = f"{self.base_url}?data={encoded_payload}"
            
            self.request_count += 1
            
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                print(f"[HERMES] Bridge response status: {response.status}")
                if response.status == 200:
                    try:
                        data = await response.json()
                        print(f"[HERMES] Bridge returned data: {str(data)[:150]}...")
                        # Handle different response formats
                        if isinstance(data, dict):
                            if 'response' in data:
                                print(f"[HERMES] Using 'response' field: {data['response'][:80]}...")
                                return True, data['response']
                            elif 'message' in data:
                                return True, data['message']
                            elif 'content' in data:
                                return True, data['content']
                            else:
                                return True, str(data)
                        else:
                            return True, str(data)
                    except:
                        # Non-JSON response
                        text = await response.text()
                        return True, text
                
                elif response.status == 429:
                    self.error_count += 1
                    self.last_error = "Rate limited by Hermes API"
                    return False, "Hermes API rate limit hit"
                
                else:
                    self.error_count += 1
                    error_text = await response.text()
                    self.last_error = f"HTTP {response.status}: {error_text[:100]}"
                    return False, f"API error (status {response.status})"
                    
        except asyncio.TimeoutError:
            self.error_count += 1
            self.last_error = "Request timeout"
            return False, "Hermes API timeout (30s)"
        
        except aiohttp.ClientConnectorError as e:
            self.error_count += 1
            self.last_error = str(e)
            return False, f"Cannot connect to Hermes: {e}"
        
        except Exception as e:
            self.error_count += 1
            self.last_error = str(e)
            return False, f"Request error: {e}"
    
    async def generate_calendar_response(self, query, author_name):
        """
        Generate a calendar/almanac response specifically
        
        This is a convenience method that adds context to help Hermes
        understand this is a calendar/almanac request
        """
        enhanced_message = f"[Calendar/Almanac Query] {query}"
        return await self.generate_response(
            message_content=enhanced_message,
            author_name=author_name,
            channel_type='GROUP_DM',
            is_mention=True
        )
    
    def get_stats(self):
        """
        Get connector statistics
        """
        return {
            'requests': self.request_count,
            'errors': self.error_count,
            'success_rate': ((self.request_count - self.error_count) / max(1, self.request_count)) * 100,
            'last_error': self.last_error
        }

def create_hermes_connector(config):
    """
    Factory function to create HermesConnector from config
    """
    return HermesConnector(base_url=config.get_hermes_url())
