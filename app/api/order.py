import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    get_current_seller,
    get_current_user,
)
from app.database.database import get_db
from app.models.coupon import Coupon
from app.models.order import Order, OrderItem
from app.models.payment import Payment
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.shipment import Shipment
from app.models.user import User
from app.schemas.order import (
    OrderCreate,
    OrderResponse,
)


router = APIRouter(
    prefix="/orders",
    tags=["Orders"],
)


# =========================================================
# CREATE ORDER - CUSTOMER
# =========================================================

@router.post(
    "/",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_order(
    order_data: OrderCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payload = await request.json()

    print("*** Request Payload ***")
    print(json.dumps(payload, indent=2))
    print("******")

    if current_user.role != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can create orders.",
        )

    if not order_data.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order must contain at least one item.",
        )

    # -----------------------------------------------------
    # GET PRODUCTS
    # -----------------------------------------------------

    product_ids = [
        item.product_id
        for item in order_data.items
    ]

    result = await db.execute(
        select(Product).where(
            Product.id.in_(product_ids),
            Product.is_deleted.is_(False),
            Product.is_active.is_(True),
        )
    )

    products = result.scalars().all()

    products_by_id = {
        product.id: product
        for product in products
    }

    if len(products_by_id) != len(set(product_ids)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more products were not found.",
        )

    # -----------------------------------------------------
    # CALCULATE SUBTOTAL
    # -----------------------------------------------------

    subtotal = 0.0

    for item_data in order_data.items:
        product = products_by_id[item_data.product_id]

        if product.stock < item_data.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Not enough stock for product "
                    f"'{product.name}'. Available stock: "
                    f"{product.stock}."
                ),
            )

        item_total = (
            float(product.price)
            * item_data.quantity
        )

        subtotal += item_total

    # -----------------------------------------------------
    # COUPON
    # -----------------------------------------------------

    discount_amount = 0.0
    coupon_code = None
    coupon = None

    if order_data.coupon_code:
        coupon_code = (
            order_data.coupon_code.strip().upper()
        )

        if not coupon_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Coupon code cannot be empty.",
            )

        coupon_result = await db.execute(
            select(Coupon).where(
                Coupon.code == coupon_code
            )
        )

        coupon = coupon_result.scalar_one_or_none()

        if not coupon:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid coupon code.",
            )

        # -------------------------------------------------
        # CHECK ACTIVE
        # -------------------------------------------------

        if not coupon.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This coupon is inactive.",
            )

        # -------------------------------------------------
        # CHECK DATES
        # -------------------------------------------------

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

        # -------------------------------------------------
        # CHECK USAGE LIMIT
        # -------------------------------------------------

        if (
            coupon.usage_limit is not None
            and coupon.used_count >= coupon.usage_limit
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This coupon usage limit has been reached.",
            )

        # -------------------------------------------------
        # CHECK MINIMUM ORDER AMOUNT
        # -------------------------------------------------

        if (
            subtotal
            < float(coupon.minimum_order_amount)
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Minimum order amount for this coupon "
                    f"is ₹{float(coupon.minimum_order_amount):.2f}."
                ),
            )

        # -------------------------------------------------
        # CALCULATE DISCOUNT
        # -------------------------------------------------

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

        # -------------------------------------------------
        # MAXIMUM DISCOUNT
        # -------------------------------------------------

        if coupon.maximum_discount is not None:
            discount_amount = min(
                discount_amount,
                float(coupon.maximum_discount),
            )

        # -------------------------------------------------
        # DISCOUNT CANNOT EXCEED SUBTOTAL
        # -----------------------------------------------------

        discount_amount = min(
            discount_amount,
            subtotal,
        )

    # -----------------------------------------------------
    # FINAL TOTAL
    # -----------------------------------------------------

    total_amount = max(
        subtotal - discount_amount,
        0,
    )

    # -----------------------------------------------------
    # ORDER STATUS
    # -----------------------------------------------------

    if order_data.payment_method == "cod":
        order_status = "processing"
    else:
        order_status = "pending"

    # -----------------------------------------------------
    # CREATE ORDER
    # -----------------------------------------------------

    order = Order(
        user_id=current_user.id,
        total_amount=round(total_amount, 2),
        discount_amount=round(discount_amount, 2),
        coupon_code=coupon_code,
        status=order_status,
        payment_status="pending",
        shipping_address=order_data.shipping_address,
    )

    db.add(order)

    await db.flush()

    # -----------------------------------------------------
    # CREATE ORDER ITEMS
    # -----------------------------------------------------

    order_items = []

    for item_data in order_data.items:
        product = products_by_id[item_data.product_id]

        item_total = (
            float(product.price)
            * item_data.quantity
        )

        order_item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            seller_id=product.seller_id,
            quantity=item_data.quantity,
            price=product.price,
            total=item_total,
        )

        db.add(order_item)

        order_items.append(order_item)

        # Reduce stock
        product.stock -= item_data.quantity

    await db.flush()

    # =====================================================
    # CASH ON DELIVERY
    # =====================================================

    if order_data.payment_method == "cod":

        # -------------------------------------------------
        # CREATE COD PAYMENT RECORD
        # -------------------------------------------------

        cod_payment = Payment(
            order_id=order.id,
            user_id=current_user.id,
            amount=round(total_amount, 2),
            currency="INR",
            payment_method="cod",
            status="pending",
        )

        db.add(cod_payment)

        # -------------------------------------------------
        # INCREMENT COUPON USAGE
        # -------------------------------------------------

        if coupon is not None:
            coupon.used_count += 1

        # -------------------------------------------------
        # CREATE SHIPMENTS
        # -------------------------------------------------

        seller_ids = {
            item.seller_id
            for item in order_items
        }

        for seller_id in seller_ids:
            shipment = Shipment(
                order_id=order.id,
                seller_id=seller_id,
                tracking_number=None,
                status="processing",
            )

            db.add(shipment)

    # -----------------------------------------------------
    # SAVE
    # -----------------------------------------------------

    await db.commit()

    await db.refresh(order)

    # -----------------------------------------------------
    # GET PRIMARY PRODUCT IMAGES
    # -----------------------------------------------------

    image_result = await db.execute(
        select(ProductImage).where(
            ProductImage.product_id.in_(product_ids),
            ProductImage.is_primary.is_(True),
        )
    )

    primary_images = image_result.scalars().all()

    images_by_product_id = {
        image.product_id: image.image_url
        for image in primary_images
    }

    # -----------------------------------------------------
    # RETURN ORDER
    # -----------------------------------------------------

    return OrderResponse(
        id=order.id,
        user_id=order.user_id,
        total_amount=order.total_amount,
        discount_amount=order.discount_amount,
        coupon_code=order.coupon_code,
        status=order.status,
        payment_status=order.payment_status,
        shipping_address=order.shipping_address,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=[
            {
                "id": item.id,
                "order_id": item.order_id,
                "product_id": item.product_id,
                "seller_id": item.seller_id,
                "product_name": products_by_id[
                    item.product_id
                ].name,
                "product_image": images_by_product_id.get(
                    item.product_id
                ),
                "quantity": item.quantity,
                "price": item.price,
                "total": item.total,
            }
            for item in order_items
        ],
    )


