import hashlib
import hmac
import logging
import uuid
from typing import Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.razorpay import (
    RAZORPAY_KEY_ID,
    RAZORPAY_KEY_SECRET,
    razorpay_client,
)
from app.core.stripe import STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
from app.database.database import get_db
from app.models.coupon import Coupon
from app.models.order import Order, OrderItem
from app.models.payment import Payment
from app.models.shipment import Shipment
from app.models.user import User
from app.schemas.payment import (
    PaymentIntentCreate,
    PaymentIntentResponse,
    SavedCardPaymentCreate,
)

router = APIRouter(prefix="/payments", tags=["Payments"])

logger = logging.getLogger(__name__)


class RazorpayOrderCreate(BaseModel):
    order_id: int


class RazorpayVerifyRequest(BaseModel):
    order_id: int
    razorpay_order_id: str = Field(min_length=1, max_length=255)
    razorpay_payment_id: str = Field(min_length=1, max_length=255)
    razorpay_signature: str = Field(min_length=1, max_length=512)


# =========================================================
# COMMON HELPERS
# =========================================================


def customer_only(user: User) -> None:
    if user.role != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can make payments.",
        )


def stripe_error(message: str, exc: Exception) -> HTTPException:
    """Log Stripe errors without exposing provider details to the client."""

    logger.error(
        "Stripe API failure | type=%s | message=%s | request_id=%s | "
        "code=%s | param=%s",
        type(exc).__name__,
        str(exc),
        getattr(exc, "request_id", None),
        getattr(exc, "code", None),
        getattr(exc, "param", None),
        exc_info=True,
    )

    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=message,
    )


def stripe_object_id(value: Any) -> str | None:
    """Return an ID from a string or Stripe resource."""
    if value is None:
        return None

    if isinstance(value, str):
        return value

    return getattr(value, "id", None)


def order_currency(order: Order) -> str:
    """ShopSphere currently processes orders in Indian rupees."""
    return "INR"


def amount_in_paise(amount: float) -> int:
    return int(round(float(amount) * 100))


async def get_customer_order(
    order_id: int,
    user: User,
    db: AsyncSession,
) -> Order:
    result = await db.execute(
        select(Order).where(
            Order.id == order_id,
            Order.user_id == user.id,
        )
    )
    order = result.scalar_one_or_none()

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found.",
        )

    if order.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This order has been cancelled.",
        )

    if order.payment_status == "paid":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This order has already been paid.",
        )

    if float(order.total_amount) <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order amount must be greater than zero.",
        )

    return order


async def get_or_create_stripe_customer(
    user: User,
    db: AsyncSession,
) -> str:
    """Retrieve an existing Stripe customer or create one."""

    if user.stripe_customer_id:
        try:
            customer = stripe.Customer.retrieve(
                user.stripe_customer_id
            )

            if not getattr(customer, "deleted", False):
                return user.stripe_customer_id

        except stripe.error.InvalidRequestError:
            logger.warning(
                "Stored Stripe customer could not be retrieved. "
                "A replacement customer will be created. user_id=%s",
                user.id,
            )

        except stripe.error.StripeError as exc:
            raise stripe_error(
                "Unable to retrieve the Stripe customer account.",
                exc,
            )

    try:
        customer = stripe.Customer.create(
            name=user.full_name,
            email=user.email,
            metadata={
                "shopsphere_user_id": str(user.id),
            },
            idempotency_key=f"shopsphere-customer-{user.id}",
        )

    except stripe.error.StripeError as exc:
        raise stripe_error(
            "Unable to prepare the Stripe customer account.",
            exc,
        )

    user.stripe_customer_id = customer.id

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception(
            "Failed to save Stripe customer ID. user_id=%s",
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save payment customer information.",
        )

    return customer.id


# =========================================================
# CREATE STRIPE PAYMENT INTENT
# =========================================================


