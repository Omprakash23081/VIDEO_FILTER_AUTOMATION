import queue
import threading
import os

import downloader
import gemini_transcribe
import chatgpt_transcribe
import job_state
import config

print = job_state.safe_print


def part_stage(part_number):
    transcript_path = os.path.join(config.TRANSCRIPT_FOLDER, f"PART-{part_number}.txt")
    hinglish_path = os.path.join(config.TRANSCRIPT_FOLDER, f"PART-{part_number}_hinglish.txt")
    if os.path.exists(hinglish_path) and os.path.getsize(hinglish_path) >= config.TRANSCRIPT_MIN_SIZE:
        return "complete"
    if os.path.exists(transcript_path) and os.path.getsize(transcript_path) >= config.TRANSCRIPT_MIN_SIZE:
        return "chatgpt"
    return "gemini"


def main():
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

    downloader.run(on_part_ready=publish_part)
    gemini_queue.put(None)
    gemini_thread.join()

    if gemini_error:
        raise RuntimeError("Gemini worker failed") from gemini_error[0]

    print("=" * 50)
    print("RUNNING CHATGPT HINGLISH STAGE")
    print("=" * 50)
    chatgpt_transcribe.run()

    print()
    print("=" * 50)
    print("PIPELINE COMPLETE")
    print("=" * 50)

if __name__ == "__main__":
    main()
