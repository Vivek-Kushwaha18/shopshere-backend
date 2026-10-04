from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import get_current_customer
from app.database.database import get_db
from app.models.product import Product
from app.models.user import User
from app.models.wishlist import Wishlist


router = APIRouter(
    prefix="/api/wishlist",
    tags=["Wishlist"],
)


# =========================================================
# GET CUSTOMER WISHLIST
# =========================================================

@router.get("/")
async def get_wishlist(
    current_user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Wishlist)
        .options(
            selectinload(Wishlist.product)
        )
        .where(
            Wishlist.user_id == current_user.id
        )
        .order_by(
            Wishlist.created_at.desc()
        )
    )

    wishlist_items = result.scalars().all()

    items = []

    for wishlist_item in wishlist_items:
        product = wishlist_item.product

        if product is None:
            continue

        if product.is_deleted or not product.is_active:
            continue

        items.append(
            {
                "id": wishlist_item.id,
                "product_id": product.id,
                "created_at": wishlist_item.created_at,
                "product": {
                    "id": product.id,
                    "name": product.name,
                    "slug": product.slug,
                    "description": product.description,
                    "price": float(product.price),
                    "original_price": (
                        float(product.original_price)
                        if product.original_price is not None
                        else None
                    ),
                    "stock": product.stock,
                    "image_url": product.image_url,
                    "rating": product.rating,
                    "reviews_count": product.reviews_count,
                },
            }
        )

    return {
        "success": True,
        "data": {
            "items": items,
            "total_items": len(items),
        },
    }


# =========================================================
# CHECK PRODUCT WISHLIST STATUS
# =========================================================

@router.get("/check/{product_id}")
async def check_wishlist(
    product_id: int,
    current_user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Wishlist).where(
            Wishlist.user_id == current_user.id,
            Wishlist.product_id == product_id,
        )
    )

    wishlist_item = result.scalar_one_or_none()

    return {
        "success": True,
        "data": {
            "product_id": product_id,
            "is_wishlisted": wishlist_item is not None,
            "wishlist_id": (
                wishlist_item.id
                if wishlist_item is not None
                else None
            ),
        },
    }


# =========================================================
# ADD PRODUCT TO WISHLIST
# =========================================================

@router.post(
    "/{product_id}",
    status_code=status.HTTP_201_CREATED,
)
async def add_to_wishlist(
    product_id: int,
    current_user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    # -----------------------------------------------------
    # Get active product
    # -----------------------------------------------------

    result = await db.execute(
        select(Product).where(
            Product.id == product_id,
            Product.is_deleted.is_(False),
            Product.is_active.is_(True),
        )
    )

    product = result.scalar_one_or_none()

    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # -----------------------------------------------------
    # Check if already in wishlist
    # -----------------------------------------------------

    result = await db.execute(
        select(Wishlist).where(
            Wishlist.user_id == current_user.id,
            Wishlist.product_id == product.id,
        )
    )

    existing_item = result.scalar_one_or_none()

    if existing_item is not None:
        return {
            "success": True,
            "message": "Product is already in your wishlist",
            "data": {
                "wishlist_id": existing_item.id,
                "product_id": product.id,
            },
        }

    # -----------------------------------------------------
    # Create wishlist item
    # -----------------------------------------------------

    wishlist_item = Wishlist(
        user_id=current_user.id,
        product_id=product.id,
    )

    db.add(wishlist_item)

    await db.commit()

    await db.refresh(wishlist_item)

    return {
        "success": True,
        "message": "Product added to wishlist successfully",
        "data": {
            "wishlist_id": wishlist_item.id,
            "product_id": product.id,
        },
    }


# =========================================================
# REMOVE PRODUCT FROM WISHLIST
# =========================================================

@router.delete("/{product_id}")
async def remove_from_wishlist(
    product_id: int,
    current_user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Wishlist).where(
            Wishlist.user_id == current_user.id,
            Wishlist.product_id == product_id,
        )
    )

    wishlist_item = result.scalar_one_or_none()

    if wishlist_item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product is not in your wishlist",
        )

    await db.delete(wishlist_item)

    await db.commit()

    return {
        "success": True,
        "message": "Product removed from wishlist successfully",
        "data": {
            "product_id": product_id,
        },
    }