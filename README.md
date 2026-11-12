# anti-doom

Read and reply to your Instagram chats from Discord, so you don't open the IG app and doom scroll.

- One Discord channel per IG chat, created by the bot.
- Text only. Reels/posts/photos show as a tiny `📎 sent a post` note.
- Managed with slash commands. Only you (`DISCORD_OWNER_ID`) can use them.
- One inbox request per poll covers every chat, so adding chats doesn't add requests.

> Uses `instagrapi` (unofficial API) on **your main account**. Defaults are conservative, but there's always some risk.

## Commands

| Command | Does |
|---|---|
| `/scan [count] [search]` | Unbridged chats as buttons (default 5, max 25). `search` filters by name/username, e.g. `/scan search:sarah`. Click to bridge. |
| `/list` | Bridged chats |
| `/remove [delete_channel]` | Run in a chat's channel to unbridge it |
| `/mute` / `/unmute` | Pause/resume incoming messages for this channel's chat |
| `/status` | Requests this hour, last poll, active/idle, last error |

Type in a bridged channel to send as yourself. ✅ = sent, ⏳ = queued (rate limit), ⚠️ = failed.

## Safety

- **Hourly cap** (`HOURLY_CAP=150`) counts every IG request (polls, sends, scans, logins) and is saved in the database, so restarts don't reset it.
- **Login guard**: refuses to start after `MAX_LOGINS_PER_HOUR` (3) logins in an hour, so a crash loop can't keep logging in.
- **One copy only**: a heartbeat in `#anti-doom-status`. A second copy (even on another computer) exits if the first is alive.
- **Backoff**: any "slow down" from IG pauses 15 min, doubling each time up to 4 h. Other errors back off too. You get a DM.
- **No freezing on challenges**: if IG asks for a code, the bot DMs you instead of waiting on the terminal. Run `login.py` to fix.
- **Send limit**: max `SENDS_PER_MINUTE` (10) Discord → IG; extras queue in order.
- **Scan cooldown**: `/scan` at most once per `SCAN_COOLDOWN` (30 s).

## Setup

### 1. Discord
1. Make a private server for anti-doom.
2. Developer Portal → **New Application** → **Bot** → Reset Token → copy. Turn on **Message Content Intent**.
3. **OAuth2 → URL Generator**: scopes `bot` + `applications.commands`. Permissions: **View Channels, Send Messages, Read Message History, Add Reactions, Manage Channels, Manage Webhooks**. Open the URL, add it to your server.
4. Developer Mode on → right-click your server → **Copy Server ID** (`DISCORD_GUILD_ID`). Right-click yourself → **Copy User ID** (`DISCORD_OWNER_ID`).

### 2. Install

**Windows (PowerShell)**
```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

**Linux (dudbox)**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`.

### 3. Log in to IG (once)
```bash
python login.py
```
Enter a 2FA or challenge code if asked. This saves `ig_session.json`.

### 4. Run
```bash
python bot.py
```
Then `/scan` in your server.

## Moving to dudbox
Copy `.env`, `ig_session.json`, and `anti_doom.db` (all gitignored), recreate the venv, then:
```bash
sudo cp deploy/anti-doom.service /etc/systemd/system/   # edit username/paths first
sudo systemctl daemon-reload
sudo systemctl enable --now anti-doom
journalctl -u anti-doom -f
```
