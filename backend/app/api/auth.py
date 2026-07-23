from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.config import get_settings
from app.core.security import create_session_token, read_session_token
from app.schemas import DashboardSessionOut

router = APIRouter(prefix="/auth/discord", tags=["auth"])


@router.get("/login")
async def discord_login() -> dict[str, str]:
    settings = get_settings()
    params = {
        "client_id": settings.discord_client_id,
        "redirect_uri": settings.discord_redirect_uri,
        "response_type": "code",
        "scope": "identify guilds",
        "prompt": "consent",
    }
    return {"url": f"https://discord.com/oauth2/authorize?{urlencode(params)}"}


@router.get("/callback", response_model=DashboardSessionOut)
async def discord_callback(code: str = Query(min_length=8)) -> DashboardSessionOut:
    settings = get_settings()
    if not settings.discord_client_id or not settings.discord_client_secret:
        raise HTTPException(status_code=503, detail="OAuth Discord nao configurado.")

    async with httpx.AsyncClient(timeout=15) as client:
        token_response = await client.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": settings.discord_client_id,
                "client_secret": settings.discord_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.discord_redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_response.status_code >= 400:
            raise HTTPException(status_code=401, detail="Falha ao autenticar com Discord.")

        access_token = token_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}
        user_response, guilds_response = await client.get("https://discord.com/api/users/@me", headers=headers), await client.get(
            "https://discord.com/api/users/@me/guilds", headers=headers
        )
        user_response.raise_for_status()
        guilds_response.raise_for_status()

    user = user_response.json()
    guilds = [
        guild
        for guild in guilds_response.json()
        if int(guild.get("permissions", "0")) & 0x20 or guild.get("owner")
    ]
    token = create_session_token({"user_id": user["id"], "guild_ids": [guild["id"] for guild in guilds]})
    return DashboardSessionOut(token=token, user=user, guilds=guilds)


@router.get("/session")
async def read_session(token: str) -> dict:
    return read_session_token(token)
