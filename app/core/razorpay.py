
import os

import razorpay
from dotenv import load_dotenv

load_dotenv()

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")

razorpay_client = (
    razorpay.Client(
        auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)
    )
    if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET
    else None
)


def get_razorpay_client():
    if razorpay_client is None:
        raise RuntimeError(
            "Razorpay is not configured. Set RAZORPAY_KEY_ID "
            "and RAZORPAY_KEY_SECRET in your backend .env file."
        )

    return razorpay_client
