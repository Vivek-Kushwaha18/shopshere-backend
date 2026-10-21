
import hashlib
import hmac
import logging
import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import requests
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

RAZORPAY_API_BASE_URL = "https://api.razorpay.com/v1"


class RazorpayOrderCreate(BaseModel):
    order_id: int


class RazorpayQrCreate(BaseModel):
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
    logger.error(
        "Stripe API failure: type=%s request_id=%s code=%s param=%s",
        type(exc).__name__,
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
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return getattr(value, "id", None)


def order_currency(order: Order) -> str:
    return "INR"


def amount_in_paise(amount: Any) -> int:
    value = Decimal(str(amount))
    return int(
        (value * Decimal("100")).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )


def razorpay_is_configured() -> bool:
    return bool(
        razorpay_client is not None
        and RAZORPAY_KEY_ID
        and RAZORPAY_KEY_SECRET
    )


def require_razorpay() -> None:
    if not razorpay_is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Razorpay payment service is not configured.",
        )


def create_razorpay_qr_via_api(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Create a Razorpay UPI QR code using the REST API.

    Logs the exact request URL, HTTP status, and provider error
    without logging credentials or authorization headers.
    """
    url = f"{RAZORPAY_API_BASE_URL}/payments/qr_codes"

    try:
        response = requests.post(
            url,
            auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=25,
        )
    except requests.RequestException as exc:
        logger.error(
            "Razorpay QR connection failed. URL=%s ERROR_TYPE=%s",
            url,
            type(exc).__name__,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not connect to Razorpay to create the QR code.",
        ) from exc

    logger.info(
        "Razorpay QR API response. URL=%s STATUS=%s",
        response.url,
        response.status_code,
    )

    try:
        result = response.json()
    except ValueError:
        result = {
            "error": {
                "description": response.text[:1000],
            }
        }

    if not response.ok:
        logger.error(
            "Razorpay QR creation failed. URL=%s STATUS=%s RESPONSE=%s",
            response.url,
            response.status_code,
            result,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "Razorpay could not create the UPI QR code.",
                "provider_status": response.status_code,
                "provider_error": result,
            },
        )

    if not isinstance(result, dict):
        logger.error(
            "Razorpay QR API returned an unexpected response type: %s",
            type(result).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Razorpay returned an invalid QR code response.",
        )

    return result


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
            status_code=status.HTTP_409_CONFLICT,
            detail="This order has already been paid.",
        )

    if amount_in_paise(order.total_amount) <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order amount must be greater than zero.",
        )

    return order


async def get_or_create_stripe_customer(
    user: User,
    db: AsyncSession,
) -> str:
    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe payment service is not configured.",
        )

    if user.stripe_customer_id:
        try:
            customer = stripe.Customer.retrieve(user.stripe_customer_id)

            if not getattr(customer, "deleted", False):
                return user.stripe_customer_id

        except stripe.error.InvalidRequestError:
            logger.warning(
                "Stored Stripe customer is unavailable. user_id=%s",
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
            metadata={"shopsphere_user_id": str(user.id)},
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
            "Could not save Stripe customer ID. user_id=%s",
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save payment customer information.",
        )

    return customer.id


def payment_response(
    payment: Payment,
    order: Order,
    intent: Any,
) -> PaymentIntentResponse:
    return PaymentIntentResponse(
        payment_id=payment.id,
        order_id=order.id,
        amount=float(order.total_amount),
        currency=order_currency(order),
        client_secret=intent.client_secret,
    )


async def get_pending_stripe_payment(
    order: Order,
    user: User,
    db: AsyncSession,
) -> Payment | None:
    result = await db.execute(
        select(Payment)
        .where(
            Payment.order_id == order.id,
            Payment.user_id == user.id,
            Payment.payment_method == "stripe",
            Payment.status == "pending",
        )
        .order_by(Payment.created_at.desc())
    )
    return result.scalars().first()


async def save_payment_record(
    payment: Payment,
    db: AsyncSession,
) -> None:
    db.add(payment)

    try:
        await db.commit()
        await db.refresh(payment)
    except Exception:
        await db.rollback()
        logger.exception(
            "Could not save payment record. order_id=%s",
            payment.order_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "The payment provider was initialized, but the payment "
                "record could not be saved. Check payment status before "
                "retrying."
            ),
        )


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
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe payment service is not configured.",
        )

    order = await get_customer_order(data.order_id, current_user, db)
    amount = amount_in_paise(order.total_amount)
    currency = order_currency(order)

    existing = await get_pending_stripe_payment(
        order, current_user, db
    )

    if existing and existing.stripe_payment_intent_id:
        try:
            intent = stripe.PaymentIntent.retrieve(
                existing.stripe_payment_intent_id
            )

            if (
                intent.status in {
                    "requires_payment_method",
                    "requires_confirmation",
                    "requires_action",
                }
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

                return payment_response(existing, order, intent)

            if intent.status in {"processing", "succeeded"}:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "A payment is already processing. Check your "
                        "order status before trying again."
                    ),
                )

            if intent.status != "canceled":
                try:
                    stripe.PaymentIntent.cancel(intent.id)
                except stripe.error.StripeError:
                    logger.exception(
                        "Could not cancel previous PaymentIntent: %s",
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

    options: dict[str, Any] = {
        "amount": amount,
        "currency": currency.lower(),
        "customer": customer_id,
        "automatic_payment_methods": {"enabled": True},
        "description": f"ShopSphere order #{order.id}",
        "metadata": {
            "order_id": str(order.id),
            "user_id": str(current_user.id),
        },
    }

    if data.save_card:
        options["setup_future_usage"] = "off_session"

    try:
        intent = stripe.PaymentIntent.create(
            **options,
            idempotency_key=(
                f"shopsphere-payment-{order.id}-{current_user.id}-"
                f"{uuid.uuid4().hex}"
            ),
        )
    except stripe.error.StripeError as exc:
        raise stripe_error("Unable to create Stripe payment.", exc)

    payment = Payment(
        order_id=order.id,
        user_id=current_user.id,
        amount=order.total_amount,
        currency=currency,
        payment_method="stripe",
        status="pending",
        stripe_payment_intent_id=intent.id,
    )

    await save_payment_record(payment, db)
    return payment_response(payment, order, intent)


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

            if card is not None:
                cards.append({
                    "id": method.id,
                    "brand": card.brand,
                    "last4": card.last4,
                    "exp_month": card.exp_month,
                    "exp_year": card.exp_year,
                })

        return {"cards": cards}

    except stripe.error.StripeError as exc:
        raise stripe_error("Unable to retrieve saved cards.", exc)


# =========================================================
# PAY USING A SAVED STRIPE CARD
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

    order = await get_customer_order(data.order_id, current_user, db)
    customer_id = await get_or_create_stripe_customer(
        current_user, db
    )

    try:
        method = stripe.PaymentMethod.retrieve(
            data.payment_method_id
        )
    except stripe.error.InvalidRequestError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved card not found.",
        )
    except stripe.error.StripeError as exc:
        raise stripe_error("Unable to verify the saved card.", exc)

    if (
        getattr(method, "type", None) != "card"
        or stripe_object_id(getattr(method, "customer", None))
        != customer_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This saved card is not available for your account.",
        )

    amount = amount_in_paise(order.total_amount)
    currency = order_currency(order)

    existing = await get_pending_stripe_payment(
        order, current_user, db
    )

    if existing and existing.stripe_payment_intent_id:
        try:
            old_intent = stripe.PaymentIntent.retrieve(
                existing.stripe_payment_intent_id
            )

            if old_intent.status in {
                "requires_payment_method",
                "requires_confirmation",
            }:
                if (
                    old_intent.amount != amount
                    or old_intent.currency.lower() != currency.lower()
                    or stripe_object_id(
                        getattr(old_intent, "customer", None)
                    ) != customer_id
                ):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            "The existing payment does not match this "
                            "order. Please retry the payment."
                        ),
                    )

                intent = stripe.PaymentIntent.modify(
                    old_intent.id,
                    payment_method=data.payment_method_id,
                )

                return payment_response(existing, order, intent)

            if old_intent.status in {
                "requires_action",
                "processing",
                "succeeded",
            }:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Another payment attempt is in progress. "
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
            automatic_payment_methods={"enabled": True},
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
            "Unable to create payment with the saved card.", exc
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

    await save_payment_record(payment, db)
    return payment_response(payment, order, intent)


# =========================================================
# CREATE RAZORPAY CHECKOUT ORDER
# =========================================================

@router.post("/razorpay/create-order")
async def create_razorpay_order(
    data: RazorpayOrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer_only(current_user)
    require_razorpay()

    order = await get_customer_order(data.order_id, current_user, db)
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

    try:
        provider_order = razorpay_client.order.create({
            "amount": amount,
            "currency": currency,
            "receipt": f"ss-order-{order.id}-{uuid.uuid4().hex[:8]}",
            "notes": {
                "shopsphere_order_id": str(order.id),
                "shopsphere_user_id": str(current_user.id),
            },
        })
    except Exception as exc:
        logger.error(
            "Razorpay order creation failed. order_id=%s type=%s",
            order.id,
            type(exc).__name__,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to create Razorpay order.",
        ) from exc

    payment = Payment(
        order_id=order.id,
        user_id=current_user.id,
        amount=order.total_amount,
        currency=currency,
        payment_method="razorpay",
        status="pending",
        razorpay_order_id=provider_order["id"],
    )

    await save_payment_record(payment, db)

    return {
        "payment_id": payment.id,
        "order_id": order.id,
        "razorpay_order_id": provider_order["id"],
        "amount": amount,
        "currency": currency,
        "key_id": RAZORPAY_KEY_ID,
    }


# =========================================================
# CREATE RAZORPAY UPI QR CODE
# =========================================================

@router.post("/razorpay/qr/create")
async def create_razorpay_qr(
    data: RazorpayQrCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer_only(current_user)
    require_razorpay()

    order = await get_customer_order(data.order_id, current_user, db)
    amount = amount_in_paise(order.total_amount)
    currency = order_currency(order)

    result = await db.execute(
        select(Payment)
        .where(
            Payment.order_id == order.id,
            Payment.user_id == current_user.id,
            Payment.payment_method == "razorpay_upi_qr",
            Payment.status == "pending",
            Payment.razorpay_qr_code_id.is_not(None),
        )
        .order_by(Payment.created_at.desc())
    )
    existing = result.scalars().first()

    if existing:
        try:
            qr = razorpay_client.qrcode.fetch(
                existing.razorpay_qr_code_id
            )

            if (
                qr.get("status") == "active"
                and qr.get("fixed_amount") is True
                and qr.get("payment_amount") == amount
            ):
                image_url = qr.get("image_url")

                if image_url:
                    return {
                        "payment_id": existing.id,
                        "order_id": order.id,
                        "qr_code_id": existing.razorpay_qr_code_id,
                        "image_url": image_url,
                        "amount": amount,
                        "currency": currency,
                        "key_id": RAZORPAY_KEY_ID,
                        "status": "pending",
                    }

        except Exception:
            logger.warning(
                "Could not reuse existing Razorpay QR. order_id=%s",
                order.id,
                exc_info=True,
            )

    qr = create_razorpay_qr_via_api({
        "type": "upi_qr",
        "name": f"ShopSphere Order {order.id}",
        "usage": "single_use",
        "fixed_amount": True,
        "payment_amount": amount,
        "description": f"ShopSphere order #{order.id}",
        "notes": {
            "shopsphere_order_id": str(order.id),
            "shopsphere_user_id": str(current_user.id),
        },
    })

    qr_id = qr.get("id")
    image_url = qr.get("image_url")

    if not qr_id or not image_url:
        logger.error(
            "Razorpay QR response is missing required fields. "
            "order_id=%s response_keys=%s",
            order.id,
            list(qr.keys()),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Razorpay did not return a usable QR code.",
        )

    payment = Payment(
        order_id=order.id,
        user_id=current_user.id,
        amount=order.total_amount,
        currency=currency,
        payment_method="razorpay_upi_qr",
        status="pending",
        razorpay_qr_code_id=qr_id,
    )

    await save_payment_record(payment, db)

    return {
        "payment_id": payment.id,
        "order_id": order.id,
        "qr_code_id": qr_id,
        "image_url": image_url,
        "amount": amount,
        "currency": currency,
        "key_id": RAZORPAY_KEY_ID,
        "status": "pending",
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
        select(OrderItem).where(OrderItem.order_id == order.id)
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
# VERIFY RAZORPAY UPI QR PAYMENT
# =========================================================

@router.post("/razorpay/qr/verify")
async def verify_razorpay_qr_payment(
    data: RazorpayQrCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer_only(current_user)
    require_razorpay()

    payment_result = await db.execute(
        select(Payment)
        .where(
            Payment.order_id == data.order_id,
            Payment.user_id == current_user.id,
            Payment.payment_method == "razorpay_upi_qr",
            Payment.razorpay_qr_code_id.is_not(None),
        )
        .order_by(Payment.created_at.desc())
        .with_for_update()
    )
    payment = payment_result.scalars().first()

    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="UPI QR payment not found.",
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
            "payment_status": "paid",
        }

    if (
        payment.status in {"cancelled", "failed", "refunded"}
        or order.status == "cancelled"
        or order.payment_status == "paid"
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This payment can no longer be verified.",
        )

    try:
        result = razorpay_client.qrcode.fetch_all_payments(
            payment.razorpay_qr_code_id
        )
    except Exception as exc:
        logger.error(
            "Razorpay QR payment lookup failed. order_id=%s type=%s",
            order.id,
            type(exc).__name__,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to check UPI payment status.",
        ) from exc

    provider_payments = result.get("items", [])
    expected_amount = amount_in_paise(order.total_amount)
    matching_payment = None

    for provider_payment in provider_payments:
        if (
            provider_payment.get("status") == "captured"
            and provider_payment.get("captured") is True
            and provider_payment.get("method") == "upi"
            and provider_payment.get("amount") == expected_amount
            and str(
                provider_payment.get("currency", "")
            ).upper() == order_currency(order).upper()
            and provider_payment.get("refund_status") != "full"
        ):
            matching_payment = provider_payment
            break

    if matching_payment is None:
        return {
            "verified": False,
            "order_id": order.id,
            "payment_status": "pending",
            "message": (
                "Payment has not been captured yet. "
                "Complete the UPI payment and check again."
            ),
        }

    provider_payment_id = matching_payment.get("id")

    if not provider_payment_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Razorpay returned an invalid payment record.",
        )

    duplicate_result = await db.execute(
        select(Payment).where(
            Payment.razorpay_payment_id == provider_payment_id,
            Payment.id != payment.id,
        )
    )

    if duplicate_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This provider payment is already linked to another payment."
            ),
        )

    payment.razorpay_payment_id = provider_payment_id
    payment.transaction_id = provider_payment_id
    payment.status = "paid"

    await fulfil_paid_order(order, db)

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception(
            "Could not finalize Razorpay QR payment. order_id=%s",
            order.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Payment was verified, but the order could not be "
                "updated. Contact support before retrying."
            ),
        )

    return {
        "verified": True,
        "order_id": order.id,
        "payment_status": "paid",
    }


# =========================================================
# VERIFY RAZORPAY CHECKOUT PAYMENT
# =========================================================

@router.post("/razorpay/verify")
async def verify_razorpay_payment(
    data: RazorpayVerifyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer_only(current_user)
    require_razorpay()

    payment_result = await db.execute(
        select(Payment)
        .where(
            Payment.order_id == data.order_id,
            Payment.user_id == current_user.id,
            Payment.payment_method == "razorpay",
            Payment.razorpay_order_id == data.razorpay_order_id,
        )
        .with_for_update()
    )
    payment = payment_result.scalar_one_or_none()

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
        return {"verified": True, "order_id": order.id}

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
        expected_signature, data.razorpay_signature
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
        logger.error(
            "Razorpay verification failed. order_id=%s type=%s",
            order.id,
            type(exc).__name__,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to verify payment status with Razorpay.",
        ) from exc

    if provider_payment.get("order_id") != data.razorpay_order_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payment does not match this order.",
        )

    if (
        provider_payment.get("amount")
        != amount_in_paise(order.total_amount)
        or str(provider_payment.get("currency", "")).upper()
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

    if payment.razorpay_payment_id not in (
        None,
        data.razorpay_payment_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another payment is already linked to this record.",
        )

    duplicate_result = await db.execute(
        select(Payment).where(
            Payment.razorpay_payment_id == data.razorpay_payment_id,
            Payment.id != payment.id,
        )
    )

    if duplicate_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This provider payment is already linked to another payment."
            ),
        )

    payment.razorpay_payment_id = data.razorpay_payment_id
    payment.razorpay_signature = data.razorpay_signature
    payment.transaction_id = data.razorpay_payment_id
    payment.status = "paid"

    await fulfil_paid_order(order, db)

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception(
            "Could not finalize Razorpay payment. order_id=%s",
            order.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Payment was verified but the order could not be "
                "updated. Contact support before retrying."
            ),
        )

    return {"verified": True, "order_id": order.id}


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
    intent_id = stripe_object_id(event["data"]["object"])

    if not intent_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe payment event.",
        )

    if event_type == "payment_intent.succeeded":
        await handle_successful_payment(intent_id, db)
    elif event_type == "payment_intent.canceled":
        await handle_cancelled_payment(intent_id, db)

    return {"received": True}


# =========================================================
# HANDLE SUCCESSFUL STRIPE PAYMENT
# =========================================================

async def handle_successful_payment(
    payment_intent_id: str,
    db: AsyncSession,
) -> None:
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
        logger.error(
            "Stripe payment has no matching order. payment_intent_id=%s",
            payment_intent_id,
        )
        return

    try:
        intent = stripe.PaymentIntent.retrieve(payment_intent_id)
    except stripe.error.StripeError as exc:
        raise stripe_error("Unable to verify Stripe payment.", exc)

    if (
        intent.status != "succeeded"
        or intent.amount_received != amount_in_paise(order.total_amount)
        or intent.currency.lower() != order_currency(order).lower()
    ):
        logger.error(
            "Stripe payment validation failed. order_id=%s",
            order.id,
        )
        return

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
                "Unable to refund a late or duplicate payment.", exc
            )

        payment.status = "refunded"
        payment.transaction_id = refund.id

        try:
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception(
                "Could not save Stripe refund state. order_id=%s",
                order.id,
            )
            raise

        return

    payment.status = "paid"
    payment.transaction_id = payment_intent_id

    await fulfil_paid_order(order, db)

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception(
            "Could not finalize Stripe payment. order_id=%s",
            order.id,
        )
        raise


# =========================================================
# HANDLE CANCELLED STRIPE PAYMENT
# =========================================================

async def handle_cancelled_payment(
    payment_intent_id: str,
    db: AsyncSession,
) -> None:
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

    # Cancelling a payment attempt does not cancel the order.
    await db.commit()
