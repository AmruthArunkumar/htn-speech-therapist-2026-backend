# VocalCraft AI — Backend Specification

**Repository:** `htn-speech-therapist-2026-backend`  
**Frontend contract:** `htn-speech-therapist-2026/docs/frontend-specification.md`

## 1. Responsibility

The backend turns a completed clip into a display-ready result. It owns all provider keys, scoring, persistence, coaching prompts, and provider fallbacks.

```text
Audio + server prompt → validate → assess/transcribe → normalize
→ select one focus issue → generate coach cue → synthesize voice
→ persist and return result
```

The frontend must never calculate pronunciation accuracy or receive Azure, OpenAI, or ElevenLabs credentials.

## 2. Modules

| Module | Responsibility |
| --- | --- |
| `sessions` | Session lifecycle, ownership, and current scenario intent. |
| `prompts` | Server-owned `/r/` prompts, target words/phonemes, Coffee Shop intent graph. |
| `audio_validation` | MIME, decoded duration, size, silence, and quality flags. |
| `azure_assessment` | ClearSpeak pronunciation assessment adapter. |
| `transcription` | OpenAI Audio Transcription adapter for roleplay. |
| `metrics` | VAD, WPM, fillers, long pauses, optional pitch range, Conversation Flow. |
| `assessment_parser` | Provider JSON → stable aggregate, word, and phoneme objects. |
| `focus_selector` | Choose exactly one useful correction. |
| `coach` | Schema-constrained LLM copy and fixed fallback. |
| `voice` | ElevenLabs Realtime TTS and short-lived playback URL. |
| `achievements` | Pair comparable attempts for Before → After. |

## 3. API

Base path: `/api/v1`. Every protected endpoint derives user identity from the token; it never accepts a client `user_id`.

### `POST /sessions`

```json
{ "mission": "clear_speak_r" }
```

```json
{
  "session_id": "uuid",
  "mode": "clear_speak",
  "prompts": [{ "id": "r-04", "reference_text": "Red robin runs rapidly.", "sequence_no": 4 }]
}
```

### `POST /attempts/assess`

Multipart fields: `audio`, `session_id`, `prompt_id`, `idempotency_key`.

1. Verify active session and mission prompt.
2. Validate actual decoded file duration (max 20 seconds), size, and speech signal.
3. Resolve reference text exclusively from `prompt_id`.
4. Call Azure at phoneme granularity with comprehensive/prosody settings.
5. Normalize, select focus, generate coach copy/audio, and persist the result.
6. Return the `DrillAttemptResult` contract defined in the frontend specification.

### `POST /attempts/flow`

Multipart fields: `audio`, `session_id`, `intent_id`, `stress_level`, `idempotency_key`.

1. Verify the active finite Coffee Shop intent.
2. Transcribe, calculate Flow signals, and select the next allowed intent.
3. Generate an approved coach response and TTS audio.
4. Return `FlowAttemptResult` as defined by the frontend spec.

### `POST /sessions/{session_id}/complete`

Idempotently ends the session and returns a valid achievement pair.

```json
{
  "snapshot": {
    "metric": "target_word_accuracy",
    "first_attempt_id": "uuid",
    "best_attempt_id": "uuid",
    "before_value": 61,
    "after_value": 84,
    "headline": "Your R clarity improved"
  }
}
```

## 4. ClearSpeak scoring

### Azure request configuration

For scripted drills only:

- `reference_text` comes from the server-owned prompt.
- Azure Speech SDK uses `PronunciationAssessmentGranularity.Phoneme`.
- Comprehensive assessment and prosody are enabled when available.
- Locale is `en-US` for the MVP.
- Retain the raw Azure assessment JSON without credentials for fixture tests and traceability.

### Normalized response

```json
{
  "clear_speak": {
    "overall": 84,
    "accuracy": 86,
    "fluency": 81,
    "completeness": 100,
    "prosody": 77,
    "label": "Practice feedback"
  },
  "word_feedback": [{
    "word": "rapidly",
    "word_index": 3,
    "status": "retry",
    "accuracy": 61,
    "error_type": "Mispronunciation",
    "phonemes": [{ "symbol": "r", "accuracy": 61 }]
  }]
}
```

Rules:

- `overall` is Azure `PronScore`; do not invent weighting.
- Missing score components stay `null`, never `0`.
- A word is `retry` for mispronunciation/error or a target phoneme below 70.
- A valid unflagged word is `nailed_it`; unsupported feedback is `unavailable`.
- No valid recognition result means `AUDIO_UNRECOGNIZED`, not a scored attempt.

## 5. Roleplay and Conversation Flow

