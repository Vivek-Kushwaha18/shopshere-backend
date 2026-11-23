
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.auth import get_current_user
from app.database.database import get_db

from app.models.product import Product
from app.models.review import Review
from app.models.user import User
from app.models.order import Order, OrderItem

from app.schemas.review import (
    ReviewCreate,
    ReviewResponse,
    ReviewUpdate,
)


# ======================================================
# REVIEW ROUTER
# ======================================================

router = APIRouter(
    prefix="/reviews",
    tags=["Reviews"],
)


# ======================================================
# UPDATE PRODUCT AVERAGE RATING AND REVIEW COUNT
# ======================================================

async def update_product_rating(
    product_id: int,
    db: AsyncSession,
) -> None:
    result = await db.execute(
        select(
            func.avg(Review.rating),
            func.count(Review.id),
        ).where(
            Review.product_id == product_id
        )
    )

    average_rating, reviews_count = result.one()

    product_result = await db.execute(
        select(Product).where(Product.id == product_id)
    )

    product = product_result.scalar_one_or_none()

    if product:
        product.rating = float(average_rating or 0)
        product.reviews_count = int(reviews_count or 0)


# ======================================================
# REVIEW RESPONSE HELPER
# ======================================================

def review_response(review: Review) -> dict:
    return {
        "id": review.id,
        "user_id": review.user_id,
        "product_id": review.product_id,
        "rating": review.rating,
        "comment": review.comment,
        "created_at": review.created_at,
        "updated_at": review.updated_at,
        "user_name": review.user.full_name,
    }


# ======================================================
# VERIFY DELIVERED PURCHASE
# ======================================================

async def has_delivered_purchase(
    user_id: int,
    product_id: int,
    db: AsyncSession,
) -> bool:
    """
    Returns True only if the customer has an order
    containing this product with status 'delivered'.
    """

    result = await db.execute(
        select(Order.id)
        .join(
            OrderItem,
            OrderItem.order_id == Order.id,
        )
        .where(
            Order.user_id == user_id,
            OrderItem.product_id == product_id,
            func.lower(Order.status) == "delivered",
        )
        .limit(1)
    )

    return result.scalar_one_or_none() is not None


# ======================================================
# GET MY REVIEWS
# GET /reviews/me
# AUTHENTICATION REQUIRED
# ======================================================

@router.get(
    "/me",
    response_model=list[ReviewResponse],
)
async def get_my_reviews(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Review)
        .options(selectinload(Review.user))
        .where(
            Review.user_id == current_user.id
        )
        .order_by(Review.created_at.desc())
    )

    reviews = result.scalars().all()

    return [
        review_response(review)
        for review in reviews
    ]


# ======================================================
# GET ALL REVIEWS FOR A PRODUCT
# GET /reviews/product/{product_id}
# PUBLIC ENDPOINT
# ======================================================

@router.get(
    "/product/{product_id}",
    response_model=list[ReviewResponse],
)
async def get_product_reviews(
    product_id: int,
    db: AsyncSession = Depends(get_db),
):
    product_result = await db.execute(
        select(Product).where(
            Product.id == product_id
        )
    )

    product = product_result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    result = await db.execute(
        select(Review)
        .options(selectinload(Review.user))
        .where(
            Review.product_id == product_id
        )
        .order_by(Review.created_at.desc())
    )

    reviews = result.scalars().all()

    return [
        review_response(review)
        for review in reviews
    ]


# ======================================================
# CREATE REVIEW
# POST /reviews
# CUSTOMER ONLY
# DELIVERED PURCHASE REQUIRED
# ======================================================

@router.post(
    "",
    response_model=ReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_review(
    review_data: ReviewCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # ==================================================
    # CUSTOMER ROLE CHECK
    # ==================================================

    if current_user.role != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can write reviews",
        )

    # ==================================================
    # PRODUCT VALIDATION
    # ==================================================

    product_result = await db.execute(
        select(Product).where(
            Product.id == review_data.product_id,
            Product.is_deleted.is_(False),
            Product.is_active.is_(True),
        )
    )

    product = product_result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # ==================================================
    # CHECK EXISTING REVIEW
    # ==================================================

    existing_result = await db.execute(
        select(Review).where(
            Review.product_id == review_data.product_id,
            Review.user_id == current_user.id,
        )
    )

    existing_review = existing_result.scalar_one_or_none()

    if existing_review:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already reviewed this product",
        )

    # ==================================================
    # VERIFY DELIVERED PURCHASE
    # ==================================================

    delivered = await has_delivered_purchase(
        user_id=current_user.id,
        product_id=review_data.product_id,
        db=db,
    )

    if not delivered:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You can review this product only after "
                "your order has been delivered."
            ),
        )

    # ==================================================
    # CREATE REVIEW
    # ==================================================

    review = Review(
        user_id=current_user.id,
        product_id=review_data.product_id,
        rating=review_data.rating,
        comment=review_data.comment,
    )

    db.add(review)

    await db.flush()

    # ==================================================
    # UPDATE PRODUCT RATING
    # ==================================================

    await update_product_rating(
        review_data.product_id,
        db,
    )

    await db.commit()

    await db.refresh(review)

    review.user = current_user

    return review_response(review)


# ======================================================
# UPDATE REVIEW
# PUT /reviews/{review_id}
# REVIEW OWNER ONLY
# ======================================================

@router.put(
    "/{review_id}",
    response_model=ReviewResponse,
)
async def update_review(
    review_id: int,
    review_data: ReviewUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Review)
        .options(selectinload(Review.user))
        .where(
            Review.id == review_id
        )
    )

    review = result.scalar_one_or_none()

    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        )

    if review.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own review",
        )

    review.rating = review_data.rating
    review.comment = review_data.comment

    await db.flush()

    await update_product_rating(
        review.product_id,
        db,
    )

    await db.commit()

    await db.refresh(review)

    review.user = current_user

    return review_response(review)


# ======================================================
# DELETE REVIEW
# DELETE /reviews/{review_id}
# REVIEW OWNER OR ADMIN
# ======================================================

@router.delete(
    "/{review_id}",
)
async def delete_review(
    review_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Review).where(
            Review.id == review_id
        )
    )

    review = result.scalar_one_or_none()

    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        )

    if (
        review.user_id != current_user.id
        and current_user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot delete this review",
        )

    product_id = review.product_id

    await db.delete(review)

    await db.flush()

    await update_product_rating(
        product_id,
        db,
    )

    await db.commit()

    return {
        "success": True,
        "message": "Review deleted successfully",
    }
