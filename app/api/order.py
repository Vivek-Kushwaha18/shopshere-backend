from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.database import get_db
from app.models.order import Order
from app.schemas.order import OrderCreate, OrderUpdate


router = APIRouter(
    prefix="/orders",
    tags=["Orders"]
)


# CREATE ORDER
@router.post("/")
async def create_order(
    order_data: OrderCreate,
    db: AsyncSession = Depends(get_db)
):
    new_order = Order(
        user_id=order_data.user_id,
        product_id=order_data.product_id,
        quantity=order_data.quantity,
        total_price=order_data.total_price,
        status="pending"
    )

    db.add(new_order)

    await db.commit()
    await db.refresh(new_order)

    return {
        "success": True,
        "message": "Order created successfully",
        "data": new_order
    }


# GET ALL ORDERS
@router.get("/")
async def get_orders(
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Order)
    )

    orders = result.scalars().all()

    return {
        "success": True,
        "message": "Orders fetched successfully",
        "data": orders
    }


# GET SINGLE ORDER
@router.get("/{order_id}")
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Order).where(Order.id == order_id)
    )

    order = result.scalar_one_or_none()

    if order is None:
        raise HTTPException(
            status_code=404,
            detail="Order not found"
        )

    return {
        "success": True,
        "message": "Order fetched successfully",
        "data": order
    }


# UPDATE ORDER
@router.put("/{order_id}")
async def update_order(
    order_id: int,
    order_data: OrderUpdate,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Order).where(Order.id == order_id)
    )

    order = result.scalar_one_or_none()

    if order is None:
        raise HTTPException(
            status_code=404,
            detail="Order not found"
        )

    if order_data.quantity is not None:
        order.quantity = order_data.quantity

    if order_data.status is not None:
        order.status = order_data.status

    await db.commit()
    await db.refresh(order)

    return {
        "success": True,
        "message": "Order updated successfully",
        "data": order
    }


# DELETE ORDER
@router.delete("/{order_id}")
async def delete_order(
    order_id: int,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Order).where(Order.id == order_id)
    )

    order = result.scalar_one_or_none()

    if order is None:
        raise HTTPException(
            status_code=404,
            detail="Order not found"
        )

    await db.delete(order)
    await db.commit()

    return {
        "success": True,
        "message": "Order deleted successfully"
    }