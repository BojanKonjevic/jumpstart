import secrets
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import bcrypt as _bcrypt
from jose import JWTError, jwt

from ..settings import settings


def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: UUID) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": str(user_id), "exp": expire}
    return cast(
        str, jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    )


def decode_access_token(token: str) -> UUID | None:
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        user_id = payload.get("sub")
        if user_id is None:
            return None
        return UUID(user_id)
    except JWTError:
        return None


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(64)
