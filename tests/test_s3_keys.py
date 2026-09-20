"""Object keys are built from user input, so they are pinned down here.

Phones send whatever filename they like; none of it should survive into a key
unexamined.
"""

import pytest

from storage.s3 import DEFAULT_SUFFIX, build_key, is_configured

USER = "652f1a2b3c4d5e6f7a8b9c0d"


def test_key_is_namespaced_by_user(s3_bucket):
    s3_bucket()
    assert build_key(USER, "clip.wav").startswith(f"speech-attempts/{USER}/")


def test_same_filename_twice_never_collides(s3_bucket):
    """Phones send 'recording.wav' every time; a collision is a silent overwrite."""
    s3_bucket()
    assert build_key(USER, "recording.wav") != build_key(USER, "recording.wav")


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("clip.wav", ".wav"),
        ("clip.mp3", ".mp3"),
        ("clip.m4a", ".m4a"),
        ("clip.webm", ".webm"),
        ("clip.M4A", ".m4a"),  # normalised, so keys stay predictable
    ],
)
def test_recognised_audio_suffixes_are_kept(s3_bucket, filename, expected):
    s3_bucket()
    assert build_key(USER, filename).endswith(expected)


@pytest.mark.parametrize(
    "filename",
    [
        "noextension",
        "clip.exe",
        "clip.php",
        "../../etc/passwd",
        "clip.wav.exe",
        "",
    ],
)
def test_unrecognised_or_hostile_names_fall_back(s3_bucket, filename):
    """Nothing user-controlled reaches the key but a suffix from the allowlist."""
    s3_bucket()
    key = build_key(USER, filename)

    assert key.endswith(DEFAULT_SUFFIX)
    assert key.count("/") == 2, f"key gained a path segment: {key}"
    assert ".." not in key


def test_unconfigured_without_a_bucket(no_s3):
    assert is_configured() is False


def test_configured_with_a_bucket(s3_bucket):
    s3_bucket()
    assert is_configured() is True