@router.post(
    "/create-intent",
    response_model=PaymentIntentResponse,
)
async def create_payment_intent(
    data: PaymentIntentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer_only(current_user)

    if not STRIPE_SECRET_KEY:
        logger.error("Stripe secret key is not configured.")

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe payment service is not configured.",
        )

    order = await get_customer_order(
        data.order_id,
        current_user,
        db,
    )

    currency = order_currency(order)
    amount = amount_in_paise(order.total_amount)

    result = await db.execute(
        select(Payment)
        .where(
            Payment.order_id == order.id,
            Payment.user_id == current_user.id,
            Payment.payment_method == "stripe",
            Payment.status == "pending",
        )
        .order_by(Payment.created_at.desc())
    )
    existing = result.scalars().first()

    if existing and existing.stripe_payment_intent_id:
        try:
            intent = stripe.PaymentIntent.retrieve(
                existing.stripe_payment_intent_id
            )

            reusable_statuses = {
                "requires_payment_method",
                "requires_confirmation",
                "requires_action",
            }

            if (
                intent.status in reusable_statuses
                and intent.amount == amount
                and intent.currency.lower() == currency.lower()
            ):
                if (
                    data.save_card
                    and not getattr(intent, "setup_future_usage", None)
                ):
                    intent = stripe.PaymentIntent.modify(
                        intent.id,
                        setup_future_usage="off_session",
                    )

                return PaymentIntentResponse(
                    payment_id=existing.id,
                    order_id=order.id,
                    amount=float(order.total_amount),
                    currency=currency,
                    client_secret=intent.client_secret,
                )

            if intent.status in {"processing", "succeeded"}:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Payment is processing. Check your order "
                        "status before retrying."
                    ),
                )

            if intent.status not in {
                "canceled",
                "succeeded",
                "processing",
            }:
                try:
                    stripe.PaymentIntent.cancel(intent.id)
                except stripe.error.StripeError:
                    logger.exception(
                        "Unable to cancel an old PaymentIntent. "
                        "payment_intent_id=%s",
                        intent.id,
                    )

            existing.status = "cancelled"
            await db.commit()

        except HTTPException:
            raise

        except stripe.error.StripeError as exc:
            raise stripe_error(
                "Unable to retrieve the existing Stripe payment.",
                exc,
            )

    customer_id = await get_or_create_stripe_customer(
        current_user,
        db,
    )

    # Use Dashboard-managed payment methods.
    # Do not pass payment_method_types to Stripe.
    intent_options: dict[str, Any] = {
        "amount": amount,
        "currency": currency.lower(),
        "customer": customer_id,
        "automatic_payment_methods": {
            "enabled": True,
        },
        "description": f"ShopSphere order #{order.id}",
        "metadata": {
            "order_id": str(order.id),
            "user_id": str(current_user.id),
        },
    }

    if data.save_card:
        intent_options["setup_future_usage"] = "off_session"

    try:
        intent = stripe.PaymentIntent.create(
            **intent_options,
            idempotency_key=(
                f"shopsphere-payment-{order.id}-"
                f"{current_user.id}-{uuid.uuid4().hex}"
            ),
        )

    except stripe.error.StripeError as exc:
        raise stripe_error(
            "Unable to create Stripe payment.",
            exc,
        )

    payment = Payment(
        order_id=order.id,
        user_id=current_user.id,
        amount=order.total_amount,
        currency=currency,
        payment_method="stripe",
        status="pending",
        stripe_payment_intent_id=intent.id,
    )

    db.add(payment)

    try:
        await db.commit()
        await db.refresh(payment)
    except Exception:
        await db.rollback()
        logger.exception(
            "Stripe PaymentIntent was created, but its payment record "
            "could not be saved. order_id=%s payment_intent_id=%s",
            order.id,
            intent.id,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Payment was initialized, but the payment record "
                "could not be saved. Check payment status before retrying."
            ),
        )

    return PaymentIntentResponse(
        payment_id=payment.id,
        order_id=order.id,
        amount=float(order.total_amount),
        currency=currency,
        client_secret=intent.client_secret,
    )


# =========================================================
# GET SAVED STRIPE CARDS
# =========================================================


@router.get("/saved-cards")
async def get_saved_cards(
    current_user: User = Depends(get_current_user),
):
    customer_only(current_user)

    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe payment service is not configured.",
        )

    if not current_user.stripe_customer_id:
        return {"cards": []}

    try:
        methods = stripe.PaymentMethod.list(
            customer=current_user.stripe_customer_id,
            type="card",
        )

        cards = []

        for method in methods.data:
            card = getattr(method, "card", None)

            if card is None:
                continue

            cards.append(
                {
                    "id": method.id,
                    "brand": card.brand,
                    "last4": card.last4,
                    "exp_month": card.exp_month,
                    "exp_year": card.exp_year,
                }
            )

        return {"cards": cards}

    except stripe.error.StripeError as exc:
        raise stripe_error(
            "Unable to retrieve saved cards.",
            exc,
        )


# =========================================================
# CREATE PAYMENT INTENT USING A SAVED STRIPE CARD
# =========================================================


