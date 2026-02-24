from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional
from datetime import datetime


class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    full_name: str
    assigned_roles: List[str] = ["dashboard"]
    is_active: bool = True

class UserCreate(UserBase):
    password: str = Field(..., min_length=6)

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    assigned_roles: Optional[List[str]] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None

class UserOut(UserBase):
    id: int
    last_login: Optional[datetime] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class UserLogin(BaseModel):
    username: str
    password: str