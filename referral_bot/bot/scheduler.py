"""
bot/scheduler.py — Scheduled jobs (APScheduler)
"""
import os
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from database.db import get_conn, get_setting, set_setting
from database.users import get_all_users
from database.referrals import get_leaderboard, get_top3, get_weekly_referrals_2weeks

ADMIN_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "6402264162"))
MIN_REFS_PER_WEEK = int(os.getenv("MIN_REFERRALS_PER_WEEK", 5))
MIN_REFS_2_WEEKS = int(os.getenv("MIN_REFERRALS_2_WEEKS", 8))


def setup_scheduler(bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")

    # Weekly activity check — every Monday at 00:01 UTC
    scheduler.add_job(
        weekly_activity_check,
        CronTrigger(day_of_week="mon", hour=0, minute=1),
        args=[bot],
        id="weekly_activity_check",
        replace_existing=True,
    )

    # Open withdrawal window — Friday 00:00 UTC
    scheduler.add_job(
        open_withdrawal_window,
        CronTrigger(day_of_week="fri", hour=0, minute=0),
        args=[bot],
        id="open_withdrawal",
        replace_existing=True,
    )

    # Close withdrawal window — Sunday 23:59 UTC
    scheduler.add_job(
        close_withdrawal_window,
        CronTrigger(day_of_week="sun", hour=23, minute=59),
        args=[bot],
        id="close_withdrawal",
        replace_existing=True,
    )

    # Weekly leaderboard announcement — Sunday 20:00 UTC
    scheduler.add_job(
        announce_weekly_winners,
        CronTrigger(day_of_week="sun", hour=20, minute=0),
        args=[bot],
        id="weekly_announcement",
        replace_existing=True,
    )

    return scheduler


async def weekly_activity_check(bot):
    """
    Every week: warn users who haven't referred enough.
    After 2 weeks of inactivity: flag them as inactive.
    """
    users = get_all_users(active_only=True)
    warned = 0
    flagged = 0

    for u in users:
        uid = u["telegram_id"]
        total_2w = get_weekly_referrals_2weeks(uid)

        if total_2w < MIN_REFS_2_WEEKS:
            # Check if they've been warned before
            warn_key = f"activity_warned_{uid}"
            already_warned = get_setting(warn_key) == "1"

            if not already_warned:
                # First warning
                set_setting(warn_key, "1")
                try:
                    await bot.send_message(
                        uid,
                        f"⚠️ <b>Activity Warning</b>\n\n"
                        f"You currently have <b>{total_2w}</b> referrals over the last 2 weeks.\n"
                        f"The minimum requirement to be counted is <b>{MIN_REFS_2_WEEKS}</b> referrals.\n\n"
                        f"To stay <b>ACTIVE</b>, you must refer at least <b>{MIN_REFS_PER_WEEK}</b> users per week.\n\n"
                        f"Even if you're in the top 50, you must remain <b>ACTIVE</b> to be eligible for prizes.\n\n"
                        f"Keep pushing! 💪",
                        parse_mode="HTML",
                    )
                    warned += 1
                except Exception:
                    pass
            else:
                # Already warned — flag as inactive
                conn = get_conn()
                cur = conn.cursor()
                cur.execute(
                    "UPDATE users SET last_active_check = NOW() WHERE telegram_id = %s",
                    (uid,)
                )
                conn.commit(); cur.close(); conn.close()
                try:
                    await bot.send_message(
                        uid,
                        f"📉 <b>Low Activity Notice</b>\n\n"
                        f"You still only have <b>{total_2w}</b> referrals in 2 weeks (minimum: {MIN_REFS_2_WEEKS}).\n\n"
                        f"You will <b>not be counted</b> in the leaderboard rankings until you become <b>ACTIVE</b> again.\n\n"
                        f"Share your link now and start climbing! 🚀",
                        parse_mode="HTML",
                    )
                    flagged += 1
                except Exception:
                    pass
                set_setting(warn_key, "0")  # Reset for next cycle
        else:
            # Active — clear warning
            set_setting(f"activity_warned_{uid}", "0")

    print(f"[Scheduler] Activity check: {warned} warned, {flagged} flagged")


async def open_withdrawal_window(bot):
    set_setting("withdrawal_open", "1")
    users = get_all_users(active_only=True)
    top3 = get_top3()

    announcement = (
        "🎉 <b>Withdrawal Window is NOW OPEN!</b> 🎉\n\n"
        "💰 This week's prizes:\n"
        "🥇 1st Place — <b>$100</b>\n"
        "🥈 2nd Place — <b>$50</b>\n"
        "🥉 3rd Place — <b>$20</b>\n\n"
        "🏆 <b>Current Top 3:</b>\n"
    )
    for i, e in enumerate(top3, 1):
        uname = f"@{e['username']}" if e.get("username") else e["display_name"]
        announcement += f"{i}. {uname} — <b>{e['referral_count']}</b> refs\n"

    announcement += "\nIf you're in the top 3, go to <b>Withdraw</b> in the menu to claim your prize! ⚡"

    for u in users:
        try:
            await bot.send_message(u["telegram_id"], announcement, parse_mode="HTML")
        except Exception:
            pass


async def close_withdrawal_window(bot):
    set_setting("withdrawal_open", "0")
    print("[Scheduler] Withdrawal window closed.")


async def announce_weekly_winners(bot):
    top3 = get_top3()
    users = get_all_users(active_only=True)

    text = (
        "🏆 <b>This Week's Leaderboard — Final Results</b>\n\n"
        "Congratulations to our top performers!\n\n"
    )
    medals = ["🥇", "🥈", "🥉"]
    prizes = ["$100", "$50", "$20"]

    for i, e in enumerate(top3):
        uname = f"@{e['username']}" if e.get("username") else e["display_name"]
        text += f"{medals[i]} {uname} — <b>{e['referral_count']}</b> refs — <b>{prizes[i]}</b>\n"

    text += "\n\nNew week, new chance! 🚀 Share your link and compete for next week's prizes!"

    for u in users:
        try:
            await bot.send_message(u["telegram_id"], text, parse_mode="HTML")
        except Exception:
            pass
