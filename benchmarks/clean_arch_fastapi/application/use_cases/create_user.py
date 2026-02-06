# application/use_cases/create_user.py
# Clean Architecture: Use Case / Application Service

from dataclasses import dataclass
from typing import Optional
from ..domain.repositories.user_repository import IUserRepository


@dataclass
class CreateUserRequest:
    """Input DTO for the use case."""
    name: str
    email: str


@dataclass
class CreateUserResponse:
    """Output DTO for the use case."""
    success: bool
    user_id: Optional[int] = None
    error: Optional[str] = None


class CreateUserUseCase:
    """
    Application Use Case: Create a new user.
    Orchestrates the domain logic and repository calls.
    """

    def __init__(self, user_repository: IUserRepository):
        self._repository = user_repository

    def execute(self, request: CreateUserRequest) -> CreateUserResponse:
        # 1. Validation
        if "@" not in request.email:
            return CreateUserResponse(success=False, error="Invalid email")

        try:
            # 2. Persist
            user_id = self._repository.save(request.name, request.email)
            return CreateUserResponse(success=True, user_id=user_id)
        except Exception as e:
            return CreateUserResponse(success=False, error=str(e))
