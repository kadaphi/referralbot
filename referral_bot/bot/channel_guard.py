"""
bot/channel_guard.py — Detects when a user leaves a required channel,
warns them with a 5-minute window to rejoin, then bans if they don't.
"""
import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database.db import get_conn, get_setting
from database.users import get_user, ban_user
from utils.helpers import check_channel_membership

ADMIN_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "6402264162"))
REJOIN_WINDOW_SECONDS = 300  # 5 minutes

# Map channel_id -> invite link (populated from env + DB at runtime)
# We fetch invite links dynamically via bot.export_chat_invite_link
_channel_link_cache: dict[int, str] = {}


async def get_channel_invite_link(bot, channel_id: int) -> str:
    """Get or cache a channel's invite link."""
    if channel_id in _channel_link_cache:
        return _channel_link_cache[channel_id]
    try:
        chat = await bot.get_chat(channel_id)
        link = chat.invite_link or await bot.export_chat_invite_link(channel_id)
        _channel_link_cache[channel_id] = link
        return link
    except Exception:
        return f"https://t.me/c/{str(channel_id).replace('-100', '')}"


async def chat_member_update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Fires when a user's membership status changes in any chat.
    We only care about required channels and verified bot users leaving.
    """
    result = update.chat_member
    if not result:
        return

    channel_id = result.chat.id
    user = result.new_chat_member.user
    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status

    # Only act on required channels
    required_ids_str = os.getenv("REQUIRED_CHANNEL_IDS", "")
    required_ids = [
        int(x.strip()) for x in required_ids_str.split(",") if x.strip()
    ]
    if channel_id not in required_ids:
        return

    # Only act if user was a member and just left/was kicked
    was_member = old_status in ("member", "administrator", "creator", "restricted")
    now_gone = new_status in ("left", "kicked")
    if not (was_member and now_gone):
        return

    # Only act on verified bot users (ignore random non-users)
    db_user = get_user(user.id)
    if not db_user or not db_user.get("is_verified") or db_user.get("is_banned"):
        return

    # Get channel info for the alert
    channel_name = result.chat.title or f"Channel {channel_id}"
    invite_link = await get_channel_invite_link(context.bot, channel_id)

    # Check if there are other missing channels too
    all_joined, missing_ids = await check_channel_membership(context.bot, user.id)
    # Build list of all channels they're missing (including this one)
    missing_links = []
    for mid in missing_ids:
        mname = ""
        try:
            mchat = await context.bot.get_chat(mid)
            mname = mchat.title or f"Channel {mid}"
        except Exception:
            mname = f"Channel {mid}"
        mlink = await get_channel_invite_link(context.bot, mid)
        missing_links.append((mname, mlink))

    # If somehow they're still showing as member everywhere, do nothing
    if not missing_links:
        return

    # Build the warning message
    if len(missing_links) == 1:
        ch_name, ch_link = missing_links[0]
        channels_text = f"• <a href='{ch_link}'>{ch_name}</a>"
        left_phrase = "you left one of our required channels"
    else:
        channels_text = "\n".join(
            f"• <a href='{lnk}'>{nm}</a>" for nm, lnk in missing_links
        )
        left_phrase = f"you left {len(missing_links)} required channels"

    warning_msg_text = (
        f"⚠️ <b>Channel Membership Alert</b>\n\n"
        f"Hey {user.first_name}, it looks like {left_phrase}:\n\n"
        f"{channels_text}\n\n"
        f"⏳ You have <b>5 minutes</b> to rejoin or your account will be <b>automatically banned</b>.\n\n"
        f"Please rejoin now to keep your account active! 👇"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔗 Rejoin {nm}", url=lnk)]
        for nm, lnk in missing_links
    ] + [
        [InlineKeyboardButton("✅ I've Rejoined", callback_data="check_rejoin")]
    ])

    try:
        sent = await context.bot.send_message(
            user.id,
            warning_msg_text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
    except Exception as e:
        print(f"[ChannelGuard] Could not warn user {user.id}: {e}")
        return

    # Notify admin
    try:
        await context.bot.send_message(
            ADMIN_ID,
            f"⚠️ <b>Channel Leave Detected</b>\n\n"
            f"User: @{user.username or user.first_name} (<code>{user.id}</code>)\n"
            f"Left: <b>{channel_name}</b>\n"
            f"Status: Warned — 5 min window started.",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    # Schedule ban check after 5 minutes
    context.application.create_task(
        _ban_if_not_rejoined(
            bot=context.bot,
            user_id=user.id,
            username=user.username or user.first_name,
            warning_message_id=sent.message_id,
            missing_links=missing_links,
        )
    )


async def _ban_if_not_rejoined(bot, user_id: int, username: str,
                                warning_message_id: int, missing_links: list):
    """Wait 5 minutes, then check membership. Ban if still missing."""
    await asyncio.sleep(REJOIN_WINDOW_SECONDS)

    # Re-check membership
    required_ids_str = os.getenv("REQUIRED_CHANNEL_IDS", "")
    required_ids = [
        int(x.strip()) for x in required_ids_str.split(",") if x.strip()
    ]

    still_missing = []
    for cid in required_ids:
        try:
            member = await bot.get_chat_member(cid, user_id)
            if member.status in ("left", "kicked", "banned"):
                still_missing.append(cid)
        except Exception:
            still_missing.append(cid)

    if not still_missing:
        # User rejoined — send confirmation
        try:
            await bot.edit_message_reply_markup(
                chat_id=user_id,
                message_id=warning_message_id,
                reply_markup=None,
            )
            await bot.send_message(
                user_id,
                "✅ <b>You're good!</b> Thanks for rejoining. Your account remains active.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    # Still missing — ban the user
    ban_user(user_id, "Left required channel and did not rejoin within 5 minutes")

    # Edit the warning message
    try:
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=warning_message_id,
            text=(
                "🚫 <b>Account Banned</b>\n\n"
                "You did not rejoin the required channel(s) within 5 minutes.\n\n"
                "Your account has been banned. Contact support if you believe this is a mistake."
            ),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        try:
            await bot.send_message(
                user_id,
                "🚫 <b>Account Banned</b>\n\nYou did not rejoin the required channels within 5 minutes.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    # Notify admin
    try:
        missing_names = []
        for cid in still_missing:
            try:
                chat = await bot.get_chat(cid)
                missing_names.append(chat.title or str(cid))
            except Exception:
                missing_names.append(str(cid))

        await bot.send_message(
            ADMIN_ID,
            f"🚫 <b>User Auto-Banned</b>\n\n"
            f"User: @{username} (<code>{user_id}</code>)\n"
            f"Reason: Did not rejoin required channels within 5 minutes.\n"
            f"Missing channels: {', '.join(missing_names)}",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


async def check_rejoin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User taps 'I've Rejoined' button."""
    query = update.callback_query
    user = query.from_user
    await query.answer()

    all_joined, missing = await check_channel_membership(context.bot, user.id)

    if all_joined:
        await query.edit_message_text(
            "✅ <b>Verified!</b> You've rejoined all required channels. Your account is safe! 🎉",
            parse_mode=ParseMode.HTML,
        )
    else:
        # Show which ones are still missing
        missing_links = []
        for mid in missing:
            try:
                mchat = await context.bot.get_chat(mid)
                mname = mchat.title or f"Channel {mid}"
            except Exception:
                mname = f"Channel {mid}"
            mlink = await get_channel_invite_link(context.bot, mid)
            missing_links.append((mname, mlink))

        channels_text = "\n".join(
            f"• <a href='{lnk}'>{nm}</a>" for nm, lnk in missing_links
        )
        await query.answer(
            "⚠️ You're still missing some channels! Rejoin them to save your account.",
            show_alert=True,
        )
        await query.edit_message_text(
            f"⚠️ <b>Still Missing:</b>\n\n{channels_text}\n\n"
            f"Please join all channels above and tap the button again!",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🔗 Rejoin {nm}", url=lnk)]
                for nm, lnk in missing_links
            ] + [
                [InlineKeyboardButton("✅ I've Rejoined", callback_data="check_rejoin")]
            ]),
            disable_web_page_preview=True,
        )
