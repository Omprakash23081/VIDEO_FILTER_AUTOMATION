import re
import time

from playwright.sync_api import Error as PlaywrightError, TimeoutError

from .. import config, job_state

print = job_state.safe_print


def log(message, part_number=None):
    label = f"[PART-{part_number}] " if part_number is not None else ""
    print(f"[ChatGPT] {label}{message}")


def launch_persistent_context(playwright):
    log(f"Starting browser profile: {config.CHATGPT_PROFILE_DIR}")
    args = ["--disable-blink-features=AutomationControlled"]
    if config.PLAYWRIGHT_CHROME_PROFILE:
        args.append(f"--profile-directory={config.PLAYWRIGHT_CHROME_PROFILE}")
    try:
        return playwright.chromium.launch_persistent_context(
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
        return playwright.chromium.launch_persistent_context(
            user_data_dir=config.CHATGPT_FALLBACK_PROFILE_DIR,
            headless=config.PLAYWRIGHT_HEADLESS,
            channel="chrome",
            args=args,
        )


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


def send_prompt(page, prompt, previous_count, part_number):
    chat_input = find_chat_input(page)
    chat_input.fill(prompt)
    send_button = page.get_by_role("button", name=re.compile("send", re.IGNORECASE)).last
    send_button.click(timeout=15000)
    log("Waiting for response", part_number)
    return wait_for_response(page, previous_count)