| Signal | Calculation |
| --- | --- |
| Transcript | OpenAI Audio Transcription; analysis input only. |
| Active speech | Sum VAD voiced spans, require ≥1 second. |
| WPM | Recognized words ÷ active speech seconds × 60. |
| Fillers | Normalized `um`, `uh`, `like`, `you know` matches. |
| Long pauses | Internal voiced-to-voiced VAD gap ≥1.5s. |
| Pitch range | Optional p95 minus p05 voiced F0, display-only. |

```text
flow = 0.45 × pace_band_score
     + 0.35 × (100 - min(100, 8 × fillers + 15 × long_pauses))
     + 0.20 × prosody_score_if_available
```

Reweight available components to 100. Calm pace band is 105–145 WPM; Busy is 115–160 WPM. `pace_band_score` is 100 in-band and declines linearly to zero 50 WPM beyond a boundary.

Flow is never described as a pronunciation score, articulation accuracy, stuttering detection, or diagnosis.

## 6. Focus and coaching

### FocusSelector precedence

ClearSpeak: target phoneme below 70 → word mispronunciation → unexpected/missing break → lowest valid word score → celebration.

Flow: long pauses → pace outside band → fillers → prosody signal → celebration.

Return only normalized facts:

```json
{ "focus_type": "target_phoneme", "word": "rapidly", "phoneme": "r", "value": 61 }
```

### Coach response schema

```json
{
  "encouragement": "3–14 words",
  "one_coaching_cue": "5–22 words, tied to focus",
  "next_prompt": "approved prompt or scenario intent",
  "visual_label": "nailed_it | try_again | keep_flowing"
}
```

The LLM may only discuss the supplied facts. It gives one correction, never diagnoses or prescribes. Malformed/unsafe output falls back to: “Nice work. Let’s try that once more at a comfortable pace.”

## 7. Coach voice

- The backend owns the ElevenLabs key and voice ID.
- Send validated short coach text through the Realtime TTS WebSocket with `eleven_flash_v2_5` and `flush: true`.
- Return a relayed stream or short-lived signed audio URL.
- On TTS failure, persist the cue and return `TTS_UNAVAILABLE`; the client still displays text.

## 8. Persistence

| Table | Key fields |
| --- | --- |
| `practice_sessions` | user, mission, mode, scenario, stress level, status, timestamps |
| `practice_prompts` | module, reference text, target words/phonemes, sequence |
| `practice_attempts` | session, prompt, sequence, transcript, duration, status, idempotency key |
| `assessment_results` | Azure scores, Flow score, raw signals, quality flags, provider payload |
| `word_feedback` | attempt, word/index, status, accuracy, error type, phonemes |
| `coach_turns` | attempt, encouragement, cue, next prompt, audio key, fallback flag |
| `achievement_snapshots` | session, first/best attempt, metric, values, headline |

Unique `(session_id, idempotency_key)` prevents duplicate upload processing. Numeric scores are nullable or `0..100`. Retained audio is private and short-lived.

## 9. Failure and performance policy

| Code | Behaviour |
| --- | --- |
| `AUDIO_TOO_SHORT` | Reject before provider call; invite a full phrase. |
| `AUDIO_TOO_LONG` | Reject decoded clip beyond 20 seconds. |
| `AUDIO_UNRECOGNIZED` | Mark unscored; do not fabricate metrics. |
| `ASSESSMENT_UNAVAILABLE` | Retryable provider error with request ID. |
| `TTS_UNAVAILABLE` | Valid coach text, no audio. |
| `INVALID_SESSION_STATE` | `409`; do not advance roleplay. |

Targets after user stop: assessment/transcription p50 <1.0s, coaching <400ms, TTS first audio <500ms, full result <1.5s.

## 10. Demo fixture mode

- Seed `/r/` prompts plus two labelled attempts: `first_attempt_61` and `best_attempt_84`.
- Pre-generate matching coach audio.
- Enable only through server-side `DEMO_FIXTURE_MODE`; never mix a fixture with a live provider result.
- Rehearse Azure and TTS outage paths.

## 11. Tests and order of work

Test Azure fixture parsing, VAD/WPM/filler/pause boundaries, score reweighting, focus precedence, Coach JSON validation, auth/session ownership, input validation, idempotency, and provider fallbacks.

Build order:

1. FastAPI scaffold, settings, Supabase schema, health route.
2. Seed prompts/session lifecycle and Azure adapter/parser fixtures.
3. ClearSpeak endpoint, persistence, idempotency, normalized word feedback.
4. FocusSelector, Coach schema/fallback, ElevenLabs adapter.
5. Roleplay transcript/Flow pipeline and Coffee Shop intent graph.
6. Achievement pairing, fixture mode, latency/error rehearsal.
