from datetime import datetime

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    get_current_seller,
    get_current_user,
)
from app.database.database import get_db
from app.models.order import Order
from app.models.shipment import Shipment
from app.models.user import User


router = APIRouter(
    prefix="/shipments",
    tags=["Shipments"],
)


# =========================================================
# SELLER - GET MY SHIPMENTS
# =========================================================

@router.get(
    "/seller/my-shipments",
)
async def get_my_shipments(
    db: AsyncSession = Depends(get_db),
    current_seller: User = Depends(get_current_seller),
):
    result = await db.execute(
        select(Shipment)
        .where(
            Shipment.seller_id == current_seller.id
        )
        .order_by(
            Shipment.created_at.desc()
        )
    )

    shipments = result.scalars().all()

    return [
        {
            "id": shipment.id,
            "order_id": shipment.order_id,
            "seller_id": shipment.seller_id,
            "tracking_number": shipment.tracking_number,
            "status": shipment.status,
            "expected_delivery_date": (
                shipment.expected_delivery_date
            ),
            "shipped_at": shipment.shipped_at,
            "out_for_delivery_at": (
                shipment.out_for_delivery_at
            ),
            "delivered_at": shipment.delivered_at,
            "created_at": shipment.created_at,
            "updated_at": shipment.updated_at,
        }
        for shipment in shipments
    ]


# =========================================================
# SELLER - GET SINGLE SHIPMENT
# =========================================================

@router.get(
    "/seller/{shipment_id}",
)
async def get_seller_shipment(
    shipment_id: int,
    db: AsyncSession = Depends(get_db),
    current_seller: User = Depends(get_current_seller),
):
    result = await db.execute(
        select(Shipment).where(
            Shipment.id == shipment_id,
            Shipment.seller_id == current_seller.id,
        )
    )

    shipment = result.scalar_one_or_none()

    if not shipment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shipment not found.",
        )

    return {
        "id": shipment.id,
        "order_id": shipment.order_id,
        "seller_id": shipment.seller_id,
        "tracking_number": shipment.tracking_number,
        "status": shipment.status,
        "expected_delivery_date": (
            shipment.expected_delivery_date
        ),
        "shipped_at": shipment.shipped_at,
        "out_for_delivery_at": (
            shipment.out_for_delivery_at
        ),
        "delivered_at": shipment.delivered_at,
        "created_at": shipment.created_at,
        "updated_at": shipment.updated_at,
    }


# =========================================================
# SELLER - UPDATE SHIPMENT STATUS
# =========================================================

@router.patch(
    "/seller/{shipment_id}/status",
)
async def update_shipment_status(
    shipment_id: int,
    new_status: str,
    db: AsyncSession = Depends(get_db),
    current_seller: User = Depends(get_current_seller),
):
    allowed_statuses = {
        "processing",
        "shipped",
        "out_for_delivery",
        "delivered",
    }

    if new_status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Invalid shipment status. "
                "Allowed values: processing, shipped, "
                "out_for_delivery, delivered."
            ),
        )

    result = await db.execute(
        select(Shipment).where(
            Shipment.id == shipment_id,
            Shipment.seller_id == current_seller.id,
        )
    )

    shipment = result.scalar_one_or_none()

    if not shipment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shipment not found.",
        )

    # -----------------------------------------------------
    # PREVENT MOVING BACKWARD
    # -----------------------------------------------------

    status_order = {
        "processing": 1,
        "shipped": 2,
        "out_for_delivery": 3,
        "delivered": 4,
    }

    current_status_number = status_order.get(
        shipment.status,
        0,
    )

    new_status_number = status_order[new_status]

    if new_status_number < current_status_number:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Shipment cannot move from "
                f"'{shipment.status}' back to "
                f"'{new_status}'."
            ),
        )

    # -----------------------------------------------------
    # UPDATE STATUS
    # -----------------------------------------------------

    shipment.status = new_status

    # -----------------------------------------------------
    # SET TIMESTAMPS
    # -----------------------------------------------------

    now = datetime.utcnow()

    if new_status == "shipped":
        if shipment.shipped_at is None:
            shipment.shipped_at = now

    elif new_status == "out_for_delivery":
        if shipment.shipped_at is None:
            shipment.shipped_at = now

        if shipment.out_for_delivery_at is None:
            shipment.out_for_delivery_at = now

    elif new_status == "delivered":
        if shipment.shipped_at is None:
            shipment.shipped_at = now

        if shipment.out_for_delivery_at is None:
            shipment.out_for_delivery_at = now

        if shipment.delivered_at is None:
            shipment.delivered_at = now

    await db.commit()

    await db.refresh(shipment)

    return {
        "message": "Shipment status updated successfully.",
        "shipment": {
            "id": shipment.id,
            "order_id": shipment.order_id,
            "seller_id": shipment.seller_id,
            "tracking_number": shipment.tracking_number,
            "status": shipment.status,
            "expected_delivery_date": (
                shipment.expected_delivery_date
            ),
            "shipped_at": shipment.shipped_at,
            "out_for_delivery_at": (
                shipment.out_for_delivery_at
            ),
            "delivered_at": shipment.delivered_at,
            "created_at": shipment.created_at,
            "updated_at": shipment.updated_at,
        },
    }


