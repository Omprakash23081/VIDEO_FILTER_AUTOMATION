import argparse
import os
import queue
import threading
import time

from . import config, downloader, job_state
from .chatgpt import transcribe as chatgpt_transcribe
from .gemini import transcribe as gemini_transcribe

print = job_state.safe_print


def part_stage(part_number):
    transcript_path = os.path.join(config.TRANSCRIPT_FOLDER, f"PART-{part_number}.txt")
    hinglish_path = os.path.join(config.TRANSCRIPT_FOLDER, f"PART-{part_number}_hinglish.txt")
    if os.path.exists(hinglish_path) and os.path.getsize(hinglish_path) >= config.TRANSCRIPT_MIN_SIZE:
        return "complete"
    if os.path.exists(transcript_path) and os.path.getsize(transcript_path) >= config.TRANSCRIPT_MIN_SIZE:
        return "chatgpt"
    return "gemini"


def choose_pipeline_mode(input_fn=input):
    print("Choose processing mode:")
    print("1. Download video only")
    print("2. Download video and audio")
    print("3. Download video and audio, then run Gemini")
    print("4. Run all stages (video, audio, Gemini, ChatGPT)")
    while True:
        choice = input_fn("Enter 1-4: ").strip()
        if choice in {"1", "2", "3", "4"}:
            return int(choice)
        print("Invalid choice. Please enter 1, 2, 3, or 4.")


def _run_pipeline(mode):
    if mode < 3:
        downloader.run(include_audio=(mode >= 2))
    else:
        gemini_queue = queue.Queue()
        gemini_error = []

        def run_gemini():
            try:
                gemini_transcribe.run_queue(gemini_queue)
            except Exception as error:
                gemini_error.append(error)
                print(f"[Gemini] Worker stopped: {error}")

        gemini_thread = threading.Thread(target=run_gemini, name="gemini-worker")
        gemini_thread.start()
        published_parts = set()

        print("=" * 50)
        print("RUNNING DOWNLOADS AND GEMINI QUEUE")
        print("=" * 50)

        def publish_part(part_number):
            if part_number in published_parts:
                return
            published_parts.add(part_number)
            stage = part_stage(part_number)
            if stage == "complete":
                print(f"[Pipeline][PART-{part_number}] Hinglish already exists; skipping Gemini and ChatGPT")
                return
            if stage == "chatgpt":
                print(f"[Pipeline][PART-{part_number}] Transcript already exists; skipping Gemini")
                return
            gemini_queue.put(f"PART-{part_number}.m4a")

        downloader.run(on_part_ready=publish_part, include_audio=True)
        gemini_queue.put(None)
        gemini_thread.join()

        if gemini_error:
            raise RuntimeError("Gemini worker failed") from gemini_error[0]

    if mode == 4:
        print("=" * 50)
        print("RUNNING CHATGPT HINGLISH STAGE")
        print("=" * 50)
        chatgpt_transcribe.run()

    print()
    print("=" * 50)
    print("PIPELINE COMPLETE")
    print("=" * 50)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the Kuaishou processing pipeline.")
    parser.add_argument(
        "--mode",
        type=int,
        choices=(1, 2, 3, 4),
        help="Processing mode (1-4). If omitted, prompt for a mode.",
    )
    args = parser.parse_args(argv)
    mode = args.mode if args.mode is not None else choose_pipeline_mode()
    started_at = time.monotonic()
    item_count = None
    try:
        with open("links.txt", "r", encoding="utf-8") as file:
            item_count = len([line for line in file if line.strip()])
    except OSError:
        pass

    try:
        with job_state.pipeline_lock():
            _run_pipeline(mode)
    except Exception as error:
        job_state.record_metric(
            "pipeline", "failed", time.monotonic() - started_at,
            error=error, item_count=item_count
        )
        raise
    else:
        job_state.record_metric(
            "pipeline", "success", time.monotonic() - started_at,
            item_count=item_count
        )

if __name__ == "__main__":
    main()
