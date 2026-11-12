"""anti-doom: your Instagram chats, in Discord."""
import asyncio
import os
import random
import socket
import sys
import time
from collections import deque

import aiohttp
import discord
from instagrapi.exceptions import (
    ChallengeRequired,
    ClientThrottledError,
    FeedbackRequired,
    LoginRequired,
    PleaseWaitFewMinutes,
    RateLimitError,
    SentryBlock,
)

import commands
import config
from ig import IG, CapReached, message_to_text, ts
from store import Store

# Instagram telling us to slow down. Any of these -> long, doubling backoff.
RATE_ERRORS = (PleaseWaitFewMinutes, ClientThrottledError, RateLimitError, FeedbackRequired, SentryBlock)

# Same machine + same folder = same instance (so a restart isn't mistaken for a second copy)
INSTANCE_ID = f"{socket.gethostname()}:{os.path.abspath('.')}"


class AntiDoom(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)
        self.store = Store()
        self.ig = IG(config.HOURLY_CAP, self.store)
        self.send_queue = asyncio.Queue()  # Discord -> IG, sent one at a time, in order
        self.last_activity = 0.0  # last message either direction, for active/idle polling
        self.last_poll = 0.0
        self.last_scan = 0.0
        self.last_error = None
        self.started = False
        self.http_session = None
        self.status_channel = None
        self.heartbeat_msg = None

    async def setup_hook(self):
        commands.setup(self)
        await self.tree.sync(guild=discord.Object(id=config.GUILD_ID))  # instant in your server
        self.http_session = aiohttp.ClientSession()

    async def close(self):
        if self.http_session:
            await self.http_session.close()
        await super().close()

    def is_active(self):
        return time.time() - self.last_activity < config.ACTIVE_WINDOW

    async def on_ready(self):
        print(f"Discord: logged in as {self.user}")
        if self.started:  # on_ready can fire again on reconnect
            return
        self.started = True
        if not await self.claim_instance():
            return
        asyncio.create_task(self.heartbeat_loop())
        asyncio.create_task(self.send_worker())
        asyncio.create_task(self.poll_loop())

    async def notify_owner(self, text):
        try:
            owner = await self.fetch_user(config.OWNER_ID)
            await owner.send(f"anti-doom: {text}")
        except Exception as e:
            print("Couldn't DM owner:", repr(e))

    # ---------- only one copy at a time (works across computers) ----------
    async def claim_instance(self):
        """A heartbeat message in #anti-doom-status. If another copy updated it recently, quit."""
        guild = self.get_guild(config.GUILD_ID) or await self.fetch_guild(config.GUILD_ID)
        self.status_channel = discord.utils.get(guild.text_channels, name=config.STATUS_CHANNEL)
        if self.status_channel is None:
            category = await commands.get_category(guild)
            self.status_channel = await guild.create_text_channel(
                config.STATUS_CHANNEL, category=category, topic="anti-doom heartbeat. Don't delete."
            )
        async for m in self.status_channel.history(limit=20):
            if m.author.id == self.user.id and m.content.startswith("heartbeat "):
                self.heartbeat_msg = m
                break

        if self.heartbeat_msg:
            _, beat_time, other = self.heartbeat_msg.content.split(" ", 2)
            age = time.time() - float(beat_time)
            if other != INSTANCE_ID and age < config.HEARTBEAT_STALE:
                msg = f"Another copy is already running on `{other}` (seen {age:.0f}s ago). This one is exiting."
                print(msg)
                await self.notify_owner(msg)
                await self.close()
                return False
        await self.beat()
        return True

    async def beat(self):
        content = f"heartbeat {int(time.time())} {INSTANCE_ID}"
        try:
            if self.heartbeat_msg:
                await self.heartbeat_msg.edit(content=content)
            else:
                self.heartbeat_msg = await self.status_channel.send(content)
        except discord.NotFound:  # message was deleted; post a new one next time
            self.heartbeat_msg = None
        except Exception as e:
            print("Heartbeat error:", repr(e))

    async def heartbeat_loop(self):
        while True:
            await asyncio.sleep(60)
            await self.beat()

    # ---------- Discord -> IG ----------
    async def on_message(self, message: discord.Message):
        if message.author.id != config.OWNER_ID or message.webhook_id:
            return
        row = self.store.by_channel(message.channel.id)
        if row is None or not message.content:
            return
        await self.send_queue.put((message, row["thread_id"]))

    async def react(self, message, emoji, remove=None):
        try:
            if remove:
                await message.remove_reaction(remove, self.user)
            await message.add_reaction(emoji)
        except Exception:
            pass  # message deleted, missing permission, etc.

    async def send_worker(self):
        recent = deque()  # times of recent sends, for the per-minute limit
        while True:
            message, thread_id = await self.send_queue.get()
            waited = False
            while True:
                now = time.time()
                while recent and now - recent[0] > 60:
                    recent.popleft()
                if len(recent) >= config.SENDS_PER_MINUTE:
                    wait = 60 - (now - recent[0]) + 0.5
                else:
                    try:
                        sent = await self.ig.send(thread_id, message.content)
                        break
                    except CapReached as e:
                        wait = e.wait
                    except Exception as e:
                        sent = None
                        self.last_error = f"send failed: {e}"
                        print("IG send error:", repr(e))
                        break
                if not waited:
                    await self.react(message, "⏳")
                    waited = True
                await asyncio.sleep(wait)

            recent.append(time.time())
            if sent is None:
                await self.react(message, "⚠️", remove="⏳" if waited else None)
                continue
            self.store.mark_seen(sent.id)  # so it doesn't echo back
            self.last_activity = time.time()
            await self.react(message, "✅", remove="⏳" if waited else None)

    # ---------- IG -> Discord ----------
    async def relay(self, row, m, users):
        text = message_to_text(m)
        if text is None:
            return
        if m.is_sent_by_viewer or m.user_id == self.ig.my_id:
            name, avatar = "You (IG)", None
        else:
            u = users.get(m.user_id)
            name = f"{u.username} (IG)" if u else "unknown (IG)"
            avatar = str(u.profile_pic_url) if u and u.profile_pic_url else None
        webhook = discord.Webhook.from_url(row["webhook_url"], session=self.http_session)
        await webhook.send(
            text[:2000],
            username=name[:80],
            avatar_url=avatar,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def poll_once(self):
        threads = await self.ig.inbox(config.INBOX_SIZE, config.MSG_LIMIT)
        bridges = {r["thread_id"]: r for r in self.store.all()}
        for t in threads:
            row = bridges.get(str(t.id))
            if row is None or row["muted"]:
                continue
            last_seen = row["last_seen"]
            if ts(t.last_activity_at) < last_seen:
                continue  # nothing new in this chat

            # IG timestamps are whole seconds, so also check IDs for same-second messages
            def is_new(m):
                return ts(m.timestamp) >= last_seen and not self.store.was_seen(m.id)

            msgs = list(t.messages)
            new = [m for m in msgs if is_new(m)]
            if len(msgs) >= config.MSG_LIMIT and len(new) == len(msgs):
                # every included message is new, so there may be more: fetch the chat
                msgs = await self.ig.thread_messages(t.id, 50)
                new = [m for m in msgs if is_new(m)]
            if not new:
                continue

            new.sort(key=lambda m: m.timestamp)
            users = {str(u.pk): u for u in t.users}
            for m in new:
                await self.relay(row, m, users)
                self.store.mark_seen(m.id)
            self.store.set_last_seen(t.id, ts(new[-1].timestamp))
            self.last_activity = time.time()

    def normal_wait(self):
        low, high = (
            (config.ACTIVE_MIN, config.ACTIVE_MAX)
            if self.is_active()
            else (config.IDLE_MIN, config.IDLE_MAX)
        )
        return max(config.POLL_FLOOR, random.uniform(low, high))

    async def poll_loop(self):
        print("Instagram: polling started")
        errors_in_a_row = 0
        while True:
            try:
                await self.poll_once()
                self.last_poll = time.time()
                self.store.prune_seen()
                self.store.prune_calls()
                errors_in_a_row = 0
                wait = self.normal_wait()
            except CapReached as e:
                print(f"IG hourly cap reached, pausing {e.wait:.0f}s")
                wait = e.wait
            except RATE_ERRORS as e:
                errors_in_a_row += 1
                wait = min(config.BACKOFF_SECONDS * 2 ** (errors_in_a_row - 1), config.MAX_BACKOFF_SECONDS)
                self.last_error = f"IG said slow down ({type(e).__name__})"
                print(f"{self.last_error}, backing off {wait / 60:.0f} min")
                if errors_in_a_row == 1:
                    await self.notify_owner(f"{self.last_error}. Pausing {wait / 60:.0f} min.")
            except (LoginRequired, ChallengeRequired) as e:
                errors_in_a_row += 1
                self.last_error = f"login problem: {type(e).__name__}"
                print("IG login problem:", repr(e))
                await self.notify_owner(
                    "Instagram needs attention (login/challenge). Stop me, run login.py, then restart."
                )
                wait = 3600
            except Exception as e:
                errors_in_a_row += 1
                wait = min(self.normal_wait() * 2 ** errors_in_a_row, 1800)
                self.last_error = repr(e)
                print(f"IG poll error ({errors_in_a_row} in a row), retrying in {wait:.0f}s:", repr(e))
            await asyncio.sleep(wait)


if __name__ == "__main__":
    bot = AntiDoom()
    logins = bot.store.recent_logins(3600)
    if logins >= config.MAX_LOGINS_PER_HOUR:
        print(
            f"Already logged into IG {logins} times in the last hour. "
            "Refusing to start so a crash loop can't hammer Instagram. Try again later."
        )
        sys.exit(0)  # exit code 0, so systemd doesn't keep restarting
    bot.ig.login(config.IG_USERNAME, config.IG_PASSWORD)
    bot.run(config.DISCORD_TOKEN)
