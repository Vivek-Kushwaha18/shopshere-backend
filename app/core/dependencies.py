
from fastapi import (
    Depends,
    HTTPException,
    status
)

from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer
)

from jose import JWTError

from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    decode_access_token
)

from app.database.database import get_db

from app.models.user import User


# =========================================================
# HTTP BEARER SECURITY
# =========================================================

security = HTTPBearer()


# =========================================================
# GET CURRENT USER
# =========================================================

async def get_current_user(

    credentials: HTTPAuthorizationCredentials = Depends(
        security
    ),

    db: AsyncSession = Depends(
        get_db
    )

) -> User:

    token = credentials.credentials

    try:

        payload = decode_access_token(
            token
        )

        user_id = payload.get(
            "sub"
        )

        if user_id is None:

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token"
            )

        try:

            user_id = int(user_id)

        except (
            TypeError,
            ValueError
        ):

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid user ID in token"
            )

    except JWTError:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

    result = await db.execute(

        select(User).where(
            User.id == user_id
        )

    )

    user = result.scalar_one_or_none()

    if user is None:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    return user


# =========================================================
# SELLER ONLY
# =========================================================

async def get_current_seller(

    current_user: User = Depends(
        get_current_user
    )

) -> User:

    if current_user.role != "seller":

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only sellers can access this resource"
        )

    return current_user


# =========================================================
# CUSTOMER ONLY
# =========================================================

async def get_current_customer(

    current_user: User = Depends(
        get_current_user
    )

) -> User:

    if current_user.role != "customer":

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can access this resource"
        )

    return current_user


# =========================================================
# ADMIN ONLY
# =========================================================

async def get_current_admin(

    current_user: User = Depends(
        get_current_user
    )

) -> User:

    if current_user.role != "admin":

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can access this resource"
        )

    return current_user
