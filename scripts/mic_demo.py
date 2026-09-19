#!/usr/bin/env python3
"""Record from the mic, POST it to the analyze endpoint, print the coaching.

    python scripts/mic_demo.py
    python scripts/mic_demo.py --speak --context "practising a job interview answer"

Uses sounddevice's RawInputStream plus the stdlib wave module, so no numpy.
"""

import argparse
import base64
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path

import httpx
import sounddevice as sd

SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit PCM


def record_until_enter(path: Path) -> float:
    """Record until the user presses Enter. Returns seconds captured."""
    frames: list[bytes] = []

    def callback(indata, _frames, _time, status):
        if status:
            print(f"  (audio status: {status})", file=sys.stderr)
        frames.append(bytes(indata))

    stop = threading.Event()

    def wait_for_enter():
        input()
        stop.set()

    threading.Thread(target=wait_for_enter, daemon=True).start()

    with sd.RawInputStream(
        samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16", callback=callback
    ):
        print("Recording... press Enter to stop.")
        stop.wait()

    audio = b"".join(frames)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(SAMPLE_WIDTH)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(audio)

    return len(audio) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)


def print_report(data: dict) -> None:
    m, f = data["metrics"], data["feedback"]

    print("\n" + "=" * 68)
    print("TRANSCRIPT")
    print("=" * 68)
    print(data["transcript"])

    print("\n" + "=" * 68)
    print("MEASURED")
    print("=" * 68)
    print(f"  duration            {m['duration_s']}s  ({m['word_count']} words)")
    print(f"  pace                {m['wpm']} wpm")
    print(f"  articulation rate   {m['articulation_rate']} wpm")
    print(f"  speech ratio        {m['speech_ratio']}")
    print(f"  longest fluent run  {m['longest_fluent_run_s']}s")
    print(f"  avg words/sentence  {m['avg_words_per_sentence']}")
    print(f"  mid pauses (0.5-1.5s)  {m['mid_pauses']}")

    hard = [h["text"] for h in m["hard_fillers"]]
    soft = [s["text"] for s in m["soft_fillers"]]
    print(f"  hard fillers ({len(hard)})  {', '.join(hard) or '-'}")
    print(f"  soft fillers ({len(soft)})  {', '.join(soft) or '-'}")

    print(f"  long pauses ({len(m['long_pauses'])}):")
    for p in m["long_pauses"]:
        print(f"      {p['duration']}s after \"{p['after_word']}\" at {p['start']}s")

    if m["repetitions"]:
        print(f"  repetitions         {', '.join(m['repetitions'])}")
    if m["audio_events"]:
        print(f"  audio events        {', '.join(m['audio_events'])}")

    print("\n" + "=" * 68)
    print("COACH")
    print("=" * 68)
    print(f"  {f['encouragement']}")
    print(f"\n  FOCUS: {f['primary_focus']}")
    print(f"  >> {f['coaching_cue']}")
    print()
    for o in f["observations"]:
        print(f"  - {o['pattern']}")
        print(f"      evidence: {o['evidence']}")
        print(f"      why:      {o['why_it_matters']}")
    print(f"\n  TRY NEXT: {f['try_this_next']}")

    timings = ", ".join(f"{k} {v}ms" for k, v in data["timings_ms"].items())
    print(f"\n  [{timings}]")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--context", default=None, help="What you're practising")
    parser.add_argument("--speak", action="store_true", help="Play the cue aloud")
    parser.add_argument("--file", type=Path, help="Analyse this file instead of recording")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="mic_demo_"))

    if args.file:
        wav_path = args.file
    else:
        wav_path = tmp / "recording.wav"
        input("Press Enter to start recording... ")
        seconds = record_until_enter(wav_path)
        print(f"Captured {seconds:.1f}s. Analysing...")

    files = {"audio": (wav_path.name, wav_path.read_bytes(), "audio/wav")}
    data = {"context": args.context} if args.context else {}

    try:
        response = httpx.post(
            f"{args.url}/api/v1/speech/analyze",
            files=files,
            data=data,
            params={"speak": str(args.speak).lower()},
            timeout=120.0,
        )
    except httpx.ConnectError:
        print(f"Could not reach {args.url}. Is uvicorn running?", file=sys.stderr)
        return 1

    if response.status_code != 200:
        print(f"Error {response.status_code}: {response.text}", file=sys.stderr)
        return 1

    payload = response.json()
    print_report(payload)

    if args.speak and payload.get("audio_base64"):
        cue_path = tmp / "cue.mp3"
        cue_path.write_bytes(base64.b64decode(payload["audio_base64"]))
        subprocess.run(["afplay", str(cue_path)], check=False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
