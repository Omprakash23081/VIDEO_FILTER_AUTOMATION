import os
import requests

from config import API_URL, API_KEY


DOWNLOAD_FOLDER = r"H:\YOU TUBE\CEO WIFE\VIDEOS"

START_PART = 13


headers = {
    "apikey": API_KEY,
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}


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

    filename = os.path.join(
        DOWNLOAD_FOLDER,
        f"PART-{part_number}.mp4"
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
            print("FAILED: Could not fetch video")
            continue

        video_url = data["data"]["videoUrl"]

        print("Video URL received")
        print("Starting download...")

        # 2. Download video
        video_response = requests.get(
            video_url,
            stream=True,
            timeout=60
        )

        video_response.raise_for_status()

        total_size = int(
            video_response.headers.get("content-length", 0)
        )

        downloaded = 0

        # 3. Save video
        with open(filename, "wb") as file:

            for chunk in video_response.iter_content(
                chunk_size=1024 * 1024
            ):

                if chunk:

                    file.write(chunk)

                    downloaded += len(chunk)

                    if total_size:

                        percent = (
                            downloaded * 100 / total_size
                        )

                        print(
                            f"\rDownloading: {percent:.1f}%",
                            end=""
                        )

        print()
        print(f"Download complete: {filename}")

    except Exception as error:

        print(f"FAILED PART {part_number}")
        print("Error:", error)


print()
print("=" * 50)
print("ALL DOWNLOADS FINISHED")
print("=" * 50)