import unittest
from unittest.mock import patch
from types import SimpleNamespace

from pydantic import ValidationError
from starlette.testclient import TestClient

import main


class ContentFeatureTests(unittest.TestCase):
    @patch("main.get_openai_response", return_value="generated")
    @patch("main.process_input", return_value="source content")
    def test_rewrite_uses_style_language_and_url_selector(self, process_input, generate):
        result = main.run_rewrite(
            "https://example.com/article",
            "zh-CN",
            "professional",
            "article",
        )

        self.assertEqual(result, "generated")
        process_input.assert_called_once_with("https://example.com/article", "article")
        prompt = generate.call_args.args[0]
        self.assertIn("professional", prompt)
        self.assertIn("zh-CN", prompt)
        self.assertIn("source content", prompt)

    @patch("main.get_openai_response", return_value="generated")
    @patch("main.process_input", return_value="source content")
    def test_title_meta_uses_count_and_keyword(self, _process_input, generate):
        result = main.run_title_meta("article", "en", 3, "content strategy")

        self.assertEqual(result, "generated")
        prompt = generate.call_args.args[0]
        self.assertIn("3 distinct title", prompt)
        self.assertIn("content strategy", prompt)

    @patch("main.get_openai_response", return_value="generated")
    @patch("main.process_input", return_value="source content")
    def test_structure_uses_format_and_faq_count(self, _process_input, generate):
        result = main.run_structure("article", "zh-CN", "article_and_faq", 7)

        self.assertEqual(result, "generated")
        prompt = generate.call_args.args[0]
        self.assertIn("article_and_faq", prompt)
        self.assertIn("Number of FAQ items: 7", prompt)

    def test_new_request_models_validate_options_and_bounds(self):
        invalid_requests = [
            (main.RewriteRequest, {"input": "text", "lang": "en", "style": "unknown"}),
            (main.TitleMetaRequest, {"input": "text", "lang": "en", "num_titles": 11}),
            (main.StructureRequest, {"input": "text", "lang": "en", "format": "other"}),
            (main.StructureRequest, {"input": "text", "lang": "en", "num_faq": 0}),
        ]

        for model, values in invalid_requests:
            with self.subTest(model=model.__name__, values=values), self.assertRaises(ValidationError):
                model(**values)

    @patch("main.get_openai_response", return_value="generated")
    @patch("main.process_input", return_value="source content")
    def test_versioned_endpoints_return_standard_result(self, _process_input, _generate):
        requests = [
            ("/api/v1/rewrite", {"input": "text", "lang": "en", "style": "concise"}),
            ("/api/v1/title-meta", {"input": "text", "lang": "en", "num_titles": 3}),
            (
                "/api/v1/structure",
                {"input": "text", "lang": "en", "format": "faq", "num_faq": 4},
            ),
        ]
        with patch.object(main, "personal_access_token", "test-token"):
            client = TestClient(main.app)
            try:
                for path, payload in requests:
                    with self.subTest(path=path):
                        response = client.post(
                            path,
                            headers={"Authorization": "Bearer test-token"},
                            json=payload,
                        )
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.json(), {"result": "generated"})
            finally:
                client.close()

    @patch("main.process_input", return_value="source content")
    def test_legacy_stream_endpoint_remains_reachable(self, _process_input):
        chunk = SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="rewritten"))]
        )
        with patch("main.get_openai_response_stream", return_value=[chunk]):
            client = TestClient(main.app)
            try:
                response = client.post(
                    "/api/stream/get_rewrite",
                    data={"input": "text", "lang": "en", "style": "polished"},
                )
            finally:
                client.close()

        self.assertEqual(response.status_code, 200)
        self.assertIn('data: {"content": "rewritten"}', response.text)
        self.assertIn("data: [DONE]", response.text)


if __name__ == "__main__":
    unittest.main()
