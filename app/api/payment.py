from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import stripe

from app.core.dependencies import get_current_user
from app.core.stripe import (
    STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET,
)
from app.database.database import get_db
from app.models.coupon import Coupon
from app.models.order import Order, OrderItem
from app.models.payment import Payment
from app.models.product import Product
from app.models.user import User
from app.schemas.payment import (
    PaymentIntentCreate,
    PaymentIntentResponse,
)


router = APIRouter(
    prefix="/payments",
    tags=["Payments"],
)


# =========================================================
# CREATE STRIPE PAYMENT INTENT
# =========================================================

@router.post(
    "/create-intent",
    response_model=PaymentIntentResponse,
)
async def create_payment_intent(
    payment_data: PaymentIntentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can make payments.",
        )

    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe payment service is not configured.",
        )

    # -----------------------------------------------------
    # GET ORDER
    # -----------------------------------------------------

    result = await db.execute(
        select(Order).where(
            Order.id == payment_data.order_id,
            Order.user_id == current_user.id,
        )
    )

    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found.",
        )

    # -----------------------------------------------------
    # CHECK ORDER PAYMENT STATUS
    # -----------------------------------------------------

    if order.payment_status == "paid":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This order has already been paid.",
        )

    if order.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot pay for a cancelled order.",
        )

    if order.total_amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order amount must be greater than zero.",
        )

    # -----------------------------------------------------
    # CHECK EXISTING PAYMENT
    # -----------------------------------------------------

    existing_payment_result = await db.execute(
        select(Payment)
        .where(
            Payment.order_id == order.id,
            Payment.user_id == current_user.id,
            Payment.status == "pending",
        )
        .order_by(Payment.created_at.desc())
    )

    existing_payment = (
        existing_payment_result.scalars().first()
    )

    # -----------------------------------------------------
    # REUSE EXISTING PAYMENT INTENT
    # -----------------------------------------------------

    if (
        existing_payment
        and existing_payment.stripe_payment_intent_id
    ):
        try:
            payment_intent = (
                stripe.PaymentIntent.retrieve(
                    existing_payment.stripe_payment_intent_id
                )
            )

            if payment_intent.status in {
                "requires_payment_method",
                "requires_confirmation",
                "requires_action",
            }:
                return PaymentIntentResponse(
                    payment_id=existing_payment.id,
                    order_id=order.id,
                    amount=float(order.total_amount),
                    currency=order_currency(order),
                    client_secret=payment_intent.client_secret,
                )

        except stripe.error.StripeError:
            pass

    # -----------------------------------------------------
    # CREATE STRIPE PAYMENT INTENT
    # -----------------------------------------------------

    currency = order_currency(order)

    amount_in_paise = int(
        round(order.total_amount * 100)
    )

    try:
        payment_intent = stripe.PaymentIntent.create(
            amount=amount_in_paise,
            currency=currency.lower(),
            description=f"ShopSphere order #{order.id}",
            shipping={
                "name": current_user.full_name,
                "address": {
                    "line1": order.shipping_address,
                    "country": "IN",
                },
            },
            metadata={
                "order_id": str(order.id),
                "user_id": str(current_user.id),
            },
        )

    except stripe.error.StripeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unable to create Stripe payment: {str(exc)}",
        )

    # -----------------------------------------------------
    # CREATE PAYMENT RECORD
    # -----------------------------------------------------

    payment = Payment(
        order_id=order.id,
        user_id=current_user.id,
        amount=order.total_amount,
        currency=currency,
        payment_method="stripe",
        status="pending",
        stripe_payment_intent_id=payment_intent.id,
    )

    db.add(payment)

    await db.commit()

    await db.refresh(payment)

    return PaymentIntentResponse(
        payment_id=payment.id,
        order_id=order.id,
        amount=float(order.total_amount),
        currency=currency,
        client_secret=payment_intent.client_secret,
    )


# =========================================================
# STRIPE WEBHOOK
# =========================================================

