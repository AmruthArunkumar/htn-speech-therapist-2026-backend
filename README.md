# htn-speech-therapist-2026-backend
the backend for https://github.com/issarmank/htn-speech-therapist-2026

## Development

The API uses FastAPI, MongoDB, and bearer JWT authentication.

1. Install dependencies with `pip install -r requirements.txt`.
2. Copy `.env.example` to `.env` and set a strong `JWT_SECRET_KEY`.
3. Start MongoDB, then run `uvicorn main:app --reload`.

Authentication endpoints:

- `POST /auth/register` with `{ "email": "...", "password": "..." }`
- `POST /auth/login` with form fields `username` and `password`
- `GET /auth/me` with an `Authorization: Bearer <token>` header
