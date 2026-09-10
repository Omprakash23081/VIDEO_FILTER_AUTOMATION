import os
import requests
from config import API_URL, API_KEY

KUAISHOU_URL = "https://v.kuaishou.com/nhtEvU0Z"
DOWNLOAD_FOLDER = r"H:\YOU TUBE\CEO WIFE\VIDEOS"

headers = {
    "apikey": API_KEY,
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# 1. Get video information
response = requests.post(
    API_URL,
    headers=headers,
    json={"url": KUAISHOU_URL}
)

response.raise_for_status()

data = response.json()

if not data.get("success"):
    print("FAILED to fetch video")
    print(data)
    exit()

video_url = data["data"]["videoUrl"]

print("Video URL received")
print("Starting download...")

# 2. Download video
video_response = requests.get(
    video_url,
    stream=True
)

video_response.raise_for_status()

# 3. Save video
filename = os.path.join(DOWNLOAD_FOLDER, "test_video.mp4")

total_size = int(video_response.headers.get("content-length", 0))
downloaded = 0

with open(filename, "wb") as file:

    for chunk in video_response.iter_content(chunk_size=1024 * 1024):

        if chunk:
            file.write(chunk)
            downloaded += len(chunk)

            if total_size:
                percent = downloaded * 100 / total_size
                print(f"\rDownloading: {percent:.1f}%", end="")

print("\nDownload complete!")
print(f"Saved as: {filename}")