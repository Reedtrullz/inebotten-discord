#!/usr/bin/env python3
"""
Simple Discord Selfbot for @inebotten
Catches mentions in real channels/text
"""

import os
import sys
from pathlib import Path

import discord
from discord.ext import commands

dir_path = os.path.dirname(os.path.realpath(__file__))
hermes_root = f"{dir_path}/../../.."

intents = discord.Intents.default()
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f"{'*' * 40}\nLogged in as {bot.user.name}#{bot.user.discriminator}\n- User ID: {bot.user.id}\n{Path(__file__).resolve().parent}\n{'*' * 40}")
@bot.command()
async def test(ctx):
    await ctx.send(f"This is a test message from the selfbot! {ctx.author.mention}")

def main():
    os.environ['DISCORD_BOT_TOKEN'] = "your_discord_bot_token_here"
    
    try:
        bot.run(os.getenv('DISCORD_BOT_TOKEN'))
    except Exception as e:
        print(f"Failed to load modules: {e}")
        import traceback
        traceback.print_exc()
    
if __name__ == "__main__":
    main()
