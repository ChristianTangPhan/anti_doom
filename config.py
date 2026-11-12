"""All settings, loaded from .env."""
import os

from dotenv import load_dotenv

load_dotenv()

# Discord
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])    # your anti-doom server
OWNER_ID = int(os.environ["DISCORD_OWNER_ID"])    # your Discord user ID; only you can use the bot
CATEGORY_NAME = os.environ.get("CATEGORY_NAME", "Instagram")

# Instagram (your main account)
IG_USERNAME = os.environ["IG_USERNAME"]
IG_PASSWORD = os.environ["IG_PASSWORD"]

# Polling (seconds). Conservative defaults because this is a main account.
ACTIVE_MIN = float(os.environ.get("ACTIVE_MIN", "10"))   # while a chat is active
ACTIVE_MAX = float(os.environ.get("ACTIVE_MAX", "15"))
IDLE_MIN = float(os.environ.get("IDLE_MIN", "45"))       # while quiet
IDLE_MAX = float(os.environ.get("IDLE_MAX", "75"))
ACTIVE_WINDOW = float(os.environ.get("ACTIVE_WINDOW", "120"))  # stay active this long after a message
POLL_FLOOR = float(os.environ.get("POLL_FLOOR", "8"))          # hard minimum wait, guards against typos
HOURLY_CAP = int(os.environ.get("HOURLY_CAP", "150"))          # max IG requests in any rolling hour
BACKOFF_SECONDS = int(os.environ.get("BACKOFF_SECONDS", "900"))  # pause after a rate-limit warning

INBOX_SIZE = int(os.environ.get("INBOX_SIZE", "20"))     # chats per inbox request
MSG_LIMIT = int(os.environ.get("MSG_LIMIT", "10"))       # recent messages included per chat

# Safety limits
SENDS_PER_MINUTE = int(os.environ.get("SENDS_PER_MINUTE", "10"))      # Discord -> IG burst limit
SCAN_COOLDOWN = float(os.environ.get("SCAN_COOLDOWN", "30"))           # seconds between /scan
MAX_LOGINS_PER_HOUR = int(os.environ.get("MAX_LOGINS_PER_HOUR", "3"))  # refuse to start past this
MAX_BACKOFF_SECONDS = int(os.environ.get("MAX_BACKOFF_SECONDS", "14400"))  # backoff doubles up to 4 h
HEARTBEAT_STALE = float(os.environ.get("HEARTBEAT_STALE", "180"))      # another copy counts as alive this long
STATUS_CHANNEL = os.environ.get("STATUS_CHANNEL", "anti-doom-status")
