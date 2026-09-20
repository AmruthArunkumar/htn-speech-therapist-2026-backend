"""Pydantic models shared across the speech analysis pipeline."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PrimaryFocus = Literal[
    "fillers",
    "pacing",
    "pauses",
    "repetition",
    "sentence_length",
    "confidence",
]


class WordTiming(BaseModel):
    """A single token from Scribe, trimmed to what the analyser needs."""

    text: str
    start: float | None = None
    end: float | None = None
    type: str = "word"


class FillerHit(BaseModel):
    text: str
    start: float | None = None


class PauseHit(BaseModel):
    after_word: str
    start: float
    duration: float


class SpeechMetrics(BaseModel):
    """Deterministic measurements of *how* someone spoke. No LLM involved."""

    duration_s: float
    word_count: int
    wpm: float | None = None
    articulation_rate: float | None = None
    speech_ratio: float | None = None
    hard_fillers: list[FillerHit] = Field(default_factory=list)
    soft_fillers: list[FillerHit] = Field(default_factory=list)
    long_pauses: list[PauseHit] = Field(default_factory=list)
    mid_pauses: int = 0
    repetitions: list[str] = Field(default_factory=list)
    longest_fluent_run_s: float | None = None
    avg_words_per_sentence: float | None = None
    audio_events: list[str] = Field(default_factory=list)


class Observation(BaseModel):
    pattern: str
    evidence: str
    why_it_matters: str


class CoachFeedback(BaseModel):
    """The coaching turn. Doubles as the Gemini structured-output schema."""

    encouragement: str
    primary_focus: PrimaryFocus
    coaching_cue: str
    observations: list[Observation]
    try_this_next: str


class SpeechAnalysisResponse(BaseModel):
    transcript: str
    metrics: SpeechMetrics
    feedback: CoachFeedback
    audio_base64: str | None = None
    timings_ms: dict[str, int] = Field(default_factory=dict)
