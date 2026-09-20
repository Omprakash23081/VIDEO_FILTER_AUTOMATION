import downloader
import gemini_transcribe

def main():
    print("=" * 50)
    print("1. RUNNING DOWNLOADER")
    print("=" * 50)
    downloader.run()

    print()
    print("=" * 50)
    print("2. RUNNING GEMINI TRANSCRIBER")
    print("=" * 50)
    gemini_transcribe.run()
    
    print()
    print("=" * 50)
    print("PIPELINE COMPLETE")
    print("=" * 50)

if __name__ == "__main__":
    main()
