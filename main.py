import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import logging
import colorlog
from datetime import datetime
from web.dashboard import app

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Configure logging
logger = logging.getLogger('discord')
logger.setLevel(logging.INFO)

handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    '%(log_color)s%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    log_colors={
        'DEBUG': 'cyan',
        'INFO': 'green',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'red,bg_white',
    }
))
logger.addHandler(handler)

# Create bot instance
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix='!', intents=intents)
bot.start_time = datetime.now()

@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user}')

async def load_cogs():
    """Load all cogs."""
    try:
        await bot.load_extension('bot.cogs.music')
        await bot.load_extension('bot.cogs.music_display')
        logger.info("Successfully loaded all cogs")
    except Exception as e:
        logger.error(f"Error loading cogs: {e}")

async def main():
    """Main function to start the bot and web dashboard."""
    await load_cogs()
    
    # Start Flask in a separate thread
    import threading
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000, use_reloader=False)).start()
    
    # Start the bot
    await bot.start(TOKEN)

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
