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


# =====================================================
# GET PRODUCT FOR OWNER
# =====================================================

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


# =====================================================
# CREATE OPTION GROUP
# =====================================================

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

    # -------------------------------------------------
    # CHECK PRODUCT
    # -------------------------------------------------

    product = await get_product_for_owner(
        product_id,
        current_user,
        db,
    )

    # -------------------------------------------------
    # CLEAN OPTION GROUP NAME
    # -------------------------------------------------

    option_name = data.name.strip()

    if not option_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Option group name is required",
        )

    # -------------------------------------------------
    # CHECK DUPLICATE OPTION GROUP
    #
    # Example:
    # Color
    # color
    # COLOR
    #
    # All are treated as the same option.
    # -------------------------------------------------

    result = await db.execute(
        select(ProductOptionGroup).where(
            ProductOptionGroup.product_id == product.id,
            ProductOptionGroup.name.ilike(
                option_name
            ),
        )
    )

    existing_group = result.scalar_one_or_none()

    if existing_group is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f'The option group "{option_name}" '
                "already exists for this product."
            ),
        )

    # -------------------------------------------------
    # VALIDATE OPTION VALUES
    # -------------------------------------------------

    if not data.values:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f'At least one value is required '
                f'for "{option_name}".'
            ),
        )

    cleaned_values = []

    existing_value_names = set()

    for value_data in data.values:

        value = value_data.value.strip()

        if not value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f'Option "{option_name}" '
                    "contains an empty value."
                ),
            )

        normalized_value = value.lower()

        if normalized_value in existing_value_names:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f'Duplicate value "{value}" '
                    f'found in option "{option_name}".'
                ),
            )

        existing_value_names.add(
            normalized_value
        )

        cleaned_values.append(
            (
                value,
                value_data.sort_order,
            )
        )

    # -------------------------------------------------
    # CREATE OPTION GROUP
    # -------------------------------------------------

    option_group = ProductOptionGroup(
        product_id=product.id,
        name=option_name,
        sort_order=data.sort_order,
    )

    db.add(option_group)

    await db.flush()

    # -------------------------------------------------
    # CREATE OPTION VALUES
    # -------------------------------------------------

    for value, sort_order in cleaned_values:

        option_value = ProductOptionValue(
            option_group_id=option_group.id,
            value=value,
            sort_order=sort_order,
        )

        db.add(option_value)

    # -------------------------------------------------
    # SAVE
    # -------------------------------------------------

    await db.commit()

    # -------------------------------------------------
    # LOAD CREATED GROUP WITH VALUES
    # -------------------------------------------------

    result = await db.execute(
        select(ProductOptionGroup).where(
            ProductOptionGroup.id ==
            option_group.id
        )
    )

    created_group = (
        result.scalar_one()
    )

    return created_group


# =====================================================
# GET PRODUCT OPTIONS
# =====================================================

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

    # -------------------------------------------------
    # CHECK PRODUCT
    # -------------------------------------------------

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

    # -------------------------------------------------
    # GET OPTION GROUPS
    # -------------------------------------------------

    result = await db.execute(
        select(ProductOptionGroup)
        .where(
            ProductOptionGroup.product_id ==
            product_id
        )
        .order_by(
            ProductOptionGroup.sort_order,
            ProductOptionGroup.id,
        )
    )

    groups = result.scalars().all()

    return groups


# =====================================================
# DELETE OPTION GROUP
# =====================================================

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

    # -------------------------------------------------
    # FIND OPTION GROUP
    # -------------------------------------------------

    result = await db.execute(
        select(ProductOptionGroup).where(
            ProductOptionGroup.id ==
            option_group_id
        )
    )

    option_group = (
        result.scalar_one_or_none()
    )

    if option_group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Option group not found",
        )

    # -------------------------------------------------
    # CHECK PRODUCT OWNER
    # -------------------------------------------------

    await get_product_for_owner(
        option_group.product_id,
        current_user,
        db,
    )

    # -------------------------------------------------
    # DELETE
    #
    # ProductOptionValue records should be deleted
    # automatically if the relationship has
    # cascade="all, delete-orphan".
    # -------------------------------------------------

    await db.delete(option_group)

    await db.commit()

    return {
        "success": True,
        "message": "Option group deleted successfully",
    }