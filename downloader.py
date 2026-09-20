import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

import requests

from config import API_URL, API_KEY


import config
import job_state

print = job_state.safe_print

VIDEO_FOLDER = config.VIDEO_FOLDER
AUDIO_FOLDER = config.AUDIO_FOLDER

START_PART = 30
MAX_RETRIES = 3
CHUNK_SIZE = 1024 * 1024


class DownloadHTTPError(requests.HTTPError):
    def __init__(self, status_code, url):
        super().__init__(f"HTTP {status_code} for URL: {url}")
        self.status_code = status_code


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
        _thread_state.cdn_headers = {
            "User-Agent": config.CDN_USER_AGENT,
            "Referer": config.CDN_REFERER,
            "Accept": "*/*",
        }
    return _thread_state.session


import time

def download_file(url, filename, file_type, part_number=None, retries=MAX_RETRIES):
    """Download a file with progress and retry logic."""
    session = get_session()
    temporary_filename = f"{filename}.part"
    part_label = f"[Downloader][PART-{part_number}] " if part_number is not None else "[Downloader] "
    expected_size = 0
    try:
        with session.head(
            url,
            headers=_thread_state.cdn_headers,
            timeout=30,
        ) as head_response:
            expected_size = int(head_response.headers.get("content-length", 0))
    except Exception:
        pass

    if os.path.exists(filename):
        actual_size = os.path.getsize(filename)
        if actual_size >= config.MIN_COMPLETE_FILE_SIZE and (expected_size == 0 or actual_size == expected_size):
            print(f"{part_label}Skipping existing complete {file_type}: {filename}")
            return
        if actual_size > 0:
            print(f"{part_label}Found partial/corrupted {file_type} (Size: {actual_size}/{expected_size}). Restarting download...")
        else:
            print(f"{part_label}Starting {file_type} download: {filename}")
    else:
        print(f"{part_label}Starting {file_type} download: {filename}")

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            with session.get(
                url,
                headers=_thread_state.cdn_headers,
                stream=True,
                timeout=60,
            ) as response:
                if response.status_code == 403:
                    raise DownloadHTTPError(403, url)
                response.raise_for_status()
                total_size = int(response.headers.get("content-length", 0) or 0)
                downloaded = 0

                with open(temporary_filename, "wb") as file:
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        if chunk:
                            file.write(chunk)
                            downloaded += len(chunk)

            if downloaded < config.MIN_COMPLETE_FILE_SIZE:
                raise RuntimeError(f"Downloaded {file_type} is too small: {downloaded} bytes")
            if total_size and downloaded != total_size:
                raise RuntimeError(f"Incomplete {file_type} download: {downloaded}/{total_size} bytes")

            os.replace(temporary_filename, filename)
            print(f"{part_label}{file_type} download complete: {filename}")
            return

        except DownloadHTTPError:
            if os.path.exists(temporary_filename):
                os.remove(temporary_filename)
            raise
        except (requests.RequestException, OSError, RuntimeError) as error:
            if os.path.exists(temporary_filename):
                os.remove(temporary_filename)
            last_error = error
            print(f"{part_label}Attempt {attempt}/{retries} failed for {file_type}: {error}")
            if attempt < retries:
                backoff_time = 2 ** attempt
                print(f"{part_label}Retrying in {backoff_time} seconds...")
                time.sleep(backoff_time)

    raise RuntimeError(f"All {retries} attempts failed for {file_type}: {last_error}")


