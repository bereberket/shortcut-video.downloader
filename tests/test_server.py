import tempfile
import threading
import unittest
from subprocess import CompletedProcess
from pathlib import Path
from urllib.request import urlopen
from unittest.mock import patch

import server


class ServerHelpersTest(unittest.TestCase):
    def test_valid_video_url_accepts_http_and_https(self):
        self.assertTrue(server.is_valid_video_url("https://example.com/video.mp4"))
        self.assertTrue(server.is_valid_video_url("http://example.com/watch?v=1"))

    def test_valid_video_url_rejects_other_schemes(self):
        self.assertFalse(server.is_valid_video_url("file:///etc/passwd"))
        self.assertFalse(server.is_valid_video_url("javascript:alert(1)"))
        self.assertFalse(server.is_valid_video_url("not a url"))

    def test_normalize_video_url_extracts_link_from_share_text(self):
        self.assertEqual(
            server.normalize_video_url("Watch this https%3A%2F%2Fwww.instagram.com%2Freel%2Fabc%2F extra"),
            "https://www.instagram.com/reel/abc/",
        )

    def test_normalize_video_url_adds_scheme_for_www(self):
        self.assertEqual(
            server.normalize_video_url("www.instagram.com/reel/abc/"),
            "https://www.instagram.com/reel/abc/",
        )

    def test_safe_header_filename_removes_bad_characters(self):
        self.assertEqual(
            server.safe_header_filename(Path('my:bad/video"name.mp4')),
            "video_name.mp4",
        )

    def test_friendly_ytdlp_error_explains_login_required(self):
        message = server.friendly_ytdlp_error("ERROR: You need to log in to access this content")
        self.assertIn("giris istiyor", message)
        self.assertIn("Public", message)

    def test_ios_compatible_mp4_is_detected(self):
        probe = CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"streams":[{"codec_type":"video","codec_name":"h264"},'
            '{"codec_type":"audio","codec_name":"aac"}]}',
            stderr="",
        )
        with patch.object(server.subprocess, "run", return_value=probe):
            self.assertTrue(server.is_ios_compatible_video(Path("video.mp4")))

    def test_auto_mode_skips_transcode_for_compatible_mp4(self):
        source = Path("video.mp4")
        with (
            patch.object(server, "IOS_TRANSCODE_MODE", "auto"),
            patch.object(server, "is_ios_compatible_video", return_value=True),
            patch.object(server.subprocess, "run") as run,
        ):
            self.assertEqual(server.make_ios_compatible_video(source, Path(".")), source)
            run.assert_not_called()

    def test_read_download_query_decodes_url(self):
        url, token, debug, prepare = server.read_download_query(
            "/api/download?token=abc&debug=1&prepare=1&url=https%3A%2F%2Fexample.com%2Fvideo"
        )
        self.assertEqual(url, "https://example.com/video")
        self.assertEqual(token, "abc")
        self.assertTrue(debug)
        self.assertTrue(prepare)

    def test_read_download_query_finds_raw_encoded_url(self):
        url, token, debug, _prepare = server.read_download_query(
            "/api/download?debug=1&https%3A%2F%2Fwww.instagram.com%2Freel%2Fabc%2F"
        )
        self.assertEqual(url, "https://www.instagram.com/reel/abc/")
        self.assertEqual(token, "")
        self.assertTrue(debug)

    def test_read_download_query_accepts_alternate_key(self):
        url, _token, _debug, _prepare = server.read_download_query(
            "/api/download?u=Watch%2520this%2520https%253A%252F%252Fwww.instagram.com%252Freel%252Fabc%252F"
        )
        self.assertEqual(url, "https://www.instagram.com/reel/abc/")

    def test_background_download_job_stores_ready_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_dir = root / "job"
            ready_dir = root / "ready"
            job_dir.mkdir()
            source = job_dir / "video.mp4"
            source.write_bytes(b"video-data")

            server._download_jobs.clear()
            server._active_downloads = 0
            with (
                patch.object(server, "READY_ROOT", ready_dir),
                patch.object(server, "download_video", return_value=(source, job_dir)),
            ):
                job_id = server.start_download_job("https://example.com/video")
                event = server._download_jobs[job_id]["event"]
                self.assertTrue(event.wait(timeout=2))
                job = server._download_jobs[job_id]

            self.assertEqual(job["state"], "ready")
            self.assertEqual(job["file_size"], len(b"video-data"))
            self.assertTrue((ready_dir / str(job["file_name"])).exists())
            self.assertEqual(server._active_downloads, 0)
            server._download_jobs.clear()

    def test_background_download_job_rejects_invalid_url(self):
        with self.assertRaises(server.ShortcutDownloadError):
            server.start_download_job("not-a-url")

    def test_get_download_follows_wait_redirects_to_video(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_dir = root / "job"
            ready_dir = root / "ready"
            job_dir.mkdir()
            source = job_dir / "video.mp4"
            source.write_bytes(b"real-video-bytes")

            server._download_jobs.clear()
            server._active_downloads = 0
            httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
            http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            with (
                patch.object(server, "READY_ROOT", ready_dir),
                patch.object(server, "download_video", return_value=(source, job_dir)),
            ):
                http_thread.start()
                port = httpd.server_address[1]
                with urlopen(
                    f"http://127.0.0.1:{port}/api/download"
                    "?url=https%3A%2F%2Fexample.com%2Fvideo",
                    timeout=5,
                ) as response:
                    self.assertEqual(response.headers.get_content_type(), "video/mp4")
                    self.assertEqual(response.read(), b"real-video-bytes")

            httpd.shutdown()
            httpd.server_close()
            http_thread.join(timeout=2)
            server._download_jobs.clear()


if __name__ == "__main__":
    unittest.main()
