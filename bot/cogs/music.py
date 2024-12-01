import discord
from discord.ext import commands
import yt_dlp
import asyncio
import logging
from discord.ui import Button, View
import re
from datetime import datetime

logger = logging.getLogger(__name__)

# YouTube DL options
YTDL_SEARCH_OPTS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch5',  # Get top 5 results
    'source_address': '0.0.0.0',
}

YTDL_DOWNLOAD_OPTS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'quiet': True,
    'no_warnings': True,
    'source_address': '0.0.0.0',
}

ytdl_search = yt_dlp.YoutubeDL(YTDL_SEARCH_OPTS)
ytdl_download = yt_dlp.YoutubeDL(YTDL_DOWNLOAD_OPTS)

class SearchResultView(View):
    def __init__(self, cog, search_results):
        super().__init__(timeout=60.0)  # 60 second timeout
        self.cog = cog
        self.search_results = search_results
        
        # Add selection buttons for each result
        for i, result in enumerate(search_results, 1):
            duration_str = self.format_duration(result.get('duration', 0))
            button = Button(
                style=discord.ButtonStyle.primary,
                label=f"{i}",
                custom_id=f"select_{i-1}",
                row=0
            )
            button.callback = self.create_callback(i-1)
            self.add_item(button)
            
        # Add cancel button
        cancel_button = Button(
            style=discord.ButtonStyle.danger,
            label="Cancel",
            custom_id="cancel",
            row=1
        )
        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)
        
    def format_duration(self, duration):
        if not duration:
            return "Unknown"
        minutes = int(duration / 60)
        seconds = duration % 60
        return f"{minutes:02d}:{seconds:02d}"
        
    def create_callback(self, index):
        async def callback(interaction):
            if interaction.user.id != self.cog.last_search_user.id:
                await interaction.response.send_message("This is not your search result!", ephemeral=True)
                return
                
            selected = self.search_results[index]
            await interaction.response.defer()
            await self.cog.play_from_search_result(interaction, selected)
            self.stop()
            
        return callback
        
    async def cancel_callback(self, interaction):
        if interaction.user.id != self.cog.last_search_user.id:
            await interaction.response.send_message("This is not your search result!", ephemeral=True)
            return
            
        await interaction.message.delete()
        self.stop()

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_states = {}
        self.last_search_user = None
        self.filters = {
            'bass_boost': {
                'bass': '+5dB'
            },
            'long_drive': {
                'bass': '-5dB',
                'treble': '-5dB'
            },
            'vaporwave': {
                'tempo': '0.80',
                'pitch': '0.84'
            },
            'highcore': {
                'tempo': '1.10',
                'pitch': '1.15'
            },
            'drugs': {
                'combined': 'tremolo=f=5:d=0.9,flanger=delay=0:depth=2:speed=0.5:width=71:regen=10,chorus=0.5:0.9:50|60:0.4|0.32:0.25|0.4:2'
            }
        }
        self.current_tracks = {}
        self.db_session = None
        self.players = {}
        self.music_queues = {}  # Guild-specific music queues
        self.play_history = {}  # Guild-specific play history
        self.start_times = {}  # Track start times

    async def search_youtube(self, query):
        """Search YouTube and return top 5 results"""
        try:
            data = await self.bot.loop.run_in_executor(
                None,
                lambda: ytdl_search.extract_info(query, download=False)
            )
            
            if 'entries' not in data:
                return []
                
            return data['entries'][:5]  # Return top 5 results
            
        except Exception as e:
            logger.error(f"Error searching YouTube: {str(e)}")
            return []

    async def play_from_search_result(self, interaction, video_data):
        """Play the selected search result"""
        ctx = await self.bot.get_context(interaction.message)
        
        try:
            # Get player for the selected video
            url = video_data.get('webpage_url', video_data.get('url'))
            player = await YTDLSource.from_url(url, loop=self.bot.loop)
            
            if ctx.voice_client.is_playing():
                ctx.voice_client.stop()
            
            # Play the song
            ctx.voice_client.play(player, after=lambda e: self.bot.loop.call_soon_threadsafe(
                lambda: asyncio.run_coroutine_threadsafe(self.after_playing(ctx, e), self.bot.loop)
            ))
            
            # Create embed
            embed = discord.Embed(title="Now Playing 🎵", color=discord.Color.blue())
            embed.add_field(name="Track", value=player.title, inline=False)
            if player.duration:
                minutes = int(player.duration / 60)
                seconds = player.duration % 60
                embed.add_field(name="Duration", value=f"{minutes:02d}:{seconds:02d}")
            embed.add_field(name="Requested by", value=interaction.user.name)
            
            if player.thumbnail:
                embed.set_thumbnail(url=player.thumbnail)
            
            # Store current track info
            self.current_tracks[ctx.guild.id] = {
                'title': player.title,
                'url': player.url,
                'duration': player.duration,
                'thumbnail': player.thumbnail,
                'requested_by': interaction.user.name
            }
            
            # Delete search results message
            await interaction.message.delete()
            
            # Send now playing message with view
            view = MusicPlayerView(self)
            await ctx.send(embed=embed, view=view)
            
        except Exception as e:
            await ctx.send(f'An error occurred: {str(e)}')

    @commands.command(name='play', aliases=['p'])
    async def play(self, ctx: commands.Context, *, query: str):
        """Search and play a song"""
        try:
            await self.ensure_voice(ctx)
            self.last_search_user = ctx.author
            
            # If it's a direct URL, play it immediately
            if re.match(r'^https?://', query):
                async with ctx.typing():
                    player = await YTDLSource.from_url(query, loop=self.bot.loop)
                    if ctx.voice_client.is_playing():
                        ctx.voice_client.stop()
                    
                    ctx.voice_client.play(player, after=lambda e: self.bot.loop.call_soon_threadsafe(
                        lambda: asyncio.run_coroutine_threadsafe(self.after_playing(ctx, e), self.bot.loop)
                    ))
                    
                    embed = discord.Embed(title="Now Playing 🎵", color=discord.Color.blue())
                    embed.add_field(name="Track", value=player.title, inline=False)
                    if player.duration:
                        minutes = int(player.duration / 60)
                        seconds = player.duration % 60
                        embed.add_field(name="Duration", value=f"{minutes:02d}:{seconds:02d}")
                    embed.add_field(name="Requested by", value=ctx.author.name)
                    
                    if player.thumbnail:
                        embed.set_thumbnail(url=player.thumbnail)
                    
                    view = MusicPlayerView(self)
                    await ctx.send(embed=embed, view=view)
                return
            
            # Search YouTube
            async with ctx.typing():
                results = await self.search_youtube(query)
                
                if not results:
                    return await ctx.send("No results found.")
                
                # Create embed with search results
                embed = discord.Embed(
                    title="Search Results 🔍",
                    description="Select a track to play:",
                    color=discord.Color.blue()
                )
                
                for i, result in enumerate(results, 1):
                    duration = self.format_duration(result.get('duration', 0))
                    title = result.get('title', 'Unknown')
                    channel = result.get('channel', 'Unknown')
                    embed.add_field(
                        name=f"{i}. {title}",
                        value=f"Duration: {duration} | Channel: {channel}",
                        inline=False
                    )
                
                # Send results with selection buttons
                view = SearchResultView(self, results)
                await ctx.send(embed=embed, view=view)
                
        except Exception as e:
            await ctx.send(f'An error occurred: {str(e)}')
            
    def format_duration(self, duration):
        if not duration:
            return "Unknown"
        minutes = int(duration / 60)
        seconds = duration % 60
        return f"{minutes:02d}:{seconds:02d}"

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
            
            # Create embed message
            embed = discord.Embed(
                title="Now Playing 🎵",
                description=f"**[{player.title}]({player.webpage_url})**",
                color=discord.Color.purple()
            )
            
            # Add duration if available
            if player.duration:
                minutes, seconds = divmod(player.duration, 60)
                embed.add_field(
                    name="Duration",
                    value=f"{int(minutes)}:{int(seconds):02d}",
                    inline=True
                )
            
            # Add requester
            embed.add_field(
                name="Requested by",
                value=str(ctx.author),
                inline=True
            )
            
            # Add thumbnail if available
            if player.thumbnail:
                embed.set_thumbnail(url=player.thumbnail)
            
            # Set initial volume
            player.volume = 1.0
            
            # Start playing the track
            ctx.voice_client.play(player, after=lambda e: self.bot.loop.create_task(self.after_playing(ctx, e)))
            
            # Create and send the message with buttons
            view = MusicPlayerView(self)
            await ctx.send(embed=embed, view=view)
            
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
            
        except Exception as e:
            logger.error(f"Error playing track: {str(e)}")
            await ctx.send(f'An error occurred while playing the track: {str(e)}')
            if self.db_session:
                self.db_session.rollback()

    async def after_playing(self, ctx, error):
        """Callback for when a song finishes playing"""
        if error:
            await ctx.send(f'An error occurred: {str(error)}')
        
        # Play next song if available
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            
        try:
            # Get next song from queue
            async with ctx.typing():
                guild_data = self.get_guild_data(ctx.guild.id)
                if guild_data['queue']:
                    next_track = guild_data['queue'].pop(0)
                    ctx.voice_client.play(next_track, after=lambda e: self.bot.loop.call_soon_threadsafe(
                        lambda: asyncio.run_coroutine_threadsafe(self.after_playing(ctx, e), self.bot.loop)
                    ))
                    await ctx.send(f'Now playing: {next_track.title}')
                else:
                    # No more songs in queue
                    pass
        except Exception as e:
            await ctx.send(f'An error occurred: {str(e)}')

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

    async def get_youtube_info(self, url, loop=None):
        """Get YouTube video info with better error handling."""
        ydl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'force_generic_extractor': False,
            'cachedir': False,
            'default_search': 'ytsearch',
            'source_address': '0.0.0.0',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }

        try:
            # If the URL is not a valid YouTube URL, treat it as a search query
            if not ('youtube.com' in url or 'youtu.be' in url):
                url = f'ytsearch:{url}'

            loop = loop or asyncio.get_event_loop()
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                data = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                
                # Handle search results
                if 'entries' in data:
                    data = data['entries'][0]
                
                if not data:
                    raise ValueError("Could not find any matching videos")
                    
                return data
                
        except Exception as e:
            logger.error(f"Error extracting info: {str(e)}")
            if 'data' in locals() and 'entries' in locals():
                logger.error(f"Extracted data: {data}")
            raise ValueError(f"Could not process the song: {str(e)}")

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
        view = MusicPlayerView(self)
        await ctx.send(embed=embed, view=view)

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

    @commands.command(name='restart')
    async def _restart(self, ctx: commands.Context):
        """Restarts the current song from beginning"""
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            return await ctx.send('Nothing is playing right now.')
            
        # Store current track info
        current_source = ctx.voice_client.source
        if not hasattr(current_source, 'data'):
            return await ctx.send('Cannot restart this type of track.')

        # Stop current playback
        ctx.voice_client.stop()
        
        # Create new source from same URL
        try:
            source = await YTDLSource.from_url(current_source.data['webpage_url'], loop=self.bot.loop)
            ctx.voice_client.play(source, after=lambda e: self.bot.loop.call_soon_threadsafe(
                lambda: asyncio.run_coroutine_threadsafe(self.after_playing(ctx, e), self.bot.loop)
            ))
            await ctx.send('⏮️ Restarted the current song.')
        except Exception as e:
            await ctx.send(f'An error occurred: {str(e)}')

    @commands.command(name='filter')
    async def _filter(self, ctx: commands.Context, filter_name: str = None):
        """Apply an audio filter to the current song"""
        if not ctx.voice_client or not ctx.voice_client.source:
            return await ctx.send('Nothing is playing right now.')
            
        if not filter_name:
            return await ctx.send('Available filters: bass_boost, long_drive, vaporwave, highcore, drugs')
            
        if filter_name.lower() not in self.filters:
            return await ctx.send('Invalid filter. Available filters: bass_boost, long_drive, vaporwave, highcore, drugs')
            
        # Store current track info
        current_source = ctx.voice_client.source
        if not hasattr(current_source, 'data'):
            return await ctx.send('Cannot apply filter to this type of track.')
            
        # Stop current playback
        ctx.voice_client.stop()
        
        try:
            # Create new source with filter
            source = await YTDLSource.from_url(
                current_source.data['webpage_url'],
                loop=self.bot.loop,
                filter_options=self.filters[filter_name.lower()]
            )
            ctx.voice_client.play(source, after=lambda e: self.bot.loop.call_soon_threadsafe(
                lambda: asyncio.run_coroutine_threadsafe(self.after_playing(ctx, e), self.bot.loop)
            ))
            await ctx.send(f'🎛️ Applied filter: {filter_name}')
        except Exception as e:
            await ctx.send(f'An error occurred: {str(e)}')