# =========================================================
# CUSTOMER - MY ORDERS
# =========================================================

@router.get(
    "/my-orders",
    response_model=list[OrderResponse],
)
async def get_my_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can view their orders.",
        )

    result = await db.execute(
        select(Order)
        .where(
            Order.user_id == current_user.id
        )
        .order_by(Order.created_at.desc())
    )

    orders = result.scalars().all()

    response = []

    for order in orders:
        items_result = await db.execute(
            select(OrderItem).where(
                OrderItem.order_id == order.id
            )
        )

        items = items_result.scalars().all()

        product_ids = [
            item.product_id
            for item in items
        ]

        products_result = await db.execute(
            select(Product).where(
                Product.id.in_(product_ids)
            )
        )

        products = products_result.scalars().all()

        products_by_id = {
            product.id: product
            for product in products
        }

        image_result = await db.execute(
            select(ProductImage).where(
                ProductImage.product_id.in_(product_ids),
                ProductImage.is_primary.is_(True),
            )
        )

        primary_images = image_result.scalars().all()

        images_by_product_id = {
            image.product_id: image.image_url
            for image in primary_images
        }

        response.append(
            OrderResponse(
                id=order.id,
                user_id=order.user_id,
                total_amount=order.total_amount,
                discount_amount=order.discount_amount,
                coupon_code=order.coupon_code,
                status=order.status,
                payment_status=order.payment_status,
                shipping_address=order.shipping_address,
                created_at=order.created_at,
                updated_at=order.updated_at,
                items=[
                    {
                        "id": item.id,
                        "order_id": item.order_id,
                        "product_id": item.product_id,
                        "seller_id": item.seller_id,
                        "product_name": products_by_id[
                            item.product_id
                        ].name,
                        "product_image": images_by_product_id.get(
                            item.product_id
                        ),
                        "quantity": item.quantity,
                        "price": item.price,
                        "total": item.total,
                    }
                    for item in items
                ],
            )
        )

    return response


