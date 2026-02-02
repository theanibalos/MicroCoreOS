import re
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List

# === SCHEMAS PARA API (Swagger/Pydantic) ===
class UserBase(BaseModel):
    name: str = Field(..., min_length=3, description="Nombre completo del usuario")
    email: EmailStr = Field(..., description="Correo electrónico único")

class UserCreate(UserBase):
    pass

class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=3)
    email: Optional[EmailStr] = None

class UserUpdateWithId(UserUpdate):
    id: int = Field(..., description="ID del usuario a actualizar")

class UserIdRequest(BaseModel):
    id: int = Field(..., description="ID único del usuario")

class UserPublic(UserBase):
    id: int

class UserListResponse(BaseModel):
    success: bool
    users: List[UserPublic]

class UserResponse(BaseModel):
    success: bool
    user: Optional[UserPublic] = None
    error: Optional[str] = None

# === OBJETO DE DOMINIO ===
class UserModel:
    def __init__(self, name=None, email=None, id=None):
        self.id = id
        self.name = name
        self.email = email

    @staticmethod
    def validate_name(name):
        if not name or not isinstance(name, str) or len(name) < 3:
            return False, "Debe tener al menos 3 caracteres."
        return True, None

    @staticmethod
    def validate_email(email):
        regex = r'^[a-z0-9]+[\._]?[a-z0-9]+[@]\w+[.]\w+$'
        if not email or not re.match(regex, email):
            return False, "Formato no válido."
        return True, None

    def to_dict(self):
        return {"id": self.id, "name": self.name, "email": self.email}

    @staticmethod
    def from_row(row):
        """Convierte una fila de la base de datos (id, name, email) en un objeto UserModel."""
        if not row: return None
        return UserModel(id=row[0], name=row[1], email=row[2])