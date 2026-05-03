"""
bot/admin.py — Admin panel (only accessible by ADMIN_TELEGRAM_ID)
"""
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode
from database.db import get_setting, set_setting
from database.users import (
    get_all_users, ban_user, unban_user, get_user, get_user_count
)
from database.referrals import upsert_seeded, delete_seeded, get_leaderboard
from utils.helpers import is_maintenance

ADMIN_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "6402264162"))

# Conversation states
(
    ADMIN_MAIN, AWAIT_BROADCAST_CONTENT, AWAIT_BROADCAST_CONFIRM,
    AWAIT_WELCOME_IMAGE, AWAIT_WELCOME_TEXT, AWAIT_WELCOME_LINK,
    AWAIT_MAIN_MENU_TEXT, AWAIT_BAN_ID, AWAIT_UNBAN_ID,
    AWAIT_MSG_USER_ID, AWAIT_MSG_USER_TEXT,
    AWAIT_SEED_POS, AWAIT_SEED_NAME, AWAIT_SEED_USER, AWAIT_SEED_COUNT,
    AWAIT_RULES_TEXT, AWAIT_SUPPORT_REPLY,
) = range(17)


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


def admin_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast"),
         InlineKeyboardButton("🖼 Welcome Settings", callback_data="adm_welcome")],
        [InlineKeyboardButton("🚫 Ban User", callback_data="adm_ban"),
         InlineKeyboardButton("✅ Unban User", callback_data="adm_unban")],
        [InlineKeyboardButton("💬 Message User", callback_data="adm_msg_user"),
         InlineKeyboardButton("📊 Bot Stats", callback_data="adm_stats")],
        [InlineKeyboardButton("🌱 Seed Leaderboard", callback_data="adm_seed"),
         InlineKeyboardButton("📜 Edit Rules", callback_data="adm_rules")],
        [InlineKeyboardButton("🔧 Maintenance", callback_data="adm_maintenance"),
         InlineKeyboardButton("💸 Toggle Withdrawal", callback_data="adm_withdrawal")],
        [InlineKeyboardButton("📝 Edit Main Menu Text", callback_data="adm_main_text"),
         InlineKeyboardButton("📋 View Users", callback_data="adm_users")],
    ])


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # Hard block non-admins
    if not is_admin(user.id):
        try:
            await update.message.delete()
        except Exception:
            pass
        return

    await update.message.reply_text(
        "👑 <b>Admin Panel</b>\n\nWelcome back, Boss. What would you like to do?",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_main_keyboard(),
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    if not is_admin(user.id):
        await query.answer("⛔ Unauthorized", show_alert=True)
        return
    await query.answer()
    data = query.data

    if data == "adm_stats":
        total = get_user_count()
        board = get_leaderboard(3)
        top_text = "\n".join(
            f"{i+1}. {e['display_name']} — {e['referral_count']} refs"
            for i, e in enumerate(board[:3])
        ) or "No data yet"
        await query.edit_message_text(
            f"📊 <b>Bot Statistics</b>\n\n"
            f"👥 Total Users: <b>{total}</b>\n\n"
            f"🏆 <b>Top 3 This Week:</b>\n{top_text}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_back")]]),
        )

    elif data == "adm_maintenance":
        current = get_setting("maintenance_mode")
        new_val = "0" if current == "1" else "1"
        set_setting("maintenance_mode", new_val)
        status = "🔴 ON (bot locked)" if new_val == "1" else "🟢 OFF (bot active)"
        await query.edit_message_text(
            f"🔧 <b>Maintenance Mode</b>: {status}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_back")]]),
        )

    elif data == "adm_withdrawal":
        current = get_setting("withdrawal_open")
        new_val = "0" if current == "1" else "1"
        set_setting("withdrawal_open", new_val)
        status = "🟢 OPEN" if new_val == "1" else "🔴 CLOSED"
        await query.edit_message_text(
            f"💸 <b>Withdrawal Window</b>: {status}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_back")]]),
        )

    elif data == "adm_back":
        await query.edit_message_text(
            "👑 <b>Admin Panel</b>\n\nWhat would you like to do?",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_main_keyboard(),
        )

    elif data == "adm_broadcast":
        context.user_data["broadcast"] = {}
        await query.edit_message_text(
            "📢 <b>Broadcast Message</b>\n\n"
            "Send me the content to broadcast.\n"
            "You can send: text, photo, video, audio, document, or photo+caption.\n\n"
            "Send /cancel to abort.",
            parse_mode=ParseMode.HTML,
        )
        context.user_data["state"] = "await_broadcast"

    elif data == "adm_welcome":
        await query.edit_message_text(
            "🖼 <b>Welcome Settings</b>\n\nWhat do you want to edit?",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🖼 Change Image", callback_data="adm_w_img"),
                 InlineKeyboardButton("📝 Change Text", callback_data="adm_w_text")],
                [InlineKeyboardButton("🔗 Change Join Link", callback_data="adm_w_link"),
                 InlineKeyboardButton("⬅️ Back", callback_data="adm_back")],
            ]),
        )

    elif data == "adm_w_img":
        await query.edit_message_text(
            "🖼 Send me the new welcome image (photo):",
            parse_mode=ParseMode.HTML,
        )
        context.user_data["state"] = "await_welcome_image"

    elif data == "adm_w_text":
        current = get_setting("welcome_text")
        await query.edit_message_text(
            f"📝 Current welcome text:\n\n{current}\n\n"
            "Send me the new welcome text (HTML formatting supported):",
            parse_mode=ParseMode.HTML,
        )
        context.user_data["state"] = "await_welcome_text"

    elif data == "adm_w_link":
        current = get_setting("folder_invite_link")
        await query.edit_message_text(
            f"🔗 Current join link:\n{current}\n\nSend me the new folder invite link:",
        )
        context.user_data["state"] = "await_welcome_link"

    elif data == "adm_main_text":
        current = get_setting("main_menu_text")
        await query.edit_message_text(
            f"📝 Current main menu text:\n\n{current}\n\n"
            "Send me the new main menu text (HTML supported):",
            parse_mode=ParseMode.HTML,
        )
        context.user_data["state"] = "await_main_menu_text"

    elif data == "adm_ban":
        await query.edit_message_text(
            "🚫 Send me the <b>Telegram ID</b> of the user to ban, followed by the reason.\n"
            "Format: <code>123456789 reason here</code>",
            parse_mode=ParseMode.HTML,
        )
        context.user_data["state"] = "await_ban"

    elif data == "adm_unban":
        await query.edit_message_text(
            "✅ Send me the <b>Telegram ID</b> of the user to unban:",
            parse_mode=ParseMode.HTML,
        )
        context.user_data["state"] = "await_unban"

    elif data == "adm_msg_user":
        await query.edit_message_text(
            "💬 Send me the <b>Telegram ID</b> of the user to message:",
            parse_mode=ParseMode.HTML,
        )
        context.user_data["state"] = "await_msg_user_id"

    elif data == "adm_seed":
        await query.edit_message_text(
            "🌱 <b>Seed Leaderboard Entry</b>\n\n"
            "Send position (1 or 2), display name, @username, and referral count.\n"
            "Format: <code>1 John Doe @johndoe 45</code>\n\n"
            "To remove a seeded entry: <code>remove 1</code>",
            parse_mode=ParseMode.HTML,
        )
        context.user_data["state"] = "await_seed"

    elif data == "adm_rules":
        current = get_setting("rules_text")
        await query.edit_message_text(
            f"📜 Current rules:\n\n{current}\n\n"
            "Send me the new rules text (HTML supported):",
            parse_mode=ParseMode.HTML,
        )
        context.user_data["state"] = "await_rules"

    elif data == "adm_users":
        users = get_all_users()
        total = len(users)
        banned = sum(1 for u in users if u.get("is_banned"))
        text = (
            f"📋 <b>User Overview</b>\n\n"
            f"Total verified: <b>{total}</b>\n"
            f"Banned: <b>{banned}</b>\n"
            f"Active: <b>{total - banned}</b>"
        )
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_back")]]),
        )

    elif data.startswith("adm_confirm_broadcast_"):
        await _do_broadcast(update, context, query)

    elif data == "adm_cancel_broadcast":
        context.user_data.pop("broadcast", None)
        context.user_data.pop("state", None)
        await query.edit_message_text("❌ Broadcast cancelled.")


