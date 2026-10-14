import os
import queue
import time
from playwright.sync_api import sync_playwright

from .. import config, job_state
from . import browser, transcript as text

print = job_state.safe_print
log = browser.log


def transcript_is_complete(transcript_path):
    return (
        os.path.exists(transcript_path)
        and os.path.getsize(transcript_path) >= config.TRANSCRIPT_MIN_SIZE
    )


def write_transcript(transcript_path, text):
    temporary_path = f"{transcript_path}.tmp"
    try:
        with open(temporary_path, "w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, transcript_path)
    except Exception:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)
        raise

def process_file_with_page(page, audio_path, transcript_path, part_number):
    response = browser.extract_audio_response(page, audio_path, part_number)
    cleaned_text = text.clean_gemini_response(response)
    if not cleaned_text:
        log("Error: Response contained no narration after cleanup.", part_number)
        return False

    write_transcript(transcript_path, cleaned_text)

    if not transcript_is_complete(transcript_path):
        log("Error: Transcript was not written completely.", part_number)
        return False
        
    job_state.update_part(os.path.splitext(os.path.basename(audio_path))[0].replace("PART-", ""), transcript="complete")
    log(f"Saving: {transcript_path}", part_number)
    return True


def process_audio_job(page, audio_file):
    started_at = time.monotonic()
    attempts = 0
    audio_path = os.path.join(config.AUDIO_FOLDER, audio_file)
    base_name = os.path.splitext(audio_file)[0]
    transcript_path = os.path.join(config.TRANSCRIPT_FOLDER, f"{base_name}.txt")
    hinglish_path = os.path.join(config.TRANSCRIPT_FOLDER, f"{base_name}_hinglish.txt")
    part_number = base_name.replace("PART-", "")

    if transcript_is_complete(hinglish_path):
        log(f"Skipping completed part; Hinglish already exists: {hinglish_path}", part_number)
        job_state.update_part(part_number, transcript="complete", hinglish="complete")
        job_state.record_metric("gemini", "skipped", time.monotonic() - started_at, part_number)
        return True

    if config.SKIP_EXISTING_TRANSCRIPTS and transcript_is_complete(transcript_path):
        log(f"Skipping existing transcript: {transcript_path}", part_number)
        job_state.update_part(part_number, transcript="complete")
        job_state.record_metric("gemini", "skipped", time.monotonic() - started_at, part_number)
        return True

    if not os.path.exists(audio_path):
        job_state.record_failure("gemini", part_number, "audio file missing")
        job_state.update_part(part_number, transcript="failed")
        job_state.record_metric(
            "gemini", "failed", time.monotonic() - started_at, part_number, error="audio file missing"
        )
        return False

    for attempt in range(1, config.GEMINI_MAX_RETRIES + 1):
        attempts = attempt
        try:
            log(f"Processing: {audio_file} (attempt {attempt})", part_number)
            if process_file_with_page(page, audio_path, transcript_path, part_number):
                log(f"Completed: {audio_file}", part_number)
                job_state.record_metric(
                    "gemini", "success", time.monotonic() - started_at, part_number, attempts=attempts
                )
                return True
        except Exception as error:
            log(f"Attempt {attempt} failed for {audio_file}: {error}", part_number)

        if attempt < config.GEMINI_MAX_RETRIES:
            time.sleep(3)

    job_state.update_part(part_number, transcript="failed")
    job_state.record_failure("gemini", part_number, "all retries failed")
    job_state.record_metric(
        "gemini", "failed", time.monotonic() - started_at, part_number,
        attempts=attempts, error="all retries failed"
    )
    log(f"[ERROR] Failed to process {audio_file}", part_number)
    return False


def run_queue(job_queue):
    os.makedirs(config.TRANSCRIPT_FOLDER, exist_ok=True)

    with sync_playwright() as playwright:
        log("Starting Gemini browser session...")
        args = ["--disable-blink-features=AutomationControlled"]
        if config.PLAYWRIGHT_CHROME_PROFILE:
            args.append(f"--profile-directory={config.PLAYWRIGHT_CHROME_PROFILE}")

        context = playwright.chromium.launch_persistent_context(
            user_data_dir=config.PLAYWRIGHT_PROFILE_DIR,
            headless=config.PLAYWRIGHT_HEADLESS,
            channel="chrome",
            args=args,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            for extra_page in context.pages[1:]:
                extra_page.close()

            browser.start_new_gemini_chat(page, None)
            log("Logged-in session detected. Waiting for downloaded audio...")

            while True:
                audio_file = job_queue.get()
                try:
                    if audio_file is None:
                        break
                    process_audio_job(page, audio_file)
                finally:
                    job_queue.task_done()
        finally:
            context.close()


def run():
    if not os.path.exists(config.AUDIO_FOLDER):
        log(f"Audio folder '{config.AUDIO_FOLDER}' does not exist. Nothing to do.")
        return

    audio_files = sorted(
        f for f in os.listdir(config.AUDIO_FOLDER)
        if f.lower().endswith((".m4a", ".mp3"))
    )
    if not audio_files:
        log("No audio files found.")
        return

    jobs = queue.Queue()
    for audio_file in audio_files:
        jobs.put(audio_file)
    jobs.put(None)
    run_queue(jobs)

if __name__ == "__main__":
    run()