async def setup(bot):
    await bot.add_cog(Music(bot))

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('webpage_url')
        self.duration = data.get('duration')
        self.thumbnail = data.get('thumbnail')
        
    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True, filter_options=None):
        loop = loop or asyncio.get_event_loop()
        
        # Base FFMPEG options
        ffmpeg_options = {
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            'options': '-vn'
        }
        
        # Add filter options if provided
        if filter_options:
            filter_string = []
            for effect, value in filter_options.items():
                if effect == 'bass':
                    filter_string.append(f"bass=g={value}")
                elif effect == 'treble':
                    filter_string.append(f"treble=g={value}")
                elif effect == 'tempo':
                    filter_string.append(f"atempo={value}")
                elif effect == 'pitch':
                    filter_string.append(f"asetrate=44100*{value},aresample=44100")
                elif effect == 'combined':
                    filter_string.append(value)
                    
            if filter_string:
                ffmpeg_options['options'] = f'-vn -af "{",".join(filter_string)}"'
                logger.info(f"Using FFmpeg filter: {ffmpeg_options['options']}")
        
        try:
            # Extract video info
            data = await loop.run_in_executor(None, lambda: ytdl_download.extract_info(url, download=not stream))
            
            if 'entries' in data:
                data = data['entries'][0]
                
            filename = data['url'] if stream else ytdl_download.prepare_filename(data)
            source = discord.FFmpegPCMAudio(filename, **ffmpeg_options)
            return cls(source, data=data)
            
        except Exception as e:
            logger.error(f"Error in YTDLSource.from_url: {str(e)}")
            logger.error(f"FFmpeg options: {ffmpeg_options}")
            raise

