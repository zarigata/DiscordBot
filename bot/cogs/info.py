from discord.ext import commands
import discord
import psutil
import platform
from datetime import datetime

class Info(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = datetime.utcnow()

    @commands.command(name='ping')
    async def ping(self, ctx):
        """Get the bot's current latency."""
        latency = round(self.bot.latency * 1000)
        await ctx.send(f'🏓 Pong! Latency: {latency}ms')

    @commands.command(name='stats')
    async def stats(self, ctx):
        """Get detailed statistics about the bot."""
        embed = discord.Embed(title='Bot Statistics', color=discord.Color.blue())
        
        # System info
        cpu_usage = psutil.cpu_percent()
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        embed.add_field(name='System', value=f'```\n'
                       f'CPU Usage: {cpu_usage}%\n'
                       f'Memory: {mem.percent}%\n'
                       f'Disk: {disk.percent}%```', inline=False)
        
        # Bot info
        embed.add_field(name='Bot', value=f'```\n'
                       f'Guilds: {len(self.bot.guilds)}\n'
                       f'Users: {sum(g.member_count for g in self.bot.guilds)}\n'
                       f'Commands: {len(self.bot.commands)}```', inline=False)
        
        # Add uptime
        delta = datetime.utcnow() - self.start_time
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        embed.add_field(name='Uptime', value=f'```\n{hours}h {minutes}m {seconds}s```', inline=False)
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Info(bot))
