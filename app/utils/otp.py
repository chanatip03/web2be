import random
import hashlib
import smtplib
import os
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

    with smtplib.SMTP(SMTP_HOST or "localhost", SMTP_PORT) as server:
        try:
            server.starttls()
        except Exception:
            pass
        if SMTP_USER and SMTP_PASS:
            server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)


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
