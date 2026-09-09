import unittest
from unittest.mock import patch
from types import SimpleNamespace
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp.server.auth.provider import AccessToken
from starlette.testclient import TestClient

from mcp_service import Auth0TokenVerifier, create_mcp_app


async def accept_test_token(_self, token):
    if token != "valid-token":
        return None
    return AccessToken(
        token=token,
        client_id="chatgpt",
        scopes=["ktrends:invoke"],
        resource="https://hicms.eu.org/mcp",
        subject="auth0|owner",
    )


class McpProtocolTests(unittest.TestCase):
    def create_app(self):
        return create_mcp_app(
            public_url="https://hicms.eu.org/mcp",
            issuer="https://tenant.auth0.com/",
            audience="https://hicms.eu.org/mcp",
            required_scope="ktrends:invoke",
            allowed_subject="auth0|owner",
            summarize=lambda input, lang, selector: f"summary:{input}:{lang}",
            social_post=lambda input, lang, selector: f"social:{input}:{lang}",
            keywords=lambda input, lang, count, selector: f"keywords:{count}",
            translate=lambda input, to, source: f"translated:{input}:{to}",
        )

    @patch.object(Auth0TokenVerifier, "verify_token", accept_test_token)
    def test_tools_list_and_call_return_structured_result(self):
        headers = {
            "Authorization": "Bearer valid-token",
            "Accept": "application/json, text/event-stream",
        }
        with TestClient(self.create_app(), base_url="https://hicms.eu.org") as client:
            listed = client.post(
                "/mcp",
                headers=headers,
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            )
            self.assertEqual(listed.status_code, 200)
            tools = listed.json()["result"]["tools"]
            self.assertEqual(
                {tool["name"] for tool in tools},
                {"translate_text", "summarize_content", "create_social_post", "extract_keywords"},
            )
            for tool in tools:
                self.assertTrue(tool["annotations"]["readOnlyHint"])
                self.assertFalse(tool["annotations"]["destructiveHint"])
                self.assertTrue(tool["annotations"]["openWorldHint"])
                self.assertEqual(tool["_meta"]["securitySchemes"][0]["scopes"], ["ktrends:invoke"])

            called = client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "translate_text",
                        "arguments": {"input": "hello", "to": "zh-CN"},
                    },
                },
            )
            self.assertEqual(called.status_code, 200)
            result = called.json()["result"]
            self.assertEqual(result["content"], [{"type": "text", "text": "translated:hello:zh-CN"}])
            self.assertEqual(result["structuredContent"], {"result": "translated:hello:zh-CN"})

    @patch.object(Auth0TokenVerifier, "verify_token", accept_test_token)
    def test_missing_token_is_rejected_with_oauth_metadata(self):
        with TestClient(self.create_app(), base_url="https://hicms.eu.org") as client:
            response = client.post(
                "/mcp",
                headers={"Accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            )
            self.assertEqual(response.status_code, 401)
            self.assertIn("resource_metadata=", response.headers["www-authenticate"])

            metadata = client.get("/.well-known/oauth-protected-resource/mcp")
            self.assertEqual(metadata.status_code, 200)
            body = metadata.json()
            self.assertEqual(body["resource"], "https://hicms.eu.org/mcp")
            self.assertEqual(body["authorization_servers"], ["https://tenant.auth0.com/"])


class Auth0VerifierTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.verifier = Auth0TokenVerifier(
            "https://tenant.auth0.com/",
            "https://hicms.eu.org/mcp",
            "ktrends:invoke",
            "auth0|owner",
        )
        self.verifier.jwks.get_signing_key_from_jwt = lambda _token: SimpleNamespace(
            key=self.private_key.public_key()
        )

    def token(self, **overrides):
        now = int(time.time())
        claims = {
            "iss": "https://tenant.auth0.com/",
            "aud": "https://hicms.eu.org/mcp",
            "sub": "auth0|owner",
            "scope": "ktrends:invoke",
            "iat": now,
            "exp": now + 300,
        }
        claims.update(overrides)
        return jwt.encode(claims, self.private_key, algorithm="RS256")

    async def test_accepts_valid_token(self):
        access_token = await self.verifier.verify_token(self.token())
        self.assertEqual(access_token.subject, "auth0|owner")
        self.assertEqual(access_token.resource, "https://hicms.eu.org/mcp")

    async def test_rejects_wrong_audience_scope_subject_and_expiry(self):
        invalid_tokens = [
            self.token(aud="https://other.example/mcp"),
            self.token(scope="other:scope"),
            self.token(sub="auth0|someone-else"),
            self.token(exp=int(time.time()) - 1),
        ]
        for token in invalid_tokens:
            with self.subTest(token=token[-10:]):
                self.assertIsNone(await self.verifier.verify_token(token))


if __name__ == "__main__":
    unittest.main()
