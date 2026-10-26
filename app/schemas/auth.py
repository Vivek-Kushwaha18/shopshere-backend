
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
    remember_me: bool = False


# =========================================================
# GOOGLE LOGIN
# =========================================================

class GoogleLoginRequest(BaseModel):
    credential: str = Field(
        min_length=1,
        max_length=10000,
    )
    remember_me: bool = False


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
    remember_me: bool = False


# =========================================================
# REFRESH TOKEN
# =========================================================

class RefreshTokenRequest(BaseModel):
    refresh_token: str | None = None
    remember_me: bool = False


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


# =========================================================
# PROFILE RESPONSE
# =========================================================

class ProfileResponse(BaseModel):
    full_name: str
    email: EmailStr
    phone: str | None = None

    gender: Literal[
        "male",
        "female",
        "other",
        "prefer_not_to_say",
    ] | None = None

    role: str
    is_active: bool
    is_verified: bool


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

    gender: Literal[
        "male",
        "female",
        "other",
        "prefer_not_to_say",
    ] | None = None


# =========================================================
# CHANGE EMAIL
# =========================================================

class ChangeEmailRequest(BaseModel):
    new_email: EmailStr


# =========================================================
# VERIFY EMAIL CHANGE
# =========================================================

class VerifyEmailChangeRequest(BaseModel):
    code: str = Field(
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
    )


# =========================================================
# ADMIN - UPDATE USER
# =========================================================

class AdminUserUpdateRequest(BaseModel):
    full_name: str | None = Field(
        default=None,
        min_length=2,
        max_length=100,
    )

    phone: str | None = Field(
        default=None,
        max_length=20,
    )

    gender: Literal[
        "male",
        "female",
        "other",
        "prefer_not_to_say",
    ] | None = None

    role: Literal[
        "customer",
        "seller",
        "admin",
    ] | None = None

    is_active: bool | None = None


# =========================================================
# ADMIN - USER RESPONSE
# =========================================================

class AdminUserResponse(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    phone: str | None = None

    gender: Literal[
        "male",
        "female",
        "other",
        "prefer_not_to_say",
    ] | None = None

    role: str
    is_active: bool
    is_verified: bool
