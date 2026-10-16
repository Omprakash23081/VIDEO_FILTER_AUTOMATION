from contextlib import redirect_stdout
from io import StringIO
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from yt_dlp.utils import DownloadError

from youtube_automation.chatgpt import english
from youtube_automation.youtube_download import downloader
from app import prepare_output_directory, run_command


class YoutubeDownloadTests(unittest.TestCase):
    def test_prepare_youtube_output_directory_creates_media_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            output_directory = prepare_output_directory(
                str(Path(directory) / "Reborn to End It All"),
                "YouTube",
            )

            self.assertTrue((output_directory / "videos").is_dir())
            self.assertTrue((output_directory / "transcripts").is_dir())

    def test_format_selector_requires_1080p_without_lower_resolution_fallback(self):
        selector = downloader.YOUTUBE_FORMAT_SELECTOR

        self.assertIn("[height=1080]", selector)
        self.assertNotIn("[height<=1080]", selector)
        self.assertNotIn("bestvideo+bestaudio", selector)
        self.assertEqual(len(selector.split("/")), 3)

    def test_download_fails_clearly_when_1080p_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            youtube_dl = MagicMock()
            youtube_dl.__enter__.return_value = youtube_dl
            youtube_dl.extract_info.side_effect = DownloadError(
                "ERROR: Requested format is not available"
            )
            with (
                patch.object(downloader.imageio_ffmpeg, "get_ffmpeg_exe", return_value="ffmpeg.exe"),
                patch.object(
                    downloader,
                    "YoutubeDL",
                    return_value=youtube_dl,
                ),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "1080p is not available.*No lower-resolution version",
                ):
                    downloader.download_video(
                        "https://youtu.be/example",
                        Path(directory) / "video.mp4",
                        authorized=True,
                    )

    def test_download_progress_hook_reports_progress_without_duplicate_percentages(self):
        progress_hook = downloader._make_download_progress_hook()
        output = StringIO()

        with redirect_stdout(output):
            progress_hook(
                {
                    "status": "downloading",
                    "downloaded_bytes": 10 * 1024**2,
                    "total_bytes": 100 * 1024**2,
                    "speed": 2 * 1024**2,
                    "eta": 45,
                }
            )
            progress_hook(
                {
                    "status": "downloading",
                    "downloaded_bytes": 10 * 1024**2,
                    "total_bytes": 100 * 1024**2,
                    "speed": 2 * 1024**2,
                    "eta": 45,
                }
            )
            progress_hook({"status": "finished"})

        self.assertEqual(
            output.getvalue().splitlines(),
            [
                "YouTube download: 10% | 10.0 MiB / 100.0 MiB | 2.0 MiB/s | ETA 00:00:45",
                "Download finished; preparing the video...",
            ],
        )

    def test_ffmpeg_packaging_reports_progress_and_copies_audio(self):
        process = Mock()
        process.stdout = StringIO(
            "out_time_us=10000000\n"
            "speed=2.0x\n"
            "progress=continue\n"
            "out_time_us=20000000\n"
            "speed=2.5x\n"
            "progress=end\n"
        )
        process.wait.return_value = 0
        output = StringIO()

        with patch.object(downloader.subprocess, "Popen", return_value=process) as popen:
            with redirect_stdout(output):
                downloader.run_ffmpeg_with_progress(["ffmpeg"], 20)

        self.assertEqual(
            output.getvalue().splitlines(),
            [
                "MP4 packaging: 50% | 00:00:10 / 00:00:20 | 2.0x",
                "MP4 packaging: 100% | 00:00:20 / 00:00:20 | 2.5x",
            ],
        )
        self.assertEqual(popen.call_args.kwargs["stderr"], downloader.subprocess.STDOUT)
        self.assertEqual(process.wait.call_count, 1)

    def test_run_command_replaces_previous_download_progress_line(self):
        updates = []
        result = run_command(
            "YouTube",
            [
                sys.executable,
                "-u",
                "-c",
                "print('Downloading source'); print('YouTube download: 12%'); "
                "print('YouTube download: 13%'); print('Download finished')",
            ],
            tempfile.gettempdir(),
            1,
            os.environ.copy(),
            updates.append,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(
            result["output"].splitlines(),
            [
                "Downloading source",
                "YouTube download: 13%",
                "Download finished",
            ],
        )
        self.assertTrue(any("YouTube download: 13%" in update for update in updates))
        self.assertFalse(
            "YouTube download: 12%" in updates[-1]
        )

    def test_chatgpt_english_translation_uses_dedicated_prompt_and_output(self):
        page = Mock()
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "video.txt"
            output_path = english.output_path_for(source_path)
            source_path.write_text("यह एक लंबा हिंदी वाक्य है।", encoding="utf-8")

            with (
                patch.object(english.browser, "start_new_chat") as start_new_chat,
                patch.object(
                    english.browser,
                    "assistant_messages",
                    return_value=Mock(count=Mock(return_value=0)),
                ),
                patch.object(
                    english.browser,
                    "send_prompt",
                    return_value="This is a complete English translation of the Hindi sentence.",
                ) as send_prompt,
            ):
                result = english.translate_transcript(page, source_path, output_path)

            self.assertEqual(result, output_path)
            self.assertTrue(source_path.exists())
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "This is a complete English translation of the Hindi sentence.\n",
            )
            start_new_chat.assert_called_once_with(page, "YouTube-English")
            prompt = send_prompt.call_args.args[1]
            self.assertIn("Translate the Hindi transcript", prompt)
            self.assertNotIn("Hinglish", prompt)
            self.assertNotIn("_hinglish", output_path.name)

    def test_transcript_text_removes_webvtt_metadata_and_duplicate_cues(self):
        lines = downloader.filter_transcript_lines(
            [
                "WEBVTT",
                "00:00:01.000 --> 00:00:02.000",
                "<c>Hello &amp; welcome.</c>",
                "00:00:02.000 --> 00:00:03.000",
                "Hello &amp; welcome.",
                "00:00:03.000 --> 00:00:04.000",
                "Thanks for watching.",
            ]
        )
        self.assertEqual(
            lines,
            ["Hello & welcome.", "Thanks for watching."],
        )

    def test_filter_removes_markup_timestamps_duplicates_and_overlap(self):
        self.assertEqual(
            downloader.filter_transcript_lines(
                [
                    "<c>We are starting now.</c>",
                    "We are starting now.",
                    "starting now with the next topic.",
                    "[00:00:03.000] Here is the end.",
                ]
            ),
            [
                "We are starting now.",
                "with the next topic.",
                "Here is the end.",
            ],
        )

    def test_extract_video_id_supports_common_youtube_urls(self):
        for url in (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=playlist",
            "https://youtu.be/dQw4w9WgXcQ?si=tracking",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
            "https://www.youtube.com/live/dQw4w9WgXcQ",
        ):
            with self.subTest(url=url):
                self.assertEqual(
                    downloader.extract_video_id(url),
                    "dQw4w9WgXcQ",
                )

    def test_extract_video_id_rejects_non_youtube_or_malformed_links(self):
        for url in (
            "https://example.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/not-a-video-id",
            "https://youtube.com/channel/example",
        ):
            with self.subTest(url=url):
                with self.assertRaisesRegex(ValueError, "valid YouTube video ID"):
                    downloader.extract_video_id(url)

    def test_downloads_and_filters_transcript_from_youtube_transcript_api(self):
        transcript = Mock(
            snippets=[
                Mock(text="First useful sentence."),
                Mock(text="First useful sentence."),
                Mock(text="useful sentence. The next point."),
            ]
        )
        api_instance = Mock()
        api_instance.fetch.return_value = transcript
        api_class = Mock(return_value=api_instance)

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "video.txt"
            with patch("youtube_transcript_api.YouTubeTranscriptApi", api_class):
                result = downloader.download_transcript(
                    "https://youtu.be/dQw4w9WgXcQ",
                    output_path,
                    authorized=True,
                )

            self.assertEqual(result, output_path)
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "First useful sentence.\nThe next point.\n",
            )
            api_class.assert_called_once()
            self.assertIsInstance(
                api_class.call_args.kwargs["http_client"],
                downloader.TranscriptTimeoutSession,
            )
            api_instance.fetch.assert_called_once_with(
                "dQw4w9WgXcQ",
                languages=["en"],
            )

    def test_reports_when_english_and_hindi_transcripts_are_unavailable(self):
        from youtube_transcript_api import NoTranscriptFound

        api_instance = Mock()
        api_instance.fetch.side_effect = [
            NoTranscriptFound("dQw4w9WgXcQ", ["en"], Mock()),
            NoTranscriptFound("dQw4w9WgXcQ", ["hi"], Mock()),
        ]

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "missing.txt"
            with patch(
                "youtube_transcript_api.YouTubeTranscriptApi",
                return_value=api_instance,
            ):
                with self.assertRaisesRegex(RuntimeError, "No English or Hindi captions"):
                    downloader.download_transcript(
                        "https://youtu.be/dQw4w9WgXcQ",
                        output_path,
                        authorized=True,
                    )
            self.assertEqual(
                api_instance.fetch.call_args_list[0].args,
                ("dQw4w9WgXcQ",),
            )
            self.assertEqual(
                [call.kwargs["languages"] for call in api_instance.fetch.call_args_list],
                [["en"], ["hi"]],
            )
            self.assertFalse(output_path.exists())

    def test_saves_hindi_caption_when_english_is_unavailable(self):
        from youtube_transcript_api import NoTranscriptFound

        api_instance = Mock()
        hindi_transcript = Mock(
            snippets=[Mock(text="यह मूल हिंदी प्रतिलेख है।")]
        )
        api_instance.fetch.side_effect = [
            NoTranscriptFound("dQw4w9WgXcQ", ["en"], Mock()),
            hindi_transcript,
        ]

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "video.txt"
            with patch(
                "youtube_transcript_api.YouTubeTranscriptApi",
                return_value=api_instance,
            ):
                downloader.download_transcript(
                    "https://youtu.be/dQw4w9WgXcQ",
                    output_path,
                    authorized=True,
                )

            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "यह मूल हिंदी प्रतिलेख है।\n",
            )
            self.assertEqual(
                [call.kwargs["languages"] for call in api_instance.fetch.call_args_list],
                [["en"], ["hi"]],
            )

    def test_fetches_only_hindi_when_hindi_is_selected(self):
        api_instance = Mock()
        api_instance.fetch.return_value = Mock(
            snippets=[Mock(text="यह हिंदी में है।")]
        )

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "video.txt"
            with patch(
                "youtube_transcript_api.YouTubeTranscriptApi",
                return_value=api_instance,
            ):
                downloader.download_transcript(
                    "https://youtu.be/dQw4w9WgXcQ",
                    output_path,
                    authorized=True,
                    language="hi",
                )

            api_instance.fetch.assert_called_once_with(
                "dQw4w9WgXcQ",
                languages=["hi"],
            )
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "यह हिंदी में है।\n",
            )

    def test_rejects_unsupported_transcript_language(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "must be 'en' or 'hi'"):
                downloader.download_transcript(
                    "https://youtu.be/dQw4w9WgXcQ",
                    Path(directory) / "video.txt",
                    authorized=True,
                    language="fr",
                )

    def test_prompts_until_valid_transcript_language_is_chosen(self):
        with patch("builtins.input", side_effect=["invalid", "2"]):
            self.assertEqual(downloader.prompt_transcript_language(), "hi")

    def test_transcript_http_session_sets_a_finite_timeout(self):
        with patch.object(
            downloader.requests.Session,
            "request",
            return_value=Mock(),
        ) as request:
            session = downloader.TranscriptTimeoutSession()
            session.get("https://youtube.com")

        self.assertEqual(
            request.call_args.kwargs["timeout"],
            downloader.TRANSCRIPT_HTTP_TIMEOUT,
        )

    def test_cleans_existing_transcript_before_skipping_it(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            transcript_path = folder / "THE_MORTAL_WHO_SURVIVES_001.txt"
            transcript_path.write_text(
                "WEBVTT\n\n"
                "00:00:01.000 --> 00:00:02.000\n"
                "<c>Keep this line.</c>\n\n"
                "00:00:02.000 --> 00:00:03.000\n"
                "Keep this line.\n",
                encoding="utf-8",
            )

            result = downloader.clean_existing_transcript(transcript_path)

            self.assertEqual(result, transcript_path)
            self.assertEqual(
                transcript_path.read_text(encoding="utf-8"),
                "Keep this line.\n",
            )

    def test_keeps_existing_hindi_transcript_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript_path = Path(directory) / "hindi.txt"
            original = "यह हिंदी में है।\n"
            transcript_path.write_text(original, encoding="utf-8")
            downloader.clean_existing_transcript(transcript_path)

            self.assertEqual(
                transcript_path.read_text(encoding="utf-8"),
                original,
            )

    def test_mp4_packaging_copies_video_without_resizing(self):
        command = downloader.build_ffmpeg_command("ffmpeg", "source.mkv", "output.mp4")
        video_codec_index = command.index("-c:v") + 1
        self.assertEqual(command[video_codec_index], "copy")
        self.assertNotIn("-vf", command)
        self.assertNotIn("libx264", command)

    def test_requires_permission_confirmation_before_download(self):
        with patch.object(downloader, "YoutubeDL") as youtube_dl:
            with self.assertRaises(PermissionError):
                downloader.download_video("https://youtube.com/watch?v=test", "out.mp4", authorized=False)

        youtube_dl.assert_not_called()

    def test_downloads_urls_from_file_and_ignores_comments_and_blank_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            links_file = folder / "ytlink.txt"
            output_directory = folder / "Reborn to End It All"
            links_file.write_text(
                "# authorized videos\nhttps://youtu.be/first\n\n https://youtu.be/second \n",
                encoding="utf-8",
            )

            with patch.object(
                downloader,
                "download_video",
                side_effect=lambda url, path, *, authorized: Path(path),
            ) as download_video, patch.object(
                downloader, "download_transcript"
            ) as download_transcript:
                outputs = downloader.download_links(links_file, output_directory, authorized=True)

            self.assertEqual(
                [call.args[0] for call in download_video.call_args_list],
                ["https://youtu.be/first", "https://youtu.be/second"],
            )
            self.assertEqual(
                [path.name for path in outputs],
                [
                    "Reborn to End It All001.mp4",
                    "Reborn to End It All002.mp4",
                ],
            )
            self.assertTrue(all(path.parent.name == "videos" for path in outputs))
            transcript_paths = [
                call.args[1] for call in download_transcript.call_args_list
            ]
            self.assertEqual(
                [path.name for path in transcript_paths],
                [
                    "Reborn to End It All001.txt",
                    "Reborn to End It All002.txt",
                ],
            )
            self.assertTrue(
                all(path.parent.name == "transcripts" for path in transcript_paths)
            )
            self.assertTrue((output_directory / "videos").is_dir())
            self.assertTrue((output_directory / "transcripts").is_dir())
            self.assertEqual(download_transcript.call_count, 2)

    def test_batch_download_skips_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            links_file = folder / "ytlink.txt"
            output_directory = folder / "downloads"
            links_file.write_text("https://youtu.be/first\n", encoding="utf-8")
            existing_output = output_directory / "videos" / "downloads001.mp4"
            existing_output.parent.mkdir(parents=True)
            existing_output.write_bytes(b"complete")

            with (
                patch.object(downloader, "is_standard_output", return_value=True),
                patch.object(downloader, "download_video") as download_video,
                patch.object(downloader, "download_transcript") as download_transcript,
            ):
                outputs = downloader.download_links(
                    links_file,
                    output_directory,
                    authorized=True,
                )

            download_video.assert_not_called()
            download_transcript.assert_called_once()
            self.assertEqual(outputs, [existing_output])
            self.assertEqual(
                download_transcript.call_args.args[1],
                output_directory / "transcripts" / "downloads001.txt",
            )

    def test_existing_hindi_transcript_uses_separate_chatgpt_translation(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            links_file = folder / "ytlink.txt"
            output_directory = folder / "downloads"
            links_file.write_text("https://youtu.be/first\n", encoding="utf-8")
            existing_video = output_directory / "videos" / "downloads001.mp4"
            existing_video.parent.mkdir(parents=True)
            existing_video.write_bytes(b"video")
            existing_transcript = (
                output_directory / "transcripts" / "downloads001.txt"
            )
            existing_transcript.parent.mkdir(parents=True)
            hindi_text = "यह हिंदी में है।\n"
            existing_transcript.write_text(hindi_text, encoding="utf-8")

            with (
                patch.object(downloader, "is_standard_output", return_value=True),
                patch.object(downloader, "download_video") as download_video,
                patch.object(downloader, "download_transcript") as download_transcript,
                patch.object(
                    downloader,
                    "translate_hindi_transcript",
                    return_value=existing_transcript.with_name(
                        "downloads001_english.txt"
                    ),
                ) as translate_hindi,
            ):
                downloader.download_links(links_file, output_directory, authorized=True)

            download_video.assert_not_called()
            download_transcript.assert_not_called()
            translate_hindi.assert_called_once_with(existing_transcript)
            self.assertEqual(
                existing_transcript.read_text(encoding="utf-8"),
                hindi_text,
            )

    def test_new_hindi_transcript_uses_separate_chatgpt_translation(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            links_file = folder / "ytlink.txt"
            output_directory = folder / "downloads"
            links_file.write_text("https://youtu.be/first\n", encoding="utf-8")
            existing_video = output_directory / "videos" / "downloads001.mp4"
            existing_video.parent.mkdir(parents=True)
            existing_video.write_bytes(b"video")
            transcript_path = output_directory / "transcripts" / "downloads001.txt"
            hindi_text = "यह हिंदी में है।\n"

            def save_hindi_transcript(url, path, *, authorized, language):
                self.assertEqual(language, "en")
                Path(path).write_text(hindi_text, encoding="utf-8")
                return Path(path)

            with (
                patch.object(downloader, "is_standard_output", return_value=True),
                patch.object(downloader, "download_video") as download_video,
                patch.object(
                    downloader,
                    "download_transcript",
                    side_effect=save_hindi_transcript,
                ),
                patch.object(
                    downloader,
                    "translate_hindi_transcript",
                    return_value=transcript_path.with_name(
                        "downloads001_english.txt"
                    ),
                ) as translate_hindi,
            ):
                downloader.download_links(links_file, output_directory, authorized=True)

            download_video.assert_not_called()
            translate_hindi.assert_called_once_with(transcript_path)
            self.assertEqual(transcript_path.read_text(encoding="utf-8"), hindi_text)

    def test_hindi_batch_choice_does_not_translate_transcript(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            links_file = folder / "ytlink.txt"
            output_directory = folder / "downloads"
            links_file.write_text("https://youtu.be/first\n", encoding="utf-8")
            existing_video = output_directory / "videos" / "downloads001.mp4"
            existing_video.parent.mkdir(parents=True)
            existing_video.write_bytes(b"video")
            transcript_path = output_directory / "transcripts" / "downloads001.txt"

            def save_hindi_transcript(url, path, *, authorized, language):
                self.assertEqual(language, "hi")
                Path(path).write_text("यह हिंदी में है।\n", encoding="utf-8")
                return Path(path)

            with (
                patch.object(downloader, "is_standard_output", return_value=True),
                patch.object(downloader, "download_video") as download_video,
                patch.object(
                    downloader,
                    "download_transcript",
                    side_effect=save_hindi_transcript,
                ) as download_transcript,
                patch.object(downloader, "translate_hindi_transcript") as translate,
            ):
                downloader.download_links(
                    links_file,
                    output_directory,
                    authorized=True,
                    transcript_language="hi",
                )

            download_video.assert_not_called()
            download_transcript.assert_called_once()
            translate.assert_not_called()
            self.assertEqual(
                transcript_path.read_text(encoding="utf-8"),
                "यह हिंदी में है।\n",
            )

    def test_batch_skips_existing_output_at_original_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            links_file = folder / "ytlink.txt"
            output_directory = folder / "downloads"
            links_file.write_text("https://youtu.be/first\n", encoding="utf-8")
            old_square_output = output_directory / "videos" / "downloads001.mp4"
            old_square_output.parent.mkdir(parents=True)
            old_square_output.write_bytes(b"old square video")

            with (
                patch.object(downloader, "is_standard_output", return_value=True),
                patch.object(
                    downloader,
                    "download_video",
                    return_value=old_square_output,
                ) as download_video,
                patch.object(downloader, "download_transcript"),
            ):
                downloader.download_links(links_file, output_directory, authorized=True)

            download_video.assert_not_called()

    def test_downloads_and_packages_video_without_transcoding_resolution(self):
        youtube_options = {}

        class FakeYoutubeDL:
            def __init__(self, options):
                self.options = options
                youtube_options.update(options)

            def __enter__(self):
                return self

            def __exit__(self, exception_type, exception, traceback):
                return False

            def extract_info(self, url, download):
                self.source_path = Path(
                    self.options["outtmpl"].replace("%(ext)s", "mkv")
                )
                self.source_path.write_bytes(b"source")
                return {"filepath": str(self.source_path)}

        command_used = []

        def fake_ffmpeg(command, **kwargs):
            command_used.extend(command)
            Path(command[-1]).write_bytes(b"converted")
            process = Mock()
            process.stdout = StringIO(
                "out_time_us=1000000\nspeed=1.0x\nprogress=continue\n"
                "out_time_us=2000000\nspeed=1.0x\nprogress=end\n"
            )
            process.wait.return_value = 0
            return process

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "video.mp4"
            with (
                patch.object(downloader, "YoutubeDL", FakeYoutubeDL),
                patch.object(downloader.imageio_ffmpeg, "get_ffmpeg_exe", return_value="ffmpeg.exe"),
                patch.object(downloader.subprocess, "Popen", side_effect=fake_ffmpeg),
            ):
                result = downloader.download_video(
                    "https://youtube.com/watch?v=test",
                    output_path,
                    authorized=True,
                )

            self.assertEqual(result, output_path)
            self.assertEqual(output_path.read_bytes(), b"converted")
            self.assertIn("copy", command_used)
            self.assertEqual(
                command_used[command_used.index("-c:a") + 1],
                "copy",
            )
            self.assertNotIn("-vf", command_used)
            self.assertNotIn("libx264", command_used)
            self.assertIn("-loglevel", command_used)
            self.assertIn("-nostats", command_used)
            self.assertEqual(youtube_options["concurrent_fragment_downloads"], 8)
            self.assertEqual(youtube_options["js_runtimes"], {"node": {}})
            self.assertEqual(
                downloader.DEFAULT_OUTPUT_DIRECTORY,
                Path(r"H:\YOU TUBE\THE MORTAL WHO SURVIVES"),
            )


if __name__ == "__main__":
    unittest.main()