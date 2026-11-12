"""Slash commands: the bridge manager GUI, inside Discord."""
import re
import time

import discord
from discord import app_commands

import config
from ig import ts


def only_owner(interaction: discord.Interaction) -> bool:
    return interaction.user.id == config.OWNER_ID


def thread_title(t, my_id):
    if t.thread_title:
        return t.thread_title
    names = [u.username for u in t.users if str(u.pk) != my_id]
    return ", ".join(names) or "chat"


def channel_name(title):
    """'Comfort Zone GC!' -> 'comfort-zone-gc'"""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:90] or "chat"


async def get_category(guild: discord.Guild):
    category = discord.utils.get(guild.categories, name=config.CATEGORY_NAME)
    if category is None:
        category = await guild.create_category(config.CATEGORY_NAME)
    return category


class ScanView(discord.ui.View):
    """One button per unbridged chat. Clicking one bridges it."""

    def __init__(self, bot, chats):
        super().__init__(timeout=300)
        for thread_id, title, last_seen in chats:
            button = discord.ui.Button(label=title[:80], style=discord.ButtonStyle.primary)
            button.callback = self.make_callback(bot, thread_id, title, last_seen)
            self.add_item(button)

    def make_callback(self, bot, thread_id, title, last_seen):
        async def callback(interaction: discord.Interaction):
            if not only_owner(interaction):
                return await interaction.response.send_message("Not yours.", ephemeral=True)
            if thread_id in bot.store.thread_ids():
                return await interaction.response.send_message(f"**{title}** is already bridged.", ephemeral=True)
            await interaction.response.defer(ephemeral=True)
            category = await get_category(interaction.guild)
            channel = await interaction.guild.create_text_channel(
                channel_name(title), category=category, topic=f"IG chat: {title} (thread {thread_id})"
            )
            webhook = await channel.create_webhook(name="anti-doom")
            # last_seen = the chat's latest activity, so old history isn't dumped in
            bot.store.add(thread_id, channel.id, webhook.url, title, last_seen)
            await interaction.followup.send(f"Bridged **{title}** → {channel.mention}", ephemeral=True)

        return callback


def setup(bot):
    tree = bot.tree
    guild = discord.Object(id=config.GUILD_ID)

    @tree.command(name="scan", description="Show your top unbridged IG chats", guild=guild)
    @app_commands.check(only_owner)
    async def scan(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        threads = await bot.ig.inbox(config.INBOX_SIZE, 1)
        bridged = bot.store.thread_ids()
        chats = [
            (str(t.id), thread_title(t, bot.ig.my_id), ts(t.last_activity_at))
            for t in threads
            if str(t.id) not in bridged
        ][:5]
        if not chats:
            return await interaction.followup.send("No unbridged chats in your recent inbox.", ephemeral=True)
        await interaction.followup.send("Pick a chat to bridge:", view=ScanView(bot, chats), ephemeral=True)

    @tree.command(name="list", description="List bridged chats", guild=guild)
    @app_commands.check(only_owner)
    async def list_(interaction: discord.Interaction):
        rows = bot.store.all()
        if not rows:
            return await interaction.response.send_message("Nothing bridged yet. Try /scan.", ephemeral=True)
        lines = [f"<#{r['channel_id']}> — {r['title']}{' 🔇' if r['muted'] else ''}" for r in rows]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @tree.command(name="remove", description="Unbridge this channel's chat", guild=guild)
    @app_commands.describe(delete_channel="Also delete this Discord channel")
    @app_commands.check(only_owner)
    async def remove(interaction: discord.Interaction, delete_channel: bool = False):
        row = bot.store.by_channel(interaction.channel_id)
        if row is None:
            return await interaction.response.send_message("This channel isn't bridged.", ephemeral=True)
        bot.store.remove(row["thread_id"])
        if delete_channel:
            await interaction.response.send_message("Removed. Deleting channel…", ephemeral=True)
            await interaction.channel.delete()
        else:
            await interaction.response.send_message(f"Unbridged **{row['title']}**. Channel kept.", ephemeral=True)

    @tree.command(name="mute", description="Pause incoming messages for this chat", guild=guild)
    @app_commands.check(only_owner)
    async def mute(interaction: discord.Interaction):
        row = bot.store.by_channel(interaction.channel_id)
        if row is None:
            return await interaction.response.send_message("This channel isn't bridged.", ephemeral=True)
        bot.store.set_muted(row["thread_id"], True)
        await interaction.response.send_message(f"🔇 Muted **{row['title']}**.", ephemeral=True)

    @tree.command(name="unmute", description="Resume incoming messages for this chat", guild=guild)
    @app_commands.check(only_owner)
    async def unmute(interaction: discord.Interaction):
        row = bot.store.by_channel(interaction.channel_id)
        if row is None:
            return await interaction.response.send_message("This channel isn't bridged.", ephemeral=True)
        # skip whatever arrived while muted
        bot.store.set_muted(row["thread_id"], False, last_seen=time.time())
        await interaction.response.send_message(f"🔊 Unmuted **{row['title']}**.", ephemeral=True)

    @tree.command(name="status", description="Bot health", guild=guild)
    @app_commands.check(only_owner)
    async def status(interaction: discord.Interaction):
        last = f"<t:{int(bot.last_poll)}:R>" if bot.last_poll else "never"
        lines = [
            f"Bridged chats: {len(bot.store.all())}",
            f"IG requests last hour: {bot.ig.calls_last_hour()} / {config.HOURLY_CAP}",
            f"Last poll: {last}",
            f"Mode: {'active' if bot.is_active() else 'idle'}",
            f"Last error: {bot.last_error or 'none'}",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @tree.error
    async def on_error(interaction: discord.Interaction, error):
        if isinstance(error, app_commands.CheckFailure):
            msg = "Only the owner can use this."
        else:
            msg = f"Error: {error}"
            print("Command error:", repr(error))
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
