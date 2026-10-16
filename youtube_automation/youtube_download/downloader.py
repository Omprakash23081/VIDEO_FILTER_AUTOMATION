import argparse
import html
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import imageio_ffmpeg
import requests
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError


TRANSCRIPT_HTTP_TIMEOUT = (10, 30)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LINKS_FILE = PROJECT_ROOT / "ytlink.txt"
DEFAULT_OUTPUT_DIRECTORY = Path(r"H:\YOU TUBE\THE MORTAL WHO SURVIVES")
YOUTUBE_FORMAT_SELECTOR = (
    "bestvideo[height=1080][width<=1920][ext=mp4]+bestaudio[ext=m4a]/"
    "bestvideo[height=1080][width<=1920]+bestaudio[ext=m4a]/"
    "best[height=1080][width<=1920][ext=mp4]"
)


def _format_size(byte_count):
    size = float(byte_count)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024


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


def build_ffmpeg_command(
    ffmpeg_path,
    source_path,
    output_path,
    video_options=("-c:v", "copy"),
):
    return [
        str(ffmpeg_path),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostats",
        "-progress",
        "pipe:1",
        "-y",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        *video_options,
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def _format_duration(seconds):
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def run_ffmpeg_with_progress(command, duration_seconds):
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    progress_data = {}

    for line in process.stdout:
        key, separator, value = line.rstrip().partition("=")
        if not separator:
            if line.strip():
                print(f"[FFmpeg] {line.rstrip()}")
            continue

        progress_data[key] = value
        if key != "progress":
            continue

        elapsed = progress_data.get("out_time_us")
        speed = progress_data.get("speed", "unavailable")
        if elapsed and duration_seconds:
            elapsed_seconds = int(elapsed) / 1_000_000
            percent = min(100, int(elapsed_seconds * 100 / duration_seconds))
            status = (
                f"MP4 packaging: {percent}% | "
                f"{_format_duration(elapsed_seconds)} / "
                f"{_format_duration(duration_seconds)} | {speed}"
            )
        else:
            status = f"MP4 packaging in progress | {speed}"
        print(status)
        progress_data.clear()

    return_code = process.wait()
    if return_code:
        raise subprocess.CalledProcessError(return_code, command)


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
        and get_video_dimensions(video_path, ffmpeg_path) is not None
    )


def _make_download_progress_hook():
    last_status = None
    started = False
    finished = False

    def report_progress(progress):
        nonlocal last_status, started, finished
        if progress.get("status") == "finished":
            if not finished:
                print("Download finished; preparing the video...")
                finished = True
            return
        if progress.get("status") != "downloading":
            return

        downloaded = progress.get("downloaded_bytes", 0)
        total = progress.get("total_bytes") or progress.get("total_bytes_estimate")
        speed = progress.get("speed")
        eta = progress.get("eta")
        if total:
            percent = min(100, int(downloaded * 100 / total))
            speed_text = f"{_format_size(speed)}/s" if speed else "speed unavailable"
            eta_text = (
                f"ETA {int(eta) // 3600:02d}:{(int(eta) % 3600) // 60:02d}:{int(eta) % 60:02d}"
                if eta is not None
                else "ETA unavailable"
            )
            status = (
                f"YouTube download: {percent}% | "
                f"{_format_size(downloaded)} / {_format_size(total)} | "
                f"{speed_text} | {eta_text}"
            )
            if status != last_status:
                print(status)
                last_status = status
        elif not started:
            print("Downloading YouTube video data...")
            started = True

    return report_progress


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
        progress_hook = _make_download_progress_hook()
        options = {
            "format": YOUTUBE_FORMAT_SELECTOR,
            "merge_output_format": "mkv",
            "outtmpl": str(Path(temporary_directory) / "source.%(ext)s"),
            "ffmpeg_location": ffmpeg_path,
            "js_runtimes": {"node": {}},
            "noplaylist": True,
            "quiet": True,
            "noprogress": True,
            "no_warnings": True,
            "retries": 3,
            "concurrent_fragment_downloads": 8,
            "progress_hooks": [progress_hook],
        }
        print(f"Downloading source: {url}")
        try:
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
        except DownloadError as error:
            if "requested format is not available" in str(error).lower():
                raise RuntimeError(
                    "1080p is not available for this video. "
                    "No lower-resolution version was downloaded."
                ) from error
            raise
        source_path = find_downloaded_file(info, temporary_directory)
        print(f"Preparing MP4 (keeping original video resolution): {output_path}")

        with tempfile.NamedTemporaryFile(
            dir=output_path.parent,
            prefix=f".{output_path.stem}.",
            suffix=".mp4",
            delete=False,
        ) as temporary_file:
            temporary_output = Path(temporary_file.name)

        try:
            command = build_ffmpeg_command(ffmpeg_path, source_path, temporary_output)
            run_ffmpeg_with_progress(command, info.get("duration"))
            if not temporary_output.is_file() or temporary_output.stat().st_size == 0:
                raise RuntimeError("FFmpeg did not create the output video")
            temporary_output.replace(output_path)
            print(f"Saved video: {output_path}")
        except subprocess.CalledProcessError as error:
            raise RuntimeError(
                f"FFmpeg MP4 packaging failed with exit code {error.returncode}"
            ) from error
        finally:
            temporary_output.unlink(missing_ok=True)

    return output_path


