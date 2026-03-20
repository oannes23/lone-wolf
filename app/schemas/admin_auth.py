"""Pydantic schemas for admin authentication endpoints."""

from pydantic import BaseModel


class AdminLoginRequest(BaseModel):
    """Request body for POST /admin/auth/login."""

    username: str
    password: str


class AdminTokenResponse(BaseModel):
    """Response body for POST /admin/auth/login."""

    access_token: str
    token_type: str = "bearer"
