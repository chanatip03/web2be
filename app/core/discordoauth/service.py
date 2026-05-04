import os
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

from app.utils.generate_token import create_access_token, decode_token

DISCORD_API_BASE = "https://discord.com/api/v10"

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "1486465516406182090")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "bMlnLLOySm_-c8puBqfIcVInLNxMryOT")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:8000/api/discord/callback")
FRONTEND_URL = os.getenv("DISCORD_FRONTEND_URL", "http://localhost:3000/profile")

def build_discord_authorize_url(state: str) -> str:
    if not DISCORD_CLIENT_ID or not DISCORD_REDIRECT_URI:
        raise HTTPException(
            status_code=500,
            detail="Discord OAuth config is not configured",
        )

    params = {
        "client_id": DISCORD_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": DISCORD_REDIRECT_URI,
        "scope": "identify",
        "state": state,
        "prompt": "consent",
    }

    return "https://discord.com/oauth2/authorize?" + urlencode(params)


def generate_oauth_state(user_id: int) -> str:
    nonce = secrets.token_urlsafe(16)
    return create_access_token({"uid": user_id, "nonce": nonce})

def decode_oauth_state(state: str) -> dict | None:
    try:
        return decode_token(state)
    except Exception:
        return None


async def exchange_code_for_user(code: str) -> dict:
    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET or not DISCORD_REDIRECT_URI:
        raise HTTPException(
            status_code=500,
            detail="Discord OAuth config is not configured",
        )

    async with httpx.AsyncClient(timeout=20.0) as client:
        token_resp = await client.post(
            f"{DISCORD_API_BASE}/oauth2/token",
            data={
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": DISCORD_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if token_resp.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to exchange Discord token: {token_resp.text}",
            )

        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=400,
                detail="Discord access token not found",
            )

        user_resp = await client.get(
            f"{DISCORD_API_BASE}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if user_resp.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to fetch Discord user: {user_resp.text}",
            )

        discord_user = user_resp.json()
        if "id" not in discord_user:
            raise HTTPException(
                status_code=400,
                detail="Discord user id not found",
            )

        return discord_user