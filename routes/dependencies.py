from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from auth.security import decode_access_token, oauth2_scheme
from database.database import get_database
from database.service import find_user_by_id

Database = Annotated[AsyncIOMotorDatabase, Depends(get_database)]


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)], database: Database) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        if payload.get("type") != "access" or not payload.get("sub"):
            raise credentials_exception
    except (jwt.InvalidTokenError, HTTPException):
        raise credentials_exception from None

    user = await find_user_by_id(database, payload["sub"])
    if user is None or not user.get("is_active", True):
        raise credentials_exception
    return user


CurrentUser = Annotated[dict, Depends(get_current_user)]