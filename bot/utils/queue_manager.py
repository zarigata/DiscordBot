import json
import os
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)

class QueueManager:
    def __init__(self, queue_file: str = "data/music_queues.json"):
        self.queue_file = queue_file
        self.queues: Dict[str, List[dict]] = {}
        self._load_queues()

    def _load_queues(self):
        """Load queues from JSON file"""
        try:
            if os.path.exists(self.queue_file):
                with open(self.queue_file, 'r') as f:
                    self.queues = json.load(f)
            else:
                # Ensure the directory exists
                os.makedirs(os.path.dirname(self.queue_file), exist_ok=True)
                self.queues = {}
                self._save_queues()
        except Exception as e:
            logger.error(f"Error loading queues: {e}")
            self.queues = {}

    def _save_queues(self):
        """Save queues to JSON file"""
        try:
            with open(self.queue_file, 'w') as f:
                json.dump(self.queues, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving queues: {e}")

    def add_to_queue(self, guild_id: str, track: dict):
        """Add a track to a guild's queue"""
        if guild_id not in self.queues:
            self.queues[guild_id] = []
        self.queues[guild_id].append(track)
        self._save_queues()

    def get_next_track(self, guild_id: str) -> dict:
        """Get and remove the next track from a guild's queue"""
        if guild_id in self.queues and self.queues[guild_id]:
            track = self.queues[guild_id].pop(0)
            self._save_queues()
            return track
        return None

    def clear_queue(self, guild_id: str):
        """Clear a guild's queue"""
        if guild_id in self.queues:
            self.queues[guild_id] = []
            self._save_queues()

    def get_queue(self, guild_id: str) -> List[dict]:
        """Get a guild's queue"""
        return self.queues.get(guild_id, [])
