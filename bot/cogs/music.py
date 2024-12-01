import discord
from discord.ext import commands
import yt_dlp
import asyncio
import logging
import re
from datetime import datetime
from web.models import Session, TrackHistory, PlayCount
import os
import ssl

logger = logging.getLogger('discord')

# Create a cache directory for yt-dlp
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'cache')
os.makedirs(CACHE_DIR, exist_ok=True)

# yt-dlp Configuration
YTDL_OPTS = {
    'format': 'bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
    'outtmpl': os.path.join(CACHE_DIR, '%(extractor)s-%(id)s-%(title)s.%(ext)s'),
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'http-chunk-size': 10485760,
    'retries': 10,
    'fragment-retries': 10,
    'skip-unavailable-fragments': True,
    'extract-audio': True,
    'audio-quality': 0,
    'geo-bypass': True,
    'cachedir': CACHE_DIR,
    'no_check_certificates': True,
    'legacy_server_connect': True
}

# Add SSL context configuration
ssl._create_default_https_context = ssl._create_unverified_context

# FFmpeg options
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -b:a 192k'
}

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.duration = data.get('duration')
        self.thumbnail = data.get('thumbnail')
        self.webpage_url = data.get('webpage_url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        ytdl = yt_dlp.YoutubeDL(YTDL_OPTS)
        
        try:
            # If the URL doesn't start with http(s), assume it's a search query
            if not re.match(r'^https?://', url):
                url = f'ytsearch:{url}'

            logger.info(f"Extracting info for: {url}")
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
            
            if data is None:
                raise Exception("Could not extract video information")
            
            if 'entries' in data:
                # Take first item from a playlist or search results
                data = data['entries'][0]
            
            if stream:
                # Get the best audio-only format
                formats = data.get('formats', [])
                audio_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
                if audio_formats:
                    # Sort by quality (bitrate)
                    best_audio = max(audio_formats, key=lambda f: f.get('abr', 0))
                    data['url'] = best_audio['url']
                elif formats:
                    # If no audio-only format, use the best format available
                    data['url'] = formats[-1]['url']
            
            if 'url' not in data:
                raise Exception("Could not find audio URL in extracted data")

            filename = data['url'] if stream else ytdl.prepare_filename(data)
            logger.info(f"Playing audio from: {filename}")
            
            return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)
            
        except Exception as e:
            logger.error(f"Error in YTDLSource.from_url: {str(e)}")
            logger.error(f"URL attempted: {url}")
            if 'data' in locals() and data:
                logger.error(f"Extracted data: {data}")
            raise

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_session = None
        self.players = {}
        self.music_queues = {}  # Guild-specific music queues
        self.play_history = {}  # Guild-specific play history
        self.current_tracks = {}  # Currently playing tracks
        self.start_times = {}  # Track start times

    async def cog_load(self):
        # Initialize database session
        from web.models import Session
        self.db_session = Session()

    async def cog_unload(self):
        # Cleanup database session
        if self.db_session:
            self.db_session.close()

    def get_guild_data(self, guild_id):
        """Get or create guild-specific music data."""
        if guild_id not in self.music_queues:
            self.music_queues[guild_id] = []
        if guild_id not in self.play_history:
            self.play_history[guild_id] = []
        return {
            'queue': self.music_queues[guild_id],
            'history': self.play_history[guild_id],
            'current': self.current_tracks.get(guild_id),
            'start_time': self.start_times.get(guild_id)
        }

    async def cleanup(self, guild):
        """Disconnect and cleanup the player."""
        try:
            await guild.voice_client.disconnect()
        except:
            pass

        try:
            del self.players[guild.id]
            del self.music_queues[guild.id]
            del self.current_tracks[guild.id]
            del self.start_times[guild.id]
        except:
            pass

    async def play_track(self, ctx, player):
        try:
            # Update current track information
            self.current_tracks[ctx.guild.id] = {
                'title': player.title,
                'url': player.webpage_url,
                'duration': player.duration,
                'thumbnail': player.thumbnail,
                'requested_by': str(ctx.author),
                'guild_id': str(ctx.guild.id)
            }
            self.start_times[ctx.guild.id] = datetime.now()
            
            # Set initial volume
            player.volume = 1.0
            
            # Start playing the track first to avoid delays
            ctx.voice_client.play(player, after=lambda e: self.bot.loop.create_task(self.after_playing(ctx, e)))
            
            # Create TrackHistory entry
            try:
                track_history = TrackHistory(
                    track_title=player.title,
                    track_url=player.webpage_url,
                    user_id=str(ctx.author.id),
                    guild_id=str(ctx.guild.id),
                    started_at=datetime.now(),
                    track_metadata={
                        'duration': player.duration,
                        'thumbnail': player.thumbnail,
                        'uploader': player.uploader
                    }
                )
                
                # Use the session from the cog instance
                self.db_session.add(track_history)
                self.db_session.commit()
            except Exception as db_error:
                logger.error(f"Database error while saving track history: {str(db_error)}")
                if self.db_session:
                    self.db_session.rollback()
            
            # Let the display cog handle the now playing message
            
        except Exception as e:
            logger.error(f"Error playing track: {str(e)}")
            await ctx.send(f'An error occurred while playing the track: {str(e)}')
            if self.db_session:
                self.db_session.rollback()

    async def after_playing(self, ctx, error):
        """Callback for when a track finishes playing."""
        if error:
            await ctx.send(f'An error occurred while playing: {str(error)}')
        
        # Clear current track data
        self.current_tracks.pop(ctx.guild.id, None)
        self.start_times.pop(ctx.guild.id, None)
        
        # Play next track if available
        if ctx.guild.id in self.music_queues and self.music_queues[ctx.guild.id]:
            next_track = self.music_queues[ctx.guild.id].pop(0)
            await self.play_track(ctx, next_track)

    async def ensure_voice(self, ctx):
        """Ensure bot and user are in a voice channel."""
        if not ctx.author.voice:
            await ctx.send("You must be in a voice channel to use music commands!")
            return False

        if not ctx.voice_client:
            try:
                await ctx.author.voice.channel.connect()
            except Exception as e:
                logger.error(f"Error connecting to voice channel: {e}")
                await ctx.send("Error connecting to voice channel. Please try again.")
                return False
        return True

    @commands.command(name='play')
    async def play(self, ctx, *, query):
        """Plays a song from YouTube."""
        try:
            await self.ensure_voice(ctx)
            
            async with ctx.typing():
                try:
                    source = await YTDLSource.from_url(query, loop=self.bot.loop)
                    if not source:
                        await ctx.send("❌ Could not find any matching songs.")
                        return
                        
                    if not ctx.voice_client.is_playing():
                        await self.play_track(ctx, source)
                    else:
                        # Add to queue
                        self.music_queues[ctx.guild.id].append(source)
                        await ctx.send(f'Added to queue: {source.title}')
                        
                except Exception as e:
                    logger.error(f"Error processing YouTube URL: {str(e)}")
                    await ctx.send(f"❌ Error: Could not process the song. {str(e)}")
                    return
                    
        except Exception as e:
            logger.error(f"Error in play command: {str(e)}")
            await ctx.send(f"❌ An error occurred: {str(e)}")

    @commands.command(name='pause')
    async def pause(self, ctx):
        """Pause the currently playing song."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send(" Paused the current track.")
        else:
            await ctx.send("Nothing is playing right now.")

    @commands.command(name='resume')
    async def resume(self, ctx):
        """Resume the currently paused song."""
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send(" Resumed the current track.")
        else:
            await ctx.send("Nothing is paused right now.")

    @commands.command(name='stop')
    async def stop(self, ctx):
        """Stop playing and clear the queue."""
        if ctx.voice_client:
            await self.cleanup(ctx.guild)
            await ctx.send(" Stopped the music and cleared the queue.")
        else:
            await ctx.send("Nothing is playing right now.")

    @commands.command(name='volume')
    async def volume(self, ctx, volume: int = None):
        """Change the player's volume."""
        if not ctx.voice_client:
            return await ctx.send("Not connected to a voice channel.")

        if volume is None:
            return await ctx.send(f" Current volume: {int(ctx.voice_client.source.volume * 100)}%")

        if not 0 <= volume <= 200:
            return await ctx.send("Volume must be between 0 and 200.")

        if ctx.voice_client.source:
            ctx.voice_client.source.volume = volume / 100

        await ctx.send(f" Volume set to {volume}%")

    @commands.command(name='nowplaying', aliases=['np'])
    async def nowplaying(self, ctx):
        """Show information about the currently playing song."""
        if not ctx.voice_client or not ctx.voice_client.source:
            return await ctx.send("Nothing is playing right now.")

        source = ctx.voice_client.source
        embed = discord.Embed(
            title="Now Playing",
            description=f" {source.title}",
            color=discord.Color.blue(),
            url=source.webpage_url if hasattr(source, 'webpage_url') else None
        )
        await ctx.send(embed=embed)

    @commands.command(name='queue', aliases=['q'])
    async def queue(self, ctx):
        """Show the current queue."""
        guild_data = self.get_guild_data(ctx.guild.id)
        
        if not guild_data['current'] and not guild_data['queue']:
            return await ctx.send("No tracks in queue.")

        embed = discord.Embed(title="Music Queue", color=discord.Color.blue())
        
        # Current track
        if guild_data['current']:
            current = guild_data['current']
            duration = str(datetime.fromtimestamp(current['duration']).strftime('%M:%S')) if current.get('duration') else 'Unknown'
            elapsed = (datetime.now() - guild_data['start_time']).total_seconds() if guild_data['start_time'] else 0
            elapsed_str = str(datetime.fromtimestamp(elapsed).strftime('%M:%S'))
            
            embed.add_field(
                name="Now Playing",
                value=f"[{current['title']}]({current['url']})\n`{elapsed_str}/{duration}` | Requested by: {current['requested_by']}",
                inline=False
            )

        # Queue
        if guild_data['queue']:
            queue_list = []
            for i, track in enumerate(guild_data['queue'], 1):
                source = await YTDLSource.from_url(track['url'], loop=self.bot.loop)
                duration = str(datetime.fromtimestamp(source.duration).strftime('%M:%S')) if source.duration else 'Unknown'
                queue_list.append(f"`{i}.` [{source.title}]({track['url']}) | `{duration}` | Requested by: {track['requested_by']}")
            
            embed.add_field(
                name="Up Next",
                value="\n".join(queue_list[:10]) + (f"\n... and {len(guild_data['queue']) - 10} more" if len(guild_data['queue']) > 10 else ""),
                inline=False
            )

        await ctx.send(embed=embed)

    @commands.command(name='history')
    async def history(self, ctx):
        """Show recently played tracks."""
        guild_data = self.get_guild_data(ctx.guild.id)
        
        if not guild_data['history']:
            return await ctx.send("No track history available.")

        embed = discord.Embed(title="Recently Played Tracks", color=discord.Color.purple())
        
        history_list = []
        for i, entry in enumerate(guild_data['history'][:10], 1):
            track = entry['track']
            played_at = entry['played_at'].strftime('%H:%M:%S')
            history_list.append(f"`{i}.` [{track['title']}]({track['url']}) | Played at: {played_at}")
        
        embed.description = "\n".join(history_list)
        await ctx.send(embed=embed)

    @commands.command(name='disconnect', aliases=['leave'])
    async def disconnect(self, ctx):
        """Disconnect the bot from the voice channel."""
        if not ctx.voice_client:
            return await ctx.send("Not connected to a voice channel.")

        await self.cleanup(ctx.guild)
        await ctx.send(" Disconnected from voice channel.")

    @commands.command(name='skip')
    async def skip(self, ctx):
        """Skip the current song."""
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            return await ctx.send("Nothing is playing right now.")
            
        ctx.voice_client.stop()
        await ctx.send("⏭️ Skipped the current track.")

async def setup(bot):
    await bot.add_cog(Music(bot))
