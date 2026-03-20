"""Pydantic schemas for authentication endpoints."""

from fastapi import Form
from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    """Request body for POST /auth/register."""

    username: str
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class RegisterResponse(BaseModel):
    """Response body for POST /auth/register."""

    id: int
    username: str
    email: str


class LoginRequest(BaseModel):
    """Form-encoded request body for POST /auth/login (OAuth2 compatible)."""

    username: str
    password: str

    @classmethod
    def as_form(
        cls,
        username: str = Form(...),
        password: str = Form(...),
    ) -> "LoginRequest":
        """Construct from FastAPI Form fields for OAuth2 compatibility."""
        return cls(username=username, password=password)


class TokenResponse(BaseModel):
    """Response body for POST /auth/login."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    """Request body for POST /auth/refresh."""

    refresh_token: str


class RefreshResponse(BaseModel):
    """Response body for POST /auth/refresh."""

    access_token: str
    token_type: str = "bearer"


class ChangePasswordRequest(BaseModel):
    """Request body for POST /auth/change-password."""

    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str


class UserResponse(BaseModel):
    """Response body for GET /auth/me."""

    id: int
    username: str
    email: str
