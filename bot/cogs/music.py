import discord
from discord.ext import commands
import yt_dlp
import asyncio
import logging
from discord.ui import Button, View
import re
from datetime import datetime
from ..utils.queue_manager import QueueManager

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
            'bass_boost': {'bass': '+5dB'},
            'long_drive': {'bass': '-5dB', 'treble': '-5dB'},
            'vaporwave': {'tempo': '0.80', 'pitch': '0.84'},
            'highcore': {'tempo': '1.10', 'pitch': '1.15'},
            'drugs': {'combined': 'tremolo=f=5:d=0.9,flanger=delay=0:depth=2:speed=0.5:width=71:regen=10,chorus=0.5:0.9:50|60:0.4|0.32:0.25|0.4:2'}
        }
        self.current_tracks = {}
        self.db_session = None
        self.players = {}
        self.queue_manager = QueueManager()
        self.start_times = {}

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
            # Add to queue instead of playing immediately
            self.queue_manager.add_to_queue(str(ctx.guild.id), video_data)
            
            if not ctx.voice_client or not ctx.voice_client.is_playing():
                # If nothing is playing, start playing
                await self._play_next(ctx)
            else:
                await interaction.response.send_message(f"Added to queue: {video_data['title']}")
                
        except Exception as e:
            logger.error(f"Error in play_from_search_result: {e}")
            await interaction.response.send_message(f"An error occurred: {str(e)}")

    async def _play_next(self, ctx):
        """Play the next track in queue"""
        try:
            next_track = self.queue_manager.get_next_track(str(ctx.guild.id))
            if next_track:
                player = await YTDLSource.from_url(next_track['webpage_url'], loop=self.bot.loop)
                await self.play_track(ctx, player)
        except Exception as e:
            logger.error(f"Error in _play_next: {e}")
            await ctx.send(f"An error occurred while playing next track: {str(e)}")

    async def after_playing(self, ctx, error):
        """Callback for when a song finishes playing"""
        if error:
            logger.error(f"Error in playback: {error}")
            await ctx.send(f"An error occurred during playback: {str(error)}")
        
        try:
            # Play next track in queue
            await self._play_next(ctx)
        except Exception as e:
            logger.error(f"Error in after_playing: {e}")

    @commands.command(name='play', aliases=['p'])
    async def play(self, ctx: commands.Context, *, query: str):
        """Search and play a song"""
        try:
            if not await self.ensure_voice(ctx):
                return
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
                    
                    embed = discord.Embed(title="Now Playing ", color=discord.Color.blue())
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
                    title="Search Results ",
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

    async def cleanup(self, guild):
        """Disconnect and cleanup the player."""
        try:
            await guild.voice_client.disconnect()
        except:
            pass

        try:
            del self.players[guild.id]
            del self.current_tracks[guild.id]
            del self.start_times[guild.id]
        except:
            pass

    async def play_track(self, ctx, player, *, filter_name=None):
        """Play a track and handle queue management"""
        try:
            if ctx.voice_client.is_playing():
                ctx.voice_client.stop()

            # If filter is specified, apply it
            if filter_name and filter_name in self.filters:
                player = await YTDLSource.from_url(
                    player.webpage_url,
                    loop=self.bot.loop,
                    stream=True,
                    filter_options=self.filters[filter_name]
                )

            # Update current track information
            self.current_tracks[ctx.guild.id] = {
                'title': player.title,
                'url': player.webpage_url,
                'duration': player.duration,
                'thumbnail': player.thumbnail,
                'requested_by': str(ctx.author),
                'guild_id': str(ctx.guild.id),
                'filter': filter_name
            }
            
            # Start playing the track
            ctx.voice_client.play(
                player,
                after=lambda e: self.bot.loop.create_task(self.after_playing(ctx, e))
            )
            
            # Create embed message
            embed = discord.Embed(
                title="Now Playing",
                description=f"**[{player.title}]({player.webpage_url})**",
                color=discord.Color.purple()
            )
            
            if player.duration:
                minutes, seconds = divmod(player.duration, 60)
                embed.add_field(
                    name="Duration",
                    value=f"{int(minutes)}:{int(seconds):02d}",
                    inline=True
                )

            if filter_name:
                embed.add_field(
                    name="Filter",
                    value=filter_name,
                    inline=True
                )
            
            if player.thumbnail:
                embed.set_thumbnail(url=player.thumbnail)
            
            # Send the message with player view
            view = MusicPlayerView(self)
            await ctx.send(embed=embed, view=view)
            
        except Exception as e:
            logger.error(f"Error playing track: {str(e)}")
            await ctx.send(f'An error occurred while playing the track: {str(e)}')

    @commands.command(name='queue')
    async def queue(self, ctx):
        """Show the current queue."""
        queue_list = self.queue_manager.get_queue(str(ctx.guild.id))
        
        if not queue_list:
            return await ctx.send("The queue is empty.")
            
        embed = discord.Embed(title="Current Queue", color=discord.Color.blue())
        
        for i, track in enumerate(queue_list, 1):
            duration = self.format_duration(track.get('duration', 0))
            embed.add_field(
                name=f"{i}. {track['title']}",
                value=f"Duration: {duration}",
                inline=False
            )
            
        await ctx.send(embed=embed)

    @commands.command(name='clear')
    async def clear(self, ctx):
        """Clear the queue."""
        self.queue_manager.clear_queue(str(ctx.guild.id))
        await ctx.send("Queue cleared.")

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
        await ctx.send(" Skipped the current track.")

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
            await ctx.send(' Restarted the current song.')
        except Exception as e:
            await ctx.send(f'An error occurred: {str(e)}')

    @commands.command(name='filter')
    async def _filter(self, ctx: commands.Context, filter_name: str = None):
        """Apply an audio filter to the current song"""
        try:
            if not ctx.voice_client or not ctx.voice_client.is_playing():
                return await ctx.send("Nothing is playing right now.")

            if not filter_name:
                available_filters = ", ".join(self.filters.keys())
                return await ctx.send(f"Available filters: {available_filters}")

            if filter_name not in self.filters:
                return await ctx.send(f"Filter '{filter_name}' not found.")

            # Get current track info before stopping
            current_track = self.current_tracks.get(ctx.guild.id)
            if not current_track:
                return await ctx.send("Cannot apply filter: no track information found.")

            # Stop current playback
            ctx.voice_client.stop()

            try:
                # Recreate the source with the new filter
                source = await YTDLSource.from_url(
                    current_track['url'],
                    loop=self.bot.loop,
                    stream=True,
                    filter_options=self.filters[filter_name]
                )

                # Update current track info with filter
                current_track['filter'] = filter_name
                self.current_tracks[ctx.guild.id] = current_track

                # Play with new filter
                ctx.voice_client.play(
                    source,
                    after=lambda e: self.bot.loop.create_task(self.after_playing(ctx, e))
                )

                await ctx.send(f'Applied filter: {filter_name}')

            except Exception as e:
                logger.error(f"Error applying filter: {str(e)}")
                # If filter fails, try to restore original playback
                try:
                    source = await YTDLSource.from_url(current_track['url'], loop=self.bot.loop)
                    ctx.voice_client.play(
                        source,
                        after=lambda e: self.bot.loop.create_task(self.after_playing(ctx, e))
                    )
                    await ctx.send(f"Error applying filter. Restored original playback.")
                except:
                    await ctx.send("Failed to restore playback. Please try playing the track again.")

        except Exception as e:
            await ctx.send(f'An error occurred: {str(e)}')

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

