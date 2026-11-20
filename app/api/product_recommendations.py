
from fastapi import (
    APIRouter,
    Depends,
    Query,
)

from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.security import decode_access_token
from app.database.database import get_db
from app.models.user import User
from app.schemas.product import ProductResponse

from app.services.product_recommendations import (
    get_recommended_products,
    get_recently_viewed_products,
    record_product_view,
)

from sqlalchemy import select
from jose import JWTError

router = APIRouter(
    prefix="/api/products",
    tags=["Product Recommendations"],
)

optional_security = HTTPBearer(auto_error=False)


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        optional_security
    ),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if credentials is None:
        return None

    try:
        payload = decode_access_token(
            credentials.credentials
        )
        user_id = int(payload["sub"])
    except (JWTError, ValueError, TypeError, KeyError):
        return None

    result = await db.execute(
        select(User).where(User.id == user_id)
    )

    return result.scalar_one_or_none()


@router.post("/{product_id}/view")
async def save_product_view(
    product_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await record_product_view(
        db=db,
        user_id=current_user.id,
        product_id=product_id,
    )


@router.get(
    "/recently-viewed",
    response_model=list[ProductResponse],
)
async def recently_viewed(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_recently_viewed_products(
        db=db,
        user_id=current_user.id,
    )


@router.get(
    "/recommendations/for-me",
    response_model=list[ProductResponse],
)
async def recommendations_for_me(
    limit: int = Query(default=12, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_recommended_products(
        db=db,
        user_id=current_user.id,
        limit=limit,
    )


@router.get(
    "/{product_id}/recommendations",
    response_model=list[ProductResponse],
)
async def product_recommendations(
    product_id: int,
    limit: int = Query(default=12, ge=1, le=50),
    current_user: User | None = Depends(
        get_optional_user
    ),
    db: AsyncSession = Depends(get_db),
):
    return await get_recommended_products(
        db=db,
        product_id=product_id,
        user_id=(
            current_user.id
            if current_user is not None
            else None
        ),
        limit=limit,
    )