@router.post(
    "/saved-cards/create-intent",
    response_model=PaymentIntentResponse,
)
async def create_saved_card_payment_intent(
    data: SavedCardPaymentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer_only(current_user)

    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe payment service is not configured.",
        )

    order = await get_customer_order(
        data.order_id,
        current_user,
        db,
    )

    customer_id = await get_or_create_stripe_customer(
        current_user,
        db,
    )

    try:
        payment_method = stripe.PaymentMethod.retrieve(
            data.payment_method_id
        )

    except stripe.error.InvalidRequestError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved card not found.",
        )

    except stripe.error.StripeError as exc:
        raise stripe_error(
            "Unable to verify the saved card.",
            exc,
        )

    payment_method_type = getattr(payment_method, "type", None)
    payment_method_customer = stripe_object_id(
        getattr(payment_method, "customer", None)
    )

    if (
        payment_method_type != "card"
        or payment_method_customer != customer_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This saved card is not available for your account.",
        )

    amount = amount_in_paise(order.total_amount)
    currency = order_currency(order)

    result = await db.execute(
        select(Payment)
        .where(
            Payment.order_id == order.id,
            Payment.user_id == current_user.id,
            Payment.payment_method == "stripe",
            Payment.status == "pending",
        )
        .order_by(Payment.created_at.desc())
    )
    existing = result.scalars().first()

    if existing and existing.stripe_payment_intent_id:
        try:
            existing_intent = stripe.PaymentIntent.retrieve(
                existing.stripe_payment_intent_id
            )

            existing_customer_id = stripe_object_id(
                getattr(existing_intent, "customer", None)
            )

            if existing_intent.status in {
                "requires_payment_method",
                "requires_confirmation",
            }:
                if (
                    existing_intent.amount != amount
                    or existing_intent.currency.lower()
                    != currency.lower()
                    or existing_customer_id != customer_id
                ):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            "The existing payment does not match this "
                            "order. Please retry the payment."
                        ),
                    )

                intent = stripe.PaymentIntent.modify(
                    existing_intent.id,
                    payment_method=data.payment_method_id,
                )

                return PaymentIntentResponse(
                    payment_id=existing.id,
                    order_id=order.id,
                    amount=float(order.total_amount),
                    currency=currency,
                    client_secret=intent.client_secret,
                )

            if existing_intent.status in {
                "requires_action",
                "processing",
                "succeeded",
            }:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Another payment attempt is already in progress. "
                        "Check your order status before retrying."
                    ),
                )

            existing.status = "cancelled"
            await db.commit()

        except HTTPException:
            raise

        except stripe.error.StripeError as exc:
            raise stripe_error(
                "Unable to prepare the saved-card payment.",
                exc,
            )

    try:
        intent = stripe.PaymentIntent.create(
            amount=amount,
            currency=currency.lower(),
            customer=customer_id,
            payment_method=data.payment_method_id,
            automatic_payment_methods={
                "enabled": True,
            },
            description=f"ShopSphere order #{order.id}",
            metadata={
                "order_id": str(order.id),
                "user_id": str(current_user.id),
            },
            idempotency_key=(
                f"shopsphere-saved-card-{order.id}-"
                f"{current_user.id}-{uuid.uuid4().hex}"
            ),
        )

    except stripe.error.StripeError as exc:
        raise stripe_error(
            "Unable to create payment with the saved card.",
            exc,
        )

    payment = Payment(
        order_id=order.id,
        user_id=current_user.id,
        amount=order.total_amount,
        currency=currency,
        payment_method="stripe",
        status="pending",
        stripe_payment_intent_id=intent.id,
    )

    db.add(payment)

    try:
        await db.commit()
        await db.refresh(payment)
    except Exception:
        await db.rollback()
        logger.exception(
            "Saved-card PaymentIntent was created, but the payment "
            "record could not be saved. order_id=%s payment_intent_id=%s",
            order.id,
            intent.id,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Payment was initialized, but the payment record "
                "could not be saved. Check payment status before retrying."
            ),
        )

    return PaymentIntentResponse(
        payment_id=payment.id,
        order_id=order.id,
        amount=float(order.total_amount),
        currency=currency,
        client_secret=intent.client_secret,
    )


# =========================================================
# CREATE RAZORPAY ORDER
# =========================================================


