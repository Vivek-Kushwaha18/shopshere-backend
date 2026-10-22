
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
from app.models.payment import Payment
from app.models.shipment import Shipment
from app.models.user import User


router = APIRouter(
    prefix="/shipments",
    tags=["Shipments"],
)


def serialize_shipment(shipment: Shipment):
    return {
        "id": shipment.id,
        "order_id": shipment.order_id,
        "seller_id": shipment.seller_id,
        "tracking_number": shipment.tracking_number,
        "status": shipment.status,
        "expected_delivery_date": shipment.expected_delivery_date,
        "shipped_at": shipment.shipped_at,
        "out_for_delivery_at": shipment.out_for_delivery_at,
        "delivered_at": shipment.delivered_at,
        "created_at": shipment.created_at,
        "updated_at": shipment.updated_at,
    }


# =========================================================
# SELLER - GET MY SHIPMENTS
# =========================================================

@router.get("/seller/my-shipments")
async def get_my_shipments(
    db: AsyncSession = Depends(get_db),
    current_seller: User = Depends(get_current_seller),
):
    result = await db.execute(
        select(Shipment)
        .where(Shipment.seller_id == current_seller.id)
        .order_by(Shipment.created_at.desc())
    )

    shipments = result.scalars().all()

    return [
        serialize_shipment(shipment)
        for shipment in shipments
    ]


# =========================================================
# SELLER - GET SINGLE SHIPMENT
# =========================================================

@router.get("/seller/{shipment_id}")
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

    if shipment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shipment not found.",
        )

    return serialize_shipment(shipment)


# =========================================================
# SELLER - UPDATE SHIPMENT STATUS
# =========================================================

@router.patch("/seller/{shipment_id}/status")
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

    new_status = new_status.strip().lower()

    if new_status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Invalid shipment status. Allowed values: "
                "processing, shipped, out_for_delivery, delivered."
            ),
        )

    result = await db.execute(
        select(Shipment).where(
            Shipment.id == shipment_id,
            Shipment.seller_id == current_seller.id,
        )
    )

    shipment = result.scalar_one_or_none()

    if shipment is None:
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

    current_status = (
        shipment.status or "processing"
    ).strip().lower()

    current_status_number = status_order.get(
        current_status,
        0,
    )

    new_status_number = status_order[new_status]

    if new_status_number < current_status_number:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Shipment cannot move from "
                f"'{current_status}' back to '{new_status}'."
            ),
        )

    # -----------------------------------------------------
    # UPDATE SHIPMENT STATUS AND TIMESTAMPS
    # -----------------------------------------------------

    shipment.status = new_status

    now = datetime.utcnow()

    if new_status in {
        "shipped",
        "out_for_delivery",
        "delivered",
    }:
        if shipment.shipped_at is None:
            shipment.shipped_at = now

    if new_status in {
        "out_for_delivery",
        "delivered",
    }:
        if shipment.out_for_delivery_at is None:
            shipment.out_for_delivery_at = now

    if new_status == "delivered":
        if shipment.delivered_at is None:
            shipment.delivered_at = now

    # Ensure the updated shipment is written before
    # calculating the overall order status.
    await db.flush()

    # -----------------------------------------------------
    # GET ORDER
    # -----------------------------------------------------

    order_result = await db.execute(
        select(Order).where(
            Order.id == shipment.order_id
        )
    )

    order = order_result.scalar_one_or_none()

    if order is None:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated order not found.",
        )

    # -----------------------------------------------------
    # UPDATE CUSTOMER ORDER STATUS
    #
    # All shipments delivered -> order delivered
    # Any shipment shipped/delivered -> order shipped
    # Otherwise -> order processing
    # -----------------------------------------------------

    shipment_result = await db.execute(
        select(Shipment.status).where(
            Shipment.order_id == order.id
        )
    )

    shipment_statuses = [
        (shipment_status or "processing").strip().lower()
        for shipment_status in shipment_result.scalars().all()
    ]

    if shipment_statuses and order.status != "cancelled":
        all_shipments_delivered = all(
            shipment_status == "delivered"
            for shipment_status in shipment_statuses
        )

        any_shipment_shipped = any(
            shipment_status in {
                "shipped",
                "out_for_delivery",
                "delivered",
            }
            for shipment_status in shipment_statuses
        )

        if all_shipments_delivered:
            order.status = "delivered"
        elif any_shipment_shipped:
            order.status = "shipped"
        else:
            order.status = "processing"

    # -----------------------------------------------------
    # COD: MARK PAYMENT PAID ONLY AFTER ALL SHIPMENTS
    # HAVE BEEN DELIVERED
    # -----------------------------------------------------

    if (
        new_status == "delivered"
        and shipment_statuses
        and all(
            shipment_status == "delivered"
            for shipment_status in shipment_statuses
        )
    ):
        payment_result = await db.execute(
            select(Payment).where(
                Payment.order_id == order.id
            )
        )

        payments = payment_result.scalars().all()

        cod_methods = {
            "cod",
            "cash_on_delivery",
            "cash on delivery",
        }

        cod_payments = [
            payment
            for payment in payments
            if payment.payment_method
            and payment.payment_method.strip().lower()
            in cod_methods
        ]

        # Do not change the payment status of online payments.
        if cod_payments:
            order.payment_status = "paid"

            for payment in cod_payments:
                payment.status = "paid"

    # -----------------------------------------------------
    # SAVE SHIPMENT, ORDER, AND PAYMENT CHANGES
    # -----------------------------------------------------

    await db.commit()
    await db.refresh(shipment)
    await db.refresh(order)

    return {
        "message": "Shipment and order status updated successfully.",
        "order_status": order.status,
        "payment_status": order.payment_status,
        "shipment": serialize_shipment(shipment),
    }


# =========================================================
# SELLER - UPDATE TRACKING NUMBER
# =========================================================

@router.patch("/seller/{shipment_id}/tracking-number")
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

    if shipment is None:
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

    existing_shipment = existing_result.scalar_one_or_none()

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
        "shipment": serialize_shipment(shipment),
    }


# =========================================================
# CUSTOMER - GET ORDER SHIPMENTS
# =========================================================

@router.get("/customer/order/{order_id}")
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

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found.",
        )

    # -----------------------------------------------------
    # GET SHIPMENTS
    # -----------------------------------------------------

    shipment_result = await db.execute(
        select(Shipment)
        .where(Shipment.order_id == order_id)
        .order_by(Shipment.created_at.asc())
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
            serialize_shipment(shipment)
            for shipment in shipments
        ],
    }
