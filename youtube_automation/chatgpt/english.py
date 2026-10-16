import os
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from .. import config
from . import browser
from .transcript import split_transcript


def build_english_prompt(chunk, index, total, previous_translation=""):
    context = ""
    if previous_translation:
        context = (
            "Use this recent English translation only for consistent names and context. "
            "Do not repeat it:\n\n"
            + previous_translation[-config.CHATGPT_CONTEXT_CHARS:]
            + "\n\n"
        )
    return (
        "Translate the Hindi transcript below into accurate, natural English. "
        "Preserve every event, detail, name, relationship, and meaning. Do not "
        "summarize, add jokes, embellish, or omit anything. Return only the English "
        "translation, with no introduction or explanation.\n\n"
        f"This is chunk {index} of {total}. Translate only this chunk.\n\n"
        f"{context}HINDI TRANSCRIPT:\n{chunk}"
    )


def output_path_for(transcript_path):
    transcript_path = Path(transcript_path)
    return transcript_path.with_name(f"{transcript_path.stem}_english.txt")


def _is_usable_translation(translation):
    text = translation.strip()
    if len(text) < 20:
        return False
    if any("\u0900" <= character <= "\u097f" for character in text):
        return False
    return True


def translate_transcript(page, transcript_path, output_path):
    source = Path(transcript_path).read_text(encoding="utf-8-sig").strip()
    if not source:
        raise ValueError(f"Hindi transcript is empty: {transcript_path}")

    browser.start_new_chat(page, "YouTube-English")
    chunks = split_transcript(source)
    translated_chunks = []
    for index, chunk in enumerate(chunks, start=1):
        prompt = build_english_prompt(
            chunk,
            index,
            len(chunks),
            translated_chunks[-1] if translated_chunks else "",
        )
        previous_count = browser.assistant_messages(page).count()
        translated = browser.send_prompt(
            page,
            prompt,
            previous_count,
            "YouTube-English",
        )
        translated = "\n".join(line.rstrip() for line in translated.splitlines()).strip()
        if not _is_usable_translation(translated):
            raise ValueError(f"ChatGPT returned an invalid English translation for chunk {index}")
        translated_chunks.append(translated)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=output_path.parent,
            prefix=f".{output_path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write("\n\n".join(translated_chunks) + "\n")
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    browser.log(f"Saved English transcript: {output_path}", "YouTube-English")
    return output_path


def translate_file(transcript_path, output_path=None):
    transcript_path = Path(transcript_path)
    output_path = Path(output_path) if output_path else output_path_for(transcript_path)
    if output_path.is_file() and output_path.stat().st_size:
        browser.log(f"English transcript already exists: {output_path}", "YouTube-English")
        return output_path

    with sync_playwright() as playwright:
        context = browser.launch_persistent_context(playwright)
        try:
            page = context.new_page()
            for extra_page in context.pages:
                if extra_page != page:
                    extra_page.close()
            page.goto(config.CHATGPT_URL, wait_until="domcontentloaded", timeout=60000)
            for attempt in range(1, config.CHATGPT_MAX_RETRIES + 1):
                try:
                    browser.log(
                        f"English transcript translation attempt "
                        f"{attempt}/{config.CHATGPT_MAX_RETRIES}",
                        "YouTube-English",
                    )
                    return translate_transcript(page, transcript_path, output_path)
                except Exception:
                    if attempt == config.CHATGPT_MAX_RETRIES:
                        raise
                    time.sleep(3)
        finally:
            context.close()
