"""
bot/handlers.py — Core bot handlers: start, onboarding, main menu
"""
import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database.db import get_conn, get_setting, set_setting
from database.users import get_user, create_user, get_all_users
from database.referrals import (
    record_referral, get_user_referral_count, get_leaderboard,
    get_top3, is_user_in_top3, get_user_rank, get_weekly_referrals_2weeks
)
from utils.helpers import (
    check_channel_membership, generate_referral_link,
    generate_verification_token, is_maintenance, is_withdrawal_open,
    get_encouragement
)
from bot.admin import notify_admin_new_user, is_admin

VPS_IP = os.getenv("VPS_IP", "localhost")
WEB_PORT = os.getenv("WEB_PORT", "5000")
FOLDER_INVITE_LINK = os.getenv("FOLDER_INVITE_LINK", "")


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Statistics", callback_data="menu_stats"),
         InlineKeyboardButton("👥 Referrals", callback_data="menu_referrals")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="menu_withdraw"),
         InlineKeyboardButton("📜 Rules", callback_data="menu_rules")],
        [InlineKeyboardButton("📣 Advertise", callback_data="menu_ads"),
         InlineKeyboardButton("🆘 Support", callback_data="menu_support")],
    ])


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message

    # Delete the /start message for clean UX
    try:
        await msg.delete()
    except Exception:
        pass

    # Maintenance check (skip for admin)
    if is_maintenance() and not is_admin(user.id):
        await context.bot.send_message(
            user.id,
            "🔧 <b>Bot Maintenance</b>\n\nWe're currently performing maintenance. Please check back soon!",
            parse_mode=ParseMode.HTML,
        )
        return

    # Check if already fully registered
    db_user = get_user(user.id)
    if db_user and db_user.get("is_verified") and not db_user.get("is_banned"):
        await show_main_menu(context.bot, user.id)
        return

    if db_user and db_user.get("is_banned"):
        await context.bot.send_message(
            user.id,
            "🚫 Your account has been banned. Contact support if you think this is a mistake.",
        )
        return

    # Extract referral param
    referred_by = None
    args = context.args
    if args and args[0].startswith("ref_"):
        try:
            ref_id = int(args[0][4:])
            if ref_id != user.id:
                referred_by = ref_id
        except ValueError:
            pass

    context.user_data["referred_by"] = referred_by

    # Step 1: Show welcome / force-join screen
    await show_welcome_screen(context.bot, user)


