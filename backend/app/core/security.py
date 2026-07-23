from typing import Annotated

from fastapi import Header, HTTPException, status
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.core.config import get_settings


def require_admin_token(x_yuno_admin_token: Annotated[str | None, Header()] = None) -> None:
    settings = get_settings()
    if x_yuno_admin_token != settings.admin_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token administrativo invalido.")


def require_bot_token(x_yuno_bot_token: Annotated[str | None, Header()] = None) -> None:
    settings = get_settings()
    if x_yuno_bot_token != settings.bot_internal_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token interno do bot invalido.")


def require_admin_or_bot_token(
    x_yuno_admin_token: Annotated[str | None, Header()] = None,
    x_yuno_bot_token: Annotated[str | None, Header()] = None,
) -> None:
    settings = get_settings()
    if x_yuno_admin_token == settings.admin_token or x_yuno_bot_token == settings.bot_internal_token:
        return
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido.")


def session_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="yuno-dashboard-session")


def create_session_token(payload: dict) -> str:
    return session_serializer().dumps(payload)


def read_session_token(token: str, max_age_seconds: int = 60 * 60 * 24 * 7) -> dict:
    try:
        data = session_serializer().loads(token, max_age=max_age_seconds)
    except BadSignature as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessao invalida.") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessao invalida.")
    return data
