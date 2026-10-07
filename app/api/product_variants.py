from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    get_current_user,
)
from app.database.database import get_db
from app.models.product import Product
from app.models.product_option_group import ProductOptionGroup
from app.models.product_option_value import ProductOptionValue
from app.models.product_variant import ProductVariant
from app.models.product_variant_value import ProductVariantValue
from app.models.user import User
from app.schemas.product_variant import (
    ProductVariantCreate,
    ProductVariantResponse,
    ProductVariantUpdate,
)


router = APIRouter(
    prefix="/api/products",
    tags=["Product Variants"],
)

# =========================================================
# CHECK PRODUCT ACCESS
# =========================================================

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


# =========================================================
# VALIDATE OPTION VALUES
# =========================================================

async def validate_option_values(
    product_id: int,
    option_value_ids: list[int],
    db: AsyncSession,
) -> list[ProductOptionValue]:

    if not option_value_ids:
        return []

    if len(option_value_ids) != len(set(option_value_ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate option values are not allowed",
        )

    result = await db.execute(
        select(ProductOptionValue).where(
            ProductOptionValue.id.in_(option_value_ids)
        )
    )

    option_values = result.scalars().all()

    if len(option_values) != len(option_value_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more option values do not exist",
        )

    option_group_ids = {
        option_value.option_group_id
        for option_value in option_values
    }

    result = await db.execute(
        select(ProductOptionGroup).where(
            ProductOptionGroup.id.in_(option_group_ids),
            ProductOptionGroup.product_id == product_id,
        )
    )

    valid_groups = result.scalars().all()

    valid_group_ids = {
        group.id
        for group in valid_groups
    }

    for option_value in option_values:

        if option_value.option_group_id not in valid_group_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Option values must belong to this product",
            )

    if len(option_group_ids) != len(option_value_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only one value can be selected from each option group",
        )

    return option_values


# =========================================================
# CHECK DUPLICATE VARIANT COMBINATION
# =========================================================

async def check_duplicate_combination(
    product_id: int,
    option_value_ids: list[int],
    db: AsyncSession,
    exclude_variant_id: int | None = None,
) -> None:

    if not option_value_ids:
        return

    result = await db.execute(
        select(ProductVariant).where(
            ProductVariant.product_id == product_id
        )
    )

    variants = result.scalars().all()

    requested_values = set(option_value_ids)

    for variant in variants:

        if (
            exclude_variant_id is not None
            and variant.id == exclude_variant_id
        ):
            continue

        result = await db.execute(
            select(
                ProductVariantValue.option_value_id
            ).where(
                ProductVariantValue.variant_id == variant.id
            )
        )

        existing_values = set(
            result.scalars().all()
        )

        if existing_values == requested_values:

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This variant combination already exists",
            )


# =========================================================
# BUILD RESPONSE
# =========================================================

async def build_variant_response(
    variant: ProductVariant,
    db: AsyncSession,
) -> ProductVariantResponse:

    result = await db.execute(
        select(
            ProductVariantValue.option_value_id
        ).where(
            ProductVariantValue.variant_id == variant.id
        )
    )

    option_value_ids = list(
        result.scalars().all()
    )

    return ProductVariantResponse(
        id=variant.id,
        product_id=variant.product_id,
        sku=variant.sku,
        price=variant.price,
        original_price=variant.original_price,
        stock=variant.stock,
        is_active=variant.is_active,
        option_value_ids=option_value_ids,
    )


# =========================================================
# CREATE VARIANT
# =========================================================