def download_media_with_refresh(
    kuaishou_url,
    media_url,
    filename,
    file_type,
    part_number,
):
    current_url = media_url
    last_error = None

    for refresh_attempt in range(1, config.CDN_REFRESH_RETRIES + 1):
        try:
            download_file(
                current_url,
                filename,
                file_type,
                part_number=part_number,
            )
            return
        except DownloadHTTPError as error:
            last_error = error
            if error.status_code != 403:
                raise

            if refresh_attempt >= config.CDN_REFRESH_RETRIES:
                break

            print(
                f"[Downloader][PART-{part_number}] {file_type} URL returned 403; "
                "requesting a fresh CDN URL"
            )
            refreshed_data = fetch_video_data(kuaishou_url)
            current_url = refreshed_data.get(
                "videoUrl" if file_type == "Video" else "audioUrl"
            )
            if not current_url:
                raise RuntimeError(
                    f"API returned no refreshed {file_type.lower()} URL"
                )

    raise RuntimeError(
        f"Failed to refresh {file_type.lower()} URL after "
        f"{config.CDN_REFRESH_RETRIES} attempts: {last_error}"
    )


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
    print(f"[Downloader][PART-{part_number}] START")
    print("=" * 50)

    try:
        data = fetch_video_data(kuaishou_url)
        video_url = data.get("videoUrl")
        audio_url = data.get("audioUrl")

        if not video_url and not audio_url:
            print(f"[Downloader][PART-{part_number}] No media URLs received")
            job_state.update_part(part_number, download="failed")
            return False

        success = True
        if video_url:
            try:
                download_media_with_refresh(
                    kuaishou_url,
                    video_url,
                    video_filename,
                    "Video",
                    part_number,
                )
            except Exception as e:
                print(f"[Downloader][PART-{part_number}] Video download error: {e}")
                success = False
        else:
            print(f"[Downloader][PART-{part_number}] No video URL received")
            success = False

        if audio_url:
            try:
                download_media_with_refresh(
                    kuaishou_url,
                    audio_url,
                    audio_filename,
                    "Audio",
                    part_number,
                )
            except Exception as e:
                print(f"[Downloader][PART-{part_number}] Audio download error: {e}")
                success = False
        else:
            print(f"[Downloader][PART-{part_number}] No audio URL received")
            success = False

        job_state.update_part(part_number, download="complete" if success else "failed")
        return success

    except Exception as error:
        print(f"[Downloader][PART-{part_number}] FAILED: {error}")
        job_state.update_part(part_number, download="failed")
        return False


def audio_is_ready(part_number):
    audio_filename = os.path.join(AUDIO_FOLDER, f"PART-{part_number}.m4a")
    return file_is_complete(audio_filename)


def file_is_complete(filename):
    return (
        os.path.exists(filename)
        and os.path.getsize(filename) >= config.MIN_COMPLETE_FILE_SIZE
    )


def part_needs_download(part_number):
    return not (
        file_is_complete(os.path.join(VIDEO_FOLDER, f"PART-{part_number}.mp4"))
        and file_is_complete(os.path.join(AUDIO_FOLDER, f"PART-{part_number}.m4a"))
    )


def run(on_part_ready=None):
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

    pending_jobs = [
        (part_number, kuaishou_url)
        for part_number, kuaishou_url in part_jobs
        if part_needs_download(part_number)
    ]
    complete_jobs = [
        (part_number, kuaishou_url)
        for part_number, kuaishou_url in part_jobs
        if not part_needs_download(part_number)
    ]

    print(f"Already complete: {len(complete_jobs)}")
    print(f"Need download/API resolution: {len(pending_jobs)}")
    if pending_jobs:
        print("URLs requiring further processing:")
        for part_number, kuaishou_url in pending_jobs:
            print(f"[Downloader][PART-{part_number}] {kuaishou_url}")
    else:
        print("URLs requiring further processing: none")

    if on_part_ready:
        for part_number, _ in complete_jobs:
            if audio_is_ready(part_number):
                on_part_ready(part_number)

    failed_links = []
    with ThreadPoolExecutor(max_workers=config.DOWNLOAD_WORKERS) as executor:
        futures = {
            executor.submit(process_part, kuaishou_url, part_number): (part_number, kuaishou_url)
            for part_number, kuaishou_url in pending_jobs
        }

        for future in as_completed(futures):
            part_number, kuaishou_url = futures[future]
            try:
                result = future.result()
                if on_part_ready and audio_is_ready(part_number):
                    on_part_ready(part_number)
                if not result:
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
            if on_part_ready and audio_is_ready(part_number):
                on_part_ready(part_number)

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