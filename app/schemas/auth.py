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

    role: Literal[
        "customer",
        "seller",
    ] = "customer"


# =========================================================
# LOGIN
# =========================================================

class LoginRequest(BaseModel):

    email: EmailStr

    password: str


# =========================================================
# PROFILE UPDATE
# =========================================================

class ProfileUpdateRequest(BaseModel):

    full_name: str = Field(
        min_length=2,
        max_length=100,
    )

    phone: str | None = Field(
        default=None,
        max_length=20,
    )


# =========================================================
# CHANGE PASSWORD
# =========================================================

class ChangePasswordRequest(BaseModel):

    current_password: str

    new_password: str = Field(
        min_length=8,
        max_length=128,
    )


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
# EMAIL VERIFICATION
# =========================================================

class VerifyEmailRequest(BaseModel):

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
# USER RESPONSE
# =========================================================

class UserResponse(BaseModel):

    id: int

    full_name: str

    email: EmailStr

    phone: str | None

    role: str

    is_active: bool

    is_verified: bool


# =========================================================
# TOKEN RESPONSE
# =========================================================

class TokenResponse(BaseModel):

    access_token: str

    refresh_token: str

    token_type: str

    user: UserResponse