async def admin_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text/media replies during admin conversation states."""
    user = update.effective_user
    if not is_admin(user.id):
        return

    state = context.user_data.get("state")
    msg = update.message

    if state == "await_broadcast":
        bcast = context.user_data.setdefault("broadcast", {})
        if msg.photo:
            bcast["type"] = "photo"
            bcast["file_id"] = msg.photo[-1].file_id
            bcast["caption"] = msg.caption or ""
        elif msg.video:
            bcast["type"] = "video"
            bcast["file_id"] = msg.video.file_id
            bcast["caption"] = msg.caption or ""
        elif msg.audio:
            bcast["type"] = "audio"
            bcast["file_id"] = msg.audio.file_id
            bcast["caption"] = msg.caption or ""
        elif msg.document:
            bcast["type"] = "document"
            bcast["file_id"] = msg.document.file_id
            bcast["caption"] = msg.caption or ""
        elif msg.voice:
            bcast["type"] = "voice"
            bcast["file_id"] = msg.voice.file_id
            bcast["caption"] = msg.caption or ""
        else:
            bcast["type"] = "text"
            bcast["text"] = msg.text or ""

        users = get_all_users(active_only=True)
        count = len(users)
        preview = bcast.get("text") or bcast.get("caption") or f"[{bcast['type']} media]"
        await msg.reply_text(
            f"📢 <b>Broadcast Preview</b>\n\n"
            f"Type: <b>{bcast['type']}</b>\n"
            f"Content: {preview[:200]}\n\n"
            f"Will be sent to <b>{count}</b> users.\n\nConfirm?",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Send", callback_data="adm_confirm_broadcast_go"),
                 InlineKeyboardButton("❌ Cancel", callback_data="adm_cancel_broadcast")],
            ]),
        )

    elif state == "await_welcome_image":
        if msg.photo:
            file_id = msg.photo[-1].file_id
            set_setting("welcome_image_file_id", file_id)
            context.user_data.pop("state", None)
            await msg.reply_text("✅ Welcome image updated!")
        else:
            await msg.reply_text("❌ Please send a photo.")

    elif state == "await_welcome_text":
        set_setting("welcome_text", msg.text or "")
        context.user_data.pop("state", None)
        await msg.reply_text("✅ Welcome text updated!")

    elif state == "await_welcome_link":
        set_setting("folder_invite_link", msg.text or "")
        context.user_data.pop("state", None)
        await msg.reply_text("✅ Folder invite link updated!")

    elif state == "await_main_menu_text":
        set_setting("main_menu_text", msg.text or "")
        context.user_data.pop("state", None)
        await msg.reply_text("✅ Main menu text updated!")

    elif state == "await_ban":
        parts = (msg.text or "").split(None, 2)
        if len(parts) < 2:
            await msg.reply_text("❌ Format: <code>telegram_id reason</code>", parse_mode=ParseMode.HTML)
            return
        try:
            target_id = int(parts[0])
            reason = parts[1] if len(parts) > 1 else "Admin ban"
        except ValueError:
            await msg.reply_text("❌ Invalid Telegram ID.")
            return
        ban_user(target_id, reason)
        # Notify target
        try:
            await context.bot.send_message(
                target_id,
                "🚫 Your account has been banned from this bot.\nContact support if you believe this is an error."
            )
        except Exception:
            pass
        context.user_data.pop("state", None)
        await msg.reply_text(f"✅ User <code>{target_id}</code> banned. Reason: {reason}", parse_mode=ParseMode.HTML)

    elif state == "await_unban":
        try:
            target_id = int(msg.text.strip())
        except ValueError:
            await msg.reply_text("❌ Invalid Telegram ID.")
            return
        unban_user(target_id)
        try:
            await context.bot.send_message(
                target_id,
                "✅ Your account has been unbanned. You can now use the bot again."
            )
        except Exception:
            pass
        context.user_data.pop("state", None)
        await msg.reply_text(f"✅ User <code>{target_id}</code> unbanned.", parse_mode=ParseMode.HTML)

    elif state == "await_msg_user_id":
        try:
            target_id = int(msg.text.strip())
        except ValueError:
            await msg.reply_text("❌ Invalid Telegram ID.")
            return
        context.user_data["msg_target"] = target_id
        context.user_data["state"] = "await_msg_user_text"
        await msg.reply_text(f"💬 Now send the message to deliver to user <code>{target_id}</code>:", parse_mode=ParseMode.HTML)

    elif state == "await_msg_user_text":
        target_id = context.user_data.get("msg_target")
        if not target_id:
            context.user_data.pop("state", None)
            return
        try:
            if msg.photo:
                await context.bot.send_photo(target_id, msg.photo[-1].file_id, caption=msg.caption or "")
            elif msg.document:
                await context.bot.send_document(target_id, msg.document.file_id, caption=msg.caption or "")
            else:
                await context.bot.send_message(target_id, msg.text or "", parse_mode=ParseMode.HTML)
            await msg.reply_text(f"✅ Message delivered to <code>{target_id}</code>.", parse_mode=ParseMode.HTML)
        except Exception as e:
            await msg.reply_text(f"❌ Failed to deliver: {e}")
        context.user_data.pop("state", None)
        context.user_data.pop("msg_target", None)

    elif state == "await_seed":
        text = (msg.text or "").strip()
        if text.startswith("remove "):
            try:
                pos = int(text.split()[1])
                delete_seeded(pos)
                await msg.reply_text(f"✅ Seeded entry at position {pos} removed.")
            except Exception as e:
                await msg.reply_text(f"❌ Error: {e}")
        else:
            parts = text.split()
            if len(parts) < 4:
                await msg.reply_text("❌ Format: <code>position DisplayName @username referral_count</code>", parse_mode=ParseMode.HTML)
                return
            try:
                pos = int(parts[0])
                count = int(parts[-1])
                username = parts[-2].lstrip("@")
                display_name = " ".join(parts[1:-2])
                upsert_seeded(pos, display_name, username, count)
                await msg.reply_text(f"✅ Seeded position {pos}: <b>{display_name}</b> @{username} — {count} refs", parse_mode=ParseMode.HTML)
            except Exception as e:
                await msg.reply_text(f"❌ Error: {e}")
        context.user_data.pop("state", None)

    elif state == "await_rules":
        set_setting("rules_text", msg.text or "")
        context.user_data.pop("state", None)
        await msg.reply_text("✅ Rules updated!")


async def _do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, query):
    bcast = context.user_data.get("broadcast", {})
    if not bcast:
        await query.edit_message_text("❌ No broadcast content found.")
        return

    users = get_all_users(active_only=True)
    sent = 0
    failed = 0
    await query.edit_message_text(f"📤 Sending to {len(users)} users...")

    for u in users:
        try:
            uid = u["telegram_id"]
            btype = bcast.get("type")
            if btype == "text":
                await context.bot.send_message(uid, bcast["text"], parse_mode=ParseMode.HTML)
            elif btype == "photo":
                await context.bot.send_photo(uid, bcast["file_id"], caption=bcast.get("caption"), parse_mode=ParseMode.HTML)
            elif btype == "video":
                await context.bot.send_video(uid, bcast["file_id"], caption=bcast.get("caption"), parse_mode=ParseMode.HTML)
            elif btype == "audio":
                await context.bot.send_audio(uid, bcast["file_id"], caption=bcast.get("caption"))
            elif btype == "document":
                await context.bot.send_document(uid, bcast["file_id"], caption=bcast.get("caption"), parse_mode=ParseMode.HTML)
            elif btype == "voice":
                await context.bot.send_voice(uid, bcast["file_id"])
            sent += 1
        except Exception:
            failed += 1

    context.user_data.pop("broadcast", None)
    context.user_data.pop("state", None)

    await context.bot.send_message(
        ADMIN_ID,
        f"📢 <b>Broadcast Complete</b>\n✅ Sent: {sent}\n❌ Failed: {failed}",
        parse_mode=ParseMode.HTML,
    )

async def notify_admin_new_user(bot, user_data: dict):
    """Send new user notification to admin."""
    tg_id = user_data.get("telegram_id")
    full_name = user_data.get("full_name", "Unknown")
    username = user_data.get("username") or "no username"
    
    text = (
        f"🚦 <b>New User</b> 🚦\n\n"
        f"👤 User = {full_name}\n"
        f"👤 Username = @{username}\n"
        f"🆔 User ID = <code>{tg_id}</code>\n"
        f"🔗 User Link = <a href='tg://user?id={tg_id}'>Click Here</a>"
    )
    try:
        await bot.send_message(ADMIN_ID, text, parse_mode=ParseMode.HTML)
    except Exception as e:
        print(f"Failed to notify admin: {e}")
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    context.user_data.clear()
    try:
        await update.message.delete()
    except Exception:
        pass
    await update.effective_chat.send_message(
        "👑 <b>Admin Panel</b>\n\nCancelled. What would you like to do?",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_main_keyboard(),
    )
