from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pymongo.errors import DuplicateKeyError

from auth.security import create_access_token, hash_password, verify_password
from database.models import user_response
from database.service import create_user, find_user_by_email

from .dependencies import CurrentUser, Database
from .schemas import RegisterRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, database: Database) -> dict:
    email = str(payload.email).lower()
    if await find_user_by_email(database, email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered")

    try:
        user = await create_user(database, email, hash_password(payload.password))
    except DuplicateKeyError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered") from None
    return user_response(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()], database: Database
) -> TokenResponse:
    user = await find_user_by_email(database, form_data.username)
    if user is None or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(access_token=create_access_token(str(user["_id"])))


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUser) -> dict:
    return user_response(current_user)