from datetime import datetime
import csv
import io
import json
import zipfile

import stripe

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
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
from app.models.product_option_group import ProductOptionGroup
from app.models.product_option_value import ProductOptionValue
from app.models.product_variant import ProductVariant
from app.models.product_variant_value import ProductVariantValue
from app.models.shipment import Shipment
from app.models.user import User
from app.schemas.order import OrderCreate, OrderResponse


router = APIRouter(prefix="/orders", tags=["Orders"])


# =========================================================
# STRIPE REFUND HELPERS
# =========================================================

def get_stripe_refund_status(refund) -> str:
    """
    Convert the Stripe refund status into a ShopSphere payment status.
    """
    refund_status = getattr(refund, "status", None)

    if refund_status == "succeeded":
        return "refunded"

    if refund_status in {"pending", "requires_action"}:
        return "refund_pending"

    if refund_status in {"failed", "canceled"}:
        return "refund_failed"

    return "refund_pending"


def create_stripe_full_refund(payment_intent_id: str):
    """
    Create or retrieve the same full refund using a stable idempotency key.
    """
    return stripe.Refund.create(
        payment_intent=payment_intent_id,
        idempotency_key=f"shopsphere-full-refund-{payment_intent_id}",
    )


def apply_stripe_refund_result(
    payment: Payment,
    order: Order,
    refund,
) -> None:
    """
    Update local records using Stripe's actual refund status.
    """
    mapped_status = get_stripe_refund_status(refund)

    payment.transaction_id = refund.id
    payment.status = mapped_status
    order.payment_status = mapped_status


# =========================================================
# ORDER ITEM RESPONSE DATA
# =========================================================

