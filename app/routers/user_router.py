from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserOut
from app.core.security import hash_password

router = APIRouter(
    prefix="/users",
    tags=["User Management"]
)

@router.post("/", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_new_user(user_in: UserCreate, db: Session = Depends(get_db)):
    """
    Creates a new user for the Max-Trace portal.
    Checks if username exists, hashes the password, and saves to DB.
    """
    # 1. Check if user already exists
    existing_user = db.query(User).filter(User.username == user_in.username).first()
    if existing_user:
        raise HTTPException(
            status_code=400, 
            detail="Username already registered"
        )

    # 2. Hash the plain text password
    hashed_pwd = hash_password(user_in.password)

    # 3. Create SQLAlchemy object
    new_user = User(
        username=user_in.username,
        full_name=user_in.full_name,
        assigned_roles=user_in.assigned_roles, # ["dashboard", "pdi", etc]
        hashed_password=hashed_pwd,
        is_active=user_in.is_active
    )

    # 4. Save to Database
    db.add(new_user)
    db.commit()
    db.refresh(new_user) # Get the ID and created_at back from DB
    
    return new_user

@router.get("/", response_model=List[UserOut])
def list_all_users(db: Session = Depends(get_db)):
    """
    Returns a list of all users. 
    Note: Pydantic 'UserOut' automatically hides 'hashed_password'.
    """
    users = db.query(User).all()
    return users