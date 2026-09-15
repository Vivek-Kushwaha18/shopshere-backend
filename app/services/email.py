import os

from aiosmtplib import SMTP
from email.message import EmailMessage
from dotenv import load_dotenv


load_dotenv()


SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")


async def send_reset_password_email(
    recipient_email: str,
    reset_token: str
):

    frontend_url = os.getenv(
        "FRONTEND_URL",
        "http://localhost:3000"
    )

    reset_link = (
        f"{frontend_url}/reset-password"
        f"?token={reset_token}"
    )

    message = EmailMessage()

    message["From"] = SMTP_USERNAME
    message["To"] = recipient_email
    message["Subject"] = "ShopSphere - Reset Your Password"

    message.set_content(
        f"""
Hello,

We received a request to reset your ShopSphere password.

Click the link below to reset your password:

{reset_link}

This link will expire in 15 minutes.

If you did not request a password reset, you can safely ignore this email.

Regards,
ShopSphere Team
"""
    )

    smtp = SMTP(
        hostname=SMTP_HOST,
        port=SMTP_PORT,
        start_tls=True
    )

    await smtp.connect()

    await smtp.login(
        SMTP_USERNAME,
        SMTP_PASSWORD
    )

    await smtp.send_message(message)

    await smtp.quit()