@router.post(
    "/webhook",
)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe webhook secret is not configured.",
        )

    payload = await request.body()

    signature = request.headers.get(
        "stripe-signature"
    )

    if not signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Stripe signature.",
        )

    try:
        event = stripe.Webhook.construct_event(
            payload,
            signature,
            STRIPE_WEBHOOK_SECRET,
        )

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook payload.",
        )

    except stripe.error.SignatureVerificationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature.",
        )

    event_type = event["type"]

    # -----------------------------------------------------
    # PAYMENT SUCCEEDED
    # -----------------------------------------------------

    if event_type == "payment_intent.succeeded":
        payment_intent = event["data"]["object"]

        payment_intent_id = payment_intent["id"]

        result = await db.execute(
            select(Payment).where(
                Payment.stripe_payment_intent_id
                == payment_intent_id
            )
        )

        payment = result.scalar_one_or_none()

        if payment:
            # -------------------------------------------------
            # IMPORTANT:
            # Make webhook idempotent.
            #
            # If Stripe sends the same successful webhook
            # again after payment is already marked paid,
            # coupon usage will NOT increase again.
            # -------------------------------------------------

            if payment.status != "paid":
                payment.status = "paid"
                payment.transaction_id = payment_intent_id

                # -------------------------------------------------
                # GET ORDER
                # -------------------------------------------------

                order_result = await db.execute(
                    select(Order).where(
                        Order.id == payment.order_id
                    )
                )

                order = order_result.scalar_one_or_none()

                if order:
                    order.payment_status = "paid"
                    order.status = "processing"

                    # -------------------------------------------------
                    # INCREASE COUPON USAGE
                    # -------------------------------------------------

                    if order.coupon_code:
                        coupon_result = await db.execute(
                            select(Coupon).where(
                                Coupon.code
                                == order.coupon_code
                            )
                        )

                        coupon = (
                            coupon_result.scalar_one_or_none()
                        )

                        if coupon:
                            coupon.used_count += 1

                await db.commit()

    # -----------------------------------------------------
    # PAYMENT FAILED
    # -----------------------------------------------------

    elif event_type == "payment_intent.payment_failed":
        payment_intent = event["data"]["object"]

        payment_intent_id = payment_intent["id"]

        await handle_failed_payment(
            payment_intent_id=payment_intent_id,
            db=db,
        )

    # -----------------------------------------------------
    # PAYMENT CANCELLED
    # -----------------------------------------------------

    elif event_type == "payment_intent.canceled":
        payment_intent = event["data"]["object"]

        payment_intent_id = payment_intent["id"]

        await handle_failed_payment(
            payment_intent_id=payment_intent_id,
            db=db,
        )

    return {
        "received": True,
    }


# =========================================================
# HANDLE FAILED / CANCELLED PAYMENT
# =========================================================

async def handle_failed_payment(
    payment_intent_id: str,
    db: AsyncSession,
):
    result = await db.execute(
        select(Payment).where(
            Payment.stripe_payment_intent_id
            == payment_intent_id
        )
    )

    payment = result.scalar_one_or_none()

    if not payment:
        return

    # -----------------------------------------------------
    # IMPORTANT:
    # Only restore stock if this payment is still pending.
    #
    # This prevents duplicate Stripe webhook events from
    # restoring the same stock more than once.
    # -----------------------------------------------------

    if payment.status != "pending":
        return

    payment.status = "failed"

    # -----------------------------------------------------
    # GET ORDER
    # -----------------------------------------------------

    order_result = await db.execute(
        select(Order).where(
            Order.id == payment.order_id
        )
    )

    order = order_result.scalar_one_or_none()

    if not order:
        await db.commit()
        return

    # -----------------------------------------------------
    # RESTORE STOCK
    # -----------------------------------------------------

    items_result = await db.execute(
        select(OrderItem).where(
            OrderItem.order_id == order.id
        )
    )

    order_items = items_result.scalars().all()

    for order_item in order_items:
        product_result = await db.execute(
            select(Product).where(
                Product.id == order_item.product_id
            )
        )

        product = product_result.scalar_one_or_none()

        if product:
            product.stock += order_item.quantity

    # -----------------------------------------------------
    # CANCEL ORDER
    # -----------------------------------------------------

    order.payment_status = "failed"
    order.status = "cancelled"

    await db.commit()


# =========================================================
# ORDER CURRENCY
# =========================================================

def order_currency(order: Order) -> str:
    return "INR"