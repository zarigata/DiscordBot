from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

# Create database directory if it doesn't exist
db_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
os.makedirs(db_dir, exist_ok=True)

# Create database engine
engine = create_engine(f'sqlite:///{os.path.join(db_dir, "bot_stats.db")}')
Session = sessionmaker(bind=engine)
Base = declarative_base()

class BotStats(Base):
    __tablename__ = 'bot_stats'
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.now)
    guilds = Column(Integer)
    users = Column(Integer)
    cpu_usage = Column(Float)
    memory_usage = Column(Float)
    latency = Column(Float)

class TrackHistory(Base):
    __tablename__ = 'track_history'
    
    id = Column(Integer, primary_key=True)
    guild_id = Column(String)
    track_title = Column(String)
    track_url = Column(String)
    requested_by = Column(String)
    started_at = Column(DateTime)
    ended_at = Column(DateTime, nullable=True)
    duration = Column(Integer)

class PlayCount(Base):
    __tablename__ = 'play_counts'
    
    id = Column(Integer, primary_key=True)
    track_url = Column(String, unique=True)
    track_title = Column(String)
    play_count = Column(Integer, default=0)
    total_duration = Column(Integer, default=0)
    last_played = Column(DateTime)
    track_metadata = Column(JSON)  # Changed from 'metadata' to 'track_metadata'

# Create all tables
Base.metadata.create_all(engine)
