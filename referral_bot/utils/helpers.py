"""
utils/helpers.py — VPN detection, channel check, misc utilities
"""
import os
import secrets
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

VPNAPI_KEY = os.getenv("VPNAPI_KEY", "")
REQUIRED_CHANNEL_IDS = [
    int(x.strip())
    for x in os.getenv("REQUIRED_CHANNEL_IDS", "").split(",")
    if x.strip()
]


def check_vpn(ip: str) -> dict:
    """
    Returns {"is_vpn": bool, "error": str|None}
    Uses vpnapi.io free tier.
    """
    if not VPNAPI_KEY or ip in ("127.0.0.1", "::1"):
        return {"is_vpn": False, "error": None}
    try:
        url = f"https://vpnapi.io/api/{ip}?key={VPNAPI_KEY}"
        r = requests.get(url, timeout=5)
        data = r.json()
        security = data.get("security", {})
        is_vpn = any([
            security.get("vpn", False),
            security.get("proxy", False),
            security.get("tor", False),
            security.get("relay", False),
        ])
        return {"is_vpn": is_vpn, "error": None}
    except Exception as e:
        return {"is_vpn": False, "error": str(e)}


async def check_channel_membership(bot, user_id: int) -> tuple[bool, list[int]]:
    """
    Check if user is member of ALL required channels.
    Returns (all_joined: bool, missing_channel_ids: list)
    """
    if not REQUIRED_CHANNEL_IDS:
        return True, []
    missing = []
    for channel_id in REQUIRED_CHANNEL_IDS:
        try:
            member = await bot.get_chat_member(channel_id, user_id)
            if member.status in ("left", "kicked", "banned"):
                missing.append(channel_id)
        except Exception:
            missing.append(channel_id)
    return len(missing) == 0, missing


def generate_referral_link(bot_username: str, user_id: int) -> str:
    return f"https://t.me/{bot_username}?start=ref_{user_id}"


def generate_verification_token() -> str:
    return secrets.token_urlsafe(32)


def get_week_info() -> tuple[int, int]:
    now = datetime.utcnow()
    return now.isocalendar()[1], now.year


def is_withdrawal_open() -> bool:
    from database.db import get_setting
    return get_setting("withdrawal_open") == "1"


def is_maintenance() -> bool:
    from database.db import get_setting
    return get_setting("maintenance_mode") == "1"


ENCOURAGEMENT_MESSAGES = [
    "💪 Don't give up! Every referral brings you closer to the top. Keep grinding — the leaderboard is yours to conquer!",
    "🔥 You're not top 3 yet, but legends weren't built in a day. Share your link EVERYWHERE and watch those numbers climb!",
    "⚡ The top 3 aren't untouchable — they're just people who shared more. Your moment is coming. Push harder!",
    "🚀 Rome wasn't built in a day and neither is a leaderboard champion. Stay consistent and keep referring!",
    "🏆 The prize is right there waiting for you. One viral post, one conversation, one share — that's all it takes to change your rank!",
    "💡 Smart referrers don't stop — they strategize. Post in groups, share in stories, text your contacts. The top 3 spot is within reach!",
    "🎯 You're in this game for a reason. Your network is bigger than you think — tap into it and climb that board!",
    "🌟 Every top earner started exactly where you are. What separates them? They never stopped. Neither should you!",
]

import random
def get_encouragement() -> str:
    return random.choice(ENCOURAGEMENT_MESSAGES)
