import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from youtube_automation.youtube_download import downloader


class YoutubeDownloadTests(unittest.TestCase):
    def test_combined_h264_full_hd_format_uses_fast_copy_path(self):
        info = {
            "requested_formats": [
                {"width": 1920, "height": 1080, "vcodec": "avc1.640028"},
                {"width": None, "height": None, "vcodec": "none"},
            ]
        }

        self.assertTrue(downloader.can_copy_full_hd_video(info))
        command = downloader.build_ffmpeg_command("ffmpeg", "source.mkv", "output.mp4")
        video_codec_index = command.index("-c:v") + 1
        self.assertEqual(command[video_codec_index], "copy")

    def test_requires_permission_confirmation_before_download(self):
        with patch.object(downloader, "YoutubeDL") as youtube_dl:
            with self.assertRaises(PermissionError):
                downloader.download_video("https://youtube.com/watch?v=test", "out.mp4", authorized=False)

        youtube_dl.assert_not_called()

    def test_downloads_urls_from_file_and_ignores_comments_and_blank_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            links_file = folder / "ytlink.txt"
            output_directory = folder / "downloads"
            links_file.write_text(
                "# authorized videos\nhttps://youtu.be/first\n\n https://youtu.be/second \n",
                encoding="utf-8",
            )

            with patch.object(
                downloader,
                "download_video",
                side_effect=lambda url, path, *, authorized: Path(path),
            ) as download_video:
                outputs = downloader.download_links(
                    links_file,
                    output_directory,
                    authorized=True,
                )

            self.assertEqual(
                [call.args[0] for call in download_video.call_args_list],
                ["https://youtu.be/first", "https://youtu.be/second"],
            )
            self.assertEqual(
                [path.name for path in outputs],
                ["video_001.mp4", "video_002.mp4"],
            )

    def test_batch_download_skips_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            links_file = folder / "ytlink.txt"
            output_directory = folder / "downloads"
            links_file.write_text("https://youtu.be/first\n", encoding="utf-8")
            output_directory.mkdir()
            existing_output = output_directory / "video_001.mp4"
            existing_output.write_bytes(b"complete")

            with (
                patch.object(downloader, "is_standard_output", return_value=True),
                patch.object(downloader, "download_video") as download_video,
            ):
                outputs = downloader.download_links(
                    links_file,
                    output_directory,
                    authorized=True,
                )

            download_video.assert_not_called()
            self.assertEqual(outputs, [existing_output])

    def test_batch_redownloads_existing_square_output(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            links_file = folder / "ytlink.txt"
            output_directory = folder / "downloads"
            links_file.write_text("https://youtu.be/first\n", encoding="utf-8")
            output_directory.mkdir()
            old_square_output = output_directory / "video_001.mp4"
            old_square_output.write_bytes(b"old square video")

            with (
                patch.object(downloader, "is_standard_output", return_value=False),
                patch.object(
                    downloader,
                    "download_video",
                    return_value=old_square_output,
                ) as download_video,
            ):
                downloader.download_links(links_file, output_directory, authorized=True)

            download_video.assert_called_once()

    def test_downloads_and_converts_to_standard_1080_landscape(self):
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

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "landscape.mp4"
            with (
                patch.object(downloader, "YoutubeDL", FakeYoutubeDL),
                patch.object(downloader.imageio_ffmpeg, "get_ffmpeg_exe", return_value="ffmpeg.exe"),
                patch.object(downloader.subprocess, "run", side_effect=fake_ffmpeg),
            ):
                result = downloader.download_video(
                    "https://youtube.com/watch?v=test",
                    output_path,
                    authorized=True,
                )

            self.assertEqual(result, output_path)
            self.assertEqual(output_path.read_bytes(), b"converted")
            self.assertIn(downloader.VIDEO_FILTER, command_used)
            self.assertIn("libx264", command_used)
            self.assertIn("-loglevel", command_used)
            self.assertIn("-nostats", command_used)
            self.assertEqual(youtube_options["concurrent_fragment_downloads"], 8)
            self.assertEqual(
                downloader.DEFAULT_OUTPUT_DIRECTORY,
                Path(r"H:\YOU TUBE\THE MORTAL WHO SURVIVES"),
            )
            preset_index = command_used.index("-preset") + 1
            self.assertEqual(command_used[preset_index], "ultrafast")


if __name__ == "__main__":
    unittest.main()