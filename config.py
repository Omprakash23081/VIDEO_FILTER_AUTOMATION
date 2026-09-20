import os
from dotenv import load_dotenv

load_dotenv()


def env_int(name, default, minimum=0):
	value = os.getenv(name, str(default))
	try:
		parsed = int(value)
	except ValueError as error:
		raise ValueError(f"{name} must be an integer, got {value!r}") from error
	if parsed < minimum:
		raise ValueError(f"{name} must be >= {minimum}, got {parsed}")
	return parsed


# API Configuration
API_URL = os.getenv("API_URL")
API_KEY = os.getenv("API_KEY")

# Directory Configuration
VIDEO_FOLDER = os.getenv("VIDEO_FOLDER", r"H:\YOU TUBE\CEO WIFE\VIDEOS")
AUDIO_FOLDER = os.getenv("AUDIO_FOLDER", r"H:\YOU TUBE\CEO WIFE\AUDIO")
TRANSCRIPT_FOLDER = os.getenv("TRANSCRIPT_FOLDER", r"H:\YOU TUBE\CEO WIFE\TRANSCRIPTS")
MANIFEST_PATH = os.getenv("MANIFEST_PATH", os.path.join(TRANSCRIPT_FOLDER, "manifest.json"))
FAILED_JOBS_PATH = os.getenv("FAILED_JOBS_PATH", os.path.join(TRANSCRIPT_FOLDER, "failed_parts.txt"))

# Gemini Playwright Configuration
GEMINI_URL = os.getenv("GEMINI_URL", "https://gemini.google.com/app")
PLAYWRIGHT_PROFILE_DIR = os.getenv("PLAYWRIGHT_PROFILE_DIR", os.path.join(os.getcwd(), "playwright_profile"))
PLAYWRIGHT_CHROME_PROFILE = os.getenv("PLAYWRIGHT_CHROME_PROFILE")
PLAYWRIGHT_HEADLESS = os.getenv("PLAYWRIGHT_HEADLESS", "False").lower() in ("true", "1", "yes")
GEMINI_MAX_RETRIES = env_int("GEMINI_MAX_RETRIES", 3, 1)
SKIP_EXISTING_TRANSCRIPTS = os.getenv("SKIP_EXISTING_TRANSCRIPTS", "True").lower() in ("true", "1", "yes")
DOWNLOAD_WORKERS = env_int("DOWNLOAD_WORKERS", 3, 1)
CDN_REFRESH_RETRIES = env_int("CDN_REFRESH_RETRIES", 3, 1)
CDN_USER_AGENT = os.getenv(
	"CDN_USER_AGENT",
	"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
	"(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36",
)
CDN_REFERER = os.getenv("CDN_REFERER", "https://www.kuaishou.com/")
MIN_COMPLETE_FILE_SIZE = env_int("MIN_COMPLETE_FILE_SIZE", 1024, 1)
GEMINI_RESPONSE_TIMEOUT_SECONDS = env_int("GEMINI_RESPONSE_TIMEOUT_SECONDS", 600, 1)
TRANSCRIPT_MIN_SIZE = env_int("TRANSCRIPT_MIN_SIZE", 100, 1)

# ChatGPT website automation
CHATGPT_URL = os.getenv("CHATGPT_URL", "https://chatgpt.com/")
CHATGPT_PROFILE_DIR = os.getenv("CHATGPT_PROFILE_DIR", PLAYWRIGHT_PROFILE_DIR)
CHATGPT_FALLBACK_PROFILE_DIR = os.getenv(
	"CHATGPT_FALLBACK_PROFILE_DIR",
	os.path.join(os.getcwd(), "chatgpt_profile"),
)
CHATGPT_MAX_RETRIES = env_int("CHATGPT_MAX_RETRIES", 3, 1)
CHATGPT_RESPONSE_TIMEOUT_SECONDS = env_int("CHATGPT_RESPONSE_TIMEOUT_SECONDS", 600, 1)
CHATGPT_MAX_INPUT_CHARS = env_int("CHATGPT_MAX_INPUT_CHARS", 30000, 1000)
CHATGPT_CONTEXT_CHARS = env_int("CHATGPT_CONTEXT_CHARS", 2000, 0)
CHATGPT_WORKERS = env_int("CHATGPT_WORKERS", 1, 1)
SKIP_EXISTING_HINGLISH = os.getenv("SKIP_EXISTING_HINGLISH", "True").lower() in ("true", "1", "yes")
CHATGPT_MAX_SWEEPS = env_int("CHATGPT_MAX_SWEEPS", 3, 1)
