"""
web/app.py — Flask captcha & IP verification server
Runs on VPS_IP:WEB_PORT
"""
import os
import requests
from flask import Flask, request, jsonify, render_template_string, redirect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
from database.db import get_conn
from database.users import get_user_by_ip, is_ip_banned, ban_ip, create_user, ban_user
from utils.helpers import check_vpn, generate_verification_token

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "changeme")

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
)

HCAPTCHA_SITE_KEY = os.getenv("HCAPTCHA_SITE_KEY", "")
HCAPTCHA_SECRET_KEY = os.getenv("HCAPTCHA_SECRET_KEY", "")

CAPTCHA_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Verification — Aurora Referral Bot</title>
<script src="https://js.hcaptcha.com/1/api.js" async defer></script>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    min-height: 100vh;
    background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
    display: flex; align-items: center; justify-content: center;
    font-family: 'Segoe UI', sans-serif; color: #fff;
  }
  .card {
    background: rgba(255,255,255,0.07);
    backdrop-filter: blur(20px);
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 20px;
    padding: 40px 32px;
    max-width: 420px; width: 90%;
    text-align: center;
    box-shadow: 0 20px 60px rgba(0,0,0,0.4);
  }
  .logo { font-size: 2.5rem; margin-bottom: 8px; }
  h1 { font-size: 1.4rem; margin-bottom: 6px; color: #a78bfa; }
  p { font-size: 0.9rem; color: rgba(255,255,255,0.7); margin-bottom: 28px; line-height: 1.5; }
  .vpn-warning {
    background: rgba(239,68,68,0.2);
    border: 1px solid rgba(239,68,68,0.5);
    border-radius: 10px;
    padding: 16px;
    margin-bottom: 20px;
    font-size: 0.9rem;
    color: #fca5a5;
  }
  .error-msg {
    background: rgba(239,68,68,0.2);
    border: 1px solid rgba(239,68,68,0.4);
    border-radius: 10px;
    padding: 12px;
    margin-bottom: 16px;
    font-size: 0.85rem;
    color: #fca5a5;
  }
  .success-msg {
    background: rgba(34,197,94,0.2);
    border: 1px solid rgba(34,197,94,0.4);
    border-radius: 10px;
    padding: 12px;
    margin-bottom: 16px;
    font-size: 0.85rem;
    color: #86efac;
  }
  .h-captcha { display: flex; justify-content: center; margin-bottom: 20px; }
  button[type=submit] {
    background: linear-gradient(135deg, #7c3aed, #4f46e5);
    color: white; border: none; border-radius: 12px;
    padding: 14px 32px; font-size: 1rem; font-weight: 600;
    cursor: pointer; width: 100%; transition: opacity 0.2s;
  }
  button[type=submit]:hover { opacity: 0.9; }
  .step-indicator {
    display: flex; justify-content: center; gap: 8px; margin-bottom: 24px;
  }
  .step { width: 8px; height: 8px; border-radius: 50%; background: rgba(255,255,255,0.2); }
  .step.active { background: #a78bfa; }
  .ip-warning { font-size: 0.75rem; color: rgba(255,255,255,0.4); margin-top: 16px; }
</style>
</head>
<body>
<div class="card">
  <div class="logo">🌌</div>
  <h1>Identity Verification</h1>
  <p>To keep our referral program fair, we need to verify you're a unique user.</p>

  <div class="step-indicator">
    <div class="step {{ 'active' if step >= 1 else '' }}"></div>
    <div class="step {{ 'active' if step >= 2 else '' }}"></div>
    <div class="step {{ 'active' if step >= 3 else '' }}"></div>
  </div>

  {% if vpn_detected %}
  <div class="vpn-warning">
    🔒 <strong>VPN / Proxy Detected</strong><br><br>
    Please <strong>disable your VPN or proxy</strong> and reload this page to continue.
    VPNs are not allowed during verification to ensure fairness.
  </div>
  <script>
    setTimeout(() => location.reload(), 8000);
  </script>
  {% elif banned %}
  <div class="error-msg">
    🚫 <strong>Account Banned</strong><br><br>
    This IP address has been flagged for multiple accounts or rule violations.
    Contact support if you believe this is a mistake.
  </div>
  {% elif ip_conflict %}
  <div class="error-msg">
    ⚠️ <strong>Multiple Account Detected</strong><br><br>
    This IP address is already linked to another account in our system.
    Multiple accounts are strictly prohibited.
  </div>
  {% elif success %}
  <div class="success-msg">
    ✅ <strong>Verification Complete!</strong><br><br>
    You're all set. Return to Telegram and click "Proceed" to continue.
  </div>
  {% else %}
  {% if error %}
  <div class="error-msg">{{ error }}</div>
  {% endif %}
  <form method="POST" action="/verify">
    <input type="hidden" name="token" value="{{ token }}">
    <div class="h-captcha" data-sitekey="{{ site_key }}"></div>
    <button type="submit">✅ Verify & Continue</button>
  </form>
  {% endif %}

  <p class="ip-warning">Your IP is used solely for duplicate detection.</p>
</div>
</body>
</html>
"""


@app.route("/verify/<token>")
@limiter.limit("20 per hour")
def verify_page(token):
    ip = request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()

    # Check if IP is banned
    if is_ip_banned(ip):
        return render_template_string(CAPTCHA_PAGE, vpn_detected=False, banned=True,
                                      ip_conflict=False, success=False, error=None,
                                      token=token, site_key=HCAPTCHA_SITE_KEY, step=1)

    # VPN check
    vpn_result = check_vpn(ip)
    if vpn_result["is_vpn"]:
        return render_template_string(CAPTCHA_PAGE, vpn_detected=True, banned=False,
                                      ip_conflict=False, success=False, error=None,
                                      token=token, site_key=HCAPTCHA_SITE_KEY, step=1)

    # Check token validity
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM pending_verifications
        WHERE token = %s AND expires_at > NOW()
    """, (token,))
    pending = cur.fetchone()
    cur.close(); conn.close()

    if not pending:
        return render_template_string(CAPTCHA_PAGE, vpn_detected=False, banned=False,
                                      ip_conflict=False, success=False,
                                      error="❌ This verification link has expired or is invalid. Please start the bot again.",
                                      token=token, site_key=HCAPTCHA_SITE_KEY, step=2)

    return render_template_string(CAPTCHA_PAGE, vpn_detected=False, banned=False,
                                  ip_conflict=False, success=False, error=None,
                                  token=token, site_key=HCAPTCHA_SITE_KEY, step=2)


@app.route("/verify", methods=["POST"])
@limiter.limit("10 per hour")
def verify_submit():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()
    token = request.form.get("token", "")
    hcaptcha_response = request.form.get("h-captcha-response", "")

    # VPN re-check on submit
    vpn_result = check_vpn(ip)
    if vpn_result["is_vpn"]:
        return render_template_string(CAPTCHA_PAGE, vpn_detected=True, banned=False,
                                      ip_conflict=False, success=False, error=None,
                                      token=token, site_key=HCAPTCHA_SITE_KEY, step=1)

    # Verify hCaptcha
    if HCAPTCHA_SECRET_KEY:
        try:
            r = requests.post("https://hcaptcha.com/siteverify", data={
                "secret": HCAPTCHA_SECRET_KEY,
                "response": hcaptcha_response,
                "remoteip": ip,
            }, timeout=5)
            result = r.json()
            if not result.get("success"):
                return render_template_string(CAPTCHA_PAGE, vpn_detected=False, banned=False,
                                              ip_conflict=False, success=False,
                                              error="❌ Captcha failed. Please try again.",
                                              token=token, site_key=HCAPTCHA_SITE_KEY, step=2)
        except Exception:
            pass  # Allow through if hCaptcha API fails

    # Fetch pending verification
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM pending_verifications
        WHERE token = %s AND expires_at > NOW()
    """, (token,))
    pending = cur.fetchone()

    if not pending:
        cur.close(); conn.close()
        return render_template_string(CAPTCHA_PAGE, vpn_detected=False, banned=False,
                                      ip_conflict=False, success=False,
                                      error="❌ Verification link expired. Please restart the bot.",
                                      token=token, site_key=HCAPTCHA_SITE_KEY, step=2)

    pending = dict(pending)
    telegram_id = pending["telegram_id"]
    referred_by = pending.get("referred_by")
    full_name = pending.get("full_name", "User")

    # IP conflict check
    existing = get_user_by_ip(ip)
    if existing and existing["telegram_id"] != telegram_id:
        # Multi-account detected
        ban_ip(ip, "Multiple accounts detected")
        # Give strike to the referrer if it was a referral attempt
        if referred_by:
            from database.users import add_strike
            strikes = add_strike(referred_by, f"Attempted self-referral via IP {ip}")
            if strikes >= 3:
                ban_user(referred_by, "3 strikes: multiple account abuse")
                # Notify via DB flag for bot to pick up
                cur.execute("""
                    INSERT INTO bot_settings (key, value) VALUES (%s, %s)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """, (f"ban_notify_{referred_by}", "1"))
        cur.close(); conn.close()
        return render_template_string(CAPTCHA_PAGE, vpn_detected=False, banned=False,
                                      ip_conflict=True, success=False, error=None,
                                      token=token, site_key=HCAPTCHA_SITE_KEY, step=3)

    # All good — mark user as verified in DB
    # Get username from pending
    cur.execute("SELECT username FROM users WHERE telegram_id = %s", (telegram_id,))
    u = cur.fetchone()
    username = u["username"] if u else None

    create_user(telegram_id, username, full_name, referred_by, ip)

    # Delete the pending token
    cur.execute("DELETE FROM pending_verifications WHERE token = %s", (token,))

    # Signal bot that user is verified (bot polls this)
    cur.execute("""
        INSERT INTO bot_settings (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
    """, (f"verified_{telegram_id}", "1"))

    conn.commit(); cur.close(); conn.close()

    return render_template_string(CAPTCHA_PAGE, vpn_detected=False, banned=False,
                                  ip_conflict=False, success=True, error=None,
                                  token=token, site_key=HCAPTCHA_SITE_KEY, step=3)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    port = int(os.getenv("WEB_PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