async def build_order_items_response(
    db: AsyncSession,
    items: list[OrderItem],
) -> list[dict]:
    if not items:
        return []

    product_ids = {item.product_id for item in items}
    seller_ids = {item.seller_id for item in items}
    variant_ids = {
        item.variant_id
        for item in items
        if item.variant_id is not None
    }

    products_result = await db.execute(
        select(Product).where(Product.id.in_(product_ids))
    )
    products_by_id = {
        product.id: product
        for product in products_result.scalars().all()
    }

    sellers_result = await db.execute(
        select(User.id, User.full_name).where(
            User.id.in_(seller_ids)
        )
    )
    seller_names_by_id = {
        seller_id: full_name
        for seller_id, full_name in sellers_result.all()
    }

    variants_by_id: dict[int, ProductVariant] = {}

    if variant_ids:
        variants_result = await db.execute(
            select(ProductVariant).where(
                ProductVariant.id.in_(variant_ids)
            )
        )
        variants_by_id = {
            variant.id: variant
            for variant in variants_result.scalars().all()
        }

    variant_options_by_variant_id: dict[int, list[dict]] = {
        variant_id: [] for variant_id in variant_ids
    }

    if variant_ids:
        option_result = await db.execute(
            select(
                ProductVariantValue.variant_id,
                ProductOptionGroup.name,
                ProductOptionValue.value,
            )
            .join(
                ProductOptionValue,
                ProductOptionValue.id
                == ProductVariantValue.option_value_id,
            )
            .join(
                ProductOptionGroup,
                ProductOptionGroup.id
                == ProductOptionValue.option_group_id,
            )
            .where(
                ProductVariantValue.variant_id.in_(variant_ids)
            )
            .order_by(
                ProductOptionGroup.sort_order,
                ProductOptionValue.sort_order,
            )
        )

        for variant_id, group_name, value in option_result.all():
            variant_options_by_variant_id[variant_id].append(
                {
                    "group_name": group_name,
                    "value": value,
                }
            )

    variant_images_by_variant_id: dict[int, str] = {}

    if variant_ids:
        variant_image_result = await db.execute(
            select(ProductImage)
            .where(
                ProductImage.variant_id.in_(variant_ids),
                ProductImage.is_primary.is_(True),
            )
            .order_by(ProductImage.sort_order)
        )

        for image in variant_image_result.scalars().all():
            if image.variant_id not in variant_images_by_variant_id:
                variant_images_by_variant_id[image.variant_id] = (
                    image.image_url
                )

    product_images_result = await db.execute(
        select(ProductImage)
        .where(
            ProductImage.product_id.in_(product_ids),
            ProductImage.variant_id.is_(None),
            ProductImage.is_primary.is_(True),
        )
        .order_by(ProductImage.sort_order)
    )

    images_by_product_id: dict[int, str] = {}

    for image in product_images_result.scalars().all():
        if image.product_id not in images_by_product_id:
            images_by_product_id[image.product_id] = image.image_url

    response = []

    for item in items:
        product = products_by_id.get(item.product_id)

        if not product:
            continue

        variant = (
            variants_by_id.get(item.variant_id)
            if item.variant_id is not None
            else None
        )

        product_image = (
            variant_images_by_variant_id.get(item.variant_id)
            if item.variant_id is not None
            else None
        )

        if not product_image:
            product_image = images_by_product_id.get(item.product_id)

        response.append(
            {
                "id": item.id,
                "order_id": item.order_id,
                "product_id": item.product_id,
                "variant_id": item.variant_id,
                "seller_id": item.seller_id,
                "seller_name": seller_names_by_id.get(item.seller_id),
                "product_name": product.name,
                "product_image": product_image,
                "variant_sku": variant.sku if variant else None,
                "variant_options": (
                    variant_options_by_variant_id.get(
                        item.variant_id, []
                    )
                    if item.variant_id is not None
                    else []
                ),
                "quantity": item.quantity,
                "price": item.price,
                "total": item.total,
            }
        )

    return response


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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can create orders.",
        )

    if order_data.idempotency_key:
        lock_key = (
            f"shopsphere-order:{current_user.id}:"
            f"{order_data.idempotency_key}"
        )

        await db.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtext(lock_key)
                )
            )
        )

        existing_result = await db.execute(
            select(Order)
            .where(
                Order.user_id == current_user.id,
                Order.idempotency_key == order_data.idempotency_key,
            )
            .with_for_update()
        )
        existing_order = existing_result.scalar_one_or_none()

        if existing_order is not None:
            if existing_order.status != "cancelled":
                existing_items_result = await db.execute(
                    select(OrderItem).where(
                        OrderItem.order_id == existing_order.id
                    )
                )
                existing_items = existing_items_result.scalars().all()
                item_response = await build_order_items_response(
                    db,
                    existing_items,
                )

                return OrderResponse(
                    id=existing_order.id,
                    user_id=existing_order.user_id,
                    total_amount=existing_order.total_amount,
                    discount_amount=existing_order.discount_amount,
                    coupon_code=existing_order.coupon_code,
                    status=existing_order.status,
                    payment_status=existing_order.payment_status,
                    shipping_address=existing_order.shipping_address,
                    created_at=existing_order.created_at,
                    updated_at=existing_order.updated_at,
                    items=item_response,
                )

            existing_order.idempotency_key = None
            await db.flush()

    if not order_data.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order must contain at least one item.",
        )

    if order_data.payment_method not in {"stripe", "razorpay", "cod"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payment method.",
        )

    product_ids = [item.product_id for item in order_data.items]

    if any(item.quantity <= 0 for item in order_data.items):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product quantities must be greater than zero.",
        )

    result = await db.execute(
        select(Product)
        .where(
            Product.id.in_(product_ids),
            Product.is_deleted.is_(False),
            Product.is_active.is_(True),
        )
        .with_for_update()
    )

    products_by_id = {
        product.id: product
        for product in result.scalars().all()
    }

    if len(products_by_id) != len(set(product_ids)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more products were not found.",
        )

    variant_ids = [
        item.variant_id
        for item in order_data.items
        if item.variant_id is not None
    ]

    variants_by_id: dict[int, ProductVariant] = {}

    if variant_ids:
        variant_result = await db.execute(
            select(ProductVariant)
            .where(
                ProductVariant.id.in_(variant_ids),
                ProductVariant.is_active.is_(True),
            )
            .with_for_update()
        )

        variants_by_id = {
            variant.id: variant
            for variant in variant_result.scalars().all()
        }

        if len(variants_by_id) != len(set(variant_ids)):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or more selected product variants were not found.",
            )

    subtotal = 0.0

    for item_data in order_data.items:
        product = products_by_id[item_data.product_id]

        active_variants_result = await db.execute(
            select(ProductVariant.id).where(
                ProductVariant.product_id == product.id,
                ProductVariant.is_active.is_(True),
            )
        )
        active_variant_ids = active_variants_result.scalars().all()

        if active_variant_ids:
            if item_data.variant_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Please select a variant for product "
                        f"'{product.name}'."
                    ),
                )

            variant = variants_by_id.get(item_data.variant_id)

            if not variant or variant.product_id != product.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"The selected variant is invalid for "
                        f"product '{product.name}'."
                    ),
                )

            if variant.stock < item_data.quantity:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Not enough stock for the selected variant "
                        f"of '{product.name}'. Available stock: "
                        f"{variant.stock}."
                    ),
                )

            item_price = float(variant.price)

        else:
            if item_data.variant_id is not None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Product '{product.name}' does not have "
                        f"selectable variants."
                    ),
                )

            if product.stock < item_data.quantity:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Not enough stock for product '{product.name}'. "
                        f"Available stock: {product.stock}."
                    ),
                )

            item_price = float(product.price)

        subtotal += item_price * item_data.quantity

    discount_amount = 0.0
    coupon_code = None
    coupon = None

    if order_data.coupon_code:
        coupon_code = order_data.coupon_code.strip().upper()

        if not coupon_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Coupon code cannot be empty.",
            )

        coupon_result = await db.execute(
            select(Coupon)
            .where(Coupon.code == coupon_code)
            .with_for_update()
        )
        coupon = coupon_result.scalar_one_or_none()

        if not coupon:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid coupon code.",
            )

        if not coupon.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This coupon is inactive.",
            )

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

        if (
            coupon.usage_limit is not None
            and coupon.used_count >= coupon.usage_limit
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This coupon usage limit has been reached.",
            )

        if subtotal < float(coupon.minimum_order_amount):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Minimum order amount for this coupon is "
                    f"₹{float(coupon.minimum_order_amount):.2f}."
                ),
            )

        if coupon.discount_type == "percentage":
            discount_amount = (
                subtotal * float(coupon.discount_value) / 100
            )
        elif coupon.discount_type == "fixed":
            discount_amount = float(coupon.discount_value)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid coupon discount type.",
            )

        if coupon.maximum_discount is not None:
            discount_amount = min(
                discount_amount,
                float(coupon.maximum_discount),
            )

        discount_amount = min(discount_amount, subtotal)

    total_amount = round(max(subtotal - discount_amount, 0), 2)

    order_status = (
        "processing"
        if order_data.payment_method == "cod"
        else "pending"
    )

    order = Order(
        user_id=current_user.id,
        idempotency_key=order_data.idempotency_key,
        total_amount=total_amount,
        discount_amount=round(discount_amount, 2),
        coupon_code=coupon_code,
        status=order_status,
        payment_status="pending",
        shipping_address=order_data.shipping_address,
    )

    db.add(order)
    await db.flush()

    order_items = []

    for item_data in order_data.items:
        product = products_by_id[item_data.product_id]
        variant = None

        if item_data.variant_id is not None:
            variant = variants_by_id[item_data.variant_id]
            item_price = float(variant.price)
            variant.stock -= item_data.quantity
        else:
            item_price = float(product.price)
            product.stock -= item_data.quantity

        item_total = item_price * item_data.quantity

        order_item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            variant_id=variant.id if variant else None,
            seller_id=product.seller_id,
            quantity=item_data.quantity,
            price=item_price,
            total=item_total,
        )

        db.add(order_item)
        order_items.append(order_item)

    await db.flush()

    if order_data.payment_method == "cod":
        db.add(
            Payment(
                order_id=order.id,
                user_id=current_user.id,
                amount=total_amount,
                currency="INR",
                payment_method="cod",
                status="pending",
            )
        )

        if coupon is not None:
            coupon.used_count += 1

        seller_ids = {item.seller_id for item in order_items}

        for seller_id in seller_ids:
            db.add(
                Shipment(
                    order_id=order.id,
                    seller_id=seller_id,
                    tracking_number=None,
                    status="processing",
                )
            )

    await db.commit()
    await db.refresh(order)

    item_response = await build_order_items_response(db, order_items)

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
        items=item_response,
    )


