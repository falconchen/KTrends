import socket
import unittest
from unittest.mock import patch

from fastapi import HTTPException

import main


class UrlSecurityTests(unittest.TestCase):
    def test_rejects_non_http_and_credentials(self):
        for url in ("file:///etc/passwd", "https://user:pass@example.com/"):
            with self.subTest(url=url), self.assertRaises(HTTPException):
                main._validate_public_url(url)

    @patch("main.socket.getaddrinfo")
    def test_rejects_private_destination(self, getaddrinfo):
        getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ]
        with self.assertRaises(HTTPException) as raised:
            main._validate_public_url("https://example.test/article")
        self.assertEqual(raised.exception.status_code, 400)

    @patch("main.socket.getaddrinfo")
    def test_accepts_public_destination(self, getaddrinfo):
        getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ]
        main._validate_public_url("https://example.com/article")

    @patch("main.get_openai_response", return_value="generated")
    def test_social_post_keeps_source_url(self, _response):
        with patch("main.process_input", return_value="article"):
            result = main.run_social_post("https://example.com/article", "zh-CN")
        self.assertEqual(result, "generated\n\nhttps://example.com/article")


if __name__ == "__main__":
    unittest.main()
