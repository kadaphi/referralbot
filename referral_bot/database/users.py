"""
database/users.py — User-related DB operations
"""
from datetime import datetime, timedelta
import os
from database.db import get_conn


def get_user(telegram_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def create_user(telegram_id: int, username: str, full_name: str,
                referred_by: int = None, ip_address: str = None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO users (telegram_id, username, full_name, referred_by, ip_address, is_verified)
        VALUES (%s, %s, %s, %s, %s, TRUE)
        ON CONFLICT (telegram_id) DO UPDATE SET
            username = EXCLUDED.username,
            full_name = EXCLUDED.full_name,
            is_verified = TRUE
        RETURNING *
    """, (telegram_id, username, full_name, referred_by, ip_address))
    row = cur.fetchone()
    conn.commit(); cur.close(); conn.close()
    return dict(row) if row else None


def update_user(telegram_id: int, **kwargs):
    if not kwargs:
        return
    conn = get_conn()
    cur = conn.cursor()
    fields = ", ".join(f"{k} = %s" for k in kwargs)
    values = list(kwargs.values()) + [telegram_id]
    cur.execute(f"UPDATE users SET {fields} WHERE telegram_id = %s", values)
    conn.commit(); cur.close(); conn.close()


def ban_user(telegram_id: int, reason: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET is_banned = TRUE, ban_reason = %s WHERE telegram_id = %s",
        (reason, telegram_id)
    )
    conn.commit(); cur.close(); conn.close()


def unban_user(telegram_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET is_banned = FALSE, ban_reason = NULL, strike_count = 0 WHERE telegram_id = %s",
        (telegram_id,)
    )
    conn.commit(); cur.close(); conn.close()


def add_strike(telegram_id: int, reason: str) -> int:
    """Add a strike, return new strike count."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET strike_count = strike_count + 1 WHERE telegram_id = %s RETURNING strike_count",
        (telegram_id,)
    )
    row = cur.fetchone()
    cur.execute(
        "INSERT INTO strike_log (user_id, reason) VALUES (%s, %s)",
        (telegram_id, reason)
    )
    conn.commit(); cur.close(); conn.close()
    return row["strike_count"] if row else 0


def get_all_users(active_only=False):
    conn = get_conn()
    cur = conn.cursor()
    if active_only:
        cur.execute("SELECT * FROM users WHERE is_banned = FALSE AND is_verified = TRUE")
    else:
        cur.execute("SELECT * FROM users WHERE is_verified = TRUE")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


def get_user_by_ip(ip_address: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE ip_address = %s AND is_verified = TRUE", (ip_address,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def is_ip_banned(ip_address: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM banned_ips WHERE ip_address = %s", (ip_address,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row is not None


def ban_ip(ip_address: str, reason: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO banned_ips (ip_address, reason) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (ip_address, reason)
    )
    conn.commit(); cur.close(); conn.close()


def get_user_count() -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as c FROM users WHERE is_verified = TRUE AND is_banned = FALSE")
    row = cur.fetchone()
    cur.close(); conn.close()
    return row["c"] if row else 0
