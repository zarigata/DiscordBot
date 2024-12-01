import discord
from discord.ext import commands, tasks
import psutil
import time
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

Base = declarative_base()

class BotStats(Base):
    __tablename__ = 'bot_stats'
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    guild_count = Column(Integer, nullable=False, default=0)
    user_count = Column(Integer, nullable=False, default=0)
    latency = Column(Float, nullable=False, default=0.0)
    cpu_percent = Column(Float, nullable=False, default=0.0)
    memory_percent = Column(Float, nullable=False, default=0.0)

class Stats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()
        
        # Ensure data directory exists
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data')
        os.makedirs(data_dir, exist_ok=True)
        
        # Initialize database
        db_path = os.path.join(data_dir, 'bot_stats.db')
        self.engine = create_engine(f'sqlite:///{db_path}')
        
        # Drop existing tables and create new ones
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        
        Session = sessionmaker(bind=self.engine)
        self.db_session = Session()
        
        # Start background tasks
        self.record_stats.start()

    def cog_unload(self):
        self.record_stats.cancel()
        if self.db_session:
            self.db_session.close()

    @tasks.loop(minutes=1.0)
    async def record_stats(self):
        """Record bot statistics every minute"""
        try:
            # Calculate stats
            guild_count = len(self.bot.guilds)
            user_count = sum(len(guild.members) for guild in self.bot.guilds)
            latency = self.bot.latency * 1000  # Convert to ms
            cpu_percent = psutil.cpu_percent()
            memory_percent = psutil.virtual_memory().percent
            
            # Create new stats record
            stats = BotStats(
                guild_count=guild_count,
                user_count=user_count,
                latency=latency,
                cpu_percent=cpu_percent,
                memory_percent=memory_percent
            )
            
            self.db_session.add(stats)
            self.db_session.commit()
            
        except Exception as e:
            print(f"Error recording stats: {e}")
            # Rollback the session in case of error
            self.db_session.rollback()
            
    @record_stats.before_loop
    async def before_record_stats(self):
        """Wait until the bot is ready before starting the task"""
        await self.bot.wait_until_ready()
        
    @commands.Cog.listener()
    async def on_ready(self):
        """Initialize stats when bot starts"""
        print(f"Stats Cog ready! Monitoring {len(self.bot.guilds)} guilds and {sum(len(guild.members) for guild in self.bot.guilds)} users")

    def get_stats(self):
        """Get current bot statistics"""
        return {
            'guilds': len(self.bot.guilds),
            'users': sum(len(guild.members) for guild in self.bot.guilds),
            'latency': round(self.bot.latency * 1000, 2),  # ms
            'uptime': time.time() - self.start_time,
            'cpu': psutil.cpu_percent(),
            'memory': psutil.Process().memory_percent()
        }

    def get_historical_stats(self, hours=24):
        """Get historical statistics for the specified number of hours"""
        try:
            query = self.db_session.query(BotStats).order_by(BotStats.timestamp.desc())
            return query.limit(hours * 60).all()  # 60 entries per hour (1 per minute)
        except Exception as e:
            print(f"Error getting historical stats: {e}")
            return []

async def setup(bot):
    await bot.add_cog(Stats(bot))
