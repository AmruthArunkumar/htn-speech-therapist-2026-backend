"""Speech analysis endpoint - the surface the Expo app calls."""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status

from database.service import list_speech_reviews, save_speech_review
from speech.pipeline import (
    AudioTooLong,
    AudioTooShort,
    AudioUnrecognized,
    analyze_speech,
)
from speech.schemas import SpeechAnalysisResponse
from speech.stt import SttUnavailable
from storage.s3 import presign_get, upload_audio

from .dependencies import CurrentUser, Database

logger = logging.getLogger(__name__)

# Safety net against absurd uploads; the real limit is settings.max_audio_seconds,
# enforced on the decoded duration after transcription.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

router = APIRouter(prefix="/api/v1/speech", tags=["speech"])


def _error(code: str, message: str, http_status: int) -> HTTPException:
    return HTTPException(
        status_code=http_status, detail={"code": code, "message": message}
    )


@router.post("/analyze", response_model=SpeechAnalysisResponse)
async def analyze(
    current_user: CurrentUser,
    database: Database,
    audio: UploadFile = File(...),
    context: str | None = Form(None),
    speak: bool = Query(False, description="Also return the cue as synthesized mp3"),
) -> SpeechAnalysisResponse:
    """Transcribe a clip, measure how it was spoken, and return coaching."""
    payload = await audio.read()

    if not payload:
        raise _error(
            "AUDIO_TOO_SHORT", "No audio received.", status.HTTP_422_UNPROCESSABLE_ENTITY
        )
    if len(payload) > MAX_UPLOAD_BYTES:
        raise _error(
            "AUDIO_TOO_LONG",
            f"Upload exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB.",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )

    try:
        result = await analyze_speech(
            audio=payload,
            filename=audio.filename or "recording.wav",
            context=context,
            speak=speak,
        )
    except AudioTooShort as exc:
        raise _error(
            "AUDIO_TOO_SHORT",
            f"Not enough speech to analyse ({exc}). Try speaking for a few seconds.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        ) from exc
    except AudioTooLong as exc:
        raise _error(
            "AUDIO_TOO_LONG",
            f"Recording is too long ({exc}).",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        ) from exc
    except AudioUnrecognized as exc:
        raise _error(
            "AUDIO_UNRECOGNIZED",
            "No speech was detected in that recording.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        ) from exc
    except SttUnavailable as exc:
        raise _error(
            "ASSESSMENT_UNAVAILABLE",
            "Transcription is temporarily unavailable.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc

    user_id = str(current_user["_id"])

    # Upload before the write, so a saved review never points at a clip that
    # is not there. The reverse orphan - an object with no review - is
    # harmless and a lifecycle rule sweeps it.
    audio_ref = await upload_audio(
        user_id=user_id,
        payload=payload,
        filename=audio.filename or "recording.wav",
        content_type=audio.content_type,
        duration_s=result.metrics.duration_s,
    )

    # The coaching already succeeded, so neither a failed upload nor a dead
    # database costs the user their feedback. A failed upload still saves the
    # review, just without playback. Same trade-off main.py makes when it
    # starts with Mongo unreachable.
    try:
        await save_speech_review(
            database,
            user_id=user_id,
            transcript=result.transcript,
            metrics=result.metrics.model_dump(),
            feedback=result.feedback.model_dump(),
            context=context,
            audio=audio_ref,
        )
    except Exception:  # noqa: BLE001
        logger.warning("Failed to save speech review", exc_info=True)

    return result


@router.get("/reviews")
async def reviews(
    current_user: CurrentUser,
    database: Database,
    limit: int = Query(20, ge=1, le=100),
) -> list[dict]:
    """Past attempts for the signed-in user, newest first.

    Playback URLs are signed here rather than stored: they expire, and the
    bucket stays private.
    """
    rows = await list_speech_reviews(database, str(current_user["_id"]), limit)
    for row in rows:
        stored = row.get("audio")
        if stored and stored.get("key"):
            row["audio_url"] = await presign_get(stored["key"], stored.get("bucket"))
    return rows
