import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.fields import PasswordStr


class UserCreate(BaseModel):
    email: EmailStr
    password: PasswordStr
    full_name: str = Field(min_length=1, max_length=200)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    is_active: bool
