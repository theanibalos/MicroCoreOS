# interfaces/api/controllers/user_controller.py
# Clean Architecture: Controller / API Layer

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

from ..application.use_cases.create_user import (
    CreateUserUseCase,
    CreateUserRequest,
)
from ..infrastructure.repositories.sqlite_user_repository import SqliteUserRepository


# --- DTOs (Pydantic Models for API) ---

class CreateUserDTO(BaseModel):
    """Request DTO for the API endpoint."""
    name: str
    email: EmailStr


class UserResponseDTO(BaseModel):
    """Response DTO for the API endpoint."""
    success: bool
    user_id: int | None = None
    error: str | None = None


# --- Dependency Injection Setup (Manual) ---
# In a real app, this would be in a separate container/factory file.
user_repository = SqliteUserRepository()
create_user_use_case = CreateUserUseCase(user_repository)


# --- Router ---

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("/create", response_model=UserResponseDTO)
def create_user(dto: CreateUserDTO) -> UserResponseDTO:
    """
    API endpoint to create a new user.
    Maps HTTP request to Use Case and returns HTTP response.
    """
    request = CreateUserRequest(name=dto.name, email=dto.email)
    response = create_user_use_case.execute(request)

    if not response.success:
        # In Clean Arch, you might raise an HTTPException here
        # or let the response model handle it.
        pass

    return UserResponseDTO(
        success=response.success,
        user_id=response.user_id,
        error=response.error
    )
