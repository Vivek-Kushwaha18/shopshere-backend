from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database.database import get_db
from app.models.product import Product
from app.models.product_option_group import ProductOptionGroup
from app.models.product_option_value import ProductOptionValue
from app.models.user import User
from app.schemas.product_variant import (
    ProductOptionGroupCreate,
    ProductOptionGroupResponse,
)


router = APIRouter(
    prefix="/api/products",
    tags=["Product Options"],
)

async def get_product_for_owner(
    product_id: int,
    current_user: User,
    db: AsyncSession,
) -> Product:

    result = await db.execute(
        select(Product).where(
            Product.id == product_id,
            Product.is_deleted.is_(False),
        )
    )

    product = result.scalar_one_or_none()

    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    if (
        product.seller_id != current_user.id
        and current_user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage this product",
        )

    return product


@router.post(
    "/{product_id}/options",
    response_model=ProductOptionGroupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_option_group(
    product_id: int,
    data: ProductOptionGroupCreate,
    current_user: User = Depends(
        get_current_user
    ),
    db: AsyncSession = Depends(
        get_db
    ),
):

    product = await get_product_for_owner(
        product_id,
        current_user,
        db,
    )

    result = await db.execute(
        select(ProductOptionGroup).where(
            ProductOptionGroup.product_id == product.id,
            ProductOptionGroup.name == data.name,
        )
    )

    existing_group = result.scalar_one_or_none()

    if existing_group is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This option group already exists",
        )

    option_group = ProductOptionGroup(
        product_id=product.id,
        name=data.name,
        sort_order=data.sort_order,
    )

    db.add(option_group)

    await db.flush()

    for value_data in data.values:

        option_value = ProductOptionValue(
            option_group_id=option_group.id,
            value=value_data.value,
            sort_order=value_data.sort_order,
        )

        db.add(option_value)

    await db.commit()

    await db.refresh(option_group)

    return option_group


@router.get(
    "/{product_id}/options",
    response_model=list[ProductOptionGroupResponse],
)
async def get_product_options(
    product_id: int,
    db: AsyncSession = Depends(
        get_db
    ),
):

    result = await db.execute(
        select(Product).where(
            Product.id == product_id,
            Product.is_deleted.is_(False),
        )
    )

    product = result.scalar_one_or_none()

    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    result = await db.execute(
        select(ProductOptionGroup)
        .where(
            ProductOptionGroup.product_id == product_id
        )
        .order_by(
            ProductOptionGroup.sort_order,
            ProductOptionGroup.id,
        )
    )

    groups = result.scalars().all()

    return groups


@router.delete(
    "/options/{option_group_id}",
)
async def delete_option_group(
    option_group_id: int,
    current_user: User = Depends(
        get_current_user
    ),
    db: AsyncSession = Depends(
        get_db
    ),
):

    result = await db.execute(
        select(ProductOptionGroup).where(
            ProductOptionGroup.id == option_group_id
        )
    )

    option_group = result.scalar_one_or_none()

    if option_group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Option group not found",
        )

    await get_product_for_owner(
        option_group.product_id,
        current_user,
        db,
    )

    await db.delete(option_group)

    await db.commit()

    return {
        "success": True,
        "message": "Option group deleted successfully",
    }