# domain/repositories/user_repository.py
# Clean Architecture: Repository Interface (Port)

from abc import ABC, abstractmethod
from typing import Optional


class IUserRepository(ABC):


    @abstractmethod
    def save(self, name: str, email: str) -> int:
        pass
