# htn-speech-therapist-2026-backend
the backend for https://github.com/issarmank/htn-speech-therapist-2026

## Development

The API uses FastAPI, MongoDB, and bearer JWT authentication.

1. Install dependencies with `pip install -r requirements.txt` (or
   `requirements-dev.txt` for the mic demo and tests).
2. Copy `.env.example` to `.env`, set a strong `JWT_SECRET_KEY`, and add your
   `ELEVENLABS_API_KEY` and `GEMINI_API_KEY`.
3. Start MongoDB, then run `uvicorn main:app --reload`.

MongoDB is only needed for the auth routes. If it is unreachable the API still
starts and the speech pipeline works, since that pipeline is stateless.

Authentication endpoints:

- `POST /auth/register` with `{ "email": "...", "password": "..." }`
- `POST /auth/login` with form fields `username` and `password`
- `GET /auth/me` with an `Authorization: Bearer <token>` header

## Speech coaching pipeline

`POST /api/v1/speech/analyze` takes a recording and returns coaching on *how*
the person spoke. Multipart fields: `audio` (required), `context` (optional free
text, e.g. "practising a job interview answer"). Query: `?speak=true` also
returns the coaching cue as base64 mp3.

The pipeline is:

| Stage | Module | What it does |
| --- | --- | --- |
| Transcribe | `speech/stt.py` | ElevenLabs Scribe v2, word-level timestamps |
| Measure | `speech/metrics.py` | Pure Python: pace, fillers, pauses, repetitions |
| Coach | `speech/coach.py` | Gemini, structured output, one focus per turn |
| Speak | `speech/tts.py` | ElevenLabs TTS, optional |

All scoring is deterministic Python. Gemini only *explains* numbers it is
handed, so feedback stays reproducible and the model cannot invent statistics.
`speech/metrics.py` has no network calls, so `tests/test_metrics.py` runs
without any API key.

Try it from your mic:

```bash
uvicorn main:app --reload           # in one terminal
python scripts/mic_demo.py          # in another; Enter to start, Enter to stop
python scripts/mic_demo.py --speak --context "job interview practice"
python scripts/mic_demo.py --file some_recording.wav
```

Error codes are returned as `{"detail": {"code": ..., "message": ...}}`:
`AUDIO_TOO_SHORT`, `AUDIO_TOO_LONG`, `AUDIO_UNRECOGNIZED` (422/413), and
`ASSESSMENT_UNAVAILABLE` (503, transcription only). If Gemini is unavailable
the request still succeeds with the transcript, the metrics, and a fixed
fallback cue - the coach never fails the request.

Gemini Flash returns transient `503 UNAVAILABLE` on a few percent of calls
under load. The client retries those in place with backoff before downgrading
to `GEMINI_FALLBACK_MODEL`; `429` skips the retry and switches model at once,
because free-tier quota is per-day-per-model and backoff cannot clear it.
