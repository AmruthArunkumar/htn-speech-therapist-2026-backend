"""/analyze persistence: who owns a review, and what survives a failure.

The handler does three things after the coaching succeeds - upload the clip,
write the review, return the feedback - and the ordering and failure handling
between them is the part worth pinning down.
"""

import storage.s3 as s3
from conftest import USER_ID, FakeS3

ENDPOINT = "/api/v1/speech/analyze"
CLIP = {"audio": ("recording.m4a", b"RIFFfake-audio-bytes", "audio/mp4")}


def post_clip(client, **kwargs):
    return client.post(ENDPOINT, files=CLIP, **kwargs)


def test_analyze_rejects_callers_without_a_token(anonymous_client):
    """Unauthenticated traffic must not reach ElevenLabs or Gemini."""
    assert anonymous_client.post(ENDPOINT, files=CLIP).status_code == 401


def test_analyze_rejects_a_forged_token(anonymous_client):
    response = anonymous_client.post(
        ENDPOINT, files=CLIP, headers={"Authorization": "Bearer not.a.real.token"}
    )
    assert response.status_code == 401


def test_review_is_owned_by_the_authenticated_user(client, saved, no_s3):
    """The owner comes from the token, never from anything the client sends."""
    assert post_clip(client, data={"user_id": str(USER_ID)[::-1]}).status_code == 200

    assert len(saved) == 1
    assert saved[0]["user_id"] == USER_ID


def test_review_captures_the_transcript_metrics_and_coaching(client, saved, no_s3):
    assert post_clip(client, data={"context": "interview practice"}).status_code == 200

    review = saved[0]
    assert review["transcript"] == "um so I think it went well"
    assert review["context"] == "interview practice"
    assert review["metrics"]["word_count"] == 7
    assert review["feedback"]["primary_focus"] == "fillers"
    assert review["created_at"] is not None


def test_upload_happens_before_the_review_is_written(client, saved, s3_bucket):
    """A stored review must never point at a clip that is not in the bucket."""
    fake = s3_bucket()
    assert post_clip(client).status_code == 200

    assert len(fake.puts) == 1
    assert saved[0]["audio"]["key"] == fake.puts[0]["Key"]


def test_clip_is_uploaded_under_the_users_own_prefix(client, saved, s3_bucket):
    fake = s3_bucket()
    post_clip(client)

    put = fake.puts[0]
    assert put["Bucket"] == "htn-speech-clips"
    assert put["Key"].startswith(f"speech-attempts/{USER_ID}/")
    assert put["Body"] == b"RIFFfake-audio-bytes"
    # A wrong type makes browsers download the clip instead of playing it.
    assert put["ContentType"] == "audio/mp4"


def test_boto3_runs_off_the_event_loop(client, s3_bucket, loop_thread):
    """boto3 is synchronous: on the loop it stalls every concurrent request.

    Compared against the thread the handler itself ran on - TestClient does
    not drive the loop from MainThread, so that would prove nothing.
    """
    fake = s3_bucket()
    post_clip(client)

    assert loop_thread["name"], "never reached the handler"
    assert fake.puts[0]["_thread"] != loop_thread["name"]


def test_review_stores_the_key_and_never_a_url(client, saved, s3_bucket):
    """URLs expire; the key is what makes the row still resolvable next week."""
    s3_bucket()
    post_clip(client)

    audio = saved[0]["audio"]
    assert audio["key"] and audio["bucket"] == "htn-speech-clips"
    assert audio["size_bytes"] == len(b"RIFFfake-audio-bytes")
    assert audio["duration_s"] == 4.25
    assert not any("url" in field for field in audio)


def test_a_failed_upload_still_saves_the_review(client, saved, s3_bucket):
    """Losing playback is survivable; losing the coaching is not."""
    s3_bucket(fail=RuntimeError("AccessDenied"))

    assert post_clip(client).status_code == 200
    assert len(saved) == 1
    assert saved[0]["audio"] is None


def test_nothing_is_uploaded_when_s3_is_unconfigured(client, saved, monkeypatch, no_s3):
    """Local dev runs with no AWS credentials at all."""
    # Spy installed but no bucket set: reaching for a client at all is the bug.
    fake = FakeS3()
    monkeypatch.setattr(s3, "_get_client", lambda: fake)

    post_clip(client)

    assert fake.puts == []
    assert saved[0]["audio"] is None


def test_a_dead_database_does_not_cost_the_user_their_coaching(
    client, db_failure, no_s3
):
    """Same trade-off main.py makes when it starts with Mongo unreachable."""
    db_failure["error"] = ConnectionError("no reachable servers")

    response = post_clip(client)

    assert response.status_code == 200
    assert response.json()["feedback"]["coaching_cue"] == "Pause instead of 'um'."


def test_empty_upload_is_rejected_before_any_work_happens(client, saved, s3_bucket):
    fake = s3_bucket()
    response = client.post(ENDPOINT, files={"audio": ("empty.wav", b"", "audio/wav")})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "AUDIO_TOO_SHORT"
    assert fake.puts == [] and saved == []