# =========================================================
# CUSTOMER - MY ORDERS
# =========================================================

@router.get("/my-orders", response_model=list[OrderResponse])
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
        .where(Order.user_id == current_user.id)
        .order_by(Order.created_at.desc())
    )
    orders = result.scalars().all()

    response = []

    for order in orders:
        items_result = await db.execute(
            select(OrderItem).where(OrderItem.order_id == order.id)
        )
        items = items_result.scalars().all()
        item_response = await build_order_items_response(db, items)

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
                items=item_response,
            )
        )

    return response


# =========================================================
# SELLER - SALES ANALYTICS
# =========================================================

@router.get("/seller/analytics")
async def get_seller_analytics(
    db: AsyncSession = Depends(get_db),
    current_seller: User = Depends(get_current_seller),
):
    orders_result = await db.execute(
        select(Order.id, Order.status)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .where(OrderItem.seller_id == current_seller.id)
        .distinct()
    )
    seller_orders = orders_result.all()

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
            func.coalesce(func.sum(OrderItem.quantity), 0),
            func.coalesce(func.sum(OrderItem.total), 0),
        ).where(OrderItem.seller_id == current_seller.id)
    )
    total_units, total_sales = totals_result.one()

    top_products_result = await db.execute(
        select(
            OrderItem.product_id,
            Product.name,
            func.sum(OrderItem.quantity).label("units_sold"),
            func.sum(OrderItem.total).label("sales"),
        )
        .join(Product, Product.id == OrderItem.product_id)
        .where(OrderItem.seller_id == current_seller.id)
        .group_by(OrderItem.product_id, Product.name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(5)
    )

    return {
        "total_orders": len(seller_orders),
        "total_units": int(total_units or 0),
        "total_sales": float(total_sales or 0),
        "orders_by_status": status_counts,
        "top_products": [
            {
                "product_id": product_id,
                "product_name": product_name,
                "units_sold": int(units_sold or 0),
                "sales": float(sales or 0),
            }
            for product_id, product_name, units_sold, sales
            in top_products_result.all()
        ],
    }


# =========================================================
# SELLER - REVENUE BY DATE
# =========================================================

@router.get("/seller/revenue")
async def get_seller_revenue(
    db: AsyncSession = Depends(get_db),
    current_seller: User = Depends(get_current_seller),
):
    result = await db.execute(
        select(
            func.date(Order.created_at).label("date"),
            func.count(func.distinct(Order.id)).label("orders"),
            func.coalesce(func.sum(OrderItem.quantity), 0).label("units"),
            func.coalesce(func.sum(OrderItem.total), 0).label("sales"),
        )
        .join(OrderItem, OrderItem.order_id == Order.id)
        .where(OrderItem.seller_id == current_seller.id)
        .group_by(func.date(Order.created_at))
        .order_by(func.date(Order.created_at))
    )

    return [
        {
            "date": str(date),
            "orders": int(orders or 0),
            "units": int(units or 0),
            "sales": float(sales or 0),
        }
        for date, orders, units, sales in result.all()
    ]


# =========================================================
# SELLER - DOWNLOAD REVENUE ZIP
# =========================================================

@router.get("/seller/revenue/export")
async def export_seller_revenue(
    db: AsyncSession = Depends(get_db),
    current_seller: User = Depends(get_current_seller),
):
    """
    Download a ZIP containing this seller's revenue summary,
    daily revenue, and order items.

    All order-item queries are scoped to the authenticated seller.
    Customer shipping addresses and other sellers' items are excluded.
    """

    seller_id = current_seller.id

    # -----------------------------------------------------
    # SELLER REVENUE SUMMARY
    # -----------------------------------------------------

    summary_result = await db.execute(
        select(
            func.count(func.distinct(OrderItem.order_id)).label(
                "total_orders"
            ),
            func.coalesce(
                func.sum(OrderItem.quantity), 0
            ).label("total_units"),
            func.coalesce(
                func.sum(OrderItem.total), 0
            ).label("gross_sales"),
        )
        .where(OrderItem.seller_id == seller_id)
    )

    summary_row = summary_result.one()

    total_orders = int(summary_row.total_orders or 0)
    total_units = int(summary_row.total_units or 0)
    gross_sales = float(summary_row.gross_sales or 0)

    summary_data = {
        "seller_id": seller_id,
        "seller_name": current_seller.full_name,
        "exported_at_utc": datetime.utcnow().isoformat() + "Z",
        "currency": "INR",
        "total_orders": total_orders,
        "total_units": total_units,
        "gross_sales": round(gross_sales, 2),
        "revenue_definition": (
            "Gross value of this seller's order items. "
            "This is not a confirmed-paid-revenue calculation; "
            "order and payment statuses may vary."
        ),
    }

    # -----------------------------------------------------
    # DAILY REVENUE CSV
    # -----------------------------------------------------

    daily_result = await db.execute(
        select(
            func.date(Order.created_at).label("date"),
            func.count(
                func.distinct(Order.id)
            ).label("orders"),
            func.coalesce(
                func.sum(OrderItem.quantity), 0
            ).label("units"),
            func.coalesce(
                func.sum(OrderItem.total), 0
            ).label("sales"),
        )
        .join(
            OrderItem,
            OrderItem.order_id == Order.id,
        )
        .where(
            OrderItem.seller_id == seller_id,
        )
        .group_by(func.date(Order.created_at))
        .order_by(func.date(Order.created_at))
    )

    daily_output = io.StringIO(newline="")
    daily_writer = csv.writer(daily_output)

    daily_writer.writerow(
        ["date", "orders", "units", "gross_sales_inr"]
    )

    for date, orders, units, sales in daily_result.all():
        daily_writer.writerow(
            [
                str(date),
                int(orders or 0),
                int(units or 0),
                f"{float(sales or 0):.2f}",
            ]
        )

    daily_csv = daily_output.getvalue()
    daily_output.close()

    # -----------------------------------------------------
    # SELLER ORDER ITEMS CSV
    # -----------------------------------------------------

    items_result = await db.execute(
        select(
            Order.id.label("order_id"),
            Order.created_at.label("order_date"),
            Order.status.label("order_status"),
            Order.payment_status.label("payment_status"),
            OrderItem.id.label("order_item_id"),
            OrderItem.product_id.label("product_id"),
            Product.name.label("product_name"),
            OrderItem.variant_id.label("variant_id"),
            OrderItem.quantity.label("quantity"),
            OrderItem.price.label("unit_price"),
            OrderItem.total.label("item_total"),
        )
        .join(
            OrderItem,
            OrderItem.order_id == Order.id,
        )
        .join(
            Product,
            Product.id == OrderItem.product_id,
        )
        .where(
            OrderItem.seller_id == seller_id,
        )
        .order_by(
            Order.created_at.desc(),
            Order.id.desc(),
            OrderItem.id.asc(),
        )
    )

    items_output = io.StringIO(newline="")
    items_writer = csv.writer(items_output)

    items_writer.writerow(
        [
            "order_id",
            "order_date",
            "order_status",
            "payment_status",
            "order_item_id",
            "product_id",
            "product_name",
            "variant_id",
            "quantity",
            "unit_price_inr",
            "item_total_inr",
        ]
    )

    for row in items_result.all():
        items_writer.writerow(
            [
                row.order_id,
                (
                    row.order_date.isoformat()
                    if row.order_date
                    else ""
                ),
                row.order_status or "",
                row.payment_status or "",
                row.order_item_id,
                row.product_id,
                row.product_name or "",
                (
                    row.variant_id
                    if row.variant_id is not None
                    else ""
                ),
                int(row.quantity or 0),
                f"{float(row.unit_price or 0):.2f}",
                f"{float(row.item_total or 0):.2f}",
            ]
        )

    items_csv = items_output.getvalue()
    items_output.close()

    # -----------------------------------------------------
    # CREATE ZIP FILE IN MEMORY
    # -----------------------------------------------------

    readme = (
        "ShopSphere Seller Revenue Export\n"
        "================================\n\n"
        f"Seller ID: {seller_id}\n"
        f"Seller name: {current_seller.full_name or 'Seller'}\n"
        f"Exported at (UTC): {summary_data['exported_at_utc']}\n"
        "Currency: INR\n\n"
        "Files included:\n"
        "1. revenue_summary.json - seller revenue totals\n"
        "2. revenue_by_date.csv - daily order, unit, and sales totals\n"
        "3. seller_order_items.csv - order items belonging to this seller\n\n"
        "Important:\n"
        "Gross sales are the sum of this seller's order-item totals.\n"
        "They are not necessarily confirmed paid revenue. Check the\n"
        "payment_status and order_status columns in seller_order_items.csv.\n"
        "Customer shipping addresses and other sellers' order items are\n"
        "not included in this export.\n"
    )

    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(
        zip_buffer,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
    ) as zip_file:
        zip_file.writestr(
            "revenue_summary.json",
            json.dumps(
                summary_data,
                indent=2,
                ensure_ascii=False,
            ),
        )
        zip_file.writestr(
            "revenue_by_date.csv",
            daily_csv,
        )
        zip_file.writestr(
            "seller_order_items.csv",
            items_csv,
        )
        zip_file.writestr(
            "README.txt",
            readme,
        )

    zip_buffer.seek(0)

    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                'attachment; filename="shopsphere-seller-revenue.zip"'
            ),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