async def show_welcome_screen(bot, user):
    welcome_text = get_setting("welcome_text")
    folder_link = get_setting("folder_invite_link") or FOLDER_INVITE_LINK
    image_file_id = get_setting("welcome_image_file_id")

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(" Join Our Channel ", url=folder_link)],
        [InlineKeyboardButton("✅ Proceed", callback_data="onboard_proceed")],
    ])

    try:
       greeting = f"👮 <b>Hello Dear</b> {user.full_name}!\n\n{welcome_text}"
        if image_file_id:
            await bot.send_photo(
                user.id,
                photo=image_file_id,
                caption=greeting,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        else:
            await bot.send_message(
                user.id,
                greeting,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
    except Exception as e:
        print(f"Error sending welcome: {e}")


async def onboard_proceed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if is_maintenance() and not is_admin(user.id):
        await query.edit_message_caption(
            caption="🔧 Bot is under maintenance. Please try again later."
        )
        return

    # Check channel membership
    all_joined, missing = await check_channel_membership(context.bot, user.id)
    if not all_joined:
        folder_link = get_setting("folder_invite_link") or FOLDER_INVITE_LINK
        await query.answer(
            "⚠️ Please join all required channels first!",
            show_alert=True,
        )
        return

    # Delete the welcome message
    try:
        await query.message.delete()
    except Exception:
        pass

    # Generate verification token
    token = generate_verification_token()
    referred_by = context.user_data.get("referred_by")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO pending_verifications (token, telegram_id, full_name, referred_by)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (token) DO NOTHING
    """, (token, user.id, user.full_name, referred_by))

    # Pre-insert user with username (for lookup during verification)
    cur.execute("""
        INSERT INTO users (telegram_id, username, full_name, referred_by, is_verified)
        VALUES (%s, %s, %s, %s, FALSE)
        ON CONFLICT (telegram_id) DO UPDATE SET username = EXCLUDED.username, full_name = EXCLUDED.full_name
    """, (user.id, user.username, user.full_name, referred_by))

    conn.commit(); cur.close(); conn.close()

    verify_url = f"http://{VPS_IP}:{WEB_PORT}/verify/{token}"

    await context.bot.send_message(
        user.id,
        "🔐 <b>Identity Verification Required</b>\n\n"
        "To keep our referral program fair and prevent abuse, we need to verify you're a unique user.\n\n"
        "⚠️ <b>Important:</b> Make sure your VPN is <b>OFF</b> before clicking the link.\n\n"
        "Click the button below to complete verification:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔐 Verify Now", url=verify_url)],
            [InlineKeyboardButton("✅ I've Verified", callback_data="check_verified")],
        ]),
    )

    # Start polling for verification in background
    context.application.create_task(
        poll_for_verification(context.bot, user.id, token, referred_by, context)
    )


async def poll_for_verification(bot, user_id: int, token: str, referred_by: int, context):
    """Poll DB every 3s for up to 10 minutes to check if user completed web verification."""
    for _ in range(200):  # 200 * 3s = 10 minutes
        await asyncio.sleep(3)

        # Check if verified flag set by web app
        key = f"verified_{user_id}"
        val = get_setting(key)
        if val == "1":
            set_setting(key, "0")  # Clear flag

            db_user = get_user(user_id)
            if db_user and db_user.get("is_verified"):
                # Credit referral
                if referred_by:
                    record_referral(referred_by, user_id)
                    try:
                        ref_count = get_user_referral_count(referred_by)
                        bot_me = await bot.get_me()
                        await bot.send_message(
                            referred_by,
                            f"🎉 <b>New Referral!</b>\n\n"
                            f"Someone joined using your link!\n"
                            f"You now have <b>{ref_count}</b> total referral(s).",
                            parse_mode=ParseMode.HTML,
                        )
                    except Exception:
                        pass

                # Notify admin
                await notify_admin_new_user(bot, db_user)

                # Show main menu
                await bot.send_message(
                    user_id,
                    "✅ <b>Verification Complete!</b>\n\nWelcome aboard! 🎉",
                    parse_mode=ParseMode.HTML,
                )
                await show_main_menu(bot, user_id)
            return

        # Check ban flag
        ban_key = f"ban_notify_{user_id}"
        ban_val = get_setting(ban_key)
        if ban_val == "1":
            set_setting(ban_key, "0")
            try:
                await bot.send_message(
                    user_id,
                    "🚫 <b>Account Banned</b>\n\nMultiple accounts detected from your IP address.",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            return


async def check_verified_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    db_user = get_user(user.id)
    if db_user and db_user.get("is_verified") and not db_user.get("is_banned"):
        try:
            await query.message.delete()
        except Exception:
            pass
        await show_main_menu(context.bot, user.id)
    else:
        await query.answer("⏳ Verification not complete yet. Please finish the web verification first.", show_alert=True)


async def show_main_menu(bot, user_id: int):
    text = get_setting("main_menu_text") or "🎉 Welcome to Aurora Referral Bot!"
    await bot.send_message(
        user_id,
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(),
    )


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if is_maintenance() and not is_admin(user.id):
        await query.answer("🔧 Bot is under maintenance.", show_alert=True)
        return

    db_user = get_user(user.id)
    if not db_user or not db_user.get("is_verified"):
        await query.answer("Please complete verification first.", show_alert=True)
        return
    if db_user.get("is_banned"):
        await query.answer("🚫 Your account is banned.", show_alert=True)
        return

    data = query.data

    if data == "menu_stats":
        await show_statistics(query, user)
    elif data == "menu_referrals":
        await show_referrals(query, user, context)
    elif data == "menu_withdraw":
        await show_withdraw(query, user, context)
    elif data == "menu_rules":
        await show_rules(query)
    elif data == "menu_ads":
        await show_ads(query, context)
    elif data == "menu_support":
        await show_support(query, context)
    elif data == "menu_back":
        text = get_setting("main_menu_text") or "🎉 Welcome back!"
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard(),
        )


async def show_statistics(query, user):
    board = get_leaderboard(50)
    if not board:
        text = "📊 <b>Statistics</b>\n\nNo data yet. Be the first to refer someone!"
    else:
        lines = []
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for i, entry in enumerate(board[:50], 1):
            name = entry["display_name"] or "Anonymous"
            uname = f"@{entry['username']}" if entry.get("username") else name
            medal = medals.get(i, f"{i}.")
            seeded_tag = " ⭐" if entry.get("is_seeded") else ""
            lines.append(f"{medal} {uname} — <b>{entry['referral_count']}</b> refs{seeded_tag}")

        # Split if too long (Telegram 4096 char limit)
        header = "📊 <b>Top Referrers This Week</b>\n🏆 Top 3 win $100, $50, $20!\n\n"
        body = "\n".join(lines)
        text = header + body
        if len(text) > 4000:
            text = header + "\n".join(lines[:30]) + f"\n\n<i>...and {len(board)-30} more</i>"

    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]]),
    )


async def show_referrals(query, user, context):
    count = get_user_referral_count(user.id)
    rank = get_user_rank(user.id)
    rank_text = f"#{rank}" if rank else "Not ranked yet"

    bot_me = await context.bot.get_me()
    ref_link = generate_referral_link(bot_me.username, user.id)

    text = (
        f"👥 <b>Your Referrals</b>\n\n"
        f"Total Referrals: <b>{count}</b>\n"
        f"Your Rank: <b>{rank_text}</b>\n\n"
        f"🔗 <b>Your Referral Link:</b>\n<code>{ref_link}</code>\n\n"
        f"Share this link to earn referrals!\n"
        f"Top 3 this week win <b>$100</b>, <b>$50</b>, <b>$20</b>! 🏆"
    )
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]]),
    )


async def show_withdraw(query, user, context):
    if not is_withdrawal_open():
        await query.edit_message_text(
            "💸 <b>Withdrawal</b>\n\n"
            "🔒 Withdrawals are currently closed.\n\n"
            "The withdrawal window opens every weekend. Stay tuned!\n"
            "In the meantime, keep referring to secure your spot in the top 3! 🔥",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]]),
        )
        return

    db_user = get_user(user.id)
    if not db_user.get("username"):
        await query.edit_message_text(
            "💸 <b>Withdrawal</b>\n\n"
            "⚠️ You need a <b>Telegram username</b> to withdraw.\n\n"
            "Please set a username in Telegram settings and try again.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]]),
        )
        return

    if not is_user_in_top3(user.id):
        encouragement = get_encouragement()
        rank = get_user_rank(user.id)
        rank_text = f"#{rank}" if rank else "unranked"

        await query.edit_message_text(
            f"💸 <b>Withdrawal</b>\n\n"
            f"❌ Sorry, you're currently <b>{rank_text}</b> — not in the top 3.\n\n"
            f"{encouragement}\n\n"
            f"💡 Stay <b>ACTIVE</b> and keep referring to climb the leaderboard!\n"
            f"Even if you can't reach top 3, aim to be in the <b>top 50</b> and stay <b>ACTIVE</b> till the end of the event!",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]]),
        )
        return

    # User is top 3
    top3 = get_top3()
    rank = get_user_rank(user.id)
    prizes = {1: "$100", 2: "$50", 3: "$20"}
    prize = prizes.get(rank, "Prize")

    await query.edit_message_text(
        f"💸 <b>Withdrawal</b>\n\n"
        f"🎉 Congratulations! You're <b>#{rank}</b> this week!\n"
        f"Your prize: <b>{prize}</b> 🏆\n\n"
        f"Please send your <b>TRX wallet address</b> to proceed:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]]),
    )
    context.user_data["state"] = "await_trx_address"
    context.user_data["withdraw_rank"] = rank


async def show_rules(query):
    rules = get_setting("rules_text") or (
        "📜 <b>BOT RULES</b>\n\n"
        "1. No multi-accounts — you will be permanently banned.\n"
        "2. No VPN during verification.\n"
        "3. Must be <b>ACTIVE</b>: refer at least 5 users per week.\n"
        "   If after 2 weeks you have fewer than 8 referrals, you won't be counted.\n"
        "4. Withdrawal is only available to top 3 each week.\n"
        "5. Self-referral attempts = 3 strikes = permanent ban.\n"
        "6. Respect all members and support staff."
    )
    await query.edit_message_text(
        rules, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]]),
    )


async def show_ads(query, context):
    await query.edit_message_text(
        "📣 <b>Advertise With Us</b>\n\n"
        "Want to promote your project to our community?\n\n"
        "Tell us about your project below. You can:\n"
        "• Send a text description\n"
        "• Attach images, documents, or any media\n\n"
        "📩 Send your project details now:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]]),
    )
    context.user_data["state"] = "await_ad_content"


async def show_support(query, context):
    await query.edit_message_text(
        "🆘 <b>Support</b>\n\n"
        "Need help? Send us your message and our team will get back to you.\n\n"
        "📩 Type your support message now:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]]),
    )
    context.user_data["state"] = "await_support_msg"


async def user_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user messages during conversation states."""
    user = update.effective_user
    msg = update.message
    state = context.user_data.get("state")

    if is_maintenance() and not is_admin(user.id):
        return

    db_user = get_user(user.id)
    if not db_user or not db_user.get("is_verified") or db_user.get("is_banned"):
        return

    if state == "await_trx_address":
        trx_address = (msg.text or "").strip()
        if len(trx_address) < 20:
            await msg.reply_text(
                "❌ Invalid TRX address. Please enter a valid TRON wallet address.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="menu_back")]]),
            )
            return

        rank = context.user_data.get("withdraw_rank", 0)
        prizes = {1: 100, 2: 50, 3: 20}
        amount = prizes.get(rank, 0)
        week, year = __import__('utils.helpers', fromlist=['get_week_info']).get_week_info()

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO withdrawals (user_id, trx_address, amount_usd, rank_at_submit, week_number, year)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (user.id, trx_address, amount, rank, week, year))
        conn.commit(); cur.close(); conn.close()

        # Notify admin
        from bot.admin import ADMIN_ID
        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"💸 <b>Withdrawal Request</b>\n\n"
                f"User: @{user.username or user.full_name} (<code>{user.id}</code>)\n"
                f"Rank: #{rank} — ${amount}\n"
                f"TRX Address: <code>{trx_address}</code>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

        context.user_data.pop("state", None)
        context.user_data.pop("withdraw_rank", None)

        await msg.reply_text(
            "⏳ <b>Withdrawal Processing</b>\n\n"
            "Your withdrawal request has been submitted!\n"
            "Our team will process it shortly. Thank you for participating! 🙏",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="menu_back")]]),
        )

    elif state == "await_support_msg":
        message_text = msg.text or "[Media message]"
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO support_tickets (user_id, message) VALUES (%s, %s)",
            (user.id, message_text)
        )
        conn.commit(); cur.close(); conn.close()

        from bot.admin import ADMIN_ID
        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"🆘 <b>Support Request</b>\n\n"
                f"From: @{user.username or user.full_name} (<code>{user.id}</code>)\n\n"
                f"{message_text}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

        context.user_data.pop("state", None)
        await msg.reply_text(
            "✅ <b>Support message sent!</b>\n\nOur team will get back to you soon.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="menu_back")]]),
        )

    elif state == "await_ad_content":
        # Ask if they want to attach media
        ad_text = msg.text or ""
        file_id = None
        file_type = None

        if msg.photo:
            file_id = msg.photo[-1].file_id; file_type = "photo"
        elif msg.document:
            file_id = msg.document.file_id; file_type = "document"
        elif msg.video:
            file_id = msg.video.file_id; file_type = "video"

        if ad_text and not file_id:
            # Text only — ask if they want to attach
            context.user_data["ad_text"] = ad_text
            context.user_data["state"] = "await_ad_attach_confirm"
            await msg.reply_text(
                "📎 Would you like to attach an image or file alongside your message?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Yes, attach media", callback_data="ad_attach_yes"),
                     InlineKeyboardButton("❌ No, send as is", callback_data="ad_attach_no")],
                ]),
            )
        else:
            await _submit_ad(context, msg, user, ad_text, file_id, file_type)

    elif state == "await_ad_media":
        file_id = None
        file_type = None
        if msg.photo:
            file_id = msg.photo[-1].file_id; file_type = "photo"
        elif msg.document:
            file_id = msg.document.file_id; file_type = "document"
        elif msg.video:
            file_id = msg.video.file_id; file_type = "video"
        else:
            await msg.reply_text("❌ Please send a photo, video, or document.")
            return
        ad_text = context.user_data.get("ad_text", "")
        await _submit_ad(context, msg, user, ad_text, file_id, file_type)


