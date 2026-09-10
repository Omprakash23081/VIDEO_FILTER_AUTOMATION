import os
import requests

from config import API_URL, API_KEY


VIDEO_FOLDER = r"H:\YOU TUBE\CEO WIFE\VIDEOS"
AUDIO_FOLDER = r"H:\YOU TUBE\CEO WIFE\AUDIO"

START_PART = 22

os.makedirs(VIDEO_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)

headers = {
    "apikey": API_KEY,
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}


def download_file(url, filename, file_type):
    """Download a file and show progress."""

    print(f"Starting {file_type} download...")

    response = requests.get(
        url,
        stream=True,
        timeout=60
    )

    response.raise_for_status()

    total_size = int(
        response.headers.get("content-length", 0)
    )

    downloaded = 0

    with open(filename, "wb") as file:

        for chunk in response.iter_content(
            chunk_size=1024 * 1024
        ):

            if chunk:

                file.write(chunk)
                downloaded += len(chunk)

                if total_size:

                    percent = downloaded * 100 / total_size

                    print(
                        f"\r{file_type}: {percent:.1f}%",
                        end=""
                    )

    print()
    print(f"{file_type} download complete: {filename}")


# Read links from links.txt
with open("links.txt", "r", encoding="utf-8") as file:

    links = [
        line.strip()
        for line in file
        if line.strip()
    ]


print(f"Found {len(links)} video links")


for index, kuaishou_url in enumerate(links):

    part_number = START_PART + index

    # Video goes to VIDEOS folder
    video_filename = os.path.join(
        VIDEO_FOLDER,
        f"PART-{part_number}.mp4"
    )

    # Audio goes to AUDIO folder
    audio_filename = os.path.join(
        AUDIO_FOLDER,
        f"PART-{part_number}.m4a"
    )

    print()
    print("=" * 50)
    print(f"PART {part_number}")
    print("=" * 50)

    try:

        # 1. Get video information
        response = requests.post(
            API_URL,
            headers=headers,
            json={"url": kuaishou_url},
            timeout=60
        )

        response.raise_for_status()

        data = response.json()

        if not data.get("success"):

            print("FAILED: Could not fetch video information")
            continue

        video_url = data["data"].get("videoUrl")
        audio_url = data["data"].get("audioUrl")

        print("Video URL received")
        print("Audio URL received")

        # 2. Download video
        if video_url:

            download_file(
                video_url,
                video_filename,
                "Video"
            )

        else:

            print("No video URL received")

        # 3. Download audio
        if audio_url:

            download_file(
                audio_url,
                audio_filename,
                "Audio"
            )

        else:

            print("No audio URL received")

    except Exception as error:

        print(f"FAILED PART {part_number}")
        print("Error:", error)


print()
print("=" * 50)
print("ALL DOWNLOADS FINISHED")
print("=" * 50)