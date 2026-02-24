from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from sqlalchemy import func
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.core.security import hash_password
from app.schemas.user import UserLogin 
from app.core.security import verify_password 

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

    existing_user = db.query(User).filter(User.username == user_in.username).first()
    if existing_user:
        raise HTTPException(
            status_code=400, 
            detail="Username already registered"
        )

    hashed_pwd = hash_password(user_in.password)

    new_user = User(
        username=user_in.username,
        full_name=user_in.full_name,
        assigned_roles=user_in.assigned_roles, # ["dashboard", "pdi", etc]
        hashed_password=hashed_pwd,
        is_active=user_in.is_active
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return new_user

@router.get("/", response_model=List[UserOut])
def list_all_users(db: Session = Depends(get_db)):
    """
    Returns a list of all users. 
    Note: Pydantic 'UserOut' automatically hides 'hashed_password'.
    """
    users = db.query(User).all()
    return users


@router.patch("/{username}", response_model=UserOut)
def update_user_roles(username: str, user_update: UserUpdate, db: Session = Depends(get_db)):
    """
    Update user details or roles using their username.
    Only provided fields will be updated.
    """
    db_user = db.query(User).filter(User.username == username).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

   
    update_data = user_update.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        if key == "password":
            setattr(db_user, "hashed_password", hash_password(value))
        else:
            setattr(db_user, key, value)

    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@router.delete("/{username}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(username: str, db: Session = Depends(get_db)):
    """
    Hard delete a user from the system using their username.
    """
    db_user = db.query(User).filter(User.username == username).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    db.delete(db_user)
    db.commit()
    return None

@router.post("/login")
def login(user_credentials: UserLogin, db: Session = Depends(get_db)):
    """
    Verifies username and password. 
    Returns the user's assigned roles for frontend navigation.
    """
 
    user = db.query(User).filter(User.username == user_credentials.username).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Credentials"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Please contact Admin."
        )

    if not verify_password(user_credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Credentials"
        )

    user.last_login = func.now()
    db.commit()

    return {
        "message": "Login successful",
        "username": user.username,
        "full_name": user.full_name,
        "assigned_roles": user.assigned_roles # This is what your frontend needs!
    }