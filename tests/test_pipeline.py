import os
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

from youtube_automation import downloader, pipeline
import requests


class PipelineModeTests(unittest.TestCase):
    def test_choose_pipeline_mode_reprompts_for_invalid_choice(self):
        choices = iter(["5", "3"])

        self.assertEqual(pipeline.choose_pipeline_mode(lambda _: next(choices)), 3)

    def test_download_only_modes_skip_transcription_stages(self):
        for mode, include_audio in ((1, False), (2, True)):
            with self.subTest(mode=mode):
                with (
                    patch.object(pipeline.downloader, "run") as download,
                    patch.object(pipeline.gemini_transcribe, "run_queue") as gemini,
                    patch.object(pipeline.chatgpt_transcribe, "run") as chatgpt,
                ):
                    pipeline._run_pipeline(mode)

                download.assert_called_once_with(include_audio=include_audio)
                gemini.assert_not_called()
                chatgpt.assert_not_called()

    def test_gemini_mode_skips_chatgpt_and_all_mode_runs_it(self):
        with (
            patch.object(pipeline.downloader, "run") as download,
            patch.object(pipeline.gemini_transcribe, "run_queue") as gemini,
            patch.object(pipeline.chatgpt_transcribe, "run") as chatgpt,
        ):
            pipeline._run_pipeline(3)

        download.assert_called_once()
        gemini.assert_called_once()
        chatgpt.assert_not_called()

        with (
            patch.object(pipeline.downloader, "run") as download,
            patch.object(pipeline.gemini_transcribe, "run_queue") as gemini,
            patch.object(pipeline.chatgpt_transcribe, "run") as chatgpt,
        ):
            pipeline._run_pipeline(4)

        download.assert_called_once()
        gemini.assert_called_once()
        chatgpt.assert_called_once()


class DownloaderModeTests(unittest.TestCase):
    def test_video_only_download_does_not_require_or_download_audio(self):
        with (
            patch.object(downloader, "fetch_video_data", return_value={"videoUrl": "video"}),
            patch.object(downloader, "download_media_with_refresh") as download_media,
            patch.object(downloader.job_state, "update_part"),
            patch.object(downloader.job_state, "record_metric"),
        ):
            result = downloader.process_part("source", 7, include_audio=False)

        self.assertTrue(result)
        download_media.assert_called_once_with(
            "source",
            "video",
            downloader.os.path.join(downloader.VIDEO_FOLDER, "PART-7.mp4"),
            "Video",
            7,
        )

    def test_interrupted_download_resumes_from_partial_file(self):
        def response(status_code, headers, chunks):
            result = MagicMock()
            result.status_code = status_code
            result.headers = headers
            result.__enter__.return_value = result
            result.iter_content.return_value = chunks
            return result

        def interrupted_chunks():
            yield b"12345"
            raise requests.exceptions.ChunkedEncodingError("incomplete response")

        head_response = MagicMock()
        head_response.headers = {"content-length": "10"}
        head_response.__enter__.return_value = head_response
        first_response = response(
            200,
            {"content-length": "10"},
            interrupted_chunks(),
        )
        resumed_response = response(
            206,
            {"content-length": "5", "Content-Range": "bytes 5-9/10"},
            iter([b"67890"]),
        )
        session = Mock()
        session.head.return_value = head_response
        session.get.side_effect = [first_response, resumed_response]

        with tempfile.TemporaryDirectory() as folder:
            filename = os.path.join(folder, "video.mp4")
            with (
                patch.object(downloader, "get_session", return_value=session),
                patch.object(downloader._thread_state, "cdn_headers", {}, create=True),
                patch.object(downloader.config, "MIN_COMPLETE_FILE_SIZE", 5),
                patch.object(downloader.time, "sleep"),
            ):
                downloader.download_file("media-url", filename, "Video", retries=2)

            self.assertEqual(session.get.call_count, 2)
            self.assertEqual(
                session.get.call_args_list[1].kwargs["headers"]["Range"],
                "bytes=5-",
            )
            with open(filename, "rb") as file:
                self.assertEqual(file.read(), b"1234567890")


if __name__ == "__main__":
    unittest.main()