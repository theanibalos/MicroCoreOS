import re
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List

# === API SCHEMAS (Swagger/Pydantic) ===
class UserBase(BaseModel):
    name: str = Field(..., min_length=3, description="User's full name")
    email: EmailStr = Field(..., description="Unique email address")

class UserCreate(UserBase):
    password: str = Field(..., min_length=8, description="User's plain text password")

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    error: Optional[str] = None

class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=3)
    email: Optional[EmailStr] = None

class UserUpdateWithId(UserUpdate):
    id: int = Field(..., description="ID of user to update")

class UserIdRequest(BaseModel):
    id: int = Field(..., description="Unique user ID")

class UserPublic(UserBase):
    id: int

class UserListResponse(BaseModel):
    success: bool
    users: List[UserPublic]

class UserResponse(BaseModel):
    success: bool
    user: Optional[UserPublic] = None
    error: Optional[str] = None

# === DOMAIN OBJECT ===
class UserModel:
    def __init__(self, name=None, email=None, password_hash=None, id=None):
        self.id = id
        self.name = name
        self.email = email
        self.password_hash = password_hash

    @staticmethod
    def validate_name(name):
        if not name or not isinstance(name, str) or len(name) < 3:
            return False, "Must have at least 3 characters."
        return True, None

    @staticmethod
    def validate_email(email):
        regex = r'^[a-z0-9]+[\._]?[a-z0-9]+[@]\w+[.]\w+$'
        if not email or not re.match(regex, email):
            return False, "Invalid format."
        return True, None

    def to_dict(self):
        return {
            "id": self.id, 
            "name": self.name, 
            "email": self.email,
            "password_hash": self.password_hash
        }

    @staticmethod
    def from_row(row):
        """Converts a database row (id, name, email, password_hash) to a UserModel object."""
        if not row: return None
        return UserModel(id=row[0], name=row[1], email=row[2], password_hash=row[3])