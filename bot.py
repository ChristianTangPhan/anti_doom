"""anti-doom: your Instagram chats, in Discord."""
import asyncio
import random
import time

import aiohttp
import discord
from instagrapi.exceptions import (
    ChallengeRequired,
    ClientThrottledError,
    LoginRequired,
    PleaseWaitFewMinutes,
)

import commands
import config
from ig import IG, message_to_text, ts
from store import Store


class AntiDoom(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)
        self.store = Store()
        self.ig = IG(config.HOURLY_CAP)
        self.last_activity = 0.0  # last message either direction, for active/idle polling
        self.last_poll = 0.0
        self.last_error = None
        self.poller_started = False
        self.http_session = None

    async def setup_hook(self):
        commands.setup(self)
        await self.tree.sync(guild=discord.Object(id=config.GUILD_ID))  # instant in your server
        self.http_session = aiohttp.ClientSession()

    def is_active(self):
        return time.time() - self.last_activity < config.ACTIVE_WINDOW

    async def on_ready(self):
        print(f"Discord: logged in as {self.user}")
        if not self.poller_started:  # on_ready can fire again on reconnect
            self.poller_started = True
            asyncio.create_task(self.poll_loop())

    # ---------- Discord -> IG ----------
    async def on_message(self, message: discord.Message):
        if message.author.id != config.OWNER_ID or message.webhook_id:
            return
        row = self.store.by_channel(message.channel.id)
        if row is None or not message.content:
            return
        try:
            sent = await self.ig.send(row["thread_id"], message.content)
            self.store.mark_seen(sent.id)  # so it doesn't echo back
            self.last_activity = time.time()
            await message.add_reaction("✅")
        except Exception as e:
            self.last_error = f"send failed: {e}"
            print("IG send error:", repr(e))
            await message.add_reaction("⚠️")

    # ---------- IG -> Discord ----------
    async def notify_owner(self, text):
        try:
            owner = await self.fetch_user(config.OWNER_ID)
            await owner.send(f"anti-doom: {text}")
        except Exception as e:
            print("Couldn't DM owner:", repr(e))

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

    async def poll_loop(self):
        print("Instagram: polling started")
        while True:
            try:
                await self.poll_once()
                self.last_poll = time.time()
                self.store.prune_seen()
            except (PleaseWaitFewMinutes, ClientThrottledError) as e:
                self.last_error = f"rate limited: {e}"
                print(f"IG rate limited, backing off {config.BACKOFF_SECONDS}s")
                await asyncio.sleep(config.BACKOFF_SECONDS)
                continue
            except (LoginRequired, ChallengeRequired) as e:
                self.last_error = f"login problem: {e}"
                print("IG login problem:", repr(e))
                await self.notify_owner("Instagram needs attention (login/challenge). Run login.py, then restart me.")
                await asyncio.sleep(3600)
                continue
            except Exception as e:
                self.last_error = repr(e)
                print("IG poll error:", repr(e))

            low, high = (
                (config.ACTIVE_MIN, config.ACTIVE_MAX)
                if self.is_active()
                else (config.IDLE_MIN, config.IDLE_MAX)
            )
            await asyncio.sleep(max(config.POLL_FLOOR, random.uniform(low, high)))


if __name__ == "__main__":
    bot = AntiDoom()
    bot.ig.login(config.IG_USERNAME, config.IG_PASSWORD)
    bot.run(config.DISCORD_TOKEN)