class MusicPlayerView(View):
    def __init__(self, cog):
        super().__init__(timeout=60.0)  # 60 second timeout
        self.cog = cog
        
        # Add buttons
        play_pause_button = Button(
            style=discord.ButtonStyle.success,
            label="Play/Pause",
            custom_id="play_pause",
            row=0
        )
        play_pause_button.callback = self.play_pause_callback
        self.add_item(play_pause_button)
        
        stop_button = Button(
            style=discord.ButtonStyle.danger,
            label="Stop",
            custom_id="stop",
            row=0
        )
        stop_button.callback = self.stop_callback
        self.add_item(stop_button)
        
        skip_button = Button(
            style=discord.ButtonStyle.primary,
            label="Skip",
            custom_id="skip",
            row=1
        )
        skip_button.callback = self.skip_callback
        self.add_item(skip_button)
        
        restart_button = Button(
            style=discord.ButtonStyle.primary,
            label="Restart",
            custom_id="restart",
            row=1
        )
        restart_button.callback = self.restart_callback
        self.add_item(restart_button)
        
        queue_button = Button(
            style=discord.ButtonStyle.primary,
            label="Queue",
            custom_id="queue",
            row=2
        )
        queue_button.callback = self.queue_callback
        self.add_item(queue_button)
        
        history_button = Button(
            style=discord.ButtonStyle.primary,
            label="History",
            custom_id="history",
            row=2
        )
        history_button.callback = self.history_callback
        self.add_item(history_button)
        
    async def play_pause_callback(self, interaction):
        ctx = await self.cog.bot.get_context(interaction.message)
        if ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await interaction.response.send_message(" Paused the current track.")
        elif ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await interaction.response.send_message(" Resumed the current track.")
        else:
            await interaction.response.send_message("Nothing is playing right now.")
            
    async def stop_callback(self, interaction):
        ctx = await self.cog.bot.get_context(interaction.message)
        if ctx.voice_client:
            await self.cog.cleanup(ctx.guild)
            await interaction.response.send_message(" Stopped the music and cleared the queue.")
        else:
            await interaction.response.send_message("Nothing is playing right now.")
            
    async def skip_callback(self, interaction):
        ctx = await self.cog.bot.get_context(interaction.message)
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            return await interaction.response.send_message("Nothing is playing right now.")
            
        ctx.voice_client.stop()
        await interaction.response.send_message("⏭️ Skipped the current track.")
        
    async def restart_callback(self, interaction):
        ctx = await self.cog.bot.get_context(interaction.message)
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            return await ctx.send('Nothing is playing right now.')
            
        # Store current track info
        current_source = ctx.voice_client.source
        if not hasattr(current_source, 'data'):
            return await ctx.send('Cannot restart this type of track.')

        # Stop current playback
        ctx.voice_client.stop()
        
        # Create new source from same URL
        try:
            source = await YTDLSource.from_url(current_source.data['webpage_url'], loop=self.cog.bot.loop)
            ctx.voice_client.play(source, after=lambda e: self.cog.bot.loop.call_soon_threadsafe(
                lambda: asyncio.run_coroutine_threadsafe(self.cog.after_playing(ctx, e), self.cog.bot.loop)
            ))
            await interaction.response.send_message('⏮️ Restarted the current song.')
        except Exception as e:
            await interaction.response.send_message(f'An error occurred: {str(e)}')
            
    async def queue_callback(self, interaction):
        ctx = await self.cog.bot.get_context(interaction.message)
        guild_data = self.cog.get_guild_data(ctx.guild.id)
        
        if not guild_data['current'] and not guild_data['queue']:
            return await interaction.response.send_message("No tracks in queue.")

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
                source = await YTDLSource.from_url(track['url'], loop=self.cog.bot.loop)
                duration = str(datetime.fromtimestamp(source.duration).strftime('%M:%S')) if source.duration else 'Unknown'
                queue_list.append(f"`{i}.` [{source.title}]({track['url']}) | `{duration}` | Requested by: {track['requested_by']}")
            
            embed.add_field(
                name="Up Next",
                value="\n".join(queue_list[:10]) + (f"\n... and {len(guild_data['queue']) - 10} more" if len(guild_data['queue']) > 10 else ""),
                inline=False
            )

        await interaction.response.send_message(embed=embed)
        
    async def history_callback(self, interaction):
        ctx = await self.cog.bot.get_context(interaction.message)
        guild_data = self.cog.get_guild_data(ctx.guild.id)
        
        if not guild_data['history']:
            return await interaction.response.send_message("No track history available.")

        embed = discord.Embed(title="Recently Played Tracks", color=discord.Color.purple())
        
        history_list = []
        for i, entry in enumerate(guild_data['history'][:10], 1):
            track = entry['track']
            played_at = entry['played_at'].strftime('%H:%M:%S')
            history_list.append(f"`{i}.` [{track['title']}]({track['url']}) | Played at: {played_at}")
        
        embed.description = "\n".join(history_list)
        await interaction.response.send_message(embed=embed)
