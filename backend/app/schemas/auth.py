from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class PhoneCodeRequest(BaseModel):
    phone: str = Field(min_length=10, max_length=20)


class PhoneCodeOut(BaseModel):
    #: Seconds until the code stops working / until another code may be requested.
    expires_in: int
    resend_in: int


class PhoneVerifyRequest(BaseModel):
    phone: str = Field(min_length=10, max_length=20)
    code: str = Field(pattern=r"^\d{6}$")
    #: The separate consent to personal data processing (152-FZ art. 9); required
    #: when this sign-in creates the account.
    personal_data_consent: bool = False


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
    #: Required when this sign-in creates a new account.
    personal_data_consent: bool = False


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: str | None
    phone: str | None = None
    name: str | None
    avatar_url: str | None
    region_code: str
    onboarding_completed: bool
    #: trial | base | pro while access lasts, null without access
    tier: str | None = None


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    avatar_url: str | None = Field(default=None, max_length=500)
    region_code: str | None = Field(default=None, min_length=2, max_length=16)
