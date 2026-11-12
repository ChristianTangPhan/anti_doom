"""Instagram wrapper: login, rate-limited requests, and message formatting."""
import asyncio
import os
import time
from collections import deque

from instagrapi import Client

SESSION_FILE = "ig_session.json"

# Labels for non-text items. Shown as a tiny note instead of the content.
ITEM_LABELS = {
    "media": "a photo/video",
    "raw_media": "a photo/video",
    "voice_media": "a voice message",
    "animated_media": "a GIF",
    "clip": "a reel",
    "xma_clip": "a reel",
    "media_share": "a post",
    "xma_media_share": "a post",
    "felix_share": "a video",
    "story_share": "a story",
    "reel_share": "a story reply",
    "xma_story_share": "a story",
    "xma_reel_share": "a story reply",
    "profile": "a profile",
    "xma_profile": "a profile",
    "generic_xma": "a post",
}


def ts(dt):
    """datetime -> unix seconds."""
    return dt.timestamp() if dt else 0.0


def message_to_text(m):
    """Turn an IG message into Discord text. Returns None to skip it."""
    if m.text:
        return m.text
    kind = m.item_type or ""
    if kind == "like":
        return "❤️"
    if kind in ("action_log", "placeholder", "video_call_event", ""):
        return None
    return f"📎 sent {ITEM_LABELS.get(kind, 'something')}"


class IG:
    """All IG calls go through _call(): one at a time, counted against the hourly cap."""

    def __init__(self, hourly_cap):
        self.cl = Client()
        self.cl.delay_range = [1, 3]  # instagrapi best practice: random pause after each request
        self.lock = asyncio.Lock()    # instagrapi isn't thread-safe, so one call at a time
        self.cap = hourly_cap
        self.calls = deque()          # timestamps of recent requests

    def login(self, username, password, verification_code=""):
        """Blocking. Reuses the saved session so IG sees the same device."""
        if os.path.exists(SESSION_FILE):
            self.cl.load_settings(SESSION_FILE)
        self.cl.login(username, password, verification_code=verification_code)
        self.cl.dump_settings(SESSION_FILE)

    @property
    def my_id(self):
        return str(self.cl.user_id)

    def calls_last_hour(self):
        now = time.time()
        while self.calls and now - self.calls[0] > 3600:
            self.calls.popleft()
        return len(self.calls)

    async def _call(self, fn, *args, cost=1, **kwargs):
        """cost = how many IG requests this call makes (inbox pages are 20 chats each)."""
        async with self.lock:
            if self.calls and self.calls_last_hour() + cost > self.cap:
                wait = 3600 - (time.time() - self.calls[0])
                print(f"IG hourly cap ({self.cap}) reached, waiting {wait:.0f}s")
                await asyncio.sleep(wait)
            now = time.time()
            self.calls.extend([now] * cost)
            return await asyncio.to_thread(fn, *args, **kwargs)

    async def inbox(self, amount, msg_limit):
        pages = -(-amount // 20)  # ceiling division: 40 chats = 2 requests
        return await self._call(
            self.cl.direct_threads, amount=amount, thread_message_limit=msg_limit, cost=pages
        )

    async def thread_messages(self, thread_id, amount=50):
        return await self._call(self.cl.direct_messages, int(thread_id), amount)

    async def send(self, thread_id, text):
        return await self._call(self.cl.direct_send, text, thread_ids=[int(thread_id)])