async def _submit_ad(context, msg, user, ad_text, file_id, file_type):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO ad_requests (user_id, message, file_id, file_type) VALUES (%s, %s, %s, %s)",
        (user.id, ad_text, file_id, file_type)
    )
    conn.commit(); cur.close(); conn.close()

    from bot.admin import ADMIN_ID
    try:
        text = (
            f"📣 <b>Ad Request</b>\n\n"
            f"From: @{user.username or user.full_name} (<code>{user.id}</code>)\n\n"
            f"{ad_text}"
        )
        if file_id and file_type == "photo":
            await context.bot.send_photo(ADMIN_ID, file_id, caption=text, parse_mode=ParseMode.HTML)
        elif file_id and file_type == "document":
            await context.bot.send_document(ADMIN_ID, file_id, caption=text, parse_mode=ParseMode.HTML)
        elif file_id and file_type == "video":
            await context.bot.send_video(ADMIN_ID, file_id, caption=text, parse_mode=ParseMode.HTML)
        else:
            await context.bot.send_message(ADMIN_ID, text, parse_mode=ParseMode.HTML)
    except Exception:
        pass

    context.user_data.pop("state", None)
    context.user_data.pop("ad_text", None)
    await msg.reply_text(
        "✅ <b>Ad request submitted!</b>\n\nOur team will review your project and get back to you.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="menu_back")]]),
    )


async def ad_attach_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "ad_attach_yes":
        await query.edit_message_text(
            "📎 Send your media (photo, document, or video) now:"
        )
        context.user_data["state"] = "await_ad_media"
    elif data == "ad_attach_no":
        ad_text = context.user_data.get("ad_text", "")
        await _submit_ad(context, query.message, query.from_user, ad_text, None, None)
        await query.edit_message_text(
            "✅ <b>Ad request submitted!</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="menu_back")]]),
        )
        context.user_data.pop("state", None)
        context.user_data.pop("ad_text", None)