# =========================================================
# SELLER - SALES ANALYTICS
# =========================================================

@router.get(
    "/seller/analytics",
)
async def get_seller_analytics(
    db: AsyncSession = Depends(get_db),
    current_seller: User = Depends(get_current_seller),
):
    orders_result = await db.execute(
        select(
            Order.id,
            Order.status,
        )
        .join(
            OrderItem,
            OrderItem.order_id == Order.id,
        )
        .where(
            OrderItem.seller_id == current_seller.id
        )
        .distinct()
    )

    seller_orders = orders_result.all()

    total_orders = len(seller_orders)

    status_counts = {
        "pending": 0,
        "processing": 0,
        "shipped": 0,
        "delivered": 0,
        "cancelled": 0,
    }

    for order in seller_orders:
        if order.status in status_counts:
            status_counts[order.status] += 1

    totals_result = await db.execute(
        select(
            func.coalesce(
                func.sum(OrderItem.quantity),
                0,
            ),
            func.coalesce(
                func.sum(OrderItem.total),
                0,
            ),
        ).where(
            OrderItem.seller_id == current_seller.id
        )
    )

    total_units, total_sales = totals_result.one()

    top_products_result = await db.execute(
        select(
            OrderItem.product_id,
            Product.name,
            func.sum(
                OrderItem.quantity
            ).label("units_sold"),
            func.sum(
                OrderItem.total
            ).label("sales"),
        )
        .join(
            Product,
            Product.id == OrderItem.product_id,
        )
        .where(
            OrderItem.seller_id == current_seller.id
        )
        .group_by(
            OrderItem.product_id,
            Product.name,
        )
        .order_by(
            func.sum(
                OrderItem.quantity
            ).desc()
        )
        .limit(5)
    )

    top_products = top_products_result.all()

    return {
        "total_orders": total_orders,
        "total_units": int(total_units or 0),
        "total_sales": float(total_sales or 0),
        "orders_by_status": status_counts,
        "top_products": [
            {
                "product_id": product_id,
                "product_name": product_name,
                "units_sold": int(
                    units_sold or 0
                ),
                "sales": float(
                    sales or 0
                ),
            }
            for (
                product_id,
                product_name,
                units_sold,
                sales,
            ) in top_products
        ],
    }


# =========================================================
# SELLER - REVENUE BY DATE
# =========================================================

