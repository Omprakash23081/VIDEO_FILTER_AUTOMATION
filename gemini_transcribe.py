import os
import time
from playwright.sync_api import sync_playwright, TimeoutError
import config

PROMPT_TEXT = """Listen to the entire uploaded audio carefully.
The audio contains a Chinese story/narration.
Your task is to understand the complete story and convert it into a complete, natural Hinglish narration.
IMPORTANT RULES:
1. Do NOT summarize the story.
2. Do NOT skip any important event, dialogue, narration, reaction, or detail.
3. Preserve the complete sequence of events.
4. Understand the context before converting the narration.
5. Correct obvious transcription/context mistakes using the surrounding context.
6. Keep character names consistent throughout the story.
7. Convert Chinese narration naturally into Hinglish suitable for Indian YouTube storytelling.
8. Do not translate word-for-word when that produces unnatural Hinglish.
9. Preserve the meaning, emotions, relationships, actions, and dialogue.
10. Do not invent events, characters, dialogue, or information that is not present in the audio.
11. Do not add your own explanations or commentary.
12. Make the final text natural and easy to speak as a voice-over.
13. Keep the complete story; do not shorten it.
14. Output ONLY the final Hinglish narration.
15. Do not include headings such as 'Transcript', 'Hinglish Translation', 'Summary', etc.
16. Do not include analysis or explanations outside the narration.
17. Do not include any timestamps, speaker labels, or other metadata.
Return only the final Hinglish storytelling transcript."""

def log(msg):
    print(f"[Gemini] {msg}")

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

def process_file_with_page(page, audio_path, transcript_path):
    log(f"Uploading: {os.path.basename(audio_path)}")
    
    upload_button = page.get_by_role("button", name="Upload & tools")
    try:
        upload_button.wait_for(state="visible", timeout=15000)
        upload_button.click()
    except TimeoutError:
        log("Upload controls not found. Make sure you are logged in and on the correct page.")
        return False

    file_input = page.locator("input[type='file']").last
    try:
        file_input.wait_for(state="attached", timeout=15000)
    except TimeoutError:
        log("File input did not appear after opening the upload menu.")
        return False
        
    file_input.set_input_files(audio_path)
    
    log("Waiting for upload to complete...")
    chat_input = page.locator("[contenteditable='true'][aria-label='Enter a prompt for Gemini']")
    try:
        chat_input.wait_for(state="visible", timeout=120000)
    except TimeoutError:
        log("Gemini did not enable the prompt editor after uploading the file.")
        return False
    
    log("Sending prompt...")
    chat_input.fill(PROMPT_TEXT)
    send_button = page.get_by_role("button", name="Send message")
    send_button.wait_for(state="visible", timeout=15000)
    send_button.click()
    
    log("Waiting for response...")
    # Wait for the response to finish generating
    # Usually the model response is in a message-content or similar tag.
    # We will wait for the generating state to finish. 
    # Because Gemini UI changes, we use a robust polling mechanism.
    
    # Let's wait for a new response element to appear
    page.wait_for_selector("message-content, .model-response-text, .response-container", state="attached", timeout=60000)
    
    # Wait until it's done generating. A common way is to wait until the submit button is re-enabled,
    # or the stop generating button disappears.
    time.sleep(20) # Give it 20 seconds to generate a substantial amount
    
    # Keep checking if the response is still growing or if a copy button appears.
    last_text = ""
    stable_count = 0
    
    for _ in range(60): # Max wait 60 * 5 = 300 seconds
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
        log("Error: Empty response received.")
        return False
        
    log("Response received.")
    cleaned_text = clean_gemini_response(last_text)

    if not cleaned_text:
        log("Error: Response contained no narration after cleanup.")
        return False
    
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(cleaned_text)
        
    log(f"Saving: {transcript_path}")
    return True


def run():
    os.makedirs(config.TRANSCRIPT_FOLDER, exist_ok=True)
    
    if not os.path.exists(config.AUDIO_FOLDER):
        log(f"Audio folder '{config.AUDIO_FOLDER}' does not exist. Nothing to do.")
        return

    audio_files = [f for f in os.listdir(config.AUDIO_FOLDER) if f.lower().endswith((".m4a", ".mp3"))]
    if not audio_files:
        log("No audio files found.")
        return
        
    log(f"Found {len(audio_files)} audio files.")
    
    for audio_file in audio_files:
        audio_path = os.path.join(config.AUDIO_FOLDER, audio_file)
        base_name = os.path.splitext(audio_file)[0]
        transcript_path = os.path.join(config.TRANSCRIPT_FOLDER, f"{base_name}.txt")
        
        if config.SKIP_EXISTING_TRANSCRIPTS and os.path.exists(transcript_path):
            log(f"Skipping existing transcript: {transcript_path}")
            continue
            
        log(f"Processing: {audio_file}")
        
        success = False
        for attempt in range(1, config.GEMINI_MAX_RETRIES + 1):
            try:
                # We initialize Playwright inside the attempt loop so if the browser crashes, 
                # it will completely restart for the next attempt.
                with sync_playwright() as p:
                    log("Starting/connecting to browser...")
                    
                    args = ["--disable-blink-features=AutomationControlled"]
                    if config.PLAYWRIGHT_CHROME_PROFILE:
                        args.append(f"--profile-directory={config.PLAYWRIGHT_CHROME_PROFILE}")
                        
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=config.PLAYWRIGHT_PROFILE_DIR,
                        headless=config.PLAYWRIGHT_HEADLESS,
                        channel="chrome",
                        args=args
                    )
                    
                    # Persistent contexts can restore blank tabs. Reuse the first
                    # page so navigation happens in the visible browser window.
                    page = context.pages[0] if context.pages else context.new_page()
                    for extra_page in context.pages[1:]:
                        extra_page.close()
                    log(f"Opening Gemini ({config.GEMINI_URL})...")
                    page.goto(config.GEMINI_URL, wait_until="domcontentloaded", timeout=60000)
                    
                    log("Please ensure you are logged in. Waiting for the Gemini upload button.")
                    page.get_by_role("button", name="Upload & tools").wait_for(state="visible", timeout=120000)
                    log("Logged-in session detected (upload button found).")
                    
                    time.sleep(2) # Give it a moment to fully initialize
                    
                    success = process_file_with_page(page, audio_path, transcript_path)
                    
                    context.close()
                    
                    if success:
                        break
                        
            except Exception as e:
                log(f"Attempt {attempt} failed: {e}")
                
            if not success and attempt < config.GEMINI_MAX_RETRIES:
                log(f"Retrying ({attempt}/{config.GEMINI_MAX_RETRIES})...")
                time.sleep(3)
                
        if not success:
            log(f"[ERROR] Failed to process {audio_file}")
        else:
            log(f"Completed: {audio_file}")

if __name__ == "__main__":
    run()
