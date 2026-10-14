# YouTube Video Automation

This project downloads videos and audio, processes them through Gemini and ChatGPT, and produces translated transcripts for TTS workflows.

## Structure

```text
youtube_automation/
   cartesia/tts.py     Cartesia audio generation
   chatgpt/browser.py  ChatGPT page interaction
   chatgpt/transcript.py
                                 Prompting and translation text processing
   chatgpt/transcribe.py
                                 Translation workflow and job state
   gemini/browser.py   Gemini upload and response interaction
   gemini/transcript.py
                                 Transcript response cleanup
   gemini/transcribe.py
                                 Transcription workflow and job state
   youtube_download/   Authorized video download and square conversion
   whisper/transcribe.py
                                 Local Whisper transcription
   config.py           Application settings
   downloader.py       Media downloads
   pipeline.py         Workflow orchestration
   job_state.py        Locks, metrics, and job state
tests/                Behavior tests
links.txt             Input URLs
```

## Running

1. Create and activate a virtual environment.
2. Install dependencies:
   `pip install -r requirements.txt`
3. Set your environment variables in `.env`.
4. Run the pipeline with `python -m youtube_automation.pipeline`.

Run Cartesia TTS with `python -m youtube_automation.cartesia.tts <transcript.txt>`.

Add one authorized YouTube URL per line to `ytlink.txt`. Blank lines and lines
starting with `#` are ignored. Then run the batch downloader; converted videos
are saved to `H:\YOU TUBE\THE MORTAL WHO SURVIVES` as `video_001.mp4`,
`video_002.mp4`, and so on. Each output is 1920×1080 landscape and preserves the
full picture, adding padding when the source aspect ratio differs:

```powershell
python -m youtube_automation.youtube_download.downloader --authorized
```

Use `--links PATH` or `--output-dir PATH` to select a different list or output folder.

Run local Whisper transcription with `python -m youtube_automation.whisper.transcribe`.

Run the behavior tests with `python -m unittest discover -s tests -v`. They cover
pipeline modes, video-only downloads, transfer resuming, and Gemini chat setup.
