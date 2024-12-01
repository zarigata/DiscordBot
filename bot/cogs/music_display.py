import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import asyncio

class MusicDisplay(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.music_messages = {}  # Store message IDs for each guild
        self.update_display.start()

    def cog_unload(self):
        self.update_display.cancel()

    def format_duration(self, seconds):
        """Format seconds into MM:SS"""
        if not seconds:
            return "00:00"
        return str(timedelta(seconds=int(seconds))).removeprefix('0:')

    def create_progress_bar(self, current, total, length=20):
        """Create a text-based progress bar"""
        filled = int(length * (current / total))
        bar = '▰' * filled + '▱' * (length - filled)
        return bar

    async def get_music_embed(self, guild_id):
        """Create an embed for the current music status"""
        music_cog = self.bot.get_cog('Music')
        if not music_cog:
            return None

        current_track = music_cog.current_tracks.get(guild_id)
        if not current_track:
            embed = discord.Embed(
                title="No music playing",
                description="Use !play [song name/URL] to play something!",
                color=discord.Color.blue()
            )
            return embed

        start_time = music_cog.start_times.get(guild_id)
        if not start_time:
            return None

        elapsed = (datetime.now() - start_time).total_seconds()
        duration = current_track.get('duration', 0)
        progress = min(100, (elapsed / duration) * 100) if duration else 0

        # Create progress bar
        progress_bar = self.create_progress_bar(elapsed, duration)
        time_display = f"{self.format_duration(elapsed)} / {self.format_duration(duration)}"

        embed = discord.Embed(
            title="Now Playing 🎵",
            description=f"**[{current_track['title']}]({current_track['url']})**",
            color=discord.Color.purple()
        )

        embed.add_field(
            name="Progress",
            value=f"{progress_bar}\n{time_display}",
            inline=False
        )

        embed.add_field(
            name="Requested by",
            value=current_track['requested_by'],
            inline=True
        )

        if current_track.get('thumbnail'):
            embed.set_thumbnail(url=current_track['thumbnail'])

        # Add queue info if available
        if hasattr(music_cog, 'music_queues'):
            queue = music_cog.music_queues.get(guild_id, [])
            if queue:
                next_up = queue[0].title if hasattr(queue[0], 'title') else "Unknown"
                embed.add_field(
                    name="Next in queue",
                    value=f"🎵 {next_up}",
                    inline=True
                )
                embed.set_footer(text=f"🎵 {len(queue)} songs in queue")

        return embed

    async def create_button_controls(self):
        """Create button controls for music playback"""
        buttons = discord.ui.View(timeout=None)
        
        # Volume Down Button
        buttons.add_item(discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            emoji="🔉",
            custom_id="volume_down"
        ))
        
        # Previous Track Button
        buttons.add_item(discord.ui.Button(
            style=discord.ButtonStyle.primary,
            emoji="⏮️",
            custom_id="prev_track"
        ))
        
        # Play/Pause Button
        buttons.add_item(discord.ui.Button(
            style=discord.ButtonStyle.success,
            emoji="⏯️",
            custom_id="play_pause"
        ))
        
        # Next Track Button
        buttons.add_item(discord.ui.Button(
            style=discord.ButtonStyle.primary,
            emoji="⏭️",
            custom_id="next_track"
        ))
        
        # Volume Up Button
        buttons.add_item(discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            emoji="🔊",
            custom_id="volume_up"
        ))
        
        return buttons

    @tasks.loop(seconds=10.0)
    async def update_display(self):
        """Update all music display messages"""
        for guild_id, message_id in self.music_messages.items():
            try:
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue

                channel = discord.utils.get(guild.text_channels, name="music-bot")
                if not channel:
                    continue

                try:
                    message = await channel.fetch_message(message_id)
                except discord.NotFound:
                    message = None

                embed = await self.get_music_embed(guild_id)
                if not embed:
                    continue

                if message:
                    await message.edit(embed=embed)
                else:
                    buttons = await self.create_button_controls()
                    new_message = await channel.send(embed=embed, view=buttons)
                    self.music_messages[guild_id] = new_message.id

            except Exception as e:
                print(f"Error updating music display: {e}")

    @update_display.before_loop
    async def before_update_display(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Handle button interactions"""
        if not interaction.data or 'custom_id' not in interaction.data:
            return

        music_cog = self.bot.get_cog('Music')
        if not music_cog:
            await interaction.response.send_message("Music system is not available.", ephemeral=True)
            return

        custom_id = interaction.data['custom_id']
        voice_client = interaction.guild.voice_client

        if not voice_client:
            await interaction.response.send_message("Not connected to a voice channel.", ephemeral=True)
            return

        try:
            if custom_id == "volume_down":
                current_volume = voice_client.source.volume if voice_client.source else 1.0
                new_volume = max(0.0, current_volume - 0.1)
                if voice_client.source:
                    voice_client.source.volume = new_volume
                await interaction.response.send_message(f"Volume set to {int(new_volume * 100)}%", ephemeral=True)

            elif custom_id == "volume_up":
                current_volume = voice_client.source.volume if voice_client.source else 1.0
                new_volume = min(2.0, current_volume + 0.1)
                if voice_client.source:
                    voice_client.source.volume = new_volume
                await interaction.response.send_message(f"Volume set to {int(new_volume * 100)}%", ephemeral=True)

            elif custom_id == "play_pause":
                if voice_client.is_paused():
                    voice_client.resume()
                    await interaction.response.send_message("Resumed playback", ephemeral=True)
                else:
                    voice_client.pause()
                    await interaction.response.send_message("Paused playback", ephemeral=True)

            elif custom_id == "next_track":
                if hasattr(music_cog, 'skip'):
                    ctx = await self.bot.get_context(interaction.message)
                    await music_cog.skip(ctx)
                    await interaction.response.send_message("Skipped to next track", ephemeral=True)

            elif custom_id == "prev_track":
                await interaction.response.send_message("Previous track feature coming soon!", ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(MusicDisplay(bot))
