from typing import Literal

from pydantic import BaseModel, EmailStr, Field


# =========================================================
# SIGNUP
# =========================================================

class SignupRequest(BaseModel):

    full_name: str = Field(
        min_length=2,
        max_length=100
    )

    email: EmailStr

    phone: str = Field(
        min_length=10,
        max_length=20
    )

    password: str = Field(
        min_length=8,
        max_length=100
    )

    role: Literal["customer", "seller"] = "customer"


# =========================================================
# LOGIN
# =========================================================

class LoginRequest(BaseModel):

    email: EmailStr

    password: str


# =========================================================
# FORGOT PASSWORD
# =========================================================

class ForgotPasswordRequest(BaseModel):

    email: EmailStr


# =========================================================
# UPDATE PASSWORD USING EMAIL LINK
# =========================================================

class UpdatePasswordRequest(BaseModel):

    token: str

    new_password: str = Field(
        min_length=8,
        max_length=100
    )


# =========================================================
# CHANGE PASSWORD AFTER LOGIN
# =========================================================

class ChangePasswordRequest(BaseModel):

    current_password: str

    new_password: str = Field(
        min_length=8,
        max_length=100
    )

    confirm_password: str = Field(
        min_length=8,
        max_length=100
    )