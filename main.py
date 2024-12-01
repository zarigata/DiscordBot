import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import logging
import colorlog
from datetime import datetime
from web.dashboard import setup_dashboard, run_dashboard, app

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

@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user}')

async def load_cogs():
    """Load all cogs"""
    for filename in os.listdir('./bot/cogs'):
        if filename.endswith('.py'):
            try:
                await bot.load_extension(f'bot.cogs.{filename[:-3]}')
                print(f'Loaded {filename}')
            except Exception as e:
                print(f'Failed to load {filename}: {str(e)}')

async def main():
    """Main function to start the bot and web dashboard."""
    try:
        # Load cogs first
        await load_cogs()
        
        # Start the bot
        bot.start_time = datetime.now()
        await bot.start(TOKEN)
        
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        raise

if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('bot.log')
        ]
    )
    
    # Initialize Flask dashboard
    setup_dashboard(bot)
    
    # Run the dashboard in a separate thread
    from threading import Thread
    dashboard_thread = Thread(target=run_dashboard, daemon=True)
    dashboard_thread.start()
    
    # Run the bot
    import asyncio
    asyncio.run(main())
