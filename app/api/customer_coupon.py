from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_customer
from app.database.database import get_db
from app.models.coupon import Coupon
from app.models.user import User


router = APIRouter(
    prefix="/coupons",
    tags=["Customer Coupons"],
)


# =========================================================
# VALIDATE COUPON REQUEST
# =========================================================

class CouponValidateRequest(BaseModel):
    code: str = Field(
        ...,
        min_length=1,
        max_length=50,
    )

    subtotal: float = Field(
        ...,
        gt=0,
    )


# =========================================================
# VALIDATE COUPON RESPONSE
# =========================================================

class CouponValidateResponse(BaseModel):
    valid: bool
    code: str
    discount_type: str
    discount_value: float
    discount_amount: float
    subtotal: float
    final_amount: float


# =========================================================
# VALIDATE COUPON - CUSTOMER
# =========================================================

@router.post(
    "/validate",
    response_model=CouponValidateResponse,
)
async def validate_coupon(
    coupon_data: CouponValidateRequest,
    db: AsyncSession = Depends(get_db),
    current_customer: User = Depends(get_current_customer),
):
    code = coupon_data.code.strip().upper()

    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Coupon code cannot be empty.",
        )

    subtotal = float(coupon_data.subtotal)

    # -----------------------------------------------------
    # GET COUPON
    # -----------------------------------------------------

    result = await db.execute(
        select(Coupon).where(
            Coupon.code == code
        )
    )

    coupon = result.scalar_one_or_none()

    if not coupon:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid coupon code.",
        )

    # -----------------------------------------------------
    # CHECK ACTIVE
    # -----------------------------------------------------

    if not coupon.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This coupon is inactive.",
        )

    # -----------------------------------------------------
    # CHECK DATE
    # -----------------------------------------------------

    now = datetime.utcnow()

    if now < coupon.start_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This coupon is not active yet.",
        )

    if now > coupon.expiry_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This coupon has expired.",
        )

    # -----------------------------------------------------
    # CHECK USAGE LIMIT
    # -----------------------------------------------------

    if (
        coupon.usage_limit is not None
        and coupon.used_count >= coupon.usage_limit
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This coupon usage limit has been reached.",
        )

    # -----------------------------------------------------
    # CHECK MINIMUM ORDER
    # -----------------------------------------------------

    if subtotal < float(coupon.minimum_order_amount):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Minimum order amount for this coupon "
                f"is ₹{float(coupon.minimum_order_amount):.2f}."
            ),
        )

    # -----------------------------------------------------
    # CALCULATE DISCOUNT
    # -----------------------------------------------------

    if coupon.discount_type == "percentage":
        discount_amount = (
            subtotal
            * float(coupon.discount_value)
            / 100
        )

    elif coupon.discount_type == "fixed":
        discount_amount = float(
            coupon.discount_value
        )

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid coupon discount type.",
        )

    # -----------------------------------------------------
    # MAXIMUM DISCOUNT
    # -----------------------------------------------------

    if coupon.maximum_discount is not None:
        discount_amount = min(
            discount_amount,
            float(coupon.maximum_discount),
        )

    # -----------------------------------------------------
    # DISCOUNT CANNOT EXCEED SUBTOTAL
    # -----------------------------------------------------

    discount_amount = min(
        discount_amount,
        subtotal,
    )

    # -----------------------------------------------------
    # FINAL AMOUNT
    # -----------------------------------------------------

    final_amount = max(
        subtotal - discount_amount,
        0,
    )

    return CouponValidateResponse(
        valid=True,
        code=coupon.code,
        discount_type=coupon.discount_type,
        discount_value=float(coupon.discount_value),
        discount_amount=round(
            discount_amount,
            2,
        ),
        subtotal=round(
            subtotal,
            2,
        ),
        final_amount=round(
            final_amount,
            2,
        ),
    )