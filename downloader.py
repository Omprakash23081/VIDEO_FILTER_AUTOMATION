import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

import requests

from config import API_URL, API_KEY


import config

VIDEO_FOLDER = config.VIDEO_FOLDER
AUDIO_FOLDER = config.AUDIO_FOLDER

START_PART = 30
MAX_RETRIES = 3
CHUNK_SIZE = 1024 * 1024
try:
    os.makedirs(VIDEO_FOLDER, exist_ok=True)
    os.makedirs(AUDIO_FOLDER, exist_ok=True)
except OSError as e:
    print(f"CRITICAL ERROR: Could not create or access folders on drive H:\nDetails: {e}")
    print("Please ensure your external drive is connected.")
    exit(1)

if not API_URL or not API_KEY:
    raise RuntimeError("API_URL and API_KEY must be set in config.py or your environment.")

_thread_state = threading.local()


def get_session():
    if not hasattr(_thread_state, "session"):
        _thread_state.session = requests.Session()
        _thread_state.session.headers.update(
            {
                "apikey": API_KEY,
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            }
        )
    return _thread_state.session


import time

def download_file(url, filename, file_type, retries=MAX_RETRIES):
    """Download a file with progress and retry logic."""
    session = get_session()
    expected_size = 0
    try:
        head_response = session.head(url, timeout=30)
        expected_size = int(head_response.headers.get("content-length", 0))
    except Exception:
        pass # Fallback to 0 if HEAD request fails

    if os.path.exists(filename):
        actual_size = os.path.getsize(filename)
        if expected_size > 0 and actual_size == expected_size:
            print(f"Skipping existing complete {file_type}: {filename}")
            return
        elif actual_size > 0:
            print(f"Found partial/corrupted {file_type}: {filename} (Size: {actual_size}/{expected_size}). Restarting download...")
        else:
            print(f"Starting {file_type} download: {filename}")
    else:
        print(f"Starting {file_type} download: {filename}")

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            response = session.get(url, stream=True, timeout=60)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0) or 0)
            downloaded = 0

            with open(filename, "wb") as file:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if not chunk:
                        continue
                    file.write(chunk)
                    downloaded += len(chunk)

                    if total_size:
                        percent = downloaded * 100 / total_size
                        print(f"\r{file_type}: {percent:.1f}%", end="", flush=True)

            print()
            print(f"{file_type} download complete: {filename}")
            return

        except requests.RequestException as error:
            last_error = error
            print(f"Attempt {attempt}/{retries} failed for {file_type}: {error}")
            if attempt < retries:
                backoff_time = 2 ** attempt  # 2s, 4s, 8s...
                print(f"Retrying in {backoff_time} seconds...")
                time.sleep(backoff_time)

    raise RuntimeError(f"All {retries} attempts failed for {file_type}: {last_error}")


def fetch_video_data(url, retries=3):
    session = get_session()
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            response = session.post(API_URL, json={"url": url}, timeout=60)
            response.raise_for_status()

            payload = response.json()
            if not payload.get("success"):
                message = payload.get("message", "Could not fetch video information")
                raise ValueError(message)

            return payload.get("data", {})
        except Exception as e:
            last_error = e
            print(f"API fetch attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)

    raise ValueError(f"Failed to fetch video data after {retries} attempts: {last_error}")


def process_part(kuaishou_url, part_number):
    video_filename = os.path.join(VIDEO_FOLDER, f"PART-{part_number}.mp4")
    audio_filename = os.path.join(AUDIO_FOLDER, f"PART-{part_number}.m4a")

    print()
    print("=" * 50)
    print(f"PART {part_number}")
    print("=" * 50)

    try:
        data = fetch_video_data(kuaishou_url)
        video_url = data.get("videoUrl")
        audio_url = data.get("audioUrl")

        if not video_url and not audio_url:
            print("No media URLs received for this part.")
            return False

        success = True
        if video_url:
            try:
                download_file(video_url, video_filename, "Video")
            except Exception as e:
                print(f"Video download error: {e}")
                success = False
        else:
            print("No video URL received")
            success = False

        if audio_url:
            try:
                download_file(audio_url, audio_filename, "Audio")
            except Exception as e:
                print(f"Audio download error: {e}")
                success = False
        else:
            print("No audio URL received")
            success = False

        return success

    except Exception as error:
        print(f"FAILED PART {part_number}")
        print("Error:", error)
        return False


def run():
    links_path = "links.txt"
    if not os.path.exists(links_path):
        print(f"CRITICAL ERROR: '{links_path}' not found. Please create it and add your URLs.")
        exit(1)

    with open(links_path, "r", encoding="utf-8") as file:
        links = [line.strip() for line in file if line.strip()]

    print(f"Found {len(links)} video links")
    
    part_jobs = [
        (START_PART + index, kuaishou_url)
        for index, kuaishou_url in enumerate(links)
    ]

    failed_links = []
    with ThreadPoolExecutor(max_workers=config.DOWNLOAD_WORKERS) as executor:
        futures = {
            executor.submit(process_part, kuaishou_url, part_number): (part_number, kuaishou_url)
            for part_number, kuaishou_url in part_jobs
        }

        for future in as_completed(futures):
            part_number, kuaishou_url = futures[future]
            try:
                if not future.result():
                    failed_links.append((part_number, kuaishou_url))
            except Exception as error:
                print(f"Unexpected error for part {part_number}: {error}")
                failed_links.append((part_number, kuaishou_url))

    if failed_links:
        print()
        print("=" * 50)
        print("RETRYING FAILED DOWNLOADS")
        print("=" * 50)

        for part_number, kuaishou_url in failed_links:
            print(f"Retrying part {part_number}: {kuaishou_url}")
            process_part(kuaishou_url, part_number)

    print()
    print("=" * 50)
    print("ALL DOWNLOADS FINISHED")
    print("=" * 50)

if __name__ == "__main__":
    run()
    
    print("\nStarting transcription pipeline (faster-whisper)...")
    import subprocess
    import sys

    try:
        subprocess.run([sys.executable, "transcribe.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Transcription pipeline failed with error code {e.returncode}")