@router.get(
    "/seller/revenue",
)
async def get_seller_revenue(
    db: AsyncSession = Depends(get_db),
    current_seller: User = Depends(get_current_seller),
):
    revenue_result = await db.execute(
        select(
            func.date(
                Order.created_at
            ).label("date"),
            func.count(
                func.distinct(Order.id)
            ).label("orders"),
            func.coalesce(
                func.sum(OrderItem.quantity),
                0,
            ).label("units"),
            func.coalesce(
                func.sum(OrderItem.total),
                0,
            ).label("sales"),
        )
        .join(
            OrderItem,
            OrderItem.order_id == Order.id,
        )
        .where(
            OrderItem.seller_id == current_seller.id
        )
        .group_by(
            func.date(Order.created_at)
        )
        .order_by(
            func.date(Order.created_at)
        )
    )

    revenue_rows = revenue_result.all()

    return [
        {
            "date": str(date),
            "orders": int(orders or 0),
            "units": int(units or 0),
            "sales": float(sales or 0),
        }
        for (
            date,
            orders,
            units,
            sales,
        ) in revenue_rows
    ]


# =========================================================
# SELLER - MY ORDERS
# =========================================================

@router.get(
    "/seller/orders",
    response_model=list[OrderResponse],
)
async def get_seller_orders(
    db: AsyncSession = Depends(get_db),
    current_seller: User = Depends(get_current_seller),
):
    seller_items_result = await db.execute(
        select(OrderItem.order_id)
        .where(
            OrderItem.seller_id == current_seller.id
        )
        .distinct()
    )

    order_ids = seller_items_result.scalars().all()

    if not order_ids:
        return []

    orders_result = await db.execute(
        select(Order)
        .where(
            Order.id.in_(order_ids)
        )
        .order_by(Order.created_at.desc())
    )

    orders = orders_result.scalars().all()

    response = []

    for order in orders:
        items_result = await db.execute(
            select(OrderItem).where(
                OrderItem.order_id == order.id,
                OrderItem.seller_id == current_seller.id,
            )
        )

        items = items_result.scalars().all()

        product_ids = [
            item.product_id
            for item in items
        ]

        products_result = await db.execute(
            select(Product).where(
                Product.id.in_(product_ids)
            )
        )

        products = products_result.scalars().all()

        products_by_id = {
            product.id: product
            for product in products
        }

        image_result = await db.execute(
            select(ProductImage).where(
                ProductImage.product_id.in_(product_ids),
                ProductImage.is_primary.is_(True),
            )
        )

        primary_images = image_result.scalars().all()

        images_by_product_id = {
            image.product_id: image.image_url
            for image in primary_images
        }

        response.append(
            OrderResponse(
                id=order.id,
                user_id=order.user_id,
                total_amount=order.total_amount,
                discount_amount=order.discount_amount,
                coupon_code=order.coupon_code,
                status=order.status,
                payment_status=order.payment_status,
                shipping_address=order.shipping_address,
                created_at=order.created_at,
                updated_at=order.updated_at,
                items=[
                    {
                        "id": item.id,
                        "order_id": item.order_id,
                        "product_id": item.product_id,
                        "seller_id": item.seller_id,
                        "product_name": products_by_id[
                            item.product_id
                        ].name,
                        "product_image": images_by_product_id.get(
                            item.product_id
                        ),
                        "quantity": item.quantity,
                        "price": item.price,
                        "total": item.total,
                    }
                    for item in items
                ],
            )
        )

    return response


# =========================================================
# SELLER - UPDATE ORDER STATUS
# =========================================================

