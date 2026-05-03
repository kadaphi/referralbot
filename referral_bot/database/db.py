"""
database/db.py — PostgreSQL connection & schema setup
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()


def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "referral_bot"),
        user=os.getenv("DB_USER", "referral_user"),
        password=os.getenv("DB_PASSWORD"),
        cursor_factory=RealDictCursor,
    )


def init_db():
    """Create all tables if they don't exist."""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id         BIGINT PRIMARY KEY,
            username            TEXT,
            full_name           TEXT,
            referred_by         BIGINT REFERENCES users(telegram_id) ON DELETE SET NULL,
            ip_address          TEXT,
            joined_at           TIMESTAMP DEFAULT NOW(),
            is_banned           BOOLEAN DEFAULT FALSE,
            ban_reason          TEXT,
            strike_count        INT DEFAULT 0,
            is_verified         BOOLEAN DEFAULT FALSE,
            last_active_check   TIMESTAMP DEFAULT NOW(),
            referral_count      INT DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS referrals (
            id              SERIAL PRIMARY KEY,
            referrer_id     BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
            referred_id     BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
            created_at      TIMESTAMP DEFAULT NOW(),
            week_number     INT,
            year            INT,
            UNIQUE(referred_id)
        );

        CREATE TABLE IF NOT EXISTS weekly_referrals (
            id              SERIAL PRIMARY KEY,
            user_id         BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
            week_number     INT,
            year            INT,
            count           INT DEFAULT 0,
            UNIQUE(user_id, week_number, year)
        );

        CREATE TABLE IF NOT EXISTS seeded_users (
            id              SERIAL PRIMARY KEY,
            display_name    TEXT NOT NULL,
            username        TEXT,
            referral_count  INT DEFAULT 0,
            position        INT UNIQUE,
            created_at      TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS withdrawals (
            id              SERIAL PRIMARY KEY,
            user_id         BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
            trx_address     TEXT NOT NULL,
            amount_usd      NUMERIC(10,2),
            status          TEXT DEFAULT 'pending',
            submitted_at    TIMESTAMP DEFAULT NOW(),
            processed_at    TIMESTAMP,
            rank_at_submit  INT,
            week_number     INT,
            year            INT
        );

        CREATE TABLE IF NOT EXISTS bot_settings (
            key     TEXT PRIMARY KEY,
            value   TEXT
        );

        CREATE TABLE IF NOT EXISTS banned_ips (
            ip_address      TEXT PRIMARY KEY,
            banned_at       TIMESTAMP DEFAULT NOW(),
            reason          TEXT
        );

        CREATE TABLE IF NOT EXISTS broadcast_log (
            id              SERIAL PRIMARY KEY,
            admin_id        BIGINT,
            message_text    TEXT,
            media_type      TEXT,
            sent_at         TIMESTAMP DEFAULT NOW(),
            recipient_count INT DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS support_tickets (
            id              SERIAL PRIMARY KEY,
            user_id         BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
            message         TEXT,
            created_at      TIMESTAMP DEFAULT NOW(),
            status          TEXT DEFAULT 'open'
        );

        CREATE TABLE IF NOT EXISTS ad_requests (
            id              SERIAL PRIMARY KEY,
            user_id         BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
            message         TEXT,
            file_id         TEXT,
            file_type       TEXT,
            created_at      TIMESTAMP DEFAULT NOW(),
            status          TEXT DEFAULT 'pending'
        );

        CREATE TABLE IF NOT EXISTS strike_log (
            id              SERIAL PRIMARY KEY,
            user_id         BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
            reason          TEXT,
            created_at      TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS pending_verifications (
            token           TEXT PRIMARY KEY,
            telegram_id     BIGINT NOT NULL,
            full_name       TEXT,
            referred_by     BIGINT,
            created_at      TIMESTAMP DEFAULT NOW(),
            expires_at      TIMESTAMP DEFAULT NOW() + INTERVAL '10 minutes'
        );
    """)

    # Default bot settings
    defaults = {
        "welcome_image_file_id": "",
        "welcome_text": "🌟 Welcome to <b>Aurora Referral Bot</b>!\n\nEarn rewards by referring friends. Top 3 every week win <b>$100</b>, <b>$50</b>, and <b>$20</b>!",
        "welcome_button_text": "✅ Proceed",
        "folder_invite_link": os.getenv("FOLDER_INVITE_LINK", ""),
        "main_menu_text": "🎉 Welcome to <b>Aurora Referral Bot</b>!\n\nHere you can earn real money by referring friends.\nTop 3 referrers every week win big prizes! 💰",
        "rules_text": "📜 <b>BOT RULES</b>\n\n1. No multi-accounts — you will be banned.\n2. No VPN during verification.\n3. Must be <b>ACTIVE</b>: refer at least 5 users/week.\n4. Withdrawal only for top 3 each week.\n5. Be respectful in support.",
        "maintenance_mode": "0",
        "withdrawal_open": "0",
        "event_start_date": "",
        "event_end_date": "",
    }
    for k, v in defaults.items():
        cur.execute(
            "INSERT INTO bot_settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
            (k, v),
        )

    conn.commit()
    cur.close()
    conn.close()
    print("✅ Database initialized successfully.")


def get_setting(key: str) -> str:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM bot_settings WHERE key = %s", (key,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row["value"] if row else ""


def set_setting(key: str, value: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO bot_settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        (key, value),
    )
    conn.commit()
    cur.close()
    conn.close()
