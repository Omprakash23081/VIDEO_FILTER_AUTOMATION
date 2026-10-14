import os
import re
import time

from playwright.sync_api import TimeoutError

from .. import config, job_state

print = job_state.safe_print

PROMPT_TEXT = """
extract the full transcript
"""


def log(message, part_number=None):
    label = f"[PART-{part_number}] " if part_number is not None else ""
    print(f"[Gemini] {label}{message}")


def start_new_gemini_chat(page, part_number):
    log(f"Opening Gemini: {config.GEMINI_URL}", part_number)
    page.goto(config.GEMINI_URL, wait_until="domcontentloaded", timeout=60000)

    try:
        page.get_by_role(
            "button",
            name=re.compile(r"new chat|new conversation", re.IGNORECASE),
        ).first.click(timeout=5000)
    except TimeoutError:
        pass

    try:
        page.get_by_role("button", name="Upload & tools").wait_for(state="visible", timeout=120000)
    except TimeoutError as error:
        log("Login required. Please log in to Gemini manually.", part_number)
        raise error

    log("Gemini session ready for a fresh transcript.", part_number)


def extract_audio_response(page, audio_path, part_number):
    start_new_gemini_chat(page, part_number)
    log(f"Uploading: {os.path.basename(audio_path)}", part_number)

    upload_button = page.get_by_role("button", name="Upload & tools")
    try:
        upload_button.wait_for(state="visible", timeout=15000)
        upload_button.click()
    except TimeoutError:
        log("Upload controls not found. Make sure you are logged in and on the correct page.", part_number)
        return ""

    file_input = page.locator("input[type='file']").last
    try:
        file_input.wait_for(state="attached", timeout=15000)
    except TimeoutError:
        log("File input did not appear after opening the upload menu.", part_number)
        return ""

    file_input.set_input_files(audio_path)

    log("Waiting for upload to complete...", part_number)
    chat_input = page.locator("[contenteditable='true'][aria-label='Enter a prompt for Gemini']")
    try:
        chat_input.wait_for(state="visible", timeout=120000)
    except TimeoutError:
        log("Gemini did not enable the prompt editor after uploading the file.", part_number)
        return ""

    log("Sending prompt...", part_number)
    chat_input.fill(PROMPT_TEXT)
    send_button = page.get_by_role("button", name="Send message")
    send_button.wait_for(state="visible", timeout=15000)
    send_button.click()

    log("Waiting for response...", part_number)
    page.wait_for_selector(
        "message-content, .model-response-text, .response-container",
        state="attached",
        timeout=60000,
    )

    last_text = ""
    stable_count = 0
    max_checks = max(1, config.GEMINI_RESPONSE_TIMEOUT_SECONDS // config.GEMINI_POLL_SECONDS)
    for _ in range(max_checks):
        elements = page.locator("message-content, .model-response-text, .response-container").all()
        if not elements:
            time.sleep(config.GEMINI_POLL_SECONDS)
            continue

        current_text = elements[-1].inner_text()
        stop_button = page.get_by_role(
            "button", name=re.compile("stop generating|stop", re.IGNORECASE)
        )
        generating = stop_button.count() > 0 and stop_button.last.is_visible()

        if current_text == last_text and current_text:
            stable_count += 1
        else:
            stable_count = 0
        last_text = current_text

        if stable_count >= config.GEMINI_STABLE_POLLS and not generating:
            break
        time.sleep(config.GEMINI_POLL_SECONDS)

    if not last_text:
        log("Error: Empty response received.", part_number)
        return ""

    log("Response received.", part_number)
    return last_text
