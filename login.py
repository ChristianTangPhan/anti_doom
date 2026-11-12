"""Run once (and whenever IG asks you to log in again). Handles 2FA and saves the session."""
from instagrapi.exceptions import TwoFactorRequired

import config
from ig import IG
from store import Store

ig = IG(hourly_cap=999, store=Store(), interactive=True)  # interactive: asks you for codes
try:
    ig.login(config.IG_USERNAME, config.IG_PASSWORD)
except TwoFactorRequired:
    code = input("2FA code: ").strip()
    ig.login(config.IG_USERNAME, config.IG_PASSWORD, verification_code=code)

print(f"Logged in as {config.IG_USERNAME}. Session saved to ig_session.json.")
