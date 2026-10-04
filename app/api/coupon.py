from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_admin
from app.database.database import get_db
from app.models.coupon import Coupon
from app.models.user import User


router = APIRouter(
    prefix="/admin/coupons",
    tags=["Admin Coupons"],
)


class CouponCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    discount_type: str
    discount_value: float
    minimum_order_amount: float = 0
    maximum_discount: float | None = None
    start_date: datetime
    expiry_date: datetime
    usage_limit: int | None = None
    is_active: bool = True


class CouponUpdate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    discount_type: str
    discount_value: float
    minimum_order_amount: float = 0
    maximum_discount: float | None = None
    start_date: datetime
    expiry_date: datetime
    usage_limit: int | None = None
    is_active: bool = True


def validate_coupon_data(data):
    if data.discount_type not in ["percentage", "fixed"]:
        raise HTTPException(
            status_code=400,
            detail="Discount type must be percentage or fixed.",
        )

    if data.discount_value <= 0:
        raise HTTPException(
            status_code=400,
            detail="Discount value must be greater than 0.",
        )

    if (
        data.discount_type == "percentage"
        and data.discount_value > 100
    ):
        raise HTTPException(
            status_code=400,
            detail="Percentage discount cannot exceed 100.",
        )

    if data.minimum_order_amount < 0:
        raise HTTPException(
            status_code=400,
            detail="Minimum order amount cannot be negative.",
        )

    if (
        data.maximum_discount is not None
        and data.maximum_discount < 0
    ):
        raise HTTPException(
            status_code=400,
            detail="Maximum discount cannot be negative.",
        )

    if data.start_date >= data.expiry_date:
        raise HTTPException(
            status_code=400,
            detail="Start date must be before expiry date.",
        )

    if (
        data.usage_limit is not None
        and data.usage_limit <= 0
    ):
        raise HTTPException(
            status_code=400,
            detail="Usage limit must be greater than 0.",
        )


@router.get("/")
async def get_coupons(
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    result = await db.execute(
        select(Coupon).order_by(
            Coupon.created_at.desc()
        )
    )

    coupons = result.scalars().all()

    return {
        "success": True,
        "message": "Coupons fetched successfully.",
        "data": coupons,
    }


@router.post("/")
async def create_coupon(
    coupon_data: CouponCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    validate_coupon_data(coupon_data)

    code = coupon_data.code.strip().upper()

    if not code:
        raise HTTPException(
            status_code=400,
            detail="Coupon code cannot be empty.",
        )

    existing_result = await db.execute(
        select(Coupon).where(
            Coupon.code == code
        )
    )

    existing_coupon = existing_result.scalar_one_or_none()

    if existing_coupon:
        raise HTTPException(
            status_code=400,
            detail="Coupon code already exists.",
        )

    coupon = Coupon(
        code=code,
        discount_type=coupon_data.discount_type,
        discount_value=coupon_data.discount_value,
        minimum_order_amount=coupon_data.minimum_order_amount,
        maximum_discount=coupon_data.maximum_discount,
        start_date=coupon_data.start_date,
        expiry_date=coupon_data.expiry_date,
        usage_limit=coupon_data.usage_limit,
        is_active=coupon_data.is_active,
    )

    db.add(coupon)

    await db.commit()
    await db.refresh(coupon)

    return {
        "success": True,
        "message": "Coupon created successfully.",
        "data": coupon,
    }


@router.get("/{coupon_id}")
async def get_coupon(
    coupon_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    result = await db.execute(
        select(Coupon).where(
            Coupon.id == coupon_id
        )
    )

    coupon = result.scalar_one_or_none()

    if not coupon:
        raise HTTPException(
            status_code=404,
            detail="Coupon not found.",
        )

    return {
        "success": True,
        "message": "Coupon fetched successfully.",
        "data": coupon,
    }


@router.put("/{coupon_id}")
async def update_coupon(
    coupon_id: int,
    coupon_data: CouponUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    validate_coupon_data(coupon_data)

    code = coupon_data.code.strip().upper()

    if not code:
        raise HTTPException(
            status_code=400,
            detail="Coupon code cannot be empty.",
        )

    result = await db.execute(
        select(Coupon).where(
            Coupon.id == coupon_id
        )
    )

    coupon = result.scalar_one_or_none()

    if not coupon:
        raise HTTPException(
            status_code=404,
            detail="Coupon not found.",
        )

    duplicate_result = await db.execute(
        select(Coupon).where(
            Coupon.code == code,
            Coupon.id != coupon_id,
        )
    )

    duplicate_coupon = (
        duplicate_result.scalar_one_or_none()
    )

    if duplicate_coupon:
        raise HTTPException(
            status_code=400,
            detail="Coupon code already exists.",
        )

    coupon.code = code
    coupon.discount_type = coupon_data.discount_type
    coupon.discount_value = coupon_data.discount_value
    coupon.minimum_order_amount = (
        coupon_data.minimum_order_amount
    )
    coupon.maximum_discount = (
        coupon_data.maximum_discount
    )
    coupon.start_date = coupon_data.start_date
    coupon.expiry_date = coupon_data.expiry_date
    coupon.usage_limit = coupon_data.usage_limit
    coupon.is_active = coupon_data.is_active

    await db.commit()
    await db.refresh(coupon)

    return {
        "success": True,
        "message": "Coupon updated successfully.",
        "data": coupon,
    }


@router.patch("/{coupon_id}/status")
async def update_coupon_status(
    coupon_id: int,
    is_active: bool,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    result = await db.execute(
        select(Coupon).where(
            Coupon.id == coupon_id
        )
    )

    coupon = result.scalar_one_or_none()

    if not coupon:
        raise HTTPException(
            status_code=404,
            detail="Coupon not found.",
        )

    coupon.is_active = is_active

    await db.commit()
    await db.refresh(coupon)

    return {
        "success": True,
        "message": "Coupon status updated successfully.",
        "data": coupon,
    }


@router.delete("/{coupon_id}")
async def delete_coupon(
    coupon_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    result = await db.execute(
        select(Coupon).where(
            Coupon.id == coupon_id
        )
    )

    coupon = result.scalar_one_or_none()

    if not coupon:
        raise HTTPException(
            status_code=404,
            detail="Coupon not found.",
        )

    await db.delete(coupon)
    await db.commit()

    return {
        "success": True,
        "message": "Coupon deleted successfully.",
        "data": None,
    }