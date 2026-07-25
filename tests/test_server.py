import unittest
from pathlib import Path

import server


class ServerHelpersTest(unittest.TestCase):
    def test_valid_video_url_accepts_http_and_https(self):
        self.assertTrue(server.is_valid_video_url("https://example.com/video.mp4"))
        self.assertTrue(server.is_valid_video_url("http://example.com/watch?v=1"))

    def test_valid_video_url_rejects_other_schemes(self):
        self.assertFalse(server.is_valid_video_url("file:///etc/passwd"))
        self.assertFalse(server.is_valid_video_url("javascript:alert(1)"))
        self.assertFalse(server.is_valid_video_url("not a url"))

    def test_safe_header_filename_removes_bad_characters(self):
        self.assertEqual(
            server.safe_header_filename(Path('my:bad/video"name.mp4')),
            "video_name.mp4",
        )

    def test_friendly_ytdlp_error_explains_login_required(self):
        message = server.friendly_ytdlp_error("ERROR: You need to log in to access this content")
        self.assertIn("giris istiyor", message)
        self.assertIn("Public", message)


if __name__ == "__main__":
    unittest.main()