# =========================================================
# SELLER - UPDATE TRACKING NUMBER
# =========================================================

@router.patch(
    "/seller/{shipment_id}/tracking-number",
)
async def update_tracking_number(
    shipment_id: int,
    tracking_number: str,
    db: AsyncSession = Depends(get_db),
    current_seller: User = Depends(get_current_seller),
):
    tracking_number = tracking_number.strip()

    if not tracking_number:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tracking number cannot be empty.",
        )

    result = await db.execute(
        select(Shipment).where(
            Shipment.id == shipment_id,
            Shipment.seller_id == current_seller.id,
        )
    )

    shipment = result.scalar_one_or_none()

    if not shipment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shipment not found.",
        )

    existing_result = await db.execute(
        select(Shipment).where(
            Shipment.tracking_number == tracking_number,
            Shipment.id != shipment_id,
        )
    )

    existing_shipment = (
        existing_result.scalar_one_or_none()
    )

    if existing_shipment:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This tracking number is already in use.",
        )

    shipment.tracking_number = tracking_number

    await db.commit()

    await db.refresh(shipment)

    return {
        "message": "Tracking number updated successfully.",
        "shipment": {
            "id": shipment.id,
            "order_id": shipment.order_id,
            "seller_id": shipment.seller_id,
            "tracking_number": shipment.tracking_number,
            "status": shipment.status,
            "expected_delivery_date": (
                shipment.expected_delivery_date
            ),
            "shipped_at": shipment.shipped_at,
            "out_for_delivery_at": (
                shipment.out_for_delivery_at
            ),
            "delivered_at": shipment.delivered_at,
            "created_at": shipment.created_at,
            "updated_at": shipment.updated_at,
        },
    }


# =========================================================
# CUSTOMER - GET ORDER SHIPMENTS
# =========================================================

@router.get(
    "/customer/order/{order_id}",
)
async def get_customer_order_shipments(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # -----------------------------------------------------
    # CHECK ORDER BELONGS TO CURRENT CUSTOMER
    # -----------------------------------------------------

    order_result = await db.execute(
        select(Order).where(
            Order.id == order_id,
            Order.user_id == current_user.id,
        )
    )

    order = order_result.scalar_one_or_none()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found.",
        )

    # -----------------------------------------------------
    # GET SHIPMENTS
    # -----------------------------------------------------

    shipment_result = await db.execute(
        select(Shipment)
        .where(
            Shipment.order_id == order_id
        )
        .order_by(
            Shipment.created_at.asc()
        )
    )

    shipments = shipment_result.scalars().all()

    # -----------------------------------------------------
    # RETURN TRACKING DATA
    # -----------------------------------------------------

    return {
        "order_id": order.id,
        "order_status": order.status,
        "payment_status": order.payment_status,
        "shipments": [
            {
                "id": shipment.id,
                "order_id": shipment.order_id,
                "seller_id": shipment.seller_id,
                "tracking_number": shipment.tracking_number,
                "status": shipment.status,
                "expected_delivery_date": (
                    shipment.expected_delivery_date
                ),
                "shipped_at": shipment.shipped_at,
                "out_for_delivery_at": (
                    shipment.out_for_delivery_at
                ),
                "delivered_at": shipment.delivered_at,
                "created_at": shipment.created_at,
                "updated_at": shipment.updated_at,
            }
            for shipment in shipments
        ],
    }