"""Coach resilience: a transient 503 must not cost the user their coaching turn."""

import logging

import pytest
from google.genai import errors

from speech import coach
from speech.schemas import CoachFeedback, FillerHit, Observation, SpeechMetrics

METRICS = SpeechMetrics(
    duration_s=18.4,
    word_count=41,
    wpm=134.0,
    hard_fillers=[FillerHit(text="um", start=3.1)],
)
TRANSCRIPT = "So um I think the biggest project I worked on was a scheduling tool."

GOOD = CoachFeedback(
    encouragement="Nice steady pace.",
    primary_focus="fillers",
    coaching_cue="Swap that 'um' for a silent breath.",
    observations=[Observation(pattern="p", evidence="e", why_it_matters="w")],
    try_this_next="Run it again.",
)


def api_error(code: int, status: str) -> errors.APIError:
    """Build a real SDK error the way the transport layer would."""
    cls = errors.ClientError if code < 500 else errors.ServerError
    return cls(code, {"error": {"code": code, "status": status, "message": "x"}})


@pytest.fixture
def calls(monkeypatch):
    """Record every (model) _generate is asked for, driven by a scripted queue."""
    seen: list[str] = []

    def install(outcomes: dict[str, object]):
        def fake_generate(model: str, prompt: str) -> CoachFeedback:
            seen.append(model)
            result = outcomes[model]
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(coach, "_generate", fake_generate)
        return seen

    return install


def test_transient_503_on_primary_downgrades_to_fallback(calls):
    settings = coach.get_settings()
    seen = calls(
        {
            settings.gemini_model: api_error(503, "UNAVAILABLE"),
            settings.gemini_fallback_model: GOOD,
        }
    )

    assert coach.generate_feedback(TRANSCRIPT, METRICS) == GOOD
    assert seen == [settings.gemini_model, settings.gemini_fallback_model]


def test_both_models_down_returns_canned_fallback_not_an_error(calls):
    settings = coach.get_settings()
    calls(
        {
            settings.gemini_model: api_error(503, "UNAVAILABLE"),
            settings.gemini_fallback_model: api_error(503, "UNAVAILABLE"),
        }
    )

    # The route has no handler for coach failures - it must never raise.
    assert coach.generate_feedback(TRANSCRIPT, METRICS) == coach.FALLBACK


def test_healthy_primary_never_touches_the_fallback(calls):
    settings = coach.get_settings()
    seen = calls({settings.gemini_model: GOOD})

    assert coach.generate_feedback(TRANSCRIPT, METRICS) == GOOD
    assert seen == [settings.gemini_model]


@pytest.mark.parametrize("code", [400, 401, 403])
def test_config_errors_do_not_burn_the_fallback(calls, caplog, code):
    """A bad key or malformed request is not a capacity problem."""
    settings = coach.get_settings()
    seen = calls(
        {
            settings.gemini_model: api_error(code, "INVALID_ARGUMENT"),
            settings.gemini_fallback_model: GOOD,
        }
    )

    with caplog.at_level(logging.ERROR, logger=coach.__name__):
        assert coach.generate_feedback(TRANSCRIPT, METRICS) == coach.FALLBACK

    assert seen == [settings.gemini_model]
    assert "config or prompt bug" in caplog.text


def test_404_still_tries_the_fallback_model(calls):
    """A retired or misspelled model id is exactly what the fallback is for."""
    settings = coach.get_settings()
    seen = calls(
        {
            settings.gemini_model: api_error(404, "NOT_FOUND"),
            settings.gemini_fallback_model: GOOD,
        }
    )

    assert coach.generate_feedback(TRANSCRIPT, METRICS) == GOOD
    assert seen == [settings.gemini_model, settings.gemini_fallback_model]


def test_client_is_configured_to_retry_transient_codes():
    """Guards the actual root cause: the SDK defaults to zero retries."""
    settings = coach.get_settings()
    coach._client.cache_clear()
    try:
        retry = coach._client()._api_client._http_options.retry_options
    finally:
        coach._client.cache_clear()

    assert retry is not None, "SDK default is stop_after_attempt(1) - no retries"
    assert retry.attempts == settings.gemini_retry_attempts > 1


def test_quota_errors_switch_model_instead_of_waiting(calls, caplog):
    """429 is per-day-per-model; backoff cannot clear it, the fallback can."""
    settings = coach.get_settings()
    seen = calls(
        {
            settings.gemini_model: api_error(429, "RESOURCE_EXHAUSTED"),
            settings.gemini_fallback_model: GOOD,
        }
    )

    with caplog.at_level(logging.WARNING, logger=coach.__name__):
        assert coach.generate_feedback(TRANSCRIPT, METRICS) == GOOD

    assert seen == [settings.gemini_model, settings.gemini_fallback_model]
    assert "quota exhausted" in caplog.text


def test_429_is_not_in_the_retried_status_codes():
    """Retrying a per-day quota error adds latency to every request all day."""
    assert 429 not in coach._RETRY_STATUS_CODES
    assert 503 in coach._RETRY_STATUS_CODES

    coach._client.cache_clear()
    try:
        retry = coach._client()._api_client._http_options.retry_options
    finally:
        coach._client.cache_clear()
    assert retry.http_status_codes == coach._RETRY_STATUS_CODES
