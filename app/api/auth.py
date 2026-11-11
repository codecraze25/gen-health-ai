from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, limit_login, limit_register
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    hash_password,
    verify_password,
)
from app.models import User
from app.schemas.auth import Token, UserCreate, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_register)],
)
def register(body: UserCreate, db: DbSession) -> User:
    email = body.email.lower()
    if db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered")
    user = User(email=email, hashed_password=hash_password(body.password))
    db.add(user)
    db.commit()
    return user


@router.post("/login", response_model=Token, dependencies=[Depends(limit_login)])
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession) -> Token:
    """OAuth2 password flow. Send the email as `username` (form-encoded)."""
    user = db.scalar(select(User).where(func.lower(User.email) == form.username.lower()))
    valid = verify_password(form.password, user.hashed_password if user else DUMMY_PASSWORD_HASH)
    if not user or not valid:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token, expires_in = create_access_token(user.id)
    return Token(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user
