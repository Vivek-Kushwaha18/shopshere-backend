
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PaymentIntentCreate(BaseModel):
    order_id: int
    save_card: bool = False


class SavedCardPaymentCreate(BaseModel):
    order_id: int
    payment_method_id: str = Field(..., min_length=1, max_length=255)


class PaymentResponse(BaseModel):
    id: int
    order_id: int
    user_id: int
    amount: float
    currency: str
    payment_method: str
    status: str
    stripe_payment_intent_id: str | None = None
    stripe_checkout_session_id: str | None = None
    razorpay_order_id: str | None = None
    razorpay_payment_id: str | None = None
    razorpay_signature: str | None = None
    transaction_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaymentIntentResponse(BaseModel):
    payment_id: int
    order_id: int
    amount: float
    currency: str
    client_secret: str