def _clean_transcript_line(line):
    text = re.sub(r"<[^>]*>", "", html.unescape(line)).strip()
    text = re.sub(
        r"^\[?\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\]?\s*",
        "",
        text,
    )
    return re.sub(r"\s+", " ", text).strip()


def filter_transcript_lines(lines):
    filtered = []
    for line in lines:
        text = _clean_transcript_line(line)
        if (
            not text
            or text == "WEBVTT"
            or text.startswith(("NOTE", "STYLE", "REGION", "Kind:", "Language:"))
            or "-->" in text
            or re.fullmatch(r"\d+", text)
        ):
            continue

        words = text.split()
        normalized = [re.sub(r"[^\w']", "", word).casefold() for word in words]
        previous_words = filtered[-1].split() if filtered else []
        previous_normalized = [
            re.sub(r"[^\w']", "", word).casefold() for word in previous_words
        ]
        if normalized == previous_normalized:
            continue

        overlap = min(len(previous_normalized), len(normalized))
        while overlap >= 2 and previous_normalized[-overlap:] != normalized[:overlap]:
            overlap -= 1
        if overlap >= 2:
            words = words[overlap:]
            text = " ".join(words)
        if text:
            filtered.append(text)
    return filtered


def contains_hindi(lines):
    return any("\u0900" <= character <= "\u097f" for line in lines for character in line)


def _write_transcript(output_path, lines):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=output_path.parent,
        prefix=f".{output_path.stem}.",
        suffix=".txt",
        delete=False,
    ) as temporary_file:
        temporary_path = Path(temporary_file.name)
        temporary_file.write("\n".join(lines) + "\n")

    try:
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output_path


def clean_existing_transcript(transcript_path):
    transcript_path = Path(transcript_path)
    original = transcript_path.read_text(encoding="utf-8-sig")
    cleaned_lines = filter_transcript_lines(original.splitlines())
    if not cleaned_lines:
        raise RuntimeError(f"Transcript contains no usable text: {transcript_path}")
    cleaned = "\n".join(cleaned_lines) + "\n"
    if cleaned != original:
        _write_transcript(transcript_path, cleaned_lines)
        print(f"Filtered existing transcript: {transcript_path}")
    return transcript_path


def download_transcript(url, output_path, *, authorized, language="en"):
    if not authorized:
        raise PermissionError("Confirm that you own or may download this video")
    if not url.strip():
        raise ValueError("A YouTube video URL is required")
    if language not in {"en", "hi"}:
        raise ValueError("Transcript language must be 'en' or 'hi'")

    output_path = Path(output_path)
    if output_path.suffix.lower() != ".txt":
        raise ValueError("Transcript output path must use the .txt extension")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    video_id = extract_video_id(url)
    from youtube_transcript_api import NoTranscriptFound, YouTubeTranscriptApi

    with TranscriptTimeoutSession() as http_client:
        api = YouTubeTranscriptApi(http_client=http_client)
        try:
            transcript = api.fetch(video_id, languages=[language])
        except NoTranscriptFound:
            if language != "en":
                raise RuntimeError(
                    f"No Hindi captions are available for {url}."
                )
            try:
                transcript = api.fetch(video_id, languages=["hi"])
            except NoTranscriptFound as hindi_error:
                raise RuntimeError(
                    f"No English or Hindi captions are available for {url}."
                ) from hindi_error

    transcript_lines = filter_transcript_lines(
        snippet.text for snippet in transcript.snippets
    )
    if not transcript_lines:
        raise RuntimeError(f"YouTube returned an empty transcript for {url}")

    _write_transcript(output_path, transcript_lines)
    print(f"Saved transcript: {output_path}")
    return output_path


def translate_hindi_transcript(transcript_path):
    transcript_path = Path(transcript_path)
    lines = transcript_path.read_text(encoding="utf-8-sig").splitlines()
    if not contains_hindi(lines):
        return None

    from ..chatgpt.english import output_path_for, translate_file

    english_path = output_path_for(transcript_path)
    return translate_file(transcript_path, english_path)


class TranscriptTimeoutSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", TRANSCRIPT_HTTP_TIMEOUT)
        return super().request(method, url, **kwargs)


def extract_video_id(url):
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/", 1)[0]
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        if parsed.path.rstrip("/") == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        else:
            parts = [part for part in parsed.path.split("/") if part]
            video_id = parts[1] if len(parts) >= 2 and parts[0] in {
                "shorts", "embed", "live", "v",
            } else ""
    else:
        video_id = ""

    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError(f"Could not find a valid YouTube video ID in URL: {url}")
    return video_id


def download_links(links_file, output_directory, *, authorized, transcript_language="en"):
    if not authorized:
        raise PermissionError("Confirm that you own or may download these videos")
    if transcript_language not in {"en", "hi"}:
        raise ValueError("Transcript language must be 'en' or 'hi'")

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
    video_directory = output_directory / "videos"
    transcript_directory = output_directory / "transcripts"
    video_directory.mkdir(parents=True, exist_ok=True)
    transcript_directory.mkdir(parents=True, exist_ok=True)
    name_prefix = output_directory.name or "video"
    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    completed = []
    failures = []

    for index, url in enumerate(urls, start=1):
        file_stem = f"{name_prefix}{index:03}"
        output_path = video_directory / f"{file_stem}.mp4"
        transcript_path = transcript_directory / f"{file_stem}.txt"
        if is_standard_output(output_path, ffmpeg_path):
            print(f"Skipping existing video: {output_path}")
            completed.append(output_path)
        else:
            try:
                completed.append(download_video(url, output_path, authorized=True))
            except Exception as error:
                failures.append((index, error))
                print(f"Failed URL {index}: {error}")
                continue

        needs_english_translation = False
        if transcript_path.is_file() and transcript_path.stat().st_size > 0:
            try:
                clean_existing_transcript(transcript_path)
            except Exception as error:
                failures.append((index, error))
                print(f"Failed to filter existing transcript {index}: {error}")
                continue
            existing_lines = transcript_path.read_text(
                encoding="utf-8-sig"
            ).splitlines()
            existing_is_hindi = contains_hindi(existing_lines)
            if (transcript_language == "hi" and existing_is_hindi) or (
                transcript_language == "en" and not existing_is_hindi
            ):
                print(f"Skipping existing transcript: {transcript_path}")
                continue
            needs_english_translation = (
                transcript_language == "en" and existing_is_hindi
            )
        else:
            try:
                download_transcript(
                    url,
                    transcript_path,
                    authorized=True,
                    language=transcript_language,
                )
                if transcript_language == "en" and transcript_path.is_file():
                    transcript_lines = transcript_path.read_text(
                        encoding="utf-8-sig"
                    ).splitlines()
                    needs_english_translation = contains_hindi(transcript_lines)
            except Exception as error:
                failures.append((index, error))
                print(f"Failed transcript {index}: {error}")
                continue

        if needs_english_translation:
            try:
                translate_hindi_transcript(transcript_path)
            except Exception as error:
                failures.append((index, error))
                print(f"Failed English translation {index}: {error}")

    if failures:
        failed_items = ", ".join(str(index) for index, _ in failures)
        raise RuntimeError(f"Failed to process URL(s): {failed_items}")

    return completed


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Download authorized YouTube URLs from a text file and package them as MP4 without resizing."
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
        help=(
            "Output folder for videos and transcripts "
            f"(default: {DEFAULT_OUTPUT_DIRECTORY})"
        ),
    )
    parser.add_argument(
        "--authorized",
        action="store_true",
        required=True,
        help="Confirm you own or have permission to download this video",
    )
    parser.add_argument(
        "--transcript-language",
        choices=("en", "hi"),
        help="Transcript language (en or hi); if omitted, you will be asked before downloads start",
    )
    args = parser.parse_args(argv)

    transcript_language = args.transcript_language or prompt_transcript_language()
    outputs = download_links(
        args.links,
        args.output_dir,
        authorized=args.authorized,
        transcript_language=transcript_language,
    )
    print(f"Completed {len(outputs)} video(s) in {args.output_dir}")


def prompt_transcript_language():
    choices = {"1": "en", "2": "hi", "en": "en", "hi": "hi"}
    while True:
        print("Choose the transcript language for this download batch:")
        print("1. English")
        print("2. Hindi")
        choice = input("Enter 1 or 2 (or en/hi): ").strip().lower()
        if choice in choices:
            return choices[choice]
        print("Invalid choice. Please enter 1 (English) or 2 (Hindi).")


if __name__ == "__main__":
    main()