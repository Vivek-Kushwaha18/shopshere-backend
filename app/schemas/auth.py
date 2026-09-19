from typing import Literal

from pydantic import BaseModel, EmailStr, Field


# =========================================================
# SIGNUP
# =========================================================

class SignupRequest(BaseModel):
    full_name: str = Field(
        min_length=2,
        max_length=100,
    )

    email: EmailStr

    phone: str | None = Field(
        default=None,
        max_length=20,
    )

    password: str = Field(
        min_length=8,
        max_length=128,
    )

    role: Literal["customer", "seller"] = "customer"


# =========================================================
# LOGIN
# =========================================================

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# =========================================================
# SEND VERIFICATION CODE
# =========================================================

class SendVerificationCodeRequest(BaseModel):
    email: EmailStr


# =========================================================
# VERIFY EMAIL
# =========================================================

class VerifyEmailRequest(BaseModel):
    email: EmailStr

    code: str = Field(
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
    )


# =========================================================
# REFRESH TOKEN
# =========================================================

class RefreshTokenRequest(BaseModel):
    refresh_token: str


# =========================================================
# FORGOT PASSWORD
# =========================================================

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


# =========================================================
# RESET PASSWORD
# =========================================================

class ResetPasswordRequest(BaseModel):
    token: str

    new_password: str = Field(
        min_length=8,
        max_length=128,
    )


# =========================================================
# USER RESPONSE
# ONLY 3 USER INFORMATION FIELDS
# =========================================================

class UserResponse(BaseModel):
    full_name: str
    email: EmailStr
    role: str


# =========================================================
# TOKEN RESPONSE
# =========================================================

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    user: UserResponse