from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def fits_bcrypt(cls, value: str) -> str:
        # bcrypt only accepts 72 bytes; Cyrillic characters take two bytes each.
        if len(value.encode()) > 72:
            raise ValueError("password is too long")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class OAuthRequest(BaseModel):
    """Identity-token exchange for Apple / Google / VK.

    The token is verified against the provider before an account is created or matched;
    in local development the stub verifier trusts a `test:<subject>` token so the whole
    onboarding flow can be exercised without provider credentials.
    """

    id_token: str
    #: Accepted for backwards compatibility and ignored: only the email verified by
    #: the provider is trusted.
    email: EmailStr | None = None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: str | None
    name: str | None
    avatar_url: str | None
    region_code: str
    onboarding_completed: bool
    tier: str = "free"


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    avatar_url: str | None = Field(default=None, max_length=500)
    region_code: str | None = Field(default=None, min_length=2, max_length=16)
