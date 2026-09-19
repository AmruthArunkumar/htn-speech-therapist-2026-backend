from datetime import datetime, timezone

from bson import ObjectId


def user_document(email: str, hashed_password: str) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "email": email,
        "hashed_password": hashed_password,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }


def user_response(document: dict) -> dict:
    return {
        "id": str(document["_id"]),
        "email": document["email"],
        "is_active": document.get("is_active", True),
    }


def as_object_id(value: str) -> ObjectId | None:
    if not ObjectId.is_valid(value):
        return None
    return ObjectId(value)