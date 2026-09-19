"""Deterministic speech-pattern measurement.

Pure functions over Scribe word timings: no network, no config, no API key.
Everything the coach says must be traceable to a number produced here.
"""

import re

from speech.schemas import FillerHit, PauseHit, SpeechMetrics, WordTiming

# Pure hesitation sounds. These are always worth surfacing.
HARD_FILLERS: set[str] = {"um", "umm", "uh", "uhh", "er", "erm", "ah", "mm", "hmm"}

# Real words that often act as fillers. Counted separately so the coach can weigh
# them by rate instead of flagging four legitimate uses of "like" as a habit.
SOFT_FILLERS: set[str] = {
    "like",
    "so",
    "right",
    "basically",
    "actually",
    "literally",
    "you know",
    "i mean",
    "sort of",
    "kind of",
}

LONG_PAUSE_S = 1.5
MID_PAUSE_S = 0.5

_MAX_NGRAM = max(len(f.split()) for f in HARD_FILLERS | SOFT_FILLERS)
_PUNCT = re.compile(r"[^\w']+")
_SENTENCE_SPLIT = re.compile(r"[.!?]+")


def normalize(token: str) -> str:
    return _PUNCT.sub("", token.lower()).strip()


def analyze(words: list[WordTiming], transcript: str) -> SpeechMetrics:
    """Measure speech patterns from word-level timings.

    Never raises: sparse or empty input yields a valid model with ``None`` rates
    rather than an error, so the caller decides what counts as unusable audio.
    """
    # "spacing" tokens are whitespace, not speech. Audio events are noted but
    # kept out of every timing calculation.
    spoken = [w for w in words if w.type == "word"]
    audio_events = [w.text for w in words if w.type == "audio_event"]

    timed = [w for w in spoken if w.start is not None and w.end is not None]

    word_count = len(spoken)
    duration_s = round(timed[-1].end - timed[0].start, 3) if timed else 0.0

    wpm: float | None = None
    articulation_rate: float | None = None
    speech_ratio: float | None = None

    if len(timed) >= 2 and duration_s >= 1.0:
        wpm = round(len(timed) / (duration_s / 60), 1)
        articulation = sum(w.end - w.start for w in timed)
        if articulation > 0:
            articulation_rate = round(len(timed) / (articulation / 60), 1)
            speech_ratio = round(min(articulation / duration_s, 1.0), 3)

    hard_fillers, soft_fillers = _find_fillers(spoken)
    long_pauses, mid_pauses = _find_pauses(timed)

    return SpeechMetrics(
        duration_s=duration_s,
        word_count=word_count,
        wpm=wpm,
        articulation_rate=articulation_rate,
        speech_ratio=speech_ratio,
        hard_fillers=hard_fillers,
        soft_fillers=soft_fillers,
        long_pauses=long_pauses,
        mid_pauses=mid_pauses,
        repetitions=_find_repetitions(spoken),
        longest_fluent_run_s=_longest_fluent_run(timed, long_pauses),
        avg_words_per_sentence=_avg_words_per_sentence(transcript),
        audio_events=audio_events,
    )


def _find_fillers(spoken: list[WordTiming]) -> tuple[list[FillerHit], list[FillerHit]]:
    """Longest-match n-gram scan so "you know" never also counts as "know"."""
    hard: list[FillerHit] = []
    soft: list[FillerHit] = []
    tokens = [normalize(w.text) for w in spoken]

    i = 0
    while i < len(tokens):
        for size in range(_MAX_NGRAM, 0, -1):
            if i + size > len(tokens):
                continue
            phrase = " ".join(tokens[i : i + size]).strip()
            if not phrase:
                continue
            if phrase in HARD_FILLERS:
                hard.append(FillerHit(text=phrase, start=spoken[i].start))
                break
            if phrase in SOFT_FILLERS:
                soft.append(FillerHit(text=phrase, start=spoken[i].start))
                break
        else:
            size = 1
        i += size

    return hard, soft


def _find_pauses(timed: list[WordTiming]) -> tuple[list[PauseHit], int]:
    """Voiced-to-voiced gaps. Audio events inside a gap don't break the silence."""
    long_pauses: list[PauseHit] = []
    mid_pauses = 0

    for prev, nxt in zip(timed, timed[1:]):
        gap = nxt.start - prev.end
        if gap >= LONG_PAUSE_S:
            long_pauses.append(
                PauseHit(
                    after_word=prev.text,
                    start=round(prev.end, 3),
                    duration=round(gap, 3),
                )
            )
        elif gap >= MID_PAUSE_S:
            mid_pauses += 1

    return long_pauses, mid_pauses


def _find_repetitions(spoken: list[WordTiming]) -> list[str]:
    """Back-to-back repeats: stumbles ("I I") and restarts ("I want to I want to").

    Exact normalised matching only — fuzzy matching flags natural emphasis.
    """
    tokens = [normalize(w.text) for w in spoken]
    tokens = [t for t in tokens if t]
    found: list[str] = []
    i = 0

    while i < len(tokens):
        # Longest window first, so a 3-word restart isn't reported as a 1-word stumble.
        for size in (3, 2, 1):
            if i + 2 * size > len(tokens):
                continue
            window = tokens[i : i + size]
            if window == tokens[i + size : i + 2 * size]:
                found.append(" ".join(window * 2))
                i += 2 * size
                break
        else:
            i += 1

    return found


def _longest_fluent_run(
    timed: list[WordTiming], long_pauses: list[PauseHit]
) -> float | None:
    """Longest continuous stretch of speech uninterrupted by a long pause."""
    if len(timed) < 2:
        return None

    start = timed[0].start
    end = timed[-1].end
    boundaries = [start]
    for pause in long_pauses:
        boundaries.extend([pause.start, pause.start + pause.duration])
    boundaries.append(end)

    runs = [boundaries[i + 1] - boundaries[i] for i in range(0, len(boundaries) - 1, 2)]
    return round(max(runs), 3) if runs else None


def _avg_words_per_sentence(transcript: str) -> float | None:
    sentences = [s for s in (p.strip() for p in _SENTENCE_SPLIT.split(transcript)) if s]
    if not sentences:
        return None
    return round(sum(len(s.split()) for s in sentences) / len(sentences), 1)
