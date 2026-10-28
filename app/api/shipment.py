
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_seller, get_current_user
from app.database.database import get_db
from app.models.order import Order, OrderItem
from app.models.payment import Payment
from app.models.shipment import Shipment
from app.models.user import User


router = APIRouter(prefix="/shipments", tags=["Shipments"])


# =========================================================
# SERIALIZE SHIPMENT
# =========================================================

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
# SYNCHRONIZE ORDER STATUS WITH ALL ITS SHIPMENTS
# =========================================================

async def synchronize_order_status(
    db: AsyncSession,
    order: Order,
):
    result = await db.execute(
        select(Shipment.status).where(
            Shipment.order_id == order.id
        )
    )

    shipment_statuses = [
        (shipment_status or "processing").strip().lower()
        for shipment_status in result.scalars().all()
    ]

    # Never overwrite a cancelled order.
    if order.status == "cancelled" or not shipment_statuses:
        return shipment_statuses

    all_delivered = all(
        shipment_status == "delivered"
        for shipment_status in shipment_statuses
    )

    any_shipped = any(
        shipment_status in {
            "shipped",
            "out_for_delivery",
            "delivered",
        }
        for shipment_status in shipment_statuses
    )

    if all_delivered:
        order.status = "delivered"
    elif any_shipped:
        order.status = "shipped"
    else:
        order.status = "processing"

    # Mark COD payment as paid only after all shipments arrive.
    if all_delivered:
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

        for payment in payments:
            payment_method = (
                payment.payment_method or ""
            ).strip().lower()

            if payment_method in cod_methods:
                payment.status = "paid"
                order.payment_status = "paid"

    return shipment_statuses


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

    return [
        serialize_shipment(shipment)
        for shipment in result.scalars().all()
    ]


# =========================================================
# SELLER - CREATE DELIVERY SHIPMENT FOR AN ORDER
# =========================================================

@router.post(
    "/seller/order/{order_id}",
    status_code=status.HTTP_201_CREATED,
)
async def create_seller_shipment(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_seller: User = Depends(get_current_seller),
):
    try:
        # Lock the order while checking and creating the shipment.
        order_result = await db.execute(
            select(Order)
            .where(Order.id == order_id)
            .with_for_update()
        )

        order = order_result.scalar_one_or_none()

        if order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found.",
            )

        if (order.status or "").strip().lower() == "cancelled":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A shipment cannot be created for a cancelled order.",
            )

        # A seller can create a shipment only for an order
        # containing at least one of their own products.
        item_result = await db.execute(
            select(OrderItem.id)
            .where(
                OrderItem.order_id == order_id,
                OrderItem.seller_id == current_seller.id,
            )
            .limit(1)
        )

        seller_has_order_item = item_result.scalar_one_or_none()

        if seller_has_order_item is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This order does not contain any products belonging to you.",
            )

        # Return the seller's existing shipment rather than
        # creating another shipment for the same order.
        existing_result = await db.execute(
            select(Shipment).where(
                Shipment.order_id == order_id,
                Shipment.seller_id == current_seller.id,
            )
        )

        existing_shipment = existing_result.scalar_one_or_none()

        if existing_shipment is not None:
            await db.commit()

            return {
                "message": "A shipment already exists for this order.",
                "shipment": serialize_shipment(existing_shipment),
            }

        shipment = Shipment(
            order_id=order_id,
            seller_id=current_seller.id,
            tracking_number=None,
            status="processing",
        )

        db.add(shipment)
        await db.flush()

        # Synchronize the order with its current shipment statuses.
        await synchronize_order_status(db, order)

        await db.commit()
        await db.refresh(shipment)
        await db.refresh(order)

        return {
            "message": "Delivery shipment created successfully.",
            "shipment": serialize_shipment(shipment),
        }

    except HTTPException:
        await db.rollback()
        raise

    except Exception:
        await db.rollback()
        raise


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

    status_order = {
        "processing": 1,
        "shipped": 2,
        "out_for_delivery": 3,
        "delivered": 4,
    }

    current_status = (
        shipment.status or "processing"
    ).strip().lower()

    if current_status not in status_order:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Shipment has an unrecognized current status: "
                f"'{current_status}'."
            ),
        )

    if status_order[new_status] < status_order[current_status]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Shipment cannot move from '{current_status}' "
                f"back to '{new_status}'."
            ),
        )

    shipment.status = new_status
    now = datetime.utcnow()

    if new_status in {
        "shipped",
        "out_for_delivery",
        "delivered",
    } and shipment.shipped_at is None:
        shipment.shipped_at = now

    if new_status in {
        "out_for_delivery",
        "delivered",
    } and shipment.out_for_delivery_at is None:
        shipment.out_for_delivery_at = now

    if new_status == "delivered" and shipment.delivered_at is None:
        shipment.delivered_at = now

    try:
        await db.flush()

        order_result = await db.execute(
            select(Order)
            .where(Order.id == shipment.order_id)
            .with_for_update()
        )

        order = order_result.scalar_one_or_none()

        if order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Associated order not found.",
            )

        await synchronize_order_status(db, order)

        await db.commit()
        await db.refresh(shipment)
        await db.refresh(order)

    except Exception:
        await db.rollback()
        raise

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

    if existing_result.scalar_one_or_none():
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
    if current_user.role != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can view their order shipments.",
        )

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

    shipment_result = await db.execute(
        select(Shipment)
        .where(Shipment.order_id == order_id)
        .order_by(Shipment.created_at.asc())
    )

    shipments = shipment_result.scalars().all()

    return {
        "order_id": order.id,
        "order_status": order.status,
        "payment_status": order.payment_status,
        "shipments": [
            serialize_shipment(shipment)
            for shipment in shipments
        ],
    }
