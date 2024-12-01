from flask import Flask, render_template, jsonify
from datetime import datetime
import psutil
import os

app = Flask(__name__)
bot = None

def get_bot_instance():
    return bot

def setup_dashboard(_bot):
    global bot
    bot = _bot

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/api/stats')
def get_stats():
    """Get current bot statistics"""
    try:
        stats_cog = bot.get_cog('Stats')
        if not stats_cog:
            return jsonify({
                'current': {
                    'guilds': len(bot.guilds),
                    'users': sum(len(guild.members) for guild in bot.guilds),
                    'latency': round(bot.latency * 1000, 2),
                    'uptime': (datetime.now() - bot.start_time).total_seconds()
                },
                'historical': {
                    'timestamps': [],
                    'latencies': [],
                    'cpu_stats': [],
                    'memory_stats': []
                }
            })
            
        current_stats = stats_cog.get_stats()
        historical_stats = stats_cog.get_historical_stats(hours=24)
        
        # Format historical data for plotting
        timestamps = [stat.timestamp.isoformat() for stat in historical_stats]
        latencies = [stat.latency for stat in historical_stats]
        guild_counts = [stat.guild_count for stat in historical_stats]
        user_counts = [stat.user_count for stat in historical_stats]
        cpu_stats = [stat.cpu_percent for stat in historical_stats]
        memory_stats = [stat.memory_percent for stat in historical_stats]
        
        return jsonify({
            'current': current_stats,
            'historical': {
                'timestamps': timestamps,
                'latencies': latencies,
                'guild_counts': guild_counts,
                'user_counts': user_counts,
                'cpu_stats': cpu_stats,
                'memory_stats': memory_stats
            }
        })
    except Exception as e:
        print(f"Error getting stats: {e}")
        return jsonify({'error': str(e)}), 500

def run_dashboard(host='0.0.0.0', port=5000):
    app.run(host=host, port=port)
