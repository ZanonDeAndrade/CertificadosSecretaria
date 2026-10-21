from __future__ import annotations

from datetime import datetime

from certificados_backend import auth
from pydantic import BaseModel, Field, field_validator


class UserResponse(BaseModel):
    id: int
    name: str
    username: str
    role: str
    is_active: bool
    must_change_password: bool
    password_changed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CreateUserRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    username: str = Field(min_length=1, max_length=auth.MAX_USERNAME_LENGTH)
    role: str = "secretaria"
    temporary_password: str = Field(
        min_length=auth.MIN_NEW_PASSWORD_LENGTH,
        max_length=auth.MAX_BCRYPT_PASSWORD_BYTES,
    )

    @field_validator("name", "username")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("role")
    @classmethod
    def valid_role(cls, value: str) -> str:
        if value not in auth.VALID_ROLES:
            raise ValueError("Perfil inválido.")
        return value


class UpdateUserRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    username: str | None = Field(default=None, min_length=1, max_length=auth.MAX_USERNAME_LENGTH)
    role: str | None = None
    # Kept in this contract for backwards compatibility; the frontend uses the
    # explicit activate/deactivate endpoints.
    is_active: bool | None = None

    @field_validator("name", "username")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("role")
    @classmethod
    def valid_role(cls, value: str | None) -> str | None:
        if value is not None and value not in auth.VALID_ROLES:
            raise ValueError("Perfil inválido.")
        return value


class ResetPasswordRequest(BaseModel):
    temporary_password: str = Field(
        min_length=auth.MIN_NEW_PASSWORD_LENGTH,
        max_length=auth.MAX_BCRYPT_PASSWORD_BYTES,
    )


class UserMutationResponse(BaseModel):
    user: UserResponse
    sessions_revoked: int = 0


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int
