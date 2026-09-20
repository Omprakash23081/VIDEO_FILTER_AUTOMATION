import os
import re
import time

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError, sync_playwright

import config
import job_state

print = job_state.safe_print

TRANSLATION_INSTRUCTIONS = """You are an expert Chinese-to-Hinglish story translator and YouTube narration editor.

Convert the provided Chinese story transcript into natural, fluent Hinglish suitable for Indian YouTube storytelling.if somting is not clear in the Chinese transcript, make a reasonable guess based on context. Do not summarize or omit any part of the story. Preserve the complete story, sequence, events, character relationships, dialogue, emotions, and important details. Do not invent events, characters, dialogue, motivations, or information. Understand the context before translating. Keep names, genders, relationships, speakers

This is NOT a summarization task. Preserve the complete story, sequence, events, character relationships, dialogue, emotions, and important details. Do not invent events, characters, dialogue, motivations, or information. Understand the context before translating. Keep names, genders, relationships, speakers, actions, chronology, locations, and important objects consistent. Correct obvious transcription mistakes only when the intended meaning is clear. Translate meaning naturally, not word-for-word. Preserve the emotional and dramatic tone and make it sound natural and little bit funny as my most audence on youtube belonging to (13 to 25). when spoken by an Indian YouTube storyteller.

Output ONLY the narration. Do not add a title, heading, bullet points, timestamps, commentary, cultural explanations, opinions, or phrases such as "Here is the translation" or "Hinglish translation:". Preserve paragraph breaks where appropriate.
"""


def log(message, part_number=None):
    label = f"[PART-{part_number}] " if part_number is not None else ""
    print(f"[ChatGPT] {label}{message}")


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


def split_transcript(text):
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks = []
    current = ""

    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if current and len(candidate) > config.CHATGPT_MAX_INPUT_CHARS:
            chunks.append(current)
            current = paragraph
        elif len(paragraph) <= config.CHATGPT_MAX_INPUT_CHARS:
            current = candidate
        else:
            for index in range(0, len(paragraph), config.CHATGPT_MAX_INPUT_CHARS):
                piece = paragraph[index:index + config.CHATGPT_MAX_INPUT_CHARS]
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(piece)

    if current:
        chunks.append(current)
    return chunks or [text]


def find_chat_input(page):
    candidates = [
        page.locator("textarea").first,
        page.locator("[contenteditable='true']").last,
        page.get_by_placeholder(re.compile("message|prompt", re.IGNORECASE)).last,
    ]
    for candidate in candidates:
        try:
            candidate.wait_for(state="visible", timeout=3000)
            return candidate
        except TimeoutError:
            continue
    raise TimeoutError("ChatGPT message input was not found")


def start_new_chat(page, part_number):
    log(f"Opening ChatGPT: {config.CHATGPT_URL}", part_number)
    page.goto(config.CHATGPT_URL, wait_until="domcontentloaded", timeout=60000)
    try:
        page.get_by_role("button", name=re.compile("new chat", re.IGNORECASE)).first.click(timeout=5000)
    except TimeoutError:
        pass
    try:
        find_chat_input(page).wait_for(state="visible", timeout=120000)
    except TimeoutError as error:
        log("Login required. Please log in to ChatGPT manually.", part_number)
        raise error
    log("ChatGPT session detected", part_number)


def assistant_messages(page):
    return page.locator("[data-message-author-role='assistant']")


def extract_latest_response(page, previous_count):
    messages = assistant_messages(page)
    if messages.count() <= previous_count:
        return ""
    return messages.last.inner_text().strip()


def wait_for_response(page, previous_count):
    deadline = time.monotonic() + config.CHATGPT_RESPONSE_TIMEOUT_SECONDS
    stable_text = ""
    stable_count = 0

    while time.monotonic() < deadline:
        current_text = extract_latest_response(page, previous_count)
        stop_button = page.get_by_role("button", name=re.compile("stop generating|stop", re.IGNORECASE))
        generating = stop_button.count() > 0 and stop_button.last.is_visible()

        if current_text and current_text == stable_text and not generating:
            stable_count += 1
        else:
            stable_count = 0
        stable_text = current_text

        if stable_count >= 2:
            return current_text
        time.sleep(3)

    raise TimeoutError("ChatGPT response timed out")


def clean_response(text):
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines).strip()


def validate_response(text, source):
    lowered = text.lower().strip()
    if not lowered or len(lowered) < 30:
        return False
    blocked = (
        "here is the translation",
        "hinglish translation:",
        "i can't translate",
        "i cannot translate",
    )
    if any(marker in lowered[:160] for marker in blocked):
        return False
    if len(source) > 500 and len(text) < max(100, len(source) // 12):
        return False
    return True


def send_prompt(page, prompt, previous_count, part_number):
    chat_input = find_chat_input(page)
    chat_input.fill(prompt)
    send_button = page.get_by_role("button", name=re.compile("send", re.IGNORECASE)).last
    send_button.click(timeout=15000)
    log("Waiting for response", part_number)
    return clean_response(wait_for_response(page, previous_count))


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
    start_new_chat(page, part_number)
    chunks = split_transcript(source)
    translated_chunks = []

    for index, chunk in enumerate(chunks, start=1):
        context = ""
        if translated_chunks:
            context = (
                "Keep names and relationships consistent with this recent translated context. "
                "Do not repeat it:\n\n"
                + translated_chunks[-1][-config.CHATGPT_CONTEXT_CHARS:]
                + "\n\n"
            )
        prompt = (
            f"{TRANSLATION_INSTRUCTIONS}\n\n"
            f"This is chunk {index} of {len(chunks)}. Translate only this chunk, do not summarize it "
            "and do not repeat the previous chunk.\n\n"
            f"{context}SOURCE CHINESE TRANSCRIPT:\n{chunk}"
        )
        log(f"Sending prompt ({index}/{len(chunks)})", part_number)
        previous_count = assistant_messages(page).count()
        translated = send_prompt(page, prompt, previous_count, part_number)
        if not validate_response(translated, chunk):
            raise ValueError(f"invalid response for chunk {index}")
        translated_chunks.append(translated)

    final_text = "\n\n".join(translated_chunks).strip()
    if not validate_response(final_text, source):
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
    for attempt in range(1, config.CHATGPT_MAX_RETRIES + 1):
        try:
            log(f"Starting (attempt {attempt}/{config.CHATGPT_MAX_RETRIES})", part_number)
            if process_transcript(page, transcript_path, part_number):
                log("Completed", part_number)
                return True
        except Exception as error:
            log(f"Attempt {attempt}/{config.CHATGPT_MAX_RETRIES} failed: {error}", part_number)
        if attempt < config.CHATGPT_MAX_RETRIES:
            log("Retrying", part_number)
            time.sleep(3)
    job_state.record_failure("chatgpt", part_number, "all retries failed")
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