# =========================================================
# SELLER - MY ORDERS
# =========================================================

@router.get("/seller/orders", response_model=list[OrderResponse])
async def get_seller_orders(
    db: AsyncSession = Depends(get_db),
    current_seller: User = Depends(get_current_seller),
):
    seller_items_result = await db.execute(
        select(OrderItem.order_id)
        .where(OrderItem.seller_id == current_seller.id)
        .distinct()
    )
    order_ids = seller_items_result.scalars().all()

    if not order_ids:
        return []

    orders_result = await db.execute(
        select(Order)
        .where(Order.id.in_(order_ids))
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
        item_response = await build_order_items_response(db, items)

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
                items=item_response,
            )
        )

    return response


# =========================================================
# SELLER - UPDATE ORDER STATUS
# =========================================================

@router.patch("/seller/{order_id}/status", response_model=OrderResponse)
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
                "Invalid order status. Allowed values: "
                "processing, shipped, delivered, cancelled."
            ),
        )

    result = await db.execute(
        select(Order)
        .where(Order.id == order_id)
        .with_for_update()
    )
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found.",
        )

    if order.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A cancelled order cannot be updated.",
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
    item_response = await build_order_items_response(db, items)

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
        items=item_response,
    )


# =========================================================
# CUSTOMER - CANCEL ORDER
# =========================================================

