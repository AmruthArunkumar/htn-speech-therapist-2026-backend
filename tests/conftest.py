"""Fixtures for the route tests: no Mongo, no AWS, no ElevenLabs, no Gemini.

Everything the /analyze handler reaches for is replaced with a fake that
records what it was asked to do, so the tests assert on the handler's own
decisions rather than on a live stack.
"""

import threading

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

import routes.speech as speech_route
import storage.s3 as s3
from database.config import get_settings
from database.database import get_database
from main import app
from routes.dependencies import get_current_user
from speech.schemas import (
    CoachFeedback,
    Observation,
    SpeechAnalysisResponse,
    SpeechMetrics,
)

USER_ID = ObjectId()

COACHING = SpeechAnalysisResponse(
    transcript="um so I think it went well",
    metrics=SpeechMetrics(duration_s=4.25, word_count=7, wpm=98.8),
    feedback=CoachFeedback(
        encouragement="Nice steady finish.",
        primary_focus="fillers",
        coaching_cue="Pause instead of 'um'.",
        observations=[Observation(pattern="filler", evidence="'um' at 0.1s", why_it_matters="breaks flow")],
        try_this_next="Read a paragraph aloud, pausing at commas.",
    ),
)


class FakeCollection:
    """Just enough of a Motor collection for insert_one and the find chain."""

    def __init__(self, rows: list[dict], fail: Exception | None = None):
        self.rows = rows
        self.fail = fail

    async def insert_one(self, document: dict):
        if self.fail is not None:
            raise self.fail
        self.rows.append(document)
        return type("Result", (), {"inserted_id": ObjectId()})()

    def find(self, _query):
        return self

    def sort(self, *_args):
        return self

    def limit(self, _n):
        return self

    def __aiter__(self):
        async def rows():
            for row in self.rows:
                yield {**row, "_id": ObjectId()}

        return rows()


@pytest.fixture
def saved() -> list[dict]:
    """Documents the handler wrote to speech_reviews."""
    return []


@pytest.fixture
def db_failure() -> dict:
    """Set ['error'] to make every insert raise."""
    return {}


@pytest.fixture
def loop_thread() -> dict:
    """Name of the thread the event loop runs on, recorded from inside a handler.

    TestClient runs the loop on its own thread, not MainThread, so a test that
    wants to prove work was pushed off the loop has to compare against this
    rather than against the thread it was collected on.
    """
    return {}


@pytest.fixture
def client(monkeypatch, saved, db_failure, loop_thread):
    """TestClient with auth, the database, and the pipeline stubbed out."""

    class FakeDB:
        def __getitem__(self, _name):
            return FakeCollection(saved, db_failure.get("error"))

    async def fake_db():
        yield FakeDB()

    async def fake_user():
        return {"_id": USER_ID, "email": "speaker@example.com", "is_active": True}

    async def fake_analyze(**_kwargs):
        # Runs inside the handler, so this is the event loop's own thread.
        loop_thread["name"] = threading.current_thread().name
        return COACHING.model_copy(deep=True)

    monkeypatch.setattr(speech_route, "analyze_speech", fake_analyze)
    app.dependency_overrides[get_database] = fake_db
    app.dependency_overrides[get_current_user] = fake_user
    try:
        yield TestClient(app)
    finally:
        # dependency_overrides is module-level state shared by every test.
        app.dependency_overrides.clear()


@pytest.fixture
def anonymous_client():
    """No auth override: exercises the real token dependency."""
    return TestClient(app)


class FakeS3:
    """Records put_object calls, including which thread ran them."""

    def __init__(self, fail: Exception | None = None):
        self.puts: list[dict] = []
        self.presigned: list[tuple] = []
        self.fail = fail

    def put_object(self, **kwargs):
        if self.fail is not None:
            raise self.fail
        kwargs["_thread"] = threading.current_thread().name
        self.puts.append(kwargs)
        return {}

    def generate_presigned_url(self, operation, Params, ExpiresIn):  # noqa: N803
        self.presigned.append((operation, Params, ExpiresIn))
        return (
            f"https://{Params['Bucket']}.s3.amazonaws.com/"
            f"{Params['Key']}?X-Amz-Signature=test"
        )


@pytest.fixture
def s3_bucket(monkeypatch):
    """Configure a bucket and hand back the fake client behind it.

    Returns a callable so a test can install a failing client instead.
    """

    def configure(fail: Exception | None = None) -> FakeS3:
        monkeypatch.setenv("S3_BUCKET", "htn-speech-clips")
        monkeypatch.setenv("S3_REGION", "us-west-2")
        # Settings are lru_cached; the env change is invisible without this.
        get_settings.cache_clear()
        monkeypatch.setattr(get_settings, "cache_clear", get_settings.cache_clear)
        fake = FakeS3(fail)
        monkeypatch.setattr(s3, "_get_client", lambda: fake)
        return fake

    yield configure
    # Later tests must not inherit this bucket.
    get_settings.cache_clear()


@pytest.fixture
def no_s3(monkeypatch):
    """Explicitly unconfigured: the default local-dev posture."""
    monkeypatch.setenv("S3_BUCKET", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
