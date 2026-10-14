"""Generate a WAV file from a Hinglish transcript with Cartesia TTS."""

import argparse
import os
import sys
import tempfile
from pathlib import Path

import requests
from dotenv import load_dotenv


API_URL = "https://api.cartesia.ai/tts/bytes"
DEFAULT_VOICE_ID = "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4"
DEFAULT_MODEL_ID = "sonic-3.6"
DEFAULT_SAMPLE_RATE = 44100

load_dotenv()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Convert a Hinglish transcript into a Cartesia WAV file."
    )
    parser.add_argument("transcript", type=Path, help="Path to the Hinglish .txt file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output WAV path (defaults to the transcript name with a .wav suffix)",
    )
    parser.add_argument(
        "--voice",
        default=os.getenv("CARTESIA_VOICE_ID", DEFAULT_VOICE_ID),
        help="Cartesia voice ID, or set CARTESIA_VOICE_ID",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("CARTESIA_MODEL_ID", DEFAULT_MODEL_ID),
        help="Cartesia model ID, or set CARTESIA_MODEL_ID",
    )
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--volume", type=float, default=1.0)
    parser.add_argument(
        "--play",
        action="store_true",
        help="Play the generated WAV after saving it on Windows",
    )
    return parser.parse_args()


def generate_audio(transcript_path, output_path, api_key, voice_id, model_id, speed, volume):
    transcript = transcript_path.read_text(encoding="utf-8").strip()
    if not transcript:
        raise ValueError(f"Transcript is empty: {transcript_path}")

    response = requests.post(
        API_URL,
        headers={
            "Cartesia-Version": "2026-08-14",
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        },
        json={
            "model_id": model_id,
            "transcript": transcript,
            "voice": voice_id,
            "output_format": {
                "container": "wav",
                "encoding": "pcm_s16le",
                "sample_rate": DEFAULT_SAMPLE_RATE,
            },
            "generation_config": {"speed": speed, "volume": volume},
        },
        timeout=120,
    )
    if not response.ok:
        detail = response.text[:500]
        raise RuntimeError(f"Cartesia request failed ({response.status_code}): {detail}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb", dir=output_path.parent, prefix=f"{output_path.name}.", suffix=".tmp", delete=False
    ) as temporary_file:
        temporary_path = Path(temporary_file.name)
        temporary_file.write(response.content)

    try:
        temporary_path.replace(output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def generate_folder(
    transcript_folder,
    output_folder,
    api_key,
    voice_id=None,
    model_id=None,
    speed=1.0,
    volume=1.0,
):
    transcript_folder = Path(transcript_folder)
    output_folder = Path(output_folder)
    transcripts = sorted(transcript_folder.glob("PART-*_hinglish.txt"))
    pending = [
        (transcript, output_folder / f"{transcript.name[:-len('_hinglish.txt')]}.wav")
        for transcript in transcripts
    ]
    pending = [(transcript, output) for transcript, output in pending if not output.is_file()]
    if not pending:
        return 0
    if not api_key:
        raise RuntimeError("Set CARTESIA_API_KEY before generating audio")

    voice_id = voice_id or os.getenv("CARTESIA_VOICE_ID", DEFAULT_VOICE_ID)
    model_id = model_id or os.getenv("CARTESIA_MODEL_ID", DEFAULT_MODEL_ID)
    for transcript, output in pending:
        generate_audio(transcript, output, api_key, voice_id, model_id, speed, volume)
        print(f"Saved audio: {output}")
    return len(pending)


def play_audio(output_path):
    if sys.platform != "win32":
        raise RuntimeError("--play is only supported on Windows")

    import winsound

    winsound.PlaySound(str(output_path), winsound.SND_FILENAME)


def main():
    args = parse_args()
    api_key = os.getenv("CARTESIA_API_KEY")
    if not api_key:
        raise RuntimeError("Set CARTESIA_API_KEY before running this script")
    if not args.transcript.is_file():
        raise FileNotFoundError(f"Transcript not found: {args.transcript}")

    output_path = args.output or args.transcript.with_suffix(".wav")
    generate_audio(
        args.transcript,
        output_path,
        api_key,
        args.voice,
        args.model,
        args.speed,
        args.volume,
    )
    print(f"Saved audio: {output_path}")
    if args.play:
        play_audio(output_path)


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)