"""Raw practice clips in S3. Mongo stores the key; the bytes live here.

boto3 is synchronous, so every call it makes is pushed onto a worker thread.
Calling it directly from a coroutine would block the event loop for the whole
upload and stall every other in-flight request, not just this one.
"""

import logging
import uuid
from pathlib import PurePosixPath

from fastapi.concurrency import run_in_threadpool

from database.config import get_settings
from database.models import audio_ref

logger = logging.getLogger(__name__)

# Suffix taken from the upload only if we recognise it: phones send arbitrary
# names, and the key should never carry user-controlled junk.
ALLOWED_SUFFIXES = {".wav", ".mp3", ".m4a", ".mp4", ".aac", ".ogg", ".opus", ".webm", ".flac"}
DEFAULT_SUFFIX = ".wav"

_client = None


def is_configured() -> bool:
    """False when no bucket is set, which is how local dev runs without AWS."""
    return bool(get_settings().s3_bucket)


def _get_client():
    """Built once and reused; each boto3 client opens its own connection pool."""
    global _client
    if _client is None:
        import boto3  # imported lazily so the app still starts without it

        settings = get_settings()
        _client = boto3.client(
            "s3",
            region_name=settings.s3_region,
            # None hands control back to boto3's credential chain.
            aws_access_key_id=settings.aws_access_key_id or None,
            aws_secret_access_key=settings.aws_secret_access_key or None,
        )
    return _client


def build_key(user_id: str, filename: str) -> str:
    """`<prefix>/<user_id>/<uuid><ext>`.

    A UUID rather than the uploaded name: phones send "recording.wav" every
    time, so names collide and would silently overwrite each other. The
    user_id prefix makes listing or deleting one user's clips a single
    prefix operation.
    """
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        suffix = DEFAULT_SUFFIX
    prefix = get_settings().s3_key_prefix.strip("/")
    return f"{prefix}/{user_id}/{uuid.uuid4().hex}{suffix}"


async def upload_audio(
    user_id: str,
    payload: bytes,
    filename: str,
    content_type: str | None = None,
    duration_s: float | None = None,
) -> dict | None:
    """Store one clip and return an audio_ref for the review document.

    Returns None if S3 is not configured or the upload fails; the caller
    saves the review without audio rather than losing it entirely.
    """
    if not is_configured():
        return None

    settings = get_settings()
    key = build_key(user_id, filename)
    # Wrong or missing type makes browsers download the file instead of
    # playing it, which breaks playback from a presigned URL.
    resolved_type = content_type or "application/octet-stream"

    try:
        await run_in_threadpool(
            _get_client().put_object,
            Bucket=settings.s3_bucket,
            Key=key,
            Body=payload,
            ContentType=resolved_type,
        )
    except Exception:  # noqa: BLE001
        logger.warning("S3 upload failed for user %s", user_id, exc_info=True)
        return None

    return audio_ref(
        bucket=settings.s3_bucket,
        key=key,
        content_type=resolved_type,
        size_bytes=len(payload),
        duration_s=duration_s,
    )


async def presign_get(key: str, bucket: str | None = None) -> str | None:
    """Time-limited playback URL, generated per request.

    Signed locally from the credentials - no call to AWS - so this is cheap
    enough to do for every row in a history response. Never store the result:
    it expires, which is why the document keeps the key instead.
    """
    if not is_configured():
        return None

    settings = get_settings()
    try:
        return await run_in_threadpool(
            _get_client().generate_presigned_url,
            "get_object",
            Params={"Bucket": bucket or settings.s3_bucket, "Key": key},
            ExpiresIn=settings.s3_url_expiry_s,
        )
    except Exception:  # noqa: BLE001
        logger.warning("Failed to presign %s", key, exc_info=True)
        return None