@router.patch("/{order_id}/cancel")
async def cancel_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can cancel orders.",
        )

    result = await db.execute(
        select(Order)
        .where(
            Order.id == order_id,
            Order.user_id == current_user.id,
        )
        .with_for_update()
    )
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found.",
        )

    if order.status not in {"pending", "processing"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Order cannot be cancelled because its current "
                f"status is '{order.status}'."
            ),
        )

    shipments_result = await db.execute(
        select(Shipment)
        .where(Shipment.order_id == order.id)
        .with_for_update()
    )
    shipments = shipments_result.scalars().all()

    if any(
        shipment.status in {"shipped", "out_for_delivery", "delivered"}
        for shipment in shipments
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This order cannot be cancelled because the shipment "
                "has already been shipped."
            ),
        )

    items_result = await db.execute(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )
    order_items = items_result.scalars().all()

    payment_result = await db.execute(
        select(Payment)
        .where(
            Payment.order_id == order.id,
            Payment.user_id == current_user.id,
        )
        .order_by(Payment.created_at.desc())
        .with_for_update()
    )
    payment = payment_result.scalars().first()

    # -----------------------------------------------------
    # STRIPE PAYMENT
    # -----------------------------------------------------

    if payment and payment.payment_method == "stripe":
        if payment.status == "refunded":
            order.payment_status = "refunded"

        elif payment.status == "refund_pending":
            order.payment_status = "refund_pending"

        elif payment.status == "refund_failed":
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "The previous refund failed. Please contact support "
                    "before cancelling this order."
                ),
            )

        elif payment.status == "paid":
            if not payment.stripe_payment_intent_id:
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Stripe payment information is missing.",
                )

            try:
                payment_intent = stripe.PaymentIntent.retrieve(
                    payment.stripe_payment_intent_id
                )

                if payment_intent.status != "succeeded":
                    await db.rollback()
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            "The recorded payment status does not match "
                            "Stripe. Refresh your orders and try again."
                        ),
                    )

                refund = create_stripe_full_refund(
                    payment.stripe_payment_intent_id
                )
                apply_stripe_refund_result(payment, order, refund)

            except HTTPException:
                raise
            except stripe.error.StripeError as exc:
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Unable to process the Stripe refund.",
                ) from exc

        elif payment.status in {"pending", "failed"}:
            if payment.stripe_payment_intent_id:
                try:
                    payment_intent = stripe.PaymentIntent.retrieve(
                        payment.stripe_payment_intent_id
                    )
                    intent_status = payment_intent.status

                    if intent_status == "succeeded":
                        refund = create_stripe_full_refund(
                            payment.stripe_payment_intent_id
                        )
                        apply_stripe_refund_result(payment, order, refund)

                    elif intent_status == "canceled":
                        payment.status = "cancelled"
                        order.payment_status = "cancelled"

                    elif intent_status in {
                        "requires_payment_method",
                        "requires_confirmation",
                        "requires_action",
                        "requires_capture",
                    }:
                        stripe.PaymentIntent.cancel(
                            payment.stripe_payment_intent_id
                        )
                        payment.status = "cancelled"
                        order.payment_status = "cancelled"

                    elif intent_status == "processing":
                        await db.rollback()
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=(
                                "Your payment is still processing. "
                                "Check your order status before cancelling."
                            ),
                        )

                    else:
                        await db.rollback()
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=(
                                "Stripe payment status has changed. "
                                "Refresh your orders before trying again."
                            ),
                        )

                except HTTPException:
                    raise
                except stripe.error.StripeError as exc:
                    await db.rollback()
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=(
                            "Unable to verify or cancel the Stripe payment."
                        ),
                    ) from exc

            else:
                payment.status = "cancelled"
                order.payment_status = "cancelled"

        elif payment.status == "cancelled":
            order.payment_status = "cancelled"

        else:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This payment cannot be cancelled automatically. "
                    "Please contact support."
                ),
            )

    # -----------------------------------------------------
    # COD PAYMENT
    # -----------------------------------------------------

    elif payment and payment.payment_method == "cod":
        if payment.status == "paid":
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This COD payment is marked paid. "
                    "Please contact support before cancelling."
                ),
            )

        payment.status = "cancelled"
        order.payment_status = "cancelled"

    # -----------------------------------------------------
    # RAZORPAY PAYMENT
    # -----------------------------------------------------

    elif payment and payment.payment_method in {
        "razorpay",
        "razorpay_upi_qr",
    }:
        if payment.status in {
            "paid",
            "refund_pending",
            "refund_failed",
        }:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This Razorpay payment requires provider-side "
                    "verification or refund processing before cancellation. "
                    "No refund has been recorded by this request."
                ),
            )

        if payment.status == "pending":
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "The Razorpay payment may still be processing. "
                    "Verify its status before cancelling this order."
                ),
            )

        payment.status = "cancelled"
        order.payment_status = "cancelled"

    elif not payment:
        order.payment_status = "cancelled"

    else:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This payment method cannot be cancelled automatically. "
                "Please contact support."
            ),
        )

    # -----------------------------------------------------
    # RESTORE STOCK
    # -----------------------------------------------------

    for order_item in order_items:
        if order_item.variant_id is not None:
            variant_result = await db.execute(
                select(ProductVariant)
                .where(ProductVariant.id == order_item.variant_id)
                .with_for_update()
            )
            variant = variant_result.scalar_one_or_none()

            if variant:
                variant.stock += order_item.quantity

        else:
            product_result = await db.execute(
                select(Product)
                .where(Product.id == order_item.product_id)
                .with_for_update()
            )
            product = product_result.scalar_one_or_none()

            if product:
                product.stock += order_item.quantity

    # -----------------------------------------------------
    # RESTORE COUPON USAGE
    # -----------------------------------------------------

    release_coupon = bool(
        order.coupon_code
        and payment
        and (
            (
                payment.payment_method == "cod"
                and payment.status == "cancelled"
            )
            or (
                payment.payment_method == "stripe"
                and payment.status in {"refunded", "cancelled"}
            )
        )
    )

    if release_coupon:
        coupon_result = await db.execute(
            select(Coupon)
            .where(Coupon.code == order.coupon_code)
            .with_for_update()
        )
        coupon = coupon_result.scalar_one_or_none()

        if coupon and coupon.used_count > 0:
            coupon.used_count -= 1

    # -----------------------------------------------------
    # CANCEL ORDER AND REMOVE UNFULFILLED SHIPMENTS
    # -----------------------------------------------------

    order.status = "cancelled"

    for shipment in shipments:
        await db.delete(shipment)

    await db.commit()
    await db.refresh(order)

    return {
        "message": (
            "Order cancelled successfully."
            if order.payment_status != "refund_pending"
            else (
                "Order cancelled. The refund is still processing "
                "with the payment provider."
            )
        ),
        "order_id": order.id,
        "status": order.status,
        "payment_status": order.payment_status,
    }


# =========================================================
# GET SINGLE ORDER
# =========================================================

@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Order).where(Order.id == order_id)
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

        if not seller_item_result.scalar_one_or_none():
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

    items_result = await db.execute(items_query)
    items = items_result.scalars().all()
    item_response = await build_order_items_response(db, items)

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
        items=item_response,
    )