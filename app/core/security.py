import os
import secrets

from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from jose import JWTError, jwt


load_dotenv()


# =========================================================
# JWT SETTINGS
# =========================================================

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")

JWT_ALGORITHM = os.getenv(
    "JWT_ALGORITHM",
    "HS256",
)

JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv(
        "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
        "60",
    )
)

JWT_REFRESH_TOKEN_EXPIRE_DAYS = int(
    os.getenv(
        "JWT_REFRESH_TOKEN_EXPIRE_DAYS",
        "30",
    )
)


if not JWT_SECRET_KEY:
    raise ValueError(
        "JWT_SECRET_KEY is not set in .env"
    )


# =========================================================
# CREATE ACCESS TOKEN
# =========================================================

def create_access_token(
    user_id: int,
    role: str,
) -> str:

    expire = (
        datetime.now(timezone.utc)
        + timedelta(
            minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        )
    )

    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "exp": expire,
    }

    return jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )


# =========================================================
# CREATE REFRESH TOKEN
# =========================================================

def create_refresh_token(
    user_id: int,
    role: str,
) -> str:

    expire = (
        datetime.now(timezone.utc)
        + timedelta(
            days=JWT_REFRESH_TOKEN_EXPIRE_DAYS
        )
    )

    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "refresh",
        "exp": expire,
    }

    return jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )


# =========================================================
# DECODE ACCESS TOKEN
# =========================================================

def decode_access_token(
    token: str,
) -> dict:

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
        )

        user_id = payload.get("sub")

        if user_id is None:
            raise JWTError(
                "User ID missing from token"
            )

        return payload

    except JWTError:
        raise


# =========================================================
# DECODE REFRESH TOKEN
# =========================================================

def decode_refresh_token(
    token: str,
) -> dict:

    try:

        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
        )

        token_type = payload.get("type")

        if token_type != "refresh":
            raise JWTError(
                "Invalid refresh token"
            )

        user_id = payload.get("sub")

        if user_id is None:
            raise JWTError(
                "User ID missing from refresh token"
            )

        return payload

    except JWTError:
        raise


# =========================================================
# CREATE RESET TOKEN
# =========================================================

def create_reset_token() -> str:

    return secrets.token_urlsafe(32)


# =========================================================
# CREATE EMAIL VERIFICATION CODE
# =========================================================

def create_verification_code() -> str:

    return str(
        secrets.randbelow(900000) + 100000
    )