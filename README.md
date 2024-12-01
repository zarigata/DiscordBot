# Discord Music Bot with Web Interface

A feature-rich Discord music bot with a web dashboard for monitoring and control.

## Features
- Music playback from various sources (YouTube, Spotify, etc.)
- Queue management
- Real-time statistics
- Web dashboard
- Modular command system

## Requirements
- Python 3.8+
- FFmpeg
- Discord Bot Token
- YouTube API Key (optional)

## Installation
1. Install FFmpeg on your system
2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `config.example.py` to `config.py` and fill in your bot token
4. Run the bot:
   ```bash
   python main.py
   ```

## Project Structure
```
├── bot/
│   ├── cogs/           # Bot command modules
│   ├── utils/          # Utility functions
│   └── music/          # Music-related functionality
├── web/
│   ├── static/         # Static web files
│   └── templates/      # Web templates
├── config.py           # Configuration
└── main.py            # Main entry point
```
