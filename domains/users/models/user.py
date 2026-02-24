from pydantic import BaseModel, EmailStr

class UserEntity(BaseModel):
    id: int | None = None
    name: str
    email: EmailStr
    password: str | None = None
