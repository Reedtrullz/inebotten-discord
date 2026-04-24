#!/usr/bin/env python3
"""
ProfileHandler - Handles commands for managing Inebotten's own Discord profile.
"""

import aiohttp
import discord
from typing import Dict, Any
from features.base_handler import BaseHandler

class ProfileHandler(BaseHandler):
    """Handler for profile management commands"""

    def __init__(self, monitor):
        super().__init__(monitor)
        self.client = monitor.client
        self.token = monitor.client.config.DISCORD_TOKEN

    async def handle_status(self, message, status: str) -> None:
        """
        Change Inebotten's online status.
        Args:
            message: Discord message
            status: online, idle, dnd, invisible
        """
        status_map = {
            "online": discord.Status.online,
            "idle": discord.Status.idle,
            "dnd": discord.Status.dnd,
            "invisible": discord.Status.invisible,
            "offline": discord.Status.offline
        }
        
        target_status = status_map.get(status.lower())
        if not target_status:
            await self.send_response(message, "⚠️ Ugyldig status. Bruk: online, idle, dnd, eller invisible.")
            return

        try:
            await self.client.change_presence(status=target_status)
            await self.send_response(message, f"✅ Status endret til **{status}**.")
        except Exception as e:
            self.log(f"Error changing status: {e}")
            await self.send_response(message, "❌ Kunne ikke endre status.")

    async def handle_activity(self, message, activity_type: str, text: str) -> None:
        """
        Change Inebotten's custom activity.
        Args:
            message: Discord message
            activity_type: playing, watching, listening, competing
            text: Activity description
        """
        type_map = {
            "playing": discord.ActivityType.playing,
            "watching": discord.ActivityType.watching,
            "listening": discord.ActivityType.listening,
            "competing": discord.ActivityType.competing
        }
        
        target_type = type_map.get(activity_type.lower())
        if not target_type:
            await self.send_response(message, "⚠️ Ugyldig aktivitetstype. Bruk: playing, watching, listening, eller competing.")
            return

        try:
            activity = discord.Activity(type=target_type, name=text)
            await self.client.change_presence(activity=activity)
            await self.send_response(message, f"✅ Aktivitet endret til: **{activity_type} {text}**")
        except Exception as e:
            self.log(f"Error changing activity: {e}")
            await self.send_response(message, "❌ Kunne ikke endre aktivitet.")

    async def handle_bio(self, message, bio_text: str) -> None:
        """
        Update Inebotten's "About Me" (bio) section.
        Since discord.py doesn't officially support bio editing, we use a direct API call.
        """
        if not self.token:
            await self.send_response(message, "❌ Fant ikke Discord-token for API-kall.")
            return

        url = "https://discord.com/api/v9/users/@me"
        headers = {
            "Authorization": self.token,
            "Content-Type": "application/json"
        }
        payload = {"bio": bio_text}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(url, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        await self.send_response(message, "✅ Bio (About Me) er oppdatert!")
                    else:
                        data = await resp.json()
                        error_msg = data.get("message", "Ukjent feil")
                        self.log(f"API Error updating bio: {resp.status} - {error_msg}")
                        await self.send_response(message, f"❌ Kunne ikke oppdatere bio: {error_msg}")
        except Exception as e:
            self.log(f"Error updating bio: {e}")
            await self.send_response(message, "❌ En teknisk feil oppstod under oppdatering av bio.")

    async def handle_profile_command(self, message) -> bool:
        """
        Main entry point for profile commands.
        Returns True if a command was handled.
        """
        content = message.content.lower()
        
        # Status command: "status online", "status dnd", etc.
        if "status" in content:
            for s in ["online", "idle", "dnd", "invisible", "offline"]:
                if s in content:
                    await self.handle_status(message, s)
                    return True
        
        # Bio command: "bio [text]" or "about me [text]"
        if content.startswith("bio") or "endre bio" in content:
            new_bio = message.content.split("bio", 1)[1].strip()
            if not new_bio:
                await self.send_response(message, "⚠️ Vennligst skriv inn teksten du vil ha i bioen din.")
            else:
                await self.handle_bio(message, new_bio)
            return True
            
        # Activity command: "spiller [x]", "ser på [x]", etc.
        if "spiller" in content or "playing" in content:
            text = message.content.split(None, 2)[-1]
            await self.handle_activity(message, "playing", text)
            return True
        if "ser på" in content or "watching" in content:
            text = message.content.split("på", 1)[-1].strip()
            await self.handle_activity(message, "watching", text)
            return True
            
        return False
