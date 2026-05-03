# 🌌 Aurora Referral Bot — Setup Guide

## Prerequisites
- Ubuntu/Debian VPS
- Python 3.11+
- PostgreSQL
- A domain OR just your VPS IP (we'll use IP)

---

## Step 1: Install System Dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv postgresql postgresql-contrib git
```

---

## Step 2: Set Up PostgreSQL

```bash
# Start PostgreSQL
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Create database and user
sudo -u postgres psql <<EOF
CREATE USER referral_user WITH PASSWORD 'YOUR_STRONG_PASSWORD_HERE';
CREATE DATABASE referral_bot OWNER referral_user;
GRANT ALL PRIVILEGES ON DATABASE referral_bot TO referral_user;
\q
EOF
```

---

## Step 3: Upload & Set Up Project

```bash
# Create project directory
mkdir -p /home/youruser/referral_bot
cd /home/youruser/referral_bot

# Upload all files here (via scp, sftp, or git clone)
# Then create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Step 4: Configure Environment

```bash
cp .env.example .env
nano .env
```

Fill in these required values:

| Variable | How to get it |
|---|---|
| `BOT_TOKEN` | @BotFather on Telegram → /newbot |
| `DB_PASSWORD` | The password you set in Step 2 |
| `VPS_IP` | Your server's public IP address |
| `FOLDER_INVITE_LINK` | Create a folder in Telegram → Share → Copy link |
| `REQUIRED_CHANNEL_IDS` | Right-click channel → Copy Channel ID (use @userinfobot) |
| `VPNAPI_KEY` | Free at https://vpnapi.io (sign up) |
| `HCAPTCHA_SITE_KEY` | Free at https://dashboard.hcaptcha.com |
| `HCAPTCHA_SECRET_KEY` | Same hCaptcha dashboard |
| `FLASK_SECRET_KEY` | Any long random string |

### How to get Channel IDs:
1. Add @userinfobot to your channel
2. It will show the channel ID (negative number like -1001234567890)
3. Add ALL channels from your folder, comma-separated

---

## Step 5: Open Firewall Port

```bash
# Allow the verification web server port
sudo ufw allow 5000/tcp
sudo ufw allow 22/tcp
sudo ufw enable
```

---

## Step 6: Test Run

```bash
cd /home/youruser/referral_bot
source venv/bin/activate
python main.py
```

You should see:
```
✅ Database initialized successfully.
🌐 Starting Flask verification server on port 5000...
🤖 Starting Telegram bot...
⏰ Scheduler started.
✅ Bot is running!
```

---

## Step 7: Run as System Service (Production)

```bash
sudo nano /etc/systemd/system/referral-bot.service
```

Paste this (replace `youruser` and paths):

```ini
[Unit]
Description=Aurora Referral Telegram Bot
After=network.target postgresql.service

[Service]
Type=simple
User=youruser
WorkingDirectory=/home/youruser/referral_bot
Environment=PATH=/home/youruser/referral_bot/venv/bin
ExecStart=/home/youruser/referral_bot/venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable referral-bot
sudo systemctl start referral-bot

# Check status
sudo systemctl status referral-bot

# View logs
sudo journalctl -u referral-bot -f
```

---

## Step 8: Add Bot as Admin to All Channels

For the membership check to work, **add your bot as an admin** to every channel in your folder with at least "Read Messages" permission.

---

## Admin Commands

Once running, send `/admin` to your bot from Telegram ID `6402264162`.

### Admin Panel Features:
- 📢 **Broadcast** — Send text/photo/video/audio/document to all users
- 🖼 **Welcome Settings** — Change image, text, and join link
- 🚫 **Ban User** — Ban by Telegram ID + reason
- ✅ **Unban User** — Unban by Telegram ID
- 💬 **Message User** — Send message directly to any user by ID
- 📊 **Bot Stats** — Total users + current top 3
- 🌱 **Seed Leaderboard** — Add/update/remove seeded entries
- 📜 **Edit Rules** — Update rules text
- 🔧 **Maintenance Mode** — Lock/unlock bot
- 💸 **Toggle Withdrawal** — Open/close withdrawal window
- 📝 **Edit Main Menu Text** — Update main screen text
- 📋 **View Users** — User count overview

### Seeding the Leaderboard:
In admin panel → Seed Leaderboard, send:
```
1 John Doe @johndoe 45
```
This seeds position 1 with 45 referrals. If a real user gets 46+ refs, they overtake the seed. To remove:
```
remove 1
```

---

## Bot Flow Summary

```
/start
  → Welcome screen with Join Channel button
  → User clicks Proceed → Channel membership checked
  → Verification link sent (Flask web app)
  → User opens link → VPN check → hCaptcha → IP duplicate check
  → Verified → Main menu shown
  → Admin notified of new user

Main Menu:
  📊 Statistics   — Live leaderboard (top 50, dynamic seeds)
  👥 Referrals    — Personal count + referral link
  💸 Withdraw     — Open weekends, top 3 only, TRX address
  📜 Rules        — Admin-editable rules
  📣 Advertise    — Ad submission with optional media
  🆘 Support      — Support ticket to admin
```

---

## Scheduled Events

| Schedule | Action |
|---|---|
| Every Monday 00:01 UTC | Activity check — warn/flag inactive users |
| Every Friday 00:00 UTC | Open withdrawal window + announce |
| Every Sunday 23:59 UTC | Close withdrawal window |
| Every Sunday 20:00 UTC | Announce weekly winners to all users |

---

## Troubleshooting

**Bot doesn't respond:**
```bash
sudo journalctl -u referral-bot -n 50
```

**Database connection error:**
```bash
sudo -u postgres psql -U referral_user -d referral_bot
```

**Verification link not loading:**
- Make sure port 5000 is open: `sudo ufw status`
- Make sure your VPS_IP in .env is correct

**Channel membership not detected:**
- Make sure bot is admin in all channels
- Check REQUIRED_CHANNEL_IDS are correct (negative numbers)

---

## Security Notes

- The admin panel is **hardware-locked** to Telegram ID `6402264162` — any other user gets blocked
- All verification tokens expire in 10 minutes
- IPs are checked against VPN databases before captcha
- Duplicate IPs trigger automatic ban + admin alert
- 3 strikes for self-referral attempts = permanent ban
