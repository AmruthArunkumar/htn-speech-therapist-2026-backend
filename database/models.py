from __future__ import annotations

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


def audio_ref(
    bucket: str,
    key: str,
    content_type: str,
    size_bytes: int,
    duration_s: float | None = None,
) -> dict:
    """Pointer to a clip stored in S3.

    Only the object key is kept. Playback URLs are presigned at read time so
    the bucket stays private; a stored URL would expire or force it public.
    """
    return {
        "bucket": bucket,
        "key": key,
        "content_type": content_type,
        "size_bytes": size_bytes,
        "duration_s": duration_s,
    }


def speech_review_document(
    user_id: str,
    transcript: str,
    metrics: dict,
    feedback: dict,
    context: str | None = None,
    audio: dict | None = None,
) -> dict:
    """One coaching attempt: what was said, how, and the coach's response.

    `audio` is an audio_ref() once clips are uploaded to S3, None until then.
    """
    now = datetime.now(timezone.utc)
    return {
        "user_id": as_object_id(user_id),
        "transcript": transcript,
        "metrics": metrics,
        "feedback": feedback,
        "context": context,
        "audio": audio,
        "created_at": now,
    }


def as_object_id(value: str) -> ObjectId | None:
    if not ObjectId.is_valid(value):
        return None
    return ObjectId(value)