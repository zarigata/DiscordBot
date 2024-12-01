import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import asyncio
from discord.ui import Button, View

class MusicDisplay(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.display_messages = {}
        self.update_display.start()

    def cog_unload(self):
        self.update_display.cancel()

    async def create_or_get_display(self, ctx):
        """Create or get the music display for a guild"""
        if ctx.guild.id in self.display_messages:
            try:
                # Try to fetch existing message
                message = self.display_messages[ctx.guild.id]
                await message.channel.fetch_message(message.id)
                return message
            except (discord.NotFound, discord.HTTPException):
                # Message was deleted or not found
                del self.display_messages[ctx.guild.id]

        # Create new display
        embed = discord.Embed(
            title="Music Player",
            description="No track playing",
            color=discord.Color.blue()
        )
        
        # Create button rows
        view = View()
        
        # First row - Playback controls
        view.add_item(Button(style=discord.ButtonStyle.primary, emoji="⏮️", custom_id="restart"))
        view.add_item(Button(style=discord.ButtonStyle.primary, emoji="⏯️", custom_id="playpause"))
        view.add_item(Button(style=discord.ButtonStyle.primary, emoji="⏭️", custom_id="skip"))
        view.add_item(Button(style=discord.ButtonStyle.primary, emoji="🔊", custom_id="volume"))
        
        # Second row - Filter buttons
        view.add_item(Button(style=discord.ButtonStyle.secondary, label="Bass Boost 🎵", custom_id="bass_boost"))
        view.add_item(Button(style=discord.ButtonStyle.secondary, label="Long Drive 🚗", custom_id="long_drive"))
        view.add_item(Button(style=discord.ButtonStyle.secondary, label="Vaporwave 🌊", custom_id="vaporwave"))
        
        # Third row - More filters
        view.add_item(Button(style=discord.ButtonStyle.secondary, label="Highcore ⚡", custom_id="highcore"))
        view.add_item(Button(style=discord.ButtonStyle.secondary, label="DrUgS 🌀", custom_id="drugs"))

        message = await ctx.send(embed=embed, view=view)
        self.display_messages[ctx.guild.id] = message
        return message

    @tasks.loop(seconds=5.0)
    async def update_display(self):
        """Update all music displays"""
        for guild_id, message in list(self.display_messages.items()):
            try:
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue

                voice_client = guild.voice_client
                if not voice_client or not voice_client.is_connected():
                    continue

                # Update embed
                embed = self.create_now_playing_embed(guild)
                await message.edit(embed=embed)

            except Exception as e:
                print(f"Error updating display: {e}")
                continue

    def create_now_playing_embed(self, guild):
        """Create the Now Playing embed"""
        voice_client = guild.voice_client
        
        if not voice_client or not voice_client.is_playing():
            return discord.Embed(
                title="Music Player",
                description="No track playing",
                color=discord.Color.blue()
            )

        source = voice_client.source
        embed = discord.Embed(title="Now Playing 🎵", color=discord.Color.blue())
        embed.add_field(name="Track", value=source.title, inline=False)
        
        # Add duration if available
        if hasattr(source, 'duration'):
            embed.add_field(name="Duration", value=self.format_duration(source.duration))
            
        # Add requester if available
        if hasattr(source, 'requester'):
            embed.add_field(name="Requested by", value=source.requester.name)

        return embed

    def format_duration(self, duration):
        """Format duration in seconds to mm:ss"""
        if not duration:
            return "Unknown"
        minutes = duration // 60
        seconds = duration % 60
        return f"{minutes:02d}:{seconds:02d}"

    @commands.Cog.listener()
    async def on_interaction(self, interaction):
        """Handle button interactions"""
        if not interaction.data or 'custom_id' not in interaction.data:
            return

        custom_id = interaction.data['custom_id']
        ctx = await self.bot.get_context(interaction.message)
        
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
        except:
            pass  # Interaction was already acknowledged

        try:
            if custom_id == "restart":
                await ctx.invoke(self.bot.get_command('restart'))
            elif custom_id == "playpause":
                await ctx.invoke(self.bot.get_command('pause'))
            elif custom_id == "skip":
                await ctx.invoke(self.bot.get_command('skip'))
            elif custom_id == "volume":
                current_volume = ctx.voice_client.source.volume if ctx.voice_client and ctx.voice_client.source else 100
                new_volume = 50 if current_volume == 100 else 100
                await ctx.invoke(self.bot.get_command('volume'), volume=new_volume)
            elif custom_id in ["bass_boost", "long_drive", "vaporwave", "highcore", "drugs"]:
                await ctx.invoke(self.bot.get_command('filter'), filter_name=custom_id)

        except Exception as e:
            print(f"Error handling button interaction: {e}")
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)

    @commands.command(name='display')
    async def _display(self, ctx):
        """Create or update the music display"""
        message = await self.create_or_get_display(ctx)
        if message:
            self.display_messages[ctx.guild.id] = message

    @update_display.before_loop
    async def before_update_display(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(MusicDisplay(bot))
