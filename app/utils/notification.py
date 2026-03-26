import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import urllib.request
import urllib.error
import json
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)


def _clean(val: str | None) -> str:
    """Strip whitespace that leaks in from .env files."""
    return (val or "").strip()


# --------------- Email (Gmail SMTP) ---------------

def send_feedback_email(to_email: str, feedback_text: str) -> dict:
    """Send feedback via Gmail SMTP. Returns {"success": bool, "error": str|None}."""
    load_dotenv(dotenv_path=ENV_PATH, override=True)
    host = _clean(os.getenv("SMTP_HOST"))
    port_str = _clean(os.getenv("SMTP_PORT"))
    user = _clean(os.getenv("SMTP_USER"))
    # Gmail App Password works with/without spaces; normalize to 16-char token.
    password = "".join(_clean(os.getenv("SMTP_PASS")).split())
    mail_from = _clean(os.getenv("MAIL_FROM")) or user

    if not all([host, port_str, user, password]):
        return {"success": False, "error": "SMTP env vars not configured"}

    port = int(port_str)

    msg = MIMEMultipart("alternative")
    msg["From"] = mail_from
    msg["To"] = to_email
    msg["Subject"] = "WEB2 - Feedback Notification"
    msg.attach(MIMEText(feedback_text, "plain", "utf-8"))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.ehlo()
            server.login(user, password)
            server.sendmail(user, to_email, msg.as_string())
        return {"success": True, "error": None}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# --------------- Discord DM (Bot REST API v10) ---------------

DISCORD_API = "https://discord.com/api/v10"


def _discord_request(method: str, path: str, body: dict | None = None) -> dict:
    """Low-level helper for Discord REST calls."""
    token = _clean(os.getenv("DISCORD_BOT_TOKEN"))
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN not set")

    url = f"{DISCORD_API}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "WEB2Bot (https://web2, 1.0)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode() if exc.fp else ""
        raise RuntimeError(f"Discord {exc.code}: {err_body}") from exc


def send_feedback_discord_dm(discord_user_id: str, feedback_text: str) -> dict:
    """Send a DM to a Discord user via the bot. Returns {"success": bool, "error": str|None}."""
    load_dotenv(dotenv_path=ENV_PATH, override=True)
    try:
        # Step 1: Open / get DM channel with the user
        dm_channel = _discord_request("POST", "/users/@me/channels", {"recipient_id": discord_user_id})
        channel_id = dm_channel["id"]

        # Step 2: Send message in that DM channel
        _discord_request("POST", f"/channels/{channel_id}/messages", {"content": feedback_text})

        return {"success": True, "error": None}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
