"""Unit tests for the deterministic metrics layer. No network, no API key."""

from speech.metrics import analyze
from speech.schemas import WordTiming


def words(spec: list[tuple[str, float, float]], type_: str = "word") -> list[WordTiming]:
    return [WordTiming(text=t, start=s, end=e, type=type_) for t, s, e in spec]


def steady(tokens: list[str], start: float = 0.0, dur: float = 0.4, gap: float = 0.1):
    """Evenly spaced words, one per `dur + gap` seconds."""
    out = []
    t = start
    for token in tokens:
        out.append(WordTiming(text=token, start=t, end=t + dur, type="word"))
        t += dur + gap
    return out


def test_empty_input_is_valid_and_empty():
    m = analyze([], "")
    assert m.word_count == 0
    assert m.duration_s == 0.0
    assert m.wpm is None
    assert m.longest_fluent_run_s is None
    assert m.avg_words_per_sentence is None


def test_single_word_has_no_rates():
    m = analyze(words([("hello", 0.0, 0.5)]), "Hello.")
    assert m.word_count == 1
    assert m.wpm is None
    assert m.longest_fluent_run_s is None


def test_wpm_is_exact():
    # 20 words, each occupying 0.5s -> 10s span -> 120 wpm.
    ws = steady(["word"] * 20, dur=0.4, gap=0.1)
    m = analyze(ws, " ".join(["word"] * 20) + ".")
    assert m.duration_s == 9.9  # first start to last end
    assert m.wpm == round(20 / (9.9 / 60), 1)


def test_hard_and_soft_fillers_are_separate():
    ws = steady(["um", "I", "uh", "think", "like", "yes", "so"])
    m = analyze(ws, "Um, I uh think like yes so.")
    assert [f.text for f in m.hard_fillers] == ["um", "uh"]
    assert [f.text for f in m.soft_fillers] == ["like", "so"]


def test_multiword_filler_does_not_double_count():
    ws = steady(["it", "was", "you", "know", "fine"])
    m = analyze(ws, "It was, you know, fine.")
    assert [f.text for f in m.soft_fillers] == ["you know"]
    # "know" alone must not also register.
    assert len(m.soft_fillers) == 1


def test_fillers_survive_punctuation_and_case():
    ws = steady(["Um,", "okay.", "Uh!"])
    m = analyze(ws, "Um, okay. Uh!")
    assert [f.text for f in m.hard_fillers] == ["um", "uh"]


def test_long_and_mid_pauses():
    ws = [
        WordTiming(text="one", start=0.0, end=0.5, type="word"),
        WordTiming(text="two", start=2.5, end=3.0, type="word"),  # 2.0s gap -> long
        WordTiming(text="three", start=3.8, end=4.3, type="word"),  # 0.8s -> mid
        WordTiming(text="four", start=4.4, end=4.9, type="word"),  # 0.1s -> neither
    ]
    m = analyze(ws, "One two three four.")
    assert len(m.long_pauses) == 1
    assert m.long_pauses[0].after_word == "one"
    assert m.long_pauses[0].duration == 2.0
    assert m.mid_pauses == 1


def test_audio_event_inside_a_gap_does_not_split_the_pause():
    ws = [
        WordTiming(text="one", start=0.0, end=0.5, type="word"),
        WordTiming(text="(laughter)", start=1.0, end=1.4, type="audio_event"),
        WordTiming(text="two", start=2.5, end=3.0, type="word"),
    ]
    m = analyze(ws, "One two.")
    assert m.word_count == 2
    assert m.audio_events == ["(laughter)"]
    assert len(m.long_pauses) == 1
    assert m.long_pauses[0].duration == 2.0


def test_spacing_tokens_are_ignored():
    ws = [
        WordTiming(text="one", start=0.0, end=0.5, type="word"),
        WordTiming(text=" ", start=0.5, end=0.5, type="spacing"),
        WordTiming(text="two", start=0.6, end=1.1, type="word"),
    ]
    m = analyze(ws, "One two.")
    assert m.word_count == 2


def test_repetitions_single_and_multiword():
    ws = steady(["I", "I", "want", "to", "want", "to", "go"])
    m = analyze(ws, "I I want to want to go.")
    assert "i i" in m.repetitions
    assert "want to want to" in m.repetitions


def test_no_false_repetitions_in_normal_speech():
    ws = steady(["the", "cat", "sat", "on", "the", "mat"])
    m = analyze(ws, "The cat sat on the mat.")
    assert m.repetitions == []


def test_longest_fluent_run_spans_between_pauses():
    ws = [
        WordTiming(text="a", start=0.0, end=0.5, type="word"),
        WordTiming(text="b", start=3.0, end=3.5, type="word"),  # 2.5s pause
        WordTiming(text="c", start=3.6, end=4.1, type="word"),
        WordTiming(text="d", start=4.2, end=8.0, type="word"),
    ]
    m = analyze(ws, "a b c d.")
    # Runs: 0.0-0.5 (0.5s) and 3.0-8.0 (5.0s).
    assert m.longest_fluent_run_s == 5.0


def test_avg_words_per_sentence():
    m = analyze(steady(["x"] * 6), "One two three. Four five six seven eight.")
    assert m.avg_words_per_sentence == 4.0


def test_words_without_timings_still_count():
    ws = [
        WordTiming(text="one", start=0.0, end=0.5, type="word"),
        WordTiming(text="two", start=None, end=None, type="word"),
        WordTiming(text="three", start=1.0, end=1.5, type="word"),
    ]
    m = analyze(ws, "One two three.")
    assert m.word_count == 3
    assert m.duration_s == 1.5
