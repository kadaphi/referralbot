"""
database/referrals.py — Referral tracking & leaderboard
"""
from datetime import datetime
from database.db import get_conn


def _current_week():
    now = datetime.utcnow()
    return now.isocalendar()[1], now.year


def record_referral(referrer_id: int, referred_id: int):
    week, year = _current_week()
    conn = get_conn()
    cur = conn.cursor()
    # Insert referral record
    cur.execute("""
        INSERT INTO referrals (referrer_id, referred_id, week_number, year)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (referred_id) DO NOTHING
        RETURNING id
    """, (referrer_id, referred_id, week, year))
    inserted = cur.fetchone()
    if inserted:
        # Update weekly referral count
        cur.execute("""
            INSERT INTO weekly_referrals (user_id, week_number, year, count)
            VALUES (%s, %s, %s, 1)
            ON CONFLICT (user_id, week_number, year)
            DO UPDATE SET count = weekly_referrals.count + 1
        """, (referrer_id, week, year))
        # Update total referral_count on user
        cur.execute(
            "UPDATE users SET referral_count = referral_count + 1 WHERE telegram_id = %s",
            (referrer_id,)
        )
    conn.commit(); cur.close(); conn.close()
    return bool(inserted)


def get_user_referral_count(user_id: int) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT referral_count FROM users WHERE telegram_id = %s", (user_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row["referral_count"] if row else 0


def get_weekly_referral_count(user_id: int, week: int = None, year: int = None) -> int:
    if week is None:
        week, year = _current_week()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT COALESCE(count, 0) as count FROM weekly_referrals
        WHERE user_id = %s AND week_number = %s AND year = %s
    """, (user_id, week, year))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row["count"] if row else 0


def get_leaderboard(limit: int = 50):
    """
    Returns merged leaderboard: real users + seeded entries, sorted by referral_count desc.
    Seeded entries are dynamic — they can be overtaken by real users.
    """
    week, year = _current_week()
    conn = get_conn()
    cur = conn.cursor()

    # Real users with their weekly referral counts
    cur.execute("""
        SELECT
            u.telegram_id,
            u.full_name AS display_name,
            u.username,
            COALESCE(wr.count, 0) AS referral_count,
            FALSE AS is_seeded
        FROM users u
        LEFT JOIN weekly_referrals wr
            ON wr.user_id = u.telegram_id
            AND wr.week_number = %s
            AND wr.year = %s
        WHERE u.is_banned = FALSE AND u.is_verified = TRUE
        ORDER BY referral_count DESC
        LIMIT %s
    """, (week, year, limit))
    real_users = [dict(r) for r in cur.fetchall()]

    # Seeded entries
    cur.execute("SELECT * FROM seeded_users ORDER BY position ASC")
    seeded = [dict(r) for r in cur.fetchall()]

    cur.close(); conn.close()

    # Merge: treat seeded entries as dynamic competitors
    combined = real_users + [
        {
            "telegram_id": None,
            "display_name": s["display_name"],
            "username": s["username"],
            "referral_count": s["referral_count"],
            "is_seeded": True,
        }
        for s in seeded
    ]
    combined.sort(key=lambda x: x["referral_count"], reverse=True)
    return combined[:limit]


def get_top3():
    board = get_leaderboard(10)
    return board[:3]


def upsert_seeded(position: int, display_name: str, username: str, referral_count: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO seeded_users (position, display_name, username, referral_count)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (position) DO UPDATE SET
            display_name = EXCLUDED.display_name,
            username = EXCLUDED.username,
            referral_count = EXCLUDED.referral_count
    """, (position, display_name, username, referral_count))
    conn.commit(); cur.close(); conn.close()


def delete_seeded(position: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM seeded_users WHERE position = %s", (position,))
    conn.commit(); cur.close(); conn.close()


def get_user_rank(user_id: int) -> int | None:
    """Returns 1-based rank of user in leaderboard, or None if not found."""
    board = get_leaderboard(200)
    for i, entry in enumerate(board, 1):
        if entry.get("telegram_id") == user_id:
            return i
    return None


def is_user_in_top3(user_id: int) -> bool:
    return (get_user_rank(user_id) or 999) <= 3


def get_weekly_referrals_2weeks(user_id: int) -> int:
    """Total referrals in last 2 weeks."""
    now = datetime.utcnow()
    week1, year1 = now.isocalendar()[1], now.year
    prev = now - __import__('datetime').timedelta(weeks=1)
    week2, year2 = prev.isocalendar()[1], prev.year

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT COALESCE(SUM(count), 0) as total FROM weekly_referrals
        WHERE user_id = %s AND (
            (week_number = %s AND year = %s) OR
            (week_number = %s AND year = %s)
        )
    """, (user_id, week1, year1, week2, year2))
    row = cur.fetchone()
    cur.close(); conn.close()
    return int(row["total"]) if row else 0
