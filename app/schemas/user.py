from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional
from datetime import datetime

# 1. Base Schema (Common fields)
class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    full_name: str
    # Your final model uses 'assigned_roles' for page access
    assigned_roles: List[str] = ["dashboard"]
    is_active: bool = True

# 2. Schema for Creating a User (Incoming JSON)
class UserCreate(UserBase):
    password: str = Field(..., min_length=6)

# 3. Schema for Updating a User (All fields optional)
class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    assigned_roles: Optional[List[str]] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None

# 4. Schema for Returning a User (Outgoing JSON - Security Layer)
class UserOut(UserBase):
    id: int
    last_login: Optional[datetime] = None
    created_at: datetime

    # This is crucial: It tells Pydantic to convert SQLAlchemy objects to JSON
    model_config = ConfigDict(from_attributes=True)