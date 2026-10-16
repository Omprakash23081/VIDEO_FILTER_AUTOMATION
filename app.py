import queue
import os
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

import streamlit as st

from youtube_automation import config
from youtube_automation.youtube_download import downloader as youtube_downloader


PROJECT_ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="Video Automation Suite", page_icon="🎬", layout="wide")


def prepare_output_directory(location, platform):
    if not location.strip():
        raise ValueError("Choose an output folder before starting the pipeline.")

    output_directory = Path(location).expanduser()
    if not output_directory.is_absolute():
        output_directory = PROJECT_ROOT / output_directory
    output_directory = output_directory.resolve()

    subdirectories = (
        ("videos", "audio", "transcripts")
        if platform == "Kuaishou"
        else ("videos", "transcripts")
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    for name in subdirectories:
        (output_directory / name).mkdir(parents=True, exist_ok=True)
    return output_directory


def run_command(
    platform,
    command,
    output_directory,
    timeout_minutes,
    environment,
    progress_callback=None,
):
    environment = environment.copy()
    environment["PYTHONUNBUFFERED"] = "1"

    try:
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as error:
        return {
            "platform": platform,
            "status": "failed",
            "error": f"Could not start the pipeline: {error}",
            "output": "",
            "output_directory": str(output_directory),
        }

    output_lines = []
    visible_lines = deque(maxlen=80)
    output_queue = queue.Queue()

    def record_line(line):
        text = line.rstrip()
        is_pipeline_progress = text.startswith(
            ("YouTube download: ", "MP4 packaging: ", "MP4 packaging in progress")
        )
        if is_pipeline_progress:
            if visible_lines and visible_lines[-1].startswith(
                ("YouTube download: ", "MP4 packaging: ", "MP4 packaging in progress")
            ):
                visible_lines[-1] = text
            else:
                visible_lines.append(text)
            if output_lines and output_lines[-1].startswith(
                ("YouTube download: ", "MP4 packaging: ", "MP4 packaging in progress")
            ):
                output_lines[-1] = line
            else:
                output_lines.append(line)
            return

        visible_lines.append(text)
        output_lines.append(line)

    def read_output():
        for line in process.stdout:
            output_queue.put(line)
        output_queue.put(None)

    reader = threading.Thread(target=read_output, name="pipeline-output-reader", daemon=True)
    reader.start()
    if progress_callback:
        progress_callback("Pipeline started. Waiting for output...")

    deadline = time.monotonic() + timeout_minutes * 60
    timed_out = False
    reader_finished = False
    while not reader_finished:
        if process.poll() is None and time.monotonic() >= deadline:
            timed_out = True
            try:
                process.terminate()
            except OSError:
                if process.poll() is None:
                    raise
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

        try:
            line = output_queue.get(timeout=0.1)
        except queue.Empty:
            if process.poll() is not None and not reader.is_alive():
                break
            continue

        if line is None:
            reader_finished = True
            continue

        record_line(line)
        if progress_callback:
            progress_callback("\n".join(visible_lines))

    process.wait()
    reader.join()
    output = "".join(output_lines).strip()
    if timed_out:
        status = "failed"
        error = f"Pipeline exceeded the {timeout_minutes}-minute time limit."
    elif process.returncode:
        status = "failed"
        error = f"Pipeline exited with code {process.returncode}."
    else:
        status = "success"
        error = None

    return {
        "platform": platform,
        "status": status,
        "error": error,
        "output": output,
        "output_directory": str(output_directory),
    }


def run_kuaishou_pipeline(mode, location, timeout_minutes, progress_callback=None):
    try:
        output_directory = prepare_output_directory(location, "Kuaishou")
        environment = os.environ.copy()
        video_directory = output_directory / "videos"
        audio_directory = output_directory / "audio"
        transcript_directory = output_directory / "transcripts"
        environment.update(
            {
                "VIDEO_FOLDER": str(video_directory),
                "AUDIO_FOLDER": str(audio_directory),
                "TRANSCRIPT_FOLDER": str(transcript_directory),
                "MANIFEST_PATH": str(transcript_directory / "manifest.json"),
                "FAILED_JOBS_PATH": str(transcript_directory / "failed_parts.txt"),
                "METRICS_PATH": str(transcript_directory / "metrics.jsonl"),
                "LOCK_PATH": str(transcript_directory / "pipeline.lock"),
            }
        )
    except (OSError, ValueError) as error:
        st.session_state.pipeline_result = {
            "platform": "Kuaishou",
            "status": "failed",
            "error": str(error),
            "output": "",
            "output_directory": str(location),
        }
        return

    st.session_state.pipeline_result = run_command(
        "Kuaishou",
        [
            sys.executable,
            "-m",
            "youtube_automation.pipeline",
            "--mode",
            str(mode),
        ],
        output_directory,
        timeout_minutes,
        environment,
        progress_callback,
    )


def run_youtube_pipeline(
    transcript_language,
    location,
    timeout_minutes,
    progress_callback=None,
):
    try:
        output_directory = prepare_output_directory(location, "YouTube")
    except (OSError, ValueError) as error:
        st.session_state.pipeline_result = {
            "platform": "YouTube",
            "status": "failed",
            "error": str(error),
            "output": "",
            "output_directory": str(location),
        }
        return

    links_file = PROJECT_ROOT / "ytlink.txt"
    st.session_state.pipeline_result = run_command(
        "YouTube",
        [
            sys.executable,
            "-m",
            "youtube_automation.youtube_download.downloader",
            "--authorized",
            "--links",
            str(links_file),
            "--output-dir",
            str(output_directory),
            "--transcript-language",
            transcript_language,
        ],
        output_directory,
        timeout_minutes,
        os.environ.copy(),
        progress_callback,
    )


st.title("Video Automation Suite")

col1, col2 = st.columns([1, 2])
with col2:
    st.subheader("Output")
    live_output = st.empty()

with st.sidebar:
    st.header("Pipeline controls")
    platform = st.selectbox("Platform", ["Kuaishou", "YouTube"], index=0)

    if platform == "Kuaishou":
        mode = st.selectbox(
            "Processing mode",
            [
                (1, "Download video only"),
                (2, "Download video and audio"),
                (3, "Download video + audio + Gemini"),
                (4, "Run all stages"),
            ],
            format_func=lambda item: item[1],
        )
        button_label = "Start Kuaishou pipeline"
        default_output_directory = Path(config.VIDEO_FOLDER).parent
    else:
        transcript_language = st.selectbox(
            "Transcript language",
            [("en", "English"), ("hi", "Hindi")],
            format_func=lambda item: item[1],
        )
        mode = None
        button_label = "Start YouTube batch"
        default_output_directory = youtube_downloader.DEFAULT_OUTPUT_DIRECTORY

    st.subheader("Storage location")
    output_location = st.text_input(
        "Folder for generated files",
        value=str(default_output_directory),
        key=f"output_location_{platform.lower()}",
        help=(
            "Kuaishou creates videos, audio, and transcripts subfolders. "
            "YouTube creates separate videos and transcripts subfolders."
        ),
    )
    timeout_minutes = st.number_input(
        "Maximum run time (minutes)",
        min_value=1,
        max_value=1440,
        value=60,
        step=5,
        help="The app stops waiting and terminates the pipeline process when this limit is reached.",
    )
    if st.button(button_label, use_container_width=True, type="primary"):
        with st.spinner(f"Running {platform} pipeline..."):
            if platform == "Kuaishou":
                run_kuaishou_pipeline(
                    mode[0],
                    output_location,
                    timeout_minutes,
                    progress_callback=lambda output: live_output.code(
                        output,
                        language="text",
                    ),
                )
            else:
                run_youtube_pipeline(
                    transcript_language[0],
                    output_location,
                    timeout_minutes,
                    progress_callback=lambda output: live_output.code(
                        output,
                        language="text",
                    ),
                )

    if st.button("Clear results", use_container_width=True):
        st.session_state.pop("pipeline_result", None)

result = st.session_state.get("pipeline_result")

with col1:
    st.subheader("Pipeline info")
    st.write("Selected platform:", platform)
    if platform == "Kuaishou":
        st.write("Selected mode:", mode[1])
    else:
        st.write("Selected transcript language:", transcript_language[1])

    if result:
        st.write("Output folder:", result["output_directory"])
        if result["status"] == "success":
            st.success(f"{result['platform']} pipeline completed successfully.")
        else:
            st.error(f"{result['platform']} pipeline failed: {result['error']}")
    else:
        st.info("No pipeline run yet.")

with col2:
    if result:
        output = result["output"].strip() or "Pipeline finished without console output."
        st.code(output, language="text")
    else:
        st.code("No output yet. Select a pipeline and click Start.", language="text")

st.caption("This project contains two separate pipelines: Kuaishou (links.txt) and YouTube (ytlink.txt).")
