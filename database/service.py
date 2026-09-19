from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from .models import as_object_id, user_document

USERS_COLLECTION = "users"


async def ensure_indexes(database: AsyncIOMotorDatabase) -> None:
    await database[USERS_COLLECTION].create_index("email", unique=True)


async def find_user_by_email(database: AsyncIOMotorDatabase, email: str) -> dict | None:
    return await database[USERS_COLLECTION].find_one({"email": email.lower()})


async def find_user_by_id(database: AsyncIOMotorDatabase, user_id: str) -> dict | None:
    object_id = as_object_id(user_id)
    if object_id is None:
        return None
    return await database[USERS_COLLECTION].find_one({"_id": object_id})


async def create_user(database: AsyncIOMotorDatabase, email: str, hashed_password: str) -> dict:
    document = user_document(email.lower(), hashed_password)
    result = await database[USERS_COLLECTION].insert_one(document)
    document["_id"] = result.inserted_id
    return document


async def touch_user(database: AsyncIOMotorDatabase, user_id: str) -> None:
    object_id = as_object_id(user_id)
    if object_id is not None:
        await database[USERS_COLLECTION].update_one(
            {"_id": object_id}, {"$set": {"updated_at": datetime.now(timezone.utc)}}
        )