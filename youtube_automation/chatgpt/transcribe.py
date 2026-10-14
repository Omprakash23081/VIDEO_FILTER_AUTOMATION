import os
import re
import time

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from .. import config, job_state
from . import browser, transcript as text

log = browser.log


def output_path_for(transcript_path):
    root, _ = os.path.splitext(transcript_path)
    return f"{root}_hinglish.txt"


def is_complete(path):
    return os.path.exists(path) and os.path.getsize(path) >= config.TRANSCRIPT_MIN_SIZE


def delete_source_transcript(transcript_path, part_number):
    if os.path.exists(transcript_path):
        os.remove(transcript_path)
        log(f"Deleted Chinese transcript: {transcript_path}", part_number)


def find_transcripts():
    return sorted(
        os.path.join(config.TRANSCRIPT_FOLDER, name)
        for name in os.listdir(config.TRANSCRIPT_FOLDER)
        if name.lower().startswith("part-")
        and name.lower().endswith(".txt")
        and not name.lower().endswith("_hinglish.txt")
    )


def process_transcript(page, transcript_path, part_number):
    output_path = output_path_for(transcript_path)
    if config.SKIP_EXISTING_HINGLISH and is_complete(output_path):
        log(f"Skipping existing Hinglish transcript: {output_path}", part_number)
        delete_source_transcript(transcript_path, part_number)
        return True

    with open(transcript_path, "r", encoding="utf-8") as file:
        source = file.read().strip()
    if not source:
        raise ValueError("Chinese transcript is empty")

    log("Reading Chinese transcript", part_number)
    browser.start_new_chat(page, part_number)
    chunks = text.split_transcript(source)
    translated_chunks = []

    for index, chunk in enumerate(chunks, start=1):
        prompt = text.build_translation_prompt(
            chunk,
            index,
            len(chunks),
            translated_chunks[-1] if translated_chunks else "",
        )
        log(f"Sending prompt ({index}/{len(chunks)})", part_number)
        previous_count = browser.assistant_messages(page).count()
        translated = text.clean_response(
            browser.send_prompt(page, prompt, previous_count, part_number)
        )
        if not text.validate_response(translated, chunk):
            raise ValueError(f"invalid response for chunk {index}")
        translated_chunks.append(translated)

    final_text = "\n\n".join(translated_chunks).strip()
    if not text.validate_response(final_text, source):
        raise ValueError("final Hinglish response failed validation")

    temporary_path = f"{output_path}.tmp"
    with open(temporary_path, "w", encoding="utf-8") as file:
        file.write(final_text)
    os.replace(temporary_path, output_path)
    log(f"Saved Hinglish transcript: {output_path}", part_number)
    delete_source_transcript(transcript_path, part_number)
    job_state.update_part(part_number, hinglish="complete")
    return True


def run_one(page, transcript_path, part_number):
    started_at = time.monotonic()
    attempts = 0
    for attempt in range(1, config.CHATGPT_MAX_RETRIES + 1):
        attempts = attempt
        try:
            log(f"Starting (attempt {attempt}/{config.CHATGPT_MAX_RETRIES})", part_number)
            if process_transcript(page, transcript_path, part_number):
                log("Completed", part_number)
                job_state.record_metric(
                    "chatgpt", "success", time.monotonic() - started_at,
                    part_number, attempts=attempts
                )
                return True
        except Exception as error:
            log(f"Attempt {attempt}/{config.CHATGPT_MAX_RETRIES} failed: {error}", part_number)
        if attempt < config.CHATGPT_MAX_RETRIES:
            log("Retrying", part_number)
            time.sleep(3)
    job_state.record_failure("chatgpt", part_number, "all retries failed")
    job_state.record_metric(
        "chatgpt", "failed", time.monotonic() - started_at,
        part_number, attempts=attempts, error="all retries failed"
    )
    log("Failed after retries", part_number)
    return False


def run(transcript_paths=None):
    os.makedirs(config.TRANSCRIPT_FOLDER, exist_ok=True)
    fixed_transcript_paths = transcript_paths

    with sync_playwright() as playwright:
        log(f"Starting browser profile: {config.CHATGPT_PROFILE_DIR}")
        args = ["--disable-blink-features=AutomationControlled"]
        if config.PLAYWRIGHT_CHROME_PROFILE:
            args.append(f"--profile-directory={config.PLAYWRIGHT_CHROME_PROFILE}")
        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=config.CHATGPT_PROFILE_DIR,
                headless=config.PLAYWRIGHT_HEADLESS,
                channel="chrome",
                args=args,
            )
        except PlaywrightError as error:
            if "existing browser session" not in str(error).lower():
                raise
            log(
                "Shared Chrome profile is locked by another browser window. "
                f"Using fallback profile: {config.CHATGPT_FALLBACK_PROFILE_DIR}"
            )
            log("Log in to ChatGPT manually in the fallback profile once.")
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=config.CHATGPT_FALLBACK_PROFILE_DIR,
                headless=config.PLAYWRIGHT_HEADLESS,
                channel="chrome",
                args=args,
            )
        try:
            log("Browser started")
            page = context.new_page()
            for extra_page in context.pages:
                if extra_page != page:
                    extra_page.close()
            log("Opening ChatGPT")
            page.goto(config.CHATGPT_URL, wait_until="domcontentloaded", timeout=60000)
            log(f"ChatGPT page loaded: {page.url}")
            for extra_page in context.pages:
                if extra_page != page:
                    extra_page.close()

            for sweep in range(1, config.CHATGPT_MAX_SWEEPS + 1):
                current_paths = (
                    fixed_transcript_paths
                    if fixed_transcript_paths is not None and sweep == 1
                    else find_transcripts()
                )
                eligible_paths = [path for path in current_paths if is_complete(path)]
                if not eligible_paths:
                    log(f"No pending Chinese transcripts found after sweep {sweep}")
                    break

                log(f"Transcript sweep {sweep}/{config.CHATGPT_MAX_SWEEPS}: {len(eligible_paths)} file(s)")
                for transcript_path in eligible_paths:
                    part_match = re.fullmatch(
                        r"PART-(\d+)\.txt", os.path.basename(transcript_path), re.IGNORECASE
                    )
                    if part_match:
                        run_one(page, transcript_path, part_match.group(1))

                remaining_paths = find_transcripts()
                if not any(is_complete(path) for path in remaining_paths):
                    log("All Chinese transcripts completed")
                    break
                if sweep < config.CHATGPT_MAX_SWEEPS:
                    log("Pending transcripts remain; starting another sweep")
        finally:
            context.close()


if __name__ == "__main__":
    run()