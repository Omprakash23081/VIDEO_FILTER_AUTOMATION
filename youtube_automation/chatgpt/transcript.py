import re

from .. import config

TRANSLATION_INSTRUCTIONS = """You are an expert translator and Text-to-Speech (TTS) script optimizer. Your task is to translate the provided Chinese video script into natural, conversational Hinglish (Hindi written in the English alphabet) while keeping the exact same story, emotion, and meaning.

Follow these strict rules to ensure the output is 100% ready for a TTS generator:

1. Maintain the Exact Story: Do not summarize, shorten, or change any part of the narrative. Translate the entire script from start to finish.
2. Natural Hinglish: The output must be completely in Hinglish. Make it sound conversational and natural to an Indian audience.
3. TTS-Optimized Format (CRITICAL):

Output ONLY the spoken dialogue.

Remove ALL speaker tags (e.g., "Speaker 1:", "Narrator:").

Remove ALL action notes, director cues, brackets, or parentheses (e.g., [sighs], (laughs), [music plays]).

Remove ALL timestamps or scene headings.
4. Phonetic Spelling: Use standard, predictable Hinglish spelling so the AI voice pronounces words correctly (e.g., use "kaise" not "kese", "main" not "me", "zaroori" not "jaruri", "kya" not "kia", "mujhe" not "muje").
5. Pacing with Punctuation: Use simple punctuation to control the AI voice's breathing and pacing. Use commas (,) for short pauses and full stops (.) for long pauses. Avoid dashes, hyphens, or semicolons as they cause TTS glitches.

Do not include any introductory greetings, explanations, or concluding remarks in your response. Return ONLY the final TTS-ready Hinglish text block.

And one final suggestion you can also modify script little bit to make it funny and interesting but do not change the story and meaning of the script. because of my major audience age belong to 13 to 24
and IMPORTANT in this script relation ship mite me not be correct so basd on story and minning you can change the relationship(like privesly didi was present insted of husband) in the script but do not change the story and meaning of the script.

Chinese Script:
"""


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


def build_translation_prompt(chunk, index, total, previous_translation=""):
    context = ""
    if previous_translation:
        context = (
            "Keep names and relationships consistent with this recent translated context. "
            "Do not repeat it:\n\n"
            + previous_translation[-config.CHATGPT_CONTEXT_CHARS:]
            + "\n\n"
        )
    return (
        f"{TRANSLATION_INSTRUCTIONS}\n\n"
        f"This is chunk {index} of {total}. Translate only this chunk, do not summarize it "
        "and do not repeat the previous chunk.\n\n"
        f"{context}SOURCE CHINESE TRANSCRIPT:\n{chunk}"
    )


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
