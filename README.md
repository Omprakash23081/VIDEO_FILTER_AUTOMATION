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
   youtube_download/   Authorized video download and MP4 packaging
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
4. Start the UI with `streamlit run app.py`.
5. Or run the CLI pipeline with `python -m youtube_automation.pipeline`.

### Web UI

The Streamlit UI supports both the Kuaishou and YouTube pipelines.

- Open the app with `streamlit run app.py`
- Choose a platform and its processing options.
- Set the output folder in **Storage location**. The app creates it when needed.
  Kuaishou creates `videos`, `audio`, and `transcripts` subfolders; YouTube
  creates separate `videos` and `transcripts` subfolders.
- Set the maximum run time. If a job exceeds this limit, the app terminates the
  pipeline process and reports the timeout and any output captured so far.
- Start the job to see live console output and YouTube download progress in the
  browser. The final output remains visible when the job completes.
- Prepare `.env` and the matching input file (`links.txt` for Kuaishou or
  `ytlink.txt` for YouTube) before running.

Run Cartesia TTS with `python -m youtube_automation.cartesia.tts <transcript.txt>`.

Add one authorized YouTube URL per line to `ytlink.txt`. Blank lines and lines
starting with `#` are ignored. Then run the batch downloader; videos
are saved under the selected output folder's `videos` subfolder, and transcripts
under its `transcripts` subfolder. The selected folder's final name is used as
the filename prefix. For example, selecting
`H:\YOU TUBE\EXPLAIN AGAIN\Reborn to End It All` creates
`videos\Reborn to End It All001.mp4` and
`transcripts\Reborn to End It All001.txt`, followed by `002`, `003`, and so on.
The original video resolution and aspect ratio are preserved; videos are
packaged as MP4 without resizing or video re-encoding:
Transcripts are fetched from YouTube using the `youtube-transcript-api` Python
package; no API key or local audio transcription is needed for this downloader.
Before downloading, the batch asks whether you want English or Hindi
transcripts. English is the default when running with
`--transcript-language en`; use `--transcript-language hi` for Hindi or omit
the option to choose interactively. It fetches captions in the selected
language. If English is selected but only Hindi captions are available, it
saves Hindi in the normal `.txt` file and uses a separate ChatGPT English
translation flow to write a sibling `*_english.txt` file. Choosing Hindi keeps
the Hindi transcript and does not translate it. The Hindi source is preserved.
This flow does not run or alter the existing Hinglish pipeline, which continues
to produce `_hinglish.txt` outputs. ChatGPT must be logged in through the
configured persistent browser profile. YouTube can rate-limit caption
requests, in which case the downloader reports the affected URL.
The YouTube downloader uses yt-dlp's default extras, including the JavaScript
challenge solver required for full YouTube download support. If upgrading an
existing environment, run `pip install -r requirements.txt`.
Transcript text is cleaned of timestamps, markup, and consecutive duplicate or
overlapping text.

```powershell
python -m youtube_automation.youtube_download.downloader --authorized
```

Use `--links PATH` or `--output-dir PATH` to select a different list or output folder.

Run local Whisper transcription with `python -m youtube_automation.whisper.transcribe`.

Run the behavior tests with `python -m unittest discover -s tests -v`. They cover
pipeline modes, video-only downloads, transfer resuming, and Gemini chat setup.
