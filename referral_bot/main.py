"""
main.py — Bot entry point
"""
import os
import asyncio
import threading
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ChatMemberHandler, filters,
)
from telegram.constants import ParseMode

from database.db import init_db
from bot.handlers import (
    start_command, onboard_proceed, check_verified_callback,
    menu_callback, user_message_handler, ad_attach_callback,
)
from bot.admin import admin_command, admin_callback, admin_message_handler, is_admin, cancel_command
from bot.scheduler import setup_scheduler
from bot.channel_guard import chat_member_update_handler, check_rejoin_callback

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "6402264162"))


def run_flask():
    """Run Flask web server in a separate thread."""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from web.app import app
    port = int(os.getenv("WEB_PORT", 5000))
    print(f"🌐 Starting Flask verification server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


async def error_handler(update, context):
    """Log errors."""
    print(f"[ERROR] {context.error}")
    if update and update.effective_user and is_admin(update.effective_user.id):
        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"⚠️ <b>Bot Error</b>\n\n<code>{str(context.error)[:500]}</code>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


def main():
    # 1. Initialize DB
    print("🗄️  Initializing database...")
    init_db()

    # 2. Start Flask in background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # 3. Build Telegram application
    print("🤖 Starting Telegram bot...")
    app = Application.builder().token(BOT_TOKEN).build()

    # --- Command handlers ---
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("cancel", cancel_command))

    # --- Callback query handlers ---
    app.add_handler(CallbackQueryHandler(onboard_proceed, pattern="^onboard_proceed$"))
    app.add_handler(CallbackQueryHandler(check_verified_callback, pattern="^check_verified$"))
    app.add_handler(CallbackQueryHandler(check_rejoin_callback, pattern="^check_rejoin$"))
    app.add_handler(CallbackQueryHandler(ad_attach_callback, pattern="^ad_attach_"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^adm_"))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu_"))

    # --- Message handlers ---
    # Admin messages (admin state machine)
    app.add_handler(MessageHandler(
        filters.User(ADMIN_ID) & ~filters.COMMAND,
        _combined_message_handler,
    ))
    # User messages
    app.add_handler(MessageHandler(
        ~filters.User(ADMIN_ID) & ~filters.COMMAND,
        user_message_handler,
    ))

    # --- Channel member update handler (leave detection) ---
    app.add_handler(ChatMemberHandler(chat_member_update_handler, ChatMemberHandler.CHAT_MEMBER))

    # --- Error handler ---
    app.add_error_handler(error_handler)

    # 4. Start scheduler
    scheduler = setup_scheduler(app.bot)
    scheduler.start()
    print("⏰ Scheduler started.")

    # 5. Run bot
    print("✅ Bot is running! Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=["message", "callback_query", "chat_member"])


async def _combined_message_handler(update, context):
    """Route admin messages to admin handler first, then user handler."""
    state = context.user_data.get("state", "")
    # Admin states
    admin_states = {
        "await_broadcast", "await_welcome_image", "await_welcome_text",
        "await_welcome_link", "await_main_menu_text", "await_ban",
        "await_unban", "await_msg_user_id", "await_msg_user_text",
        "await_seed", "await_rules",
    }
    if state in admin_states:
        await admin_message_handler(update, context)
    else:
        # Admin might also be a regular user in the bot
        await user_message_handler(update, context)


if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN not set in .env file!")
        sys.exit(1)
    main()
