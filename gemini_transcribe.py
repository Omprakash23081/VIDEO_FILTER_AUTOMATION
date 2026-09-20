import os
import queue
import time
from playwright.sync_api import sync_playwright, TimeoutError
import config
import job_state

print = job_state.safe_print

PROMPT_TEXT = """
extract the full transcript
"""

def log(msg, part_number=None):
    label = f"[PART-{part_number}] " if part_number is not None else ""
    print(f"[Gemini] {label}{msg}")

def clean_gemini_response(text):
    lines = text.splitlines()
    cleaned = []

    for line in lines:
        line = line.strip()

        if line == "M4A":
            continue

        if line.startswith("+ ") and line[2:].isdigit():
            continue

        if line == "":
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue

        cleaned.append(line)

    return "\n".join(cleaned).strip()


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
    log(f"Uploading: {os.path.basename(audio_path)}", part_number)
    
    upload_button = page.get_by_role("button", name="Upload & tools")
    try:
        upload_button.wait_for(state="visible", timeout=15000)
        upload_button.click()
    except TimeoutError:
        log("Upload controls not found. Make sure you are logged in and on the correct page.", part_number)
        return False

    file_input = page.locator("input[type='file']").last
    try:
        file_input.wait_for(state="attached", timeout=15000)
    except TimeoutError:
        log("File input did not appear after opening the upload menu.", part_number)
        return False
        
    file_input.set_input_files(audio_path)
    
    log("Waiting for upload to complete...", part_number)
    chat_input = page.locator("[contenteditable='true'][aria-label='Enter a prompt for Gemini']")
    try:
        chat_input.wait_for(state="visible", timeout=120000)
    except TimeoutError:
        log("Gemini did not enable the prompt editor after uploading the file.", part_number)
        return False
    
    log("Sending prompt...", part_number)
    chat_input.fill(PROMPT_TEXT)
    send_button = page.get_by_role("button", name="Send message")
    send_button.wait_for(state="visible", timeout=15000)
    send_button.click()
    
    log("Waiting for response...", part_number)
    # Wait for the response to finish generating
    # Usually the model response is in a message-content or similar tag.
    # We will wait for the generating state to finish. 
    # Because Gemini UI changes, we use a robust polling mechanism.
    
    # Let's wait for a new response element to appear
    page.wait_for_selector(
        "message-content, .model-response-text, .response-container",
        state="attached",
        timeout=60000,
    )
    
    # Wait until it's done generating. A common way is to wait until the submit button is re-enabled,
    # or the stop generating button disappears.
    time.sleep(20) # Give it 20 seconds to generate a substantial amount
    
    # Keep checking if the response is still growing or if a copy button appears.
    last_text = ""
    stable_count = 0
    
    max_checks = max(1, config.GEMINI_RESPONSE_TIMEOUT_SECONDS // 5)
    for _ in range(max_checks):
        elements = page.locator("message-content, .model-response-text, .response-container").all()
        if not elements:
            time.sleep(5)
            continue
            
        current_text = elements[-1].inner_text()
        
        if current_text == last_text and len(current_text) > 0:
            stable_count += 1
        else:
            stable_count = 0
            
        last_text = current_text
        
        if stable_count >= 3: # 15 seconds of no changes -> likely done
            break
            
        time.sleep(5)
    
    if not last_text:
        log("Error: Empty response received.", part_number)
        return False
        
    log("Response received.", part_number)
    cleaned_text = clean_gemini_response(last_text)

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
    audio_path = os.path.join(config.AUDIO_FOLDER, audio_file)
    base_name = os.path.splitext(audio_file)[0]
    transcript_path = os.path.join(config.TRANSCRIPT_FOLDER, f"{base_name}.txt")
    hinglish_path = os.path.join(config.TRANSCRIPT_FOLDER, f"{base_name}_hinglish.txt")
    part_number = base_name.replace("PART-", "")

    if transcript_is_complete(hinglish_path):
        log(f"Skipping completed part; Hinglish already exists: {hinglish_path}", part_number)
        job_state.update_part(part_number, transcript="complete", hinglish="complete")
        return True

    if config.SKIP_EXISTING_TRANSCRIPTS and transcript_is_complete(transcript_path):
        log(f"Skipping existing transcript: {transcript_path}", part_number)
        job_state.update_part(part_number, transcript="complete")
        return True

    if not os.path.exists(audio_path):
        job_state.record_failure("gemini", part_number, "audio file missing")
        job_state.update_part(part_number, transcript="failed")
        return False

    for attempt in range(1, config.GEMINI_MAX_RETRIES + 1):
        try:
            log(f"Processing: {audio_file} (attempt {attempt})", part_number)
            if process_file_with_page(page, audio_path, transcript_path, part_number):
                log(f"Completed: {audio_file}", part_number)
                return True
        except Exception as error:
            log(f"Attempt {attempt} failed for {audio_file}: {error}", part_number)

        if attempt < config.GEMINI_MAX_RETRIES:
            time.sleep(3)

    job_state.update_part(part_number, transcript="failed")
    job_state.record_failure("gemini", part_number, "all retries failed")
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

            log(f"Opening Gemini ({config.GEMINI_URL})...")
            page.goto(config.GEMINI_URL, wait_until="domcontentloaded", timeout=60000)
            page.get_by_role("button", name="Upload & tools").wait_for(state="visible", timeout=120000)
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
