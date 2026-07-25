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

    def test_read_download_query_decodes_url(self):
        url, token, debug = server.read_download_query(
            "/api/download?token=abc&debug=1&url=https%3A%2F%2Fexample.com%2Fvideo"
        )
        self.assertEqual(url, "https://example.com/video")
        self.assertEqual(token, "abc")
        self.assertTrue(debug)


if __name__ == "__main__":
    unittest.main()