class MusicPlayerView(View):
    def __init__(self, cog):
        super().__init__(timeout=None)  # No timeout for music controls
        self.cog = cog
        
        # Add buttons
        play_pause_button = Button(
            style=discord.ButtonStyle.success,
            label="Play/Pause",
            custom_id="playpause"
        )
        play_pause_button.callback = self.play_pause_callback
        self.add_item(play_pause_button)

        skip_button = Button(
            style=discord.ButtonStyle.primary,
            label="Skip",
            custom_id="skip"
        )
        skip_button.callback = self.skip_callback
        self.add_item(skip_button)

        restart_button = Button(
            style=discord.ButtonStyle.primary,
            label="Restart",
            custom_id="restart"
        )
        restart_button.callback = self.restart_callback
        self.add_item(restart_button)

        filter_button = Button(
            style=discord.ButtonStyle.secondary,
            label="Vaporwave",
            custom_id="vaporwave"
        )
        filter_button.callback = self.filter_callback
        self.add_item(filter_button)

    async def filter_callback(self, interaction):
        try:
            ctx = await self.cog.bot.get_context(interaction.message)
            
            if not ctx.voice_client or not ctx.voice_client.is_playing():
                await interaction.response.send_message("Nothing is playing right now.")
                return

            # Get current track info
            current_track = self.cog.current_tracks.get(ctx.guild.id)
            if not current_track:
                await interaction.response.send_message("No track information found.")
                return

            # Defer the response since this might take a while
            await interaction.response.defer()

            # Stop current playback
            ctx.voice_client.stop()

            try:
                # Apply vaporwave filter
                source = await YTDLSource.from_url(
                    current_track['url'],
                    loop=self.cog.bot.loop,
                    stream=True,
                    filter_options=self.cog.filters['vaporwave']
                )

                # Update current track info
                current_track['filter'] = 'vaporwave'
                self.cog.current_tracks[ctx.guild.id] = current_track

                # Play with filter
                ctx.voice_client.play(
                    source,
                    after=lambda e: self.cog.bot.loop.create_task(self.cog.after_playing(ctx, e))
                )

                await interaction.followup.send("Applied vaporwave filter!")

            except Exception as e:
                logger.error(f"Error applying vaporwave filter: {str(e)}")
                # Try to restore original playback
                try:
                    source = await YTDLSource.from_url(current_track['url'], loop=self.cog.bot.loop)
                    ctx.voice_client.play(
                        source,
                        after=lambda e: self.cog.bot.loop.create_task(self.cog.after_playing(ctx, e))
                    )
                    await interaction.followup.send("Error applying filter. Restored original playback.")
                except:
                    await interaction.followup.send("Failed to restore playback. Please try playing the track again.")

        except Exception as e:
            logger.error(f"Error in filter_callback: {str(e)}")
            try:
                await interaction.followup.send(f"An error occurred: {str(e)}")
            except:
                pass

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
            
    async def skip_callback(self, interaction):
        ctx = await self.cog.bot.get_context(interaction.message)
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            return await interaction.response.send_message("Nothing is playing right now.")
            
        ctx.voice_client.stop()
        await interaction.response.send_message(" Skipped the current track.")
        
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
            await interaction.response.send_message(' Restarted the current song.')
        except Exception as e:
            await interaction.response.send_message(f'An error occurred: {str(e)}')
            
