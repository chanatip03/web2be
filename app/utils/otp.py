import random
import hashlib
import smtplib
import os
import httpx
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from datetime import datetime, timedelta ,timezone

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT") or 587)
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
MAIL_FROM = os.getenv("MAIL_FROM")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

DISCORD_API_BASE = "https://discord.com/api/v10"

otp_store: dict = {}
verified_store: dict = {}


def generate_otp() -> str:
    return str(random.randint(100000, 999999)).zfill(6)


def hash_otp(otp: str) -> str:
    return hashlib.sha256(otp.encode()).hexdigest()


def send_otp_email(to_email: str, otp: str):
    msg = MIMEMultipart()
    msg["From"] = MAIL_FROM or "no-reply@example.com"
    msg["To"] = to_email
    msg["Subject"] = "Your OTP Code"

    body = f"""
รหัส OTP ของคุณคือ: {otp}

รหัสนี้หมดอายุภายใน 5 นาที
ห้ามแชร์รหัสนี้กับผู้อื่น
"""
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)


def _build_grading_message(assignment_name: str, score: int | None = None, feedback: str | None = None) -> str:
    parts = [f"Your submission of {assignment_name} has been updated."]

    if score is not None:
        parts.append(f"Score: {score}")

    if feedback:
        parts.append("")
        parts.append("Feedback:")
        parts.append(feedback)

    parts.append("")
    parts.append("Please check in WEB2.")
    return "\n".join(parts)


def send_grading_email(to_email: str, assignment_name: str, score: int | None = None, feedback: str | None = None):
    msg = MIMEMultipart()
    msg["From"] = MAIL_FROM or "no-reply@example.com"
    msg["To"] = to_email
    msg["Subject"] = "Project Graded Notification"

    body = _build_grading_message(assignment_name, score, feedback)
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
    except Exception as e:
        print(f"Failed to send grading email to {to_email}: {e}")


def send_grading_discord(discord_user_id: str, assignment_name: str, score: int | None = None, feedback: str | None = None):
    if not DISCORD_BOT_TOKEN or not discord_user_id:
        return

    body = _build_grading_message(assignment_name, score, feedback)
    body = body[:2000]

    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=20.0) as client:
            dm_resp = client.post(
                f"{DISCORD_API_BASE}/users/@me/channels",
                headers=headers,
                json={"recipient_id": discord_user_id},
            )
            dm_resp.raise_for_status()
            channel_id = dm_resp.json()["id"]

            msg_resp = client.post(
                f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
                headers=headers,
                json={"content": body},
            )
            msg_resp.raise_for_status()
    except Exception as e:
        print(f"Failed to send grading Discord DM to {discord_user_id}: {e}")

def save_otp_memory(email: str, otp_hash: str, payload: dict, ttl_minutes: int = 5):
    otp_store[email] = {
        "otp": otp_hash,
        "expires": datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
        "attempts": 0,
        "payload": payload,
    }


def get_otp_memory(email: str):
    return otp_store.get(email)


def delete_otp_memory(email: str):
    otp_store.pop(email, None)


def save_otp_verification(email: str):
    verified_store[email] = {"verified_at": datetime.now(timezone.utc).isoformat()}


def get_otp_verification(email: str):
    return verified_store.get(email)
