import os
from dotenv import load_dotenv

load_dotenv()

# API Configuration
API_URL = os.getenv("API_URL")
API_KEY = os.getenv("API_KEY")

# Directory Configuration
VIDEO_FOLDER = os.getenv("VIDEO_FOLDER", r"H:\YOU TUBE\CEO WIFE\VIDEOS")
AUDIO_FOLDER = os.getenv("AUDIO_FOLDER", r"H:\YOU TUBE\CEO WIFE\AUDIO")
TRANSCRIPT_FOLDER = os.getenv("TRANSCRIPT_FOLDER", r"H:\YOU TUBE\CEO WIFE\TRANSCRIPTS")

# Gemini Playwright Configuration
GEMINI_URL = os.getenv("GEMINI_URL", "https://gemini.google.com/app")
PLAYWRIGHT_PROFILE_DIR = os.getenv("PLAYWRIGHT_PROFILE_DIR", os.path.join(os.getcwd(), "playwright_profile"))
PLAYWRIGHT_CHROME_PROFILE = os.getenv("PLAYWRIGHT_CHROME_PROFILE")
PLAYWRIGHT_HEADLESS = os.getenv("PLAYWRIGHT_HEADLESS", "False").lower() in ("true", "1", "yes")
GEMINI_MAX_RETRIES = int(os.getenv("GEMINI_MAX_RETRIES", "3"))
SKIP_EXISTING_TRANSCRIPTS = os.getenv("SKIP_EXISTING_TRANSCRIPTS", "True").lower() in ("true", "1", "yes")
DOWNLOAD_WORKERS = int(os.getenv("DOWNLOAD_WORKERS", "3"))