class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.webpage_url = data.get('webpage_url')  # Changed from url to webpage_url
        self.url = data.get('webpage_url')  # Keep url for backwards compatibility
        self.duration = data.get('duration')
        self.thumbnail = data.get('thumbnail')
        self.uploader = data.get('uploader')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True, filter_options=None):
        loop = loop or asyncio.get_event_loop()
        
        # Enhanced FFMPEG options
        ffmpeg_options = {
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -analyzeduration 0 -loglevel 0',
            'options': '-vn -b:a 192k'  # Set audio bitrate to 192k
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
                ffmpeg_options['options'] = f'-vn -b:a 192k -af "{",".join(filter_string)}"'
                logger.info(f"Using FFmpeg filter: {ffmpeg_options['options']}")
        
        try:
            # Extract video info with better error handling
            data = await loop.run_in_executor(None, lambda: ytdl_download.extract_info(url, download=not stream))
            
            if 'entries' in data:
                data = data['entries'][0]
            
            if not stream:
                filename = ytdl_download.prepare_filename(data)
            else:
                # For streaming, ensure we have a valid URL
                if 'url' not in data:
                    raise ValueError("Could not extract stream URL from video data")
                filename = data['url']
            
            # Create the audio source with enhanced error handling
            try:
                source = discord.FFmpegPCMAudio(filename, **ffmpeg_options)
                logger.info(f"Successfully created FFmpeg audio source for: {data.get('title', 'Unknown Title')}")
                return cls(source, data=data)
            except Exception as e:
                logger.error(f"FFmpeg error: {str(e)}")
                logger.error(f"Filename: {filename}")
                logger.error(f"FFmpeg options: {ffmpeg_options}")
                raise
                
        except Exception as e:
            logger.error(f"Error in YTDLSource.from_url: {str(e)}")
            logger.error(f"URL: {url}")
            logger.error(f"Stream mode: {stream}")
            raise

async def setup(bot):
    await bot.add_cog(Music(bot))
