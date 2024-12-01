import os
from dotenv import load_dotenv

load_dotenv()

# Bot Configuration
BOT_TOKEN = os.getenv('DISCORD_TOKEN')
COMMAND_PREFIX = '!'

# Web Dashboard Configuration
WEB_HOST = '0.0.0.0'
WEB_PORT = 5000

# Logging Configuration
LOG_LEVEL = 'INFO'
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

# Music Configuration
DEFAULT_VOLUME = 100
MAX_VOLUME = 200
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}
