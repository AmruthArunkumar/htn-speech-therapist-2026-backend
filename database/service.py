from __future__ import annotations

from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from .models import as_object_id, speech_review_document, user_document

USERS_COLLECTION = "users"
REVIEWS_COLLECTION = "speech_reviews"


async def ensure_indexes(database: AsyncIOMotorDatabase) -> None:
    await database[USERS_COLLECTION].create_index("email", unique=True)
    await database[REVIEWS_COLLECTION].create_index([("user_id", 1), ("created_at", -1)])


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


async def save_speech_review(
    database: AsyncIOMotorDatabase,
    user_id: str,
    transcript: str,
    metrics: dict,
    feedback: dict,
    context: str | None = None,
    audio: dict | None = None,
) -> str:
    """Store one coaching attempt. Pass `audio` as an audio_ref() once the
    clip has been uploaded to S3; the write should happen after that upload
    succeeds so a review never points at audio that is not there."""
    document = speech_review_document(
        user_id, transcript, metrics, feedback, context, audio
    )
    result = await database[REVIEWS_COLLECTION].insert_one(document)
    return str(result.inserted_id)


async def list_speech_reviews(
    database: AsyncIOMotorDatabase, user_id: str, limit: int = 20
) -> list[dict]:
    object_id = as_object_id(user_id)
    if object_id is None:
        return []
    cursor = (
        database[REVIEWS_COLLECTION]
        .find({"user_id": object_id})
        .sort("created_at", -1)
        .limit(limit)
    )
    return [{**doc, "_id": str(doc["_id"]), "user_id": str(doc["user_id"])} async for doc in cursor]


async def touch_user(database: AsyncIOMotorDatabase, user_id: str) -> None:
    object_id = as_object_id(user_id)
    if object_id is not None:
        await database[USERS_COLLECTION].update_one(
            {"_id": object_id}, {"$set": {"updated_at": datetime.now(timezone.utc)}}
        )