@router.post("/razorpay/create-order")
async def create_razorpay_order(
    data: RazorpayOrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer_only(current_user)

    if (
        razorpay_client is None
        or not RAZORPAY_KEY_ID
        or not RAZORPAY_KEY_SECRET
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Razorpay payment service is not configured.",
        )

    order = await get_customer_order(
        data.order_id,
        current_user,
        db,
    )

    amount = amount_in_paise(order.total_amount)
    currency = order_currency(order)

    result = await db.execute(
        select(Payment)
        .where(
            Payment.order_id == order.id,
            Payment.user_id == current_user.id,
            Payment.payment_method == "razorpay",
            Payment.status == "pending",
        )
        .order_by(Payment.created_at.desc())
    )
    existing = result.scalars().first()

    if existing and existing.razorpay_order_id:
        if (
            amount_in_paise(existing.amount) == amount
            and existing.currency.upper() == currency.upper()
        ):
            return {
                "payment_id": existing.id,
                "order_id": order.id,
                "razorpay_order_id": existing.razorpay_order_id,
                "amount": amount,
                "currency": currency,
                "key_id": RAZORPAY_KEY_ID,
            }

        existing.status = "cancelled"
        await db.commit()

    try:
        provider_order = razorpay_client.order.create(
            {
                "amount": amount,
                "currency": currency,
                "receipt": f"ss-order-{order.id}",
                "notes": {
                    "shopsphere_order_id": str(order.id),
                    "shopsphere_user_id": str(current_user.id),
                },
            }
        )

    except Exception as exc:
        logger.exception(
            "Razorpay order creation failed. order_id=%s error_type=%s",
            order.id,
            type(exc).__name__,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to create Razorpay order.",
        )

    payment = Payment(
        order_id=order.id,
        user_id=current_user.id,
        amount=order.total_amount,
        currency=currency,
        payment_method="razorpay",
        status="pending",
        razorpay_order_id=provider_order["id"],
    )

    db.add(payment)

    try:
        await db.commit()
        await db.refresh(payment)
    except Exception:
        await db.rollback()
        logger.exception(
            "Razorpay order created but its payment record could not "
            "be saved. order_id=%s",
            order.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save the Razorpay payment record.",
        )

    return {
        "payment_id": payment.id,
        "order_id": order.id,
        "razorpay_order_id": provider_order["id"],
        "amount": amount,
        "currency": currency,
        "key_id": RAZORPAY_KEY_ID,
    }


# =========================================================
# FULFIL PAID ORDER
# =========================================================


async def fulfil_paid_order(
    order: Order,
    db: AsyncSession,
) -> None:
    order.payment_status = "paid"
    order.status = "processing"

    result = await db.execute(
        select(OrderItem).where(
            OrderItem.order_id == order.id
        )
    )
    items = result.scalars().all()

    seller_ids = {item.seller_id for item in items}

    for seller_id in seller_ids:
        shipment_result = await db.execute(
            select(Shipment).where(
                Shipment.order_id == order.id,
                Shipment.seller_id == seller_id,
            )
        )

        if shipment_result.scalar_one_or_none() is None:
            db.add(
                Shipment(
                    order_id=order.id,
                    seller_id=seller_id,
                    status="processing",
                )
            )

    if order.coupon_code:
        coupon_result = await db.execute(
            select(Coupon)
            .where(Coupon.code == order.coupon_code)
            .with_for_update()
        )
        coupon = coupon_result.scalar_one_or_none()

        if coupon:
            coupon.used_count += 1


# =========================================================
# VERIFY RAZORPAY PAYMENT
# =========================================================


@router.post("/razorpay/verify")
async def verify_razorpay_payment(
    data: RazorpayVerifyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer_only(current_user)

    if (
        razorpay_client is None
        or not RAZORPAY_KEY_ID
        or not RAZORPAY_KEY_SECRET
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Razorpay payment service is not configured.",
        )

    result = await db.execute(
        select(Payment)
        .where(
            Payment.order_id == data.order_id,
            Payment.user_id == current_user.id,
            Payment.payment_method == "razorpay",
            Payment.razorpay_order_id == data.razorpay_order_id,
        )
        .with_for_update()
    )
    payment = result.scalar_one_or_none()

    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Razorpay payment record not found.",
        )

    order_result = await db.execute(
        select(Order)
        .where(
            Order.id == data.order_id,
            Order.user_id == current_user.id,
        )
        .with_for_update()
    )
    order = order_result.scalar_one_or_none()

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found.",
        )

    if payment.status == "paid" and order.payment_status == "paid":
        return {
            "verified": True,
            "order_id": order.id,
        }

    if payment.status in {"cancelled", "failed", "refunded"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This payment can no longer be verified.",
        )

    if order.status == "cancelled" or order.payment_status == "paid":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This order cannot accept another payment.",
        )

    expected_signature = hmac.new(
        RAZORPAY_KEY_SECRET.encode("utf-8"),
        (
            f"{data.razorpay_order_id}|"
            f"{data.razorpay_payment_id}"
        ).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(
        expected_signature,
        data.razorpay_signature,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Razorpay payment signature.",
        )

    try:
        provider_payment = razorpay_client.payment.fetch(
            data.razorpay_payment_id
        )

    except Exception as exc:
        logger.exception(
            "Razorpay payment verification failed. order_id=%s "
            "error_type=%s",
            order.id,
            type(exc).__name__,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to verify payment status with Razorpay.",
        )

    if provider_payment.get("order_id") != data.razorpay_order_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payment does not match this order.",
        )

    expected_amount = amount_in_paise(order.total_amount)
    provider_amount = provider_payment.get("amount")
    provider_currency = provider_payment.get("currency")

    if (
        provider_amount != expected_amount
        or str(provider_currency).upper()
        != order_currency(order).upper()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payment amount or currency does not match the order.",
        )

    if provider_payment.get("status") != "captured":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payment is not captured yet. Please retry shortly.",
        )

    payment.razorpay_payment_id = data.razorpay_payment_id
    payment.razorpay_signature = data.razorpay_signature
    payment.transaction_id = data.razorpay_payment_id
    payment.status = "paid"

    await fulfil_paid_order(order, db)
    await db.commit()

    return {
        "verified": True,
        "order_id": order.id,
    }


# =========================================================
# STRIPE WEBHOOK
# =========================================================


@router.post("/webhook")
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
    signature = request.headers.get("stripe-signature")

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

    except (
        ValueError,
        stripe.error.SignatureVerificationError,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe webhook payload or signature.",
        )

    event_type = event["type"]
    intent = event["data"]["object"]
    intent_id = stripe_object_id(intent)

    if not intent_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe payment event.",
        )

    if event_type == "payment_intent.succeeded":
        await handle_successful_payment(
            intent_id,
            db,
        )

    elif event_type == "payment_intent.canceled":
        await handle_cancelled_payment(
            intent_id,
            db,
        )

    return {"received": True}


# =========================================================
# HANDLE SUCCESSFUL STRIPE PAYMENT
# =========================================================


async def handle_successful_payment(
    payment_intent_id: str,
    db: AsyncSession,
):
    result = await db.execute(
        select(Payment)
        .where(
            Payment.stripe_payment_intent_id == payment_intent_id
        )
        .with_for_update()
    )
    payment = result.scalar_one_or_none()

    if payment is None or payment.status == "paid":
        return

    order_result = await db.execute(
        select(Order)
        .where(Order.id == payment.order_id)
        .with_for_update()
    )
    order = order_result.scalar_one_or_none()

    if order is None:
        return

    try:
        intent = stripe.PaymentIntent.retrieve(
            payment_intent_id
        )

    except stripe.error.StripeError as exc:
        raise stripe_error(
            "Unable to verify Stripe payment.",
            exc,
        )

    expected_amount = amount_in_paise(order.total_amount)

    if (
        intent.status != "succeeded"
        or intent.amount_received != expected_amount
        or intent.currency.lower() != order_currency(order).lower()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stripe payment status, amount, or currency is invalid.",
        )

    if (
        order.status == "cancelled"
        or order.payment_status == "paid"
        or payment.status in {"cancelled", "failed", "refunded"}
    ):
        try:
            refund = stripe.Refund.create(
                payment_intent=payment_intent_id,
                idempotency_key=(
                    f"shopsphere-late-success-{payment_intent_id}"
                ),
            )

        except stripe.error.StripeError as exc:
            raise stripe_error(
                "Unable to refund a late or duplicate payment.",
                exc,
            )

        payment.status = "refunded"
        payment.transaction_id = refund.id

        if order.payment_status != "paid":
            order.payment_status = "refunded"

        await db.commit()
        return

    payment.status = "paid"
    payment.transaction_id = payment_intent_id

    await fulfil_paid_order(order, db)
    await db.commit()


# =========================================================
# HANDLE CANCELLED STRIPE PAYMENT
# =========================================================


async def handle_cancelled_payment(
    payment_intent_id: str,
    db: AsyncSession,
):
    result = await db.execute(
        select(Payment)
        .where(
            Payment.stripe_payment_intent_id == payment_intent_id
        )
        .with_for_update()
    )
    payment = result.scalar_one_or_none()

    if payment is None or payment.status != "pending":
        return

    payment.status = "cancelled"

    # A cancelled payment attempt does not cancel the order.
    await db.commit()