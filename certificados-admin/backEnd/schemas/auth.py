from __future__ import annotations

from certificados_backend import auth
from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=auth.MAX_USERNAME_LENGTH)
    password: str = Field(min_length=1, max_length=auth.MAX_BCRYPT_PASSWORD_BYTES)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        return auth.validate_username(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        auth._validate_bcrypt_input(value)
        return value


class AuthUserResponse(BaseModel):
    id: int
    name: str
    username: str
    role: str
    permissions: list[str]
    must_change_password: bool


class LoginResponse(BaseModel):
    user: AuthUserResponse


class ChangeOwnPasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=auth.MAX_BCRYPT_PASSWORD_BYTES)
    new_password: str = Field(
        min_length=auth.MIN_NEW_PASSWORD_LENGTH,
        max_length=auth.MAX_BCRYPT_PASSWORD_BYTES,
    )

    @field_validator("current_password", "new_password")
    @classmethod
    def bcrypt_length(cls, value: str) -> str:
        auth._validate_bcrypt_input(value)
        return value


class PasswordChangedResponse(BaseModel):
    ok: bool = True
    sessions_revoked: int


class SessionsRevokedResponse(BaseModel):
    revoked: int
