import os

from faster_whisper import WhisperModel


AUDIO_FOLDER = r"H:\YOU TUBE\CEO WIFE\AUDIO"
TRANSCRIPT_FOLDER = r"H:\YOU TUBE\CEO WIFE\TRANSCRIPTS"


try:
    os.makedirs(TRANSCRIPT_FOLDER, exist_ok=True)
except OSError as e:
    print(f"CRITICAL ERROR: Could not create TRANSCRIPT_FOLDER on drive H:\nDetails: {e}")
    exit(1)

print("Loading Whisper model...")

model = WhisperModel(
    "small",
    device="cpu",
    compute_type="int8",
    cpu_threads=4 # Optimized for older CPUs to not lock up the machine
)

if not os.path.exists(AUDIO_FOLDER):
    print(f"CRITICAL ERROR: '{AUDIO_FOLDER}' not found. Ensure drive H: is connected and downloader has run.")
    exit(1)

audio_files = [
    file
    for file in os.listdir(AUDIO_FOLDER)
    if file.lower().endswith((".m4a", ".mp3"))
]


print(f"Found {len(audio_files)} audio files")


for index, audio_file in enumerate(audio_files, start=1):

    audio_path = os.path.join(
        AUDIO_FOLDER,
        audio_file
    )

    file_name = os.path.splitext(audio_file)[0]

    output_path = os.path.join(
        TRANSCRIPT_FOLDER,
        file_name + ".txt"
    )


    print()
    print("=" * 50)
    print(f"FILE {index}/{len(audio_files)}")
    print(f"Audio: {audio_file}")
    print("=" * 50)


    if os.path.exists(output_path):
        print("Transcript already exists. Skipping...")
        continue


    try:

        print("Transcribing...")

        segments, info = model.transcribe(
            audio_path,
            beam_size=5
        )


        print(f"Detected language: {info.language}")
        print(
            f"Language probability: "
            f"{info.language_probability:.2f}"
        )


        tmp_output_path = output_path + ".tmp"
        with open(
            tmp_output_path,
            "w",
            encoding="utf-8"
        ) as file:

            for segment in segments:

                text = segment.text.strip()

                if text:
                    file.write(text + "\n")

        # Atomic rename to prevent partial transcripts if interrupted
        os.replace(tmp_output_path, output_path)

        print("Transcription complete!")
        print(f"Saved: {output_path}")


    except Exception as error:

        print("FAILED!")
        print("Error:", error)


print()
print("=" * 50)
print("ALL TRANSCRIPTIONS FINISHED")
print("=" * 50)