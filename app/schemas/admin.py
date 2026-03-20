"""Pydantic schemas for admin user management endpoints."""

from pydantic import BaseModel, Field


class UpdateMaxCharactersRequest(BaseModel):
    """Request body for PUT /admin/users/{id}."""

    max_characters: int = Field(ge=1)


class UserAdminResponse(BaseModel):
    """Response body for PUT /admin/users/{id}."""

    id: int
    username: str
    email: str
    max_characters: int


class CharacterAdminResponse(BaseModel):
    """Response body for PUT /admin/characters/{id}/restore."""

    id: int
    name: str
    is_deleted: bool