@router.patch(
    "/seller/{order_id}/status",
    response_model=OrderResponse,
)
async def update_seller_order_status(
    order_id: int,
    new_status: str,
    db: AsyncSession = Depends(get_db),
    current_seller: User = Depends(get_current_seller),
):
    allowed_statuses = {
        "processing",
        "shipped",
        "delivered",
        "cancelled",
    }

    if new_status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Invalid order status. "
                "Allowed values: processing, shipped, "
                "delivered, cancelled."
            ),
        )

    result = await db.execute(
        select(Order).where(
            Order.id == order_id
        )
    )

    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found.",
        )

    seller_item_result = await db.execute(
        select(OrderItem).where(
            OrderItem.order_id == order.id,
            OrderItem.seller_id == current_seller.id,
        )
    )

    seller_item = seller_item_result.scalar_one_or_none()

    if not seller_item:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update orders containing your products.",
        )

    order.status = new_status

    await db.commit()

    await db.refresh(order)

    items_result = await db.execute(
        select(OrderItem).where(
            OrderItem.order_id == order.id,
            OrderItem.seller_id == current_seller.id,
        )
    )

    items = items_result.scalars().all()

    product_ids = [
        item.product_id
        for item in items
    ]

    products_result = await db.execute(
        select(Product).where(
            Product.id.in_(product_ids)
        )
    )

    products = products_result.scalars().all()

    products_by_id = {
        product.id: product
        for product in products
    }

    image_result = await db.execute(
        select(ProductImage).where(
            ProductImage.product_id.in_(product_ids),
            ProductImage.is_primary.is_(True),
        )
    )

    primary_images = image_result.scalars().all()

    images_by_product_id = {
        image.product_id: image.image_url
        for image in primary_images
    }

    return OrderResponse(
        id=order.id,
        user_id=order.user_id,
        total_amount=order.total_amount,
        discount_amount=order.discount_amount,
        coupon_code=order.coupon_code,
        status=order.status,
        payment_status=order.payment_status,
        shipping_address=order.shipping_address,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=[
            {
                "id": item.id,
                "order_id": item.order_id,
                "product_id": item.product_id,
                "seller_id": item.seller_id,
                "product_name": products_by_id[
                    item.product_id
                ].name,
                "product_image": images_by_product_id.get(
                    item.product_id
                ),
                "quantity": item.quantity,
                "price": item.price,
                "total": item.total,
            }
            for item in items
        ],
    )


# =========================================================
# GET SINGLE ORDER
# =========================================================

@router.get(
    "/{order_id}",
    response_model=OrderResponse,
)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Order).where(
            Order.id == order_id
        )
    )

    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found.",
        )

    if current_user.role == "customer":
        if order.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view your own orders.",
            )

    elif current_user.role == "seller":
        seller_item_result = await db.execute(
            select(OrderItem).where(
                OrderItem.order_id == order.id,
                OrderItem.seller_id == current_user.id,
            )
        )

        seller_item = seller_item_result.scalar_one_or_none()

        if not seller_item:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view orders containing your products.",
            )

    elif current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not allowed to view this order.",
        )

    items_query = select(OrderItem).where(
        OrderItem.order_id == order.id
    )

    if current_user.role == "seller":
        items_query = items_query.where(
            OrderItem.seller_id == current_user.id
        )

    items_result = await db.execute(
        items_query
    )

    items = items_result.scalars().all()

    product_ids = [
        item.product_id
        for item in items
    ]

    products_result = await db.execute(
        select(Product).where(
            Product.id.in_(product_ids)
        )
    )

    products = products_result.scalars().all()

    products_by_id = {
        product.id: product
        for product in products
    }

    image_result = await db.execute(
        select(ProductImage).where(
            ProductImage.product_id.in_(product_ids),
            ProductImage.is_primary.is_(True),
        )
    )

    primary_images = image_result.scalars().all()

    images_by_product_id = {
        image.product_id: image.image_url
        for image in primary_images
    }

    return OrderResponse(
        id=order.id,
        user_id=order.user_id,
        total_amount=order.total_amount,
        discount_amount=order.discount_amount,
        coupon_code=order.coupon_code,
        status=order.status,
        payment_status=order.payment_status,
        shipping_address=order.shipping_address,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=[
            {
                "id": item.id,
                "order_id": item.order_id,
                "product_id": item.product_id,
                "seller_id": item.seller_id,
                "product_name": products_by_id[
                    item.product_id
                ].name,
                "product_image": images_by_product_id.get(
                    item.product_id
                ),
                "quantity": item.quantity,
                "price": item.price,
                "total": item.total,
            }
            for item in items
        ],
    )