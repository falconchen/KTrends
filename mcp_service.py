"""Authenticated MCP surface for the KTrends content tools."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from collections.abc import Callable
import hashlib
import json
import logging
import time
from typing import Annotated, Literal
from urllib.parse import urlparse

import anyio
import jwt
from jwt import PyJWKClient
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field


audit_logger = logging.getLogger("uvicorn.error.ktrends.mcp.audit")

TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    openWorldHint=True,
)


def _anonymous_subject(subject: str) -> str:
    """Return a stable, non-reversible identifier without exposing the Auth0 subject."""
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()[:16]


def _log_tool_audit(
    *,
    tool: str,
    subject: str,
    duration_ms: int,
    status: str,
    error_type: str | None,
) -> None:
    event = {
        "duration_ms": duration_ms,
        "error_type": error_type,
        "event": "mcp_tool_call",
        "status": status,
        "tool": tool,
        "user": _anonymous_subject(subject) if subject else "anonymous",
    }
    audit_logger.info(json.dumps(event, separators=(",", ":"), sort_keys=True))


class Auth0TokenVerifier:
    """Validate Auth0 RS256 access tokens and restrict use to one subject."""

    def __init__(self, issuer: str, audience: str, required_scope: str, allowed_subject: str):
        self.issuer = issuer.rstrip("/") + "/"
        self.audience = audience
        self.required_scope = required_scope
        self.allowed_subject = allowed_subject
        self.jwks = PyJWKClient(f"{self.issuer}.well-known/jwks.json", cache_keys=True)

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            signing_key = await anyio.to_thread.run_sync(self.jwks.get_signing_key_from_jwt, token)
            claims = await anyio.to_thread.run_sync(
                lambda: jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["RS256"],
                    audience=self.audience,
                    issuer=self.issuer,
                    options={"require": ["exp", "iat", "sub"]},
                )
            )
        except (jwt.PyJWTError, jwt.PyJWKClientError, OSError, ValueError):
            return None

        subject = claims.get("sub")
        if not subject or subject != self.allowed_subject:
            return None

        raw_scope = claims.get("scope", "")
        scopes = raw_scope.split() if isinstance(raw_scope, str) else list(raw_scope or [])
        if self.required_scope not in scopes:
            return None

        return AccessToken(
            token=token,
            client_id=str(claims.get("azp") or claims.get("client_id") or "chatgpt"),
            scopes=scopes,
            expires_at=claims.get("exp"),
            resource=self.audience,
            subject=subject,
            claims=claims,
        )


class SubjectRateLimiter:
    def __init__(self, calls: int, window_seconds: int):
        self.calls = calls
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, subject: str) -> None:
        now = time.monotonic()
        async with self._lock:
            events = self._events[subject]
            while events and events[0] <= now - self.window_seconds:
                events.popleft()
            if len(events) >= self.calls:
                raise ToolError("Rate limit exceeded; try again later")
            events.append(now)


def create_mcp_app(
    *,
    public_url: str,
    issuer: str,
    audience: str,
    required_scope: str,
    allowed_subject: str,
    summarize: Callable[[str, str, str | None], str],
    social_post: Callable[[str, str, str | None], str],
    keywords: Callable[[str, str, int, str | None], str],
    translate: Callable[[str, str, str | None], str],
    rewrite: Callable[[str, str, str, str | None], str],
    title_meta: Callable[[str, str, int, str | None, str | None], str],
    structure: Callable[[str, str, str, int, str | None], str],
    max_concurrency: int = 4,
    timeout_seconds: float = 120,
    rate_limit_calls: int = 30,
    rate_limit_window: int = 60,
):
    """Create a stateless, Auth0-protected Streamable HTTP MCP application."""
    if not issuer or not allowed_subject:
        raise ValueError("AUTH0_ISSUER and AUTH0_ALLOWED_SUBJECT are required when MCP is enabled")

    verifier = Auth0TokenVerifier(issuer, audience, required_scope, allowed_subject)
    server = MCPServer(
        name="ktrends",
        title="KTrends Content Assistant",
        version="1.1.0",
        instructions=(
            "Use one focused tool for translation, summarization, social posts, keyword extraction, "
            "rewriting, title and metadata creation, or article and FAQ structuring. "
            "Inputs may be plain text or a public HTTP(S) article URL where documented."
        ),
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url=issuer,
            resource_server_url=public_url,
            required_scopes=[required_scope],
            validate_token_resource=True,
        ),
    )
    semaphore = asyncio.Semaphore(max_concurrency)
    limiter = SubjectRateLimiter(rate_limit_calls, rate_limit_window)
    oauth_meta = {"securitySchemes": [{"type": "oauth2", "scopes": [required_scope]}]}

    async def invoke(tool: str, fn: Callable[..., str], *args) -> str:
        started = time.perf_counter()
        subject = ""
        status = "error"
        error_type: str | None = None
        access_token = get_access_token()
        try:
            if not access_token or not access_token.subject:
                raise ToolError("Authentication is required")
            subject = access_token.subject
            await limiter.check(subject)
            with anyio.fail_after(timeout_seconds):
                async with semaphore:
                    result = await anyio.to_thread.run_sync(lambda: fn(*args))
            status = "success"
            return result
        except TimeoutError as exc:
            error_type = "TimeoutError"
            raise ToolError("The content operation timed out") from exc
        except ToolError as exc:
            error_type = type(exc).__name__
            raise
        except Exception as exc:
            error_type = type(exc).__name__
            raise ToolError("The content operation failed") from None
        finally:
            _log_tool_audit(
                tool=tool,
                subject=subject,
                duration_ms=round((time.perf_counter() - started) * 1000),
                status=status,
                error_type=error_type,
            )

    @server.tool(
        name="translate_text",
        title="Translate text",
        description="Translate text to a requested language, optionally specifying the source language.",
        annotations=TOOL_ANNOTATIONS,
        meta=oauth_meta,
    )
    async def translate_text(
        input: Annotated[str, Field(min_length=1, description="Text to translate")],
        to: Annotated[str, Field(min_length=1, description="Target language")],
        from_language: Annotated[
            str | None,
            Field(description="Source language; omit to detect automatically"),
        ] = None,
    ) -> str:
        return await invoke(
            "translate_text",
            translate,
            input.strip(),
            to.strip(),
            from_language.strip() if from_language else None,
        )

    @server.tool(
        name="summarize_content",
        title="Summarize content",
        description="Summarize text or the main content of a public webpage in the requested language.",
        annotations=TOOL_ANNOTATIONS,
        meta=oauth_meta,
    )
    async def summarize_content(
        input: Annotated[str, Field(min_length=1, description="Text or public HTTP(S) URL")],
        lang: Annotated[str, Field(min_length=1, description="Output language")],
        css_selector: Annotated[
            str | None, Field(description="Optional CSS selector when input is a URL")
        ] = None,
    ) -> str:
        return await invoke(
            "summarize_content",
            summarize,
            input.strip(),
            lang.strip(),
            css_selector.strip() if css_selector else None,
        )

    @server.tool(
        name="create_social_post",
        title="Create social post",
        description="Create a social-media post from text or a public webpage in the requested language.",
        annotations=TOOL_ANNOTATIONS,
        meta=oauth_meta,
    )
    async def create_social_post(
        input: Annotated[str, Field(min_length=1, description="Text or public HTTP(S) URL")],
        lang: Annotated[str, Field(min_length=1, description="Output language")],
        css_selector: Annotated[
            str | None, Field(description="Optional CSS selector when input is a URL")
        ] = None,
    ) -> str:
        return await invoke(
            "create_social_post",
            social_post,
            input.strip(),
            lang.strip(),
            css_selector.strip() if css_selector else None,
        )

    @server.tool(
        name="extract_keywords",
        title="Extract keywords",
        description="Extract a requested number of keywords from text or a public webpage.",
        annotations=TOOL_ANNOTATIONS,
        meta=oauth_meta,
    )
    async def extract_keywords(
        input: Annotated[str, Field(min_length=1, description="Text or public HTTP(S) URL")],
        lang: Annotated[str, Field(min_length=1, description="Output language")],
        num_keywords: Annotated[int, Field(ge=1, le=20, description="Number of keywords")] = 5,
        css_selector: Annotated[
            str | None, Field(description="Optional CSS selector when input is a URL")
        ] = None,
    ) -> str:
        return await invoke(
            "extract_keywords",
            keywords,
            input.strip(),
            lang.strip(),
            num_keywords,
            css_selector.strip() if css_selector else None,
        )

    @server.tool(
        name="rewrite_content",
        title="Rewrite content",
        description="Rewrite or polish text or public webpage content in a selected style.",
        annotations=TOOL_ANNOTATIONS,
        meta=oauth_meta,
    )
    async def rewrite_content(
        input: Annotated[str, Field(min_length=1, description="Text or public HTTP(S) URL")],
        lang: Annotated[str, Field(min_length=1, description="Output language")],
        style: Annotated[
            Literal["polished", "concise", "professional", "conversational", "marketing"],
            Field(description="Rewriting style"),
        ] = "polished",
        css_selector: Annotated[
            str | None, Field(description="Optional CSS selector when input is a URL")
        ] = None,
    ) -> str:
        return await invoke(
            "rewrite_content",
            rewrite,
            input.strip(),
            lang.strip(),
            style,
            css_selector.strip() if css_selector else None,
        )

    @server.tool(
        name="create_title_meta",
        title="Create titles and meta description",
        description="Create title candidates and a meta description from text or a public webpage.",
        annotations=TOOL_ANNOTATIONS,
        meta=oauth_meta,
    )
    async def create_title_meta(
        input: Annotated[str, Field(min_length=1, description="Text or public HTTP(S) URL")],
        lang: Annotated[str, Field(min_length=1, description="Output language")],
        num_titles: Annotated[int, Field(ge=1, le=10, description="Number of titles")] = 5,
        target_keyword: Annotated[
            str | None, Field(max_length=100, description="Optional target keyword")
        ] = None,
        css_selector: Annotated[
            str | None, Field(description="Optional CSS selector when input is a URL")
        ] = None,
    ) -> str:
        return await invoke(
            "create_title_meta",
            title_meta,
            input.strip(),
            lang.strip(),
            num_titles,
            target_keyword.strip() if target_keyword else None,
            css_selector.strip() if css_selector else None,
        )

    @server.tool(
        name="structure_content",
        title="Structure article and FAQ",
        description="Create a structured article, FAQ, or both from text or a public webpage.",
        annotations=TOOL_ANNOTATIONS,
        meta=oauth_meta,
    )
    async def structure_content(
        input: Annotated[str, Field(min_length=1, description="Text or public HTTP(S) URL")],
        lang: Annotated[str, Field(min_length=1, description="Output language")],
        format: Annotated[
            Literal["article", "faq", "article_and_faq"],
            Field(description="Requested output format"),
        ] = "article_and_faq",
        num_faq: Annotated[int, Field(ge=1, le=20, description="Number of FAQ items")] = 5,
        css_selector: Annotated[
            str | None, Field(description="Optional CSS selector when input is a URL")
        ] = None,
    ) -> str:
        return await invoke(
            "structure_content",
            structure,
            input.strip(),
            lang.strip(),
            format,
            num_faq,
            css_selector.strip() if css_selector else None,
        )

    return server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        max_request_body_size=1024 * 1024,
        host=urlparse(public_url).hostname or "127.0.0.1",
    )