@router.post(
    "/{product_id}/variants",
    response_model=ProductVariantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_variant(
    product_id: int,
    data: ProductVariantCreate,
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

    await validate_option_values(
        product.id,
        data.option_value_ids,
        db,
    )

    await check_duplicate_combination(
        product.id,
        data.option_value_ids,
        db,
    )

    if data.sku:

        result = await db.execute(
            select(ProductVariant).where(
                ProductVariant.sku == data.sku
            )
        )

        existing_sku = (
            result.scalar_one_or_none()
        )

        if existing_sku is not None:

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SKU already exists",
            )

    variant = ProductVariant(
        product_id=product.id,
        sku=data.sku,
        price=data.price,
        original_price=data.original_price,
        stock=data.stock,
        is_active=True,
    )

    db.add(variant)

    await db.flush()

    for option_value_id in data.option_value_ids:

        db.add(
            ProductVariantValue(
                variant_id=variant.id,
                option_value_id=option_value_id,
            )
        )

    await db.commit()

    await db.refresh(variant)

    return await build_variant_response(
        variant,
        db,
    )


# =========================================================
# GET PRODUCT VARIANTS
# =========================================================

@router.get(
    "/{product_id}/variants",
    response_model=list[ProductVariantResponse],
)
async def get_product_variants(
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
        select(ProductVariant).where(
            ProductVariant.product_id == product_id,
            ProductVariant.is_active.is_(True),
        )
    )

    variants = result.scalars().all()

    responses = []

    for variant in variants:

        responses.append(
            await build_variant_response(
                variant,
                db,
            )
        )

    return responses


# =========================================================
# GET SINGLE VARIANT
# =========================================================

@router.get(
    "/variants/{variant_id}",
    response_model=ProductVariantResponse,
)
async def get_variant(
    variant_id: int,
    db: AsyncSession = Depends(
        get_db
    ),
):

    result = await db.execute(
        select(ProductVariant).where(
            ProductVariant.id == variant_id,
            ProductVariant.is_active.is_(True),
        )
    )

    variant = result.scalar_one_or_none()

    if variant is None:

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variant not found",
        )

    return await build_variant_response(
        variant,
        db,
    )


# =========================================================
# UPDATE VARIANT
# =========================================================

@router.put(
    "/variants/{variant_id}",
    response_model=ProductVariantResponse,
)
async def update_variant(
    variant_id: int,
    data: ProductVariantUpdate,
    current_user: User = Depends(
        get_current_user
    ),
    db: AsyncSession = Depends(
        get_db
    ),
):

    result = await db.execute(
        select(ProductVariant).where(
            ProductVariant.id == variant_id
        )
    )

    variant = result.scalar_one_or_none()

    if variant is None:

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variant not found",
        )

    await get_product_for_owner(
        variant.product_id,
        current_user,
        db,
    )

    if data.option_value_ids is not None:

        await validate_option_values(
            variant.product_id,
            data.option_value_ids,
            db,
        )

        await check_duplicate_combination(
            variant.product_id,
            data.option_value_ids,
            db,
            exclude_variant_id=variant.id,
        )

        result = await db.execute(
            select(ProductVariantValue).where(
                ProductVariantValue.variant_id
                == variant.id
            )
        )

        existing_values = result.scalars().all()

        for item in existing_values:
            await db.delete(item)

        for option_value_id in data.option_value_ids:

            db.add(
                ProductVariantValue(
                    variant_id=variant.id,
                    option_value_id=option_value_id,
                )
            )

    if data.sku is not None:

        result = await db.execute(
            select(ProductVariant).where(
                ProductVariant.sku == data.sku,
                ProductVariant.id != variant.id,
            )
        )

        existing_sku = (
            result.scalar_one_or_none()
        )

        if existing_sku is not None:

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SKU already exists",
            )

        variant.sku = data.sku

    if data.price is not None:
        variant.price = data.price

    if data.original_price is not None:
        variant.original_price = (
            data.original_price
        )

    if data.stock is not None:
        variant.stock = data.stock

    if data.is_active is not None:
        variant.is_active = data.is_active

    await db.commit()

    await db.refresh(variant)

    return await build_variant_response(
        variant,
        db,
    )


# =========================================================
# DELETE VARIANT
# =========================================================

@router.delete(
    "/variants/{variant_id}",
)
async def delete_variant(
    variant_id: int,
    current_user: User = Depends(
        get_current_user
    ),
    db: AsyncSession = Depends(
        get_db
    ),
):

    result = await db.execute(
        select(ProductVariant).where(
            ProductVariant.id == variant_id
        )
    )

    variant = result.scalar_one_or_none()

    if variant is None:

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variant not found",
        )

    await get_product_for_owner(
        variant.product_id,
        current_user,
        db,
    )

    variant.is_active = False

    await db.commit()

    return {
        "success": True,
        "message": "Variant deleted successfully",
    }