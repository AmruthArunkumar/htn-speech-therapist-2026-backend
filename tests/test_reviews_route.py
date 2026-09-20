"""/reviews: history is scoped to the caller, and playback URLs are signed late."""

ENDPOINT = "/api/v1/speech/reviews"
CLIP = {"audio": ("recording.m4a", b"RIFFfake-audio-bytes", "audio/mp4")}


def test_history_requires_a_token(anonymous_client):
    assert anonymous_client.get(ENDPOINT).status_code == 401


def test_history_returns_saved_reviews(client, no_s3):
    client.post("/api/v1/speech/analyze", files=CLIP, data={"context": "standup"})

    rows = client.get(ENDPOINT).json()

    assert len(rows) == 1
    assert rows[0]["transcript"] == "um so I think it went well"
    assert rows[0]["context"] == "standup"
    # ObjectId is not JSON; the service layer has to stringify these.
    assert isinstance(rows[0]["_id"], str)
    assert isinstance(rows[0]["user_id"], str)


def test_playback_url_is_signed_from_the_stored_key(client, s3_bucket):
    """The URL is generated per request - storing one would bake in its expiry."""
    fake = s3_bucket()
    client.post("/api/v1/speech/analyze", files=CLIP)

    row = client.get(ENDPOINT).json()[0]

    operation, params, expires = fake.presigned[0]
    assert operation == "get_object"
    assert params["Key"] == row["audio"]["key"]
    assert params["Bucket"] == "htn-speech-clips"
    assert expires == 3600
    assert row["audio_url"].startswith("https://htn-speech-clips.s3")


def test_rows_without_audio_carry_no_playback_url(client, no_s3):
    """Reviews saved before S3 was enabled, or when an upload failed."""
    client.post("/api/v1/speech/analyze", files=CLIP)

    row = client.get(ENDPOINT).json()[0]

    assert row["audio"] is None
    assert "audio_url" not in row


def test_limit_is_bounded(client, no_s3):
    """An unbounded limit is an easy way to ask for the whole collection."""
    assert client.get(ENDPOINT, params={"limit": 101}).status_code == 422
    assert client.get(ENDPOINT, params={"limit": 0}).status_code == 422
    assert client.get(ENDPOINT, params={"limit": 100}).status_code == 200
