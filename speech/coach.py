"""Gemini turns measurements into coaching. It explains numbers, never invents them."""

from __future__ import annotations

import json
import logging
from functools import lru_cache

from google import genai
from google.genai import errors, types

from database.config import get_settings
from speech.schemas import CoachFeedback, Observation, SpeechMetrics

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """\
You are a warm, practical speech coach helping someone build confidence and \
fluency in everyday conversation. You are not a clinician.

Rules:
- Only reference facts present in the supplied metrics and transcript. Never \
invent or estimate a number. If a metric is null, it was not measurable - do \
not guess at it.
- Choose exactly ONE primary_focus. People change one habit at a time; a list \
of five problems changes nothing.
- coaching_cue is 5-25 words, phrased as something they can do in their very \
next sentence, and must sound natural read aloud.
- Coach HOW they spoke (pace, pauses, fillers, restarts), never WHAT they said. \
Do not comment on their opinions, choices, or the content of their story.
- Never diagnose. Do not use words like stutter, dysfluency, disorder, \
impairment, or any clinical label, even if the pattern suggests one. Coach the \
pacing and, where it genuinely matters, suggest a speech-language professional \
as a positive next step.
- Weigh soft fillers (like, so, actually, you know) by rate, not raw count - \
they are ordinary words and are often used legitimately. Hard fillers (um, uh, \
er) are hesitation sounds and always count.
- If the metrics are already clean, say so and celebrate it. Do not manufacture \
a problem to have something to fix.
- Address the speaker as "you". Be specific and kind, never clinical or gushing.

Reference bands: comfortable conversational pace is roughly 120-160 words per \
minute. A pause of 1.5s or longer reads as a stall to a listener; shorter \
pauses are good rhythm and worth praising."""

FALLBACK = CoachFeedback(
    encouragement="Thanks for practising - showing up is the part that counts.",
    primary_focus="confidence",
    coaching_cue="Nice work. Let's try that once more at a comfortable pace.",
    observations=[
        Observation(
            pattern="Coaching unavailable",
            evidence="The coaching model could not be reached for this attempt.",
            why_it_matters="Your transcript and measurements below are still accurate.",
        )
    ],
    try_this_next="Record the same answer again and compare your pace and pauses.",
)


# Server-side blips worth waiting out. Deliberately NOT the SDK default set,
# which also retries 429: the free-tier quota is per-day-per-model, so a 429
# comes back with a retryDelay of ~27s and will still be there after our
# backoff. Retrying it just adds seconds to every request for the rest of the
# day. Quota is per-model, so the fallback has its own budget - switching
# models beats waiting.
_RETRY_STATUS_CODES = [408, 500, 502, 503, 504]


# The SDK ships with retries OFF (stop_after_attempt(1)), so without this every
# transient 503 is fatal on the first try.
@lru_cache
def _client() -> genai.Client:
    settings = get_settings()
    return genai.Client(
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(
            timeout=int(settings.gemini_timeout_s * 1000),
            retry_options=types.HttpRetryOptions(
                attempts=settings.gemini_retry_attempts,
                initial_delay=settings.gemini_retry_initial_delay,
                max_delay=settings.gemini_retry_max_delay,
                http_status_codes=_RETRY_STATUS_CODES,
            ),
        ),
    )


# A different model cannot fix a bad key, a malformed request, or a blocked
# prompt - only a code or config change can. Fail fast instead of burning the
# fallback and reporting a capacity problem we do not have.
_CONFIG_ERROR_CODES = frozenset({400, 401, 403})


def _is_config_error(exc: Exception) -> bool:
    return isinstance(exc, errors.APIError) and exc.code in _CONFIG_ERROR_CODES


def build_prompt(
    transcript: str, metrics: SpeechMetrics, context: str | None
) -> str:
    facts = metrics.model_dump()
    parts = []
    if context:
        parts.append(f"What they were practising: {context}")
    parts.append(f"Transcript:\n{transcript}")
    parts.append(f"Measured facts (JSON):\n{json.dumps(facts, indent=2)}")
    parts.append(
        "Give this speaker their coaching turn based only on the facts above."
    )
    return "\n\n".join(parts)


def _generate(model: str, prompt: str) -> CoachFeedback:
    settings = get_settings()
    response = _client().models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=CoachFeedback,
            temperature=0.7,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
            thinking_config=types.ThinkingConfig(
                thinking_budget=settings.gemini_thinking_budget
            ),
        ),
    )
    parsed = response.parsed
    if isinstance(parsed, CoachFeedback):
        return parsed
    return CoachFeedback.model_validate_json(response.text)


def generate_feedback(
    transcript: str, metrics: SpeechMetrics, context: str | None = None
) -> CoachFeedback:
    """Produce a coaching turn. Falls back rather than failing the request."""
    settings = get_settings()
    prompt = build_prompt(transcript, metrics, context)

    # The newest Flash model periodically returns 503 under load. _client()
    # retries that in place; the fallback model is for when it stays down.
    candidates = [settings.gemini_model]
    if settings.gemini_fallback_model != settings.gemini_model:
        candidates.append(settings.gemini_fallback_model)

    for model in candidates:
        try:
            return _generate(model, prompt)
        except Exception as exc:  # noqa: BLE001 - never fail the coaching turn
            if _is_config_error(exc):
                logger.error(
                    "Gemini rejected the request on %s (HTTP %s) - this is a "
                    "config or prompt bug, not capacity; not trying %s",
                    model,
                    exc.code,
                    " or ".join(candidates[candidates.index(model) + 1 :])
                    or "another model",
                    exc_info=True,
                )
                break
            code = getattr(exc, "code", None)
            if code == 429:
                logger.warning(
                    "Gemini quota exhausted on %s; switching model immediately "
                    "(quota is per-model, so waiting would not help)",
                    model,
                )
            else:
                logger.warning(
                    "Gemini coaching failed on %s%s; falling through",
                    model,
                    f" (HTTP {code})" if code else "",
                    exc_info=True,
                )

    logger.error("All coaching models failed; returning canned fallback")
    return FALLBACK
