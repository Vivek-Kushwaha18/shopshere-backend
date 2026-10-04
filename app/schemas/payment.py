from datetime import datetime

from pydantic import BaseModel


class PaymentIntentCreate(BaseModel):
    order_id: int


class PaymentResponse(BaseModel):
    id: int
    order_id: int
    user_id: int
    amount: float
    currency: str
    payment_method: str
    status: str
    stripe_payment_intent_id: str | None
    stripe_checkout_session_id: str | None
    transaction_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True,
    }


class PaymentIntentResponse(BaseModel):
    payment_id: int
    order_id: int
    amount: float
    currency: str
    client_secret: str