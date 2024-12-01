from flask import Flask, render_template, jsonify
import psutil
import os
from datetime import datetime, timedelta
from .models import Session, BotStats, TrackHistory, PlayCount
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler
import json

app = Flask(__name__)

def get_bot_instance():
    """Get the bot instance from the running application."""
    from main import bot
    return bot

def save_bot_stats():
    """Save current bot stats to database."""
    bot = get_bot_instance()
    session = Session()
    
    stats = BotStats(
        guilds=len(bot.guilds),
        users=sum(g.member_count for g in bot.guilds),
        cpu_usage=psutil.cpu_percent(),
        memory_usage=psutil.Process().memory_info().rss / 1024 / 1024,
        latency=round(bot.latency * 1000, 2)
    )
    
    session.add(stats)
    session.commit()
    session.close()

# Start the background scheduler for stats collection
scheduler = BackgroundScheduler()
scheduler.add_job(save_bot_stats, 'interval', seconds=30)
scheduler.start()

def generate_system_stats_graph():
    """Generate system statistics graphs."""
    session = Session()
    
    # Get last 24 hours of stats
    last_day = datetime.now() - timedelta(days=1)
    stats = session.query(BotStats).filter(BotStats.timestamp > last_day).all()
    
    if not stats:
        session.close()
        return None, None, None
    
    df = pd.DataFrame([{
        'timestamp': s.timestamp,
        'CPU Usage (%)': s.cpu_usage,
        'Memory (MB)': s.memory_usage,
        'Latency (ms)': s.latency
    } for s in stats])
    
    # CPU Usage Graph
    cpu_fig = px.line(df, x='timestamp', y='CPU Usage (%)', 
                      title='CPU Usage Over Time')
    cpu_fig.update_layout(template='plotly_dark')
    
    # Memory Usage Graph
    mem_fig = px.line(df, x='timestamp', y='Memory (MB)',
                      title='Memory Usage Over Time')
    mem_fig.update_layout(template='plotly_dark')
    
    # Latency Graph
    lat_fig = px.line(df, x='timestamp', y='Latency (ms)',
                      title='Bot Latency Over Time')
    lat_fig.update_layout(template='plotly_dark')
    
    session.close()
    return (cpu_fig.to_json(), mem_fig.to_json(), lat_fig.to_json())

def generate_music_stats():
    """Generate music-related statistics."""
    session = Session()
    
    # Top played tracks
    top_tracks = session.query(PlayCount).order_by(PlayCount.play_count.desc()).limit(10).all()
    
    # Plays by hour
    last_day = datetime.now() - timedelta(days=1)
    history = session.query(TrackHistory).filter(TrackHistory.started_at > last_day).all()
    
    plays_by_hour = {}
    for track in history:
        hour = track.started_at.strftime('%H:00')
        plays_by_hour[hour] = plays_by_hour.get(hour, 0) + 1
    
    # Create plays by hour graph
    hours = sorted(plays_by_hour.keys())
    plays = [plays_by_hour[hour] for hour in hours]
    
    plays_fig = go.Figure(data=[go.Bar(x=hours, y=plays)])
    plays_fig.update_layout(
        title='Plays by Hour',
        template='plotly_dark',
        xaxis_title='Hour',
        yaxis_title='Number of Plays'
    )
    
    session.close()
    return (top_tracks, plays_fig.to_json())

@app.route('/')
def home():
    cpu_graph, mem_graph, lat_graph = generate_system_stats_graph()
    top_tracks, plays_graph = generate_music_stats()
    
    return render_template('dashboard.html',
                         cpu_graph=cpu_graph,
                         mem_graph=mem_graph,
                         lat_graph=lat_graph,
                         plays_graph=plays_graph,
                         top_tracks=top_tracks)

@app.route('/api/stats')
def stats():
    bot = get_bot_instance()
    session = Session()
    
    # Get latest stats
    latest_stats = session.query(BotStats).order_by(BotStats.timestamp.desc()).first()
    
    if latest_stats:
        stats = {
            'guilds': latest_stats.guilds,
            'users': latest_stats.users,
            'uptime': (datetime.now() - bot.start_time).total_seconds(),
            'cpu_usage': latest_stats.cpu_usage,
            'memory_usage': latest_stats.memory_usage,
            'latency': latest_stats.latency
        }
    else:
        stats = {
            'guilds': len(bot.guilds),
            'users': sum(g.member_count for g in bot.guilds),
            'uptime': (datetime.now() - bot.start_time).total_seconds(),
            'cpu_usage': psutil.cpu_percent(),
            'memory_usage': psutil.Process().memory_info().rss / 1024 / 1024,
            'latency': round(bot.latency * 1000, 2)
        }
    
    session.close()
    return jsonify(stats)

@app.route('/api/music/<int:guild_id>')
def music_info(guild_id):
    bot = get_bot_instance()
    music_cog = bot.get_cog('Music')
    session = Session()
    
    if not music_cog:
        session.close()
        return jsonify({'error': 'Music cog not loaded'})
    
    guild_data = music_cog.get_guild_data(guild_id)
    
    # Get recent track history from database
    history = session.query(TrackHistory)\
        .filter(TrackHistory.guild_id == str(guild_id))\
        .order_by(TrackHistory.started_at.desc())\
        .limit(10)\
        .all()
    
    history_data = [{
        'track': {
            'title': h.track_title,
            'url': h.track_url
        },
        'played_at': h.started_at.isoformat(),
        'ended_at': h.ended_at.isoformat() if h.ended_at else None
    } for h in history]
    
    session.close()
    
    # Calculate current track progress
    current = guild_data['current']
    if current and guild_data['start_time']:
        elapsed = (datetime.now() - guild_data['start_time']).total_seconds()
        current['progress'] = {
            'elapsed': elapsed,
            'elapsed_formatted': str(datetime.fromtimestamp(elapsed).strftime('%M:%S')),
            'duration_formatted': str(datetime.fromtimestamp(current['duration']).strftime('%M:%S')) if current.get('duration') else 'Unknown',
            'percentage': min(100, (elapsed / current['duration'] * 100)) if current.get('duration') else 0
        }
    
    return jsonify({
        'current_track': current,
        'queue': guild_data['queue'],
        'history': history_data
    })

@app.route('/api/music/current')
def current_music():
    """Get current playing track information."""
    try:
        bot = get_bot_instance()
        music_cog = bot.get_cog('Music')
        
        if not music_cog:
            return jsonify({'error': 'Music cog not loaded'}), 404
            
        # Get the first guild that's playing music
        current_tracks = getattr(music_cog, 'current_tracks', {})
        start_times = getattr(music_cog, 'start_times', {})
        
        for guild_id, track_data in current_tracks.items():
            if track_data:
                start_time = start_times.get(guild_id)
                if start_time:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    progress = min(100, (elapsed / track_data['duration']) * 100) if track_data['duration'] else 0
                    
                    return jsonify({
                        'title': track_data['title'],
                        'url': track_data['url'],
                        'thumbnail': track_data.get('thumbnail', ''),
                        'duration': track_data['duration'],
                        'elapsed': elapsed,
                        'progress': progress,
                        'requested_by': track_data.get('requested_by', 'Unknown')
                    })
        
        return jsonify({'error': 'No music currently playing'}), 404
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
