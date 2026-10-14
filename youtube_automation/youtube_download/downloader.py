import argparse
import re
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg
from yt_dlp import YoutubeDL


WIDTH = 1920
HEIGHT = 1080
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LINKS_FILE = PROJECT_ROOT / "ytlink.txt"
DEFAULT_OUTPUT_DIRECTORY = Path(r"H:\YOU TUBE\THE MORTAL WHO SURVIVES")
VIDEO_FILTER = (
    f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
    f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2"
)


def find_downloaded_file(info, temporary_directory):
    candidates = []
    if isinstance(info, dict):
        candidates.extend((info.get("filepath"), info.get("_filename")))
    candidates.extend(Path(temporary_directory).glob("source.*"))

    for candidate in candidates:
        if candidate:
            path = Path(candidate)
            if path.is_file() and not path.name.endswith((".part", ".ytdl")):
                return path
    raise RuntimeError("yt-dlp completed without producing a video file")


def build_ffmpeg_command(ffmpeg_path, source_path, output_path):
    return [
        str(ffmpeg_path),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostats",
        "-y",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def build_transcode_command(ffmpeg_path, source_path, output_path):
    return [
        str(ffmpeg_path),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostats",
        "-y",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        VIDEO_FILTER,
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "26",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def get_video_dimensions(video_path, ffmpeg_path):
    result = subprocess.run(
        [str(ffmpeg_path), "-hide_banner", "-i", str(video_path)],
        capture_output=True,
        text=True,
    )
    match = re.search(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})\b", result.stderr, re.DOTALL)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def is_standard_output(video_path, ffmpeg_path):
    video_path = Path(video_path)
    return (
        video_path.is_file()
        and video_path.stat().st_size > 0
        and get_video_dimensions(video_path, ffmpeg_path) == (WIDTH, HEIGHT)
    )


def can_copy_full_hd_video(info):
    formats = info.get("requested_formats") or [info]
    for video_format in formats:
        try:
            width = int(video_format.get("width", 0))
            height = int(video_format.get("height", 0))
        except (TypeError, ValueError):
            continue
        codec = str(video_format.get("vcodec", "")).lower()
        if width == WIDTH and height == HEIGHT and codec.startswith(("avc1", "h264")):
            return True
    return False


def download_video(url, output_path, *, authorized):
    if not authorized:
        raise PermissionError("Confirm that you own or may download this video")
    if not url.strip():
        raise ValueError("A YouTube video URL is required")

    output_path = Path(output_path)
    if output_path.suffix.lower() != ".mp4":
        raise ValueError("Output path must use the .mp4 extension")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory(prefix="youtube_download_") as temporary_directory:
        options = {
            "format": (
                "bestvideo[height<=1080][width<=1920][vcodec^=avc1]+bestaudio/"
                "bestvideo[height<=1080][width<=1920]+bestaudio/"
                "best[height<=1080][width<=1920]/bestvideo+bestaudio/best"
            ),
            "merge_output_format": "mkv",
            "outtmpl": str(Path(temporary_directory) / "source.%(ext)s"),
            "ffmpeg_location": ffmpeg_path,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 3,
            "concurrent_fragment_downloads": 8,
        }
        print(f"Downloading source: {url}")
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
        source_path = find_downloaded_file(info, temporary_directory)
        can_copy_video = can_copy_full_hd_video(info)
        operation = "Packaging Full HD video" if can_copy_video else f"Converting to {WIDTH}x{HEIGHT}"
        print(f"{operation}: {output_path}")

        with tempfile.NamedTemporaryFile(
            dir=output_path.parent,
            prefix=f".{output_path.stem}.",
            suffix=".mp4",
            delete=False,
        ) as temporary_file:
            temporary_output = Path(temporary_file.name)

        try:
            command_builder = build_ffmpeg_command if can_copy_video else build_transcode_command
            command = command_builder(ffmpeg_path, source_path, temporary_output)
            subprocess.run(command, check=True)
            if not temporary_output.is_file() or temporary_output.stat().st_size == 0:
                raise RuntimeError("FFmpeg did not create the output video")
            temporary_output.replace(output_path)
            print(f"Saved {WIDTH}x{HEIGHT} video: {output_path}")
        except subprocess.CalledProcessError as error:
            raise RuntimeError(
                f"FFmpeg conversion failed with exit code {error.returncode}"
            ) from error
        finally:
            temporary_output.unlink(missing_ok=True)

    return output_path


def download_links(links_file, output_directory, *, authorized):
    if not authorized:
        raise PermissionError("Confirm that you own or may download these videos")

    links_file = Path(links_file)
    if not links_file.is_file():
        raise FileNotFoundError(f"Video URL list not found: {links_file}")

    urls = [
        line.strip()
        for line in links_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not urls:
        raise ValueError(f"No video URLs found in {links_file}")

    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    completed = []
    failures = []

    for index, url in enumerate(urls, start=1):
        output_path = output_directory / f"THE_MORTAL_WHO_SURVIVES_{index:03}.mp4"
        if is_standard_output(output_path, ffmpeg_path):
            print(f"Skipping existing video: {output_path}")
            completed.append(output_path)
            continue

        try:
            completed.append(download_video(url, output_path, authorized=True))
        except Exception as error:
            failures.append((index, error))
            print(f"Failed URL {index}: {error}")

    if failures:
        failed_items = ", ".join(str(index) for index, _ in failures)
        raise RuntimeError(f"Failed to download URL(s): {failed_items}")

    return completed


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Download authorized YouTube URLs from a text file and convert them to 1920x1080 MP4."
    )
    parser.add_argument(
        "--links",
        type=Path,
        default=DEFAULT_LINKS_FILE,
        help=f"Text file with one YouTube URL per line (default: {DEFAULT_LINKS_FILE})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
        help=f"Directory for converted videos (default: {DEFAULT_OUTPUT_DIRECTORY})",
    )
    parser.add_argument(
        "--authorized",
        action="store_true",
        required=True,
        help="Confirm you own or have permission to download this video",
    )
    args = parser.parse_args(argv)

    outputs = download_links(args.links, args.output_dir, authorized=args.authorized)
    print(f"Completed {len(outputs)} video(s) in {args.output_dir}")


if __name__ == "__main__":
    main()