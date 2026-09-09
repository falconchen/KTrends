# AGENTS.md

## Project overview

KTrends is a small FastAPI application that provides an AI content-assistant web UI and authenticated JSON APIs. It supports translation, summaries, social posts, and keyword extraction. OpenAI-compatible model settings and prompt templates are loaded from `.env` and `prompts.conf` when `main.py` is imported.

## Repository map

- `main.py`: FastAPI application, legacy form endpoints, authenticated `/api/v1` endpoints, webpage extraction, and OpenAI-compatible client calls.
- `home.html`: browser UI and its JavaScript client.
- `static/`: images and other static assets.
- `prompts.conf`: shared prompt templates used by both the web UI and API endpoints.
- `.env.example`: non-secret configuration template.
- `docker-compose.yml`: production-style local service definition.
- `Dockerfile`: application image definition.
- `README.md`: setup, API usage, and deployment documentation.

## Development commands

The host may not have the Python dependencies installed. Prefer running checks in the existing Compose service:

```bash
docker compose exec -T ktrends python -m py_compile main.py
docker compose restart ktrends
docker compose logs --tail 50 ktrends
```

For a fresh local environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Before committing, run:

```bash
git diff --check
docker compose exec -T ktrends python -m py_compile main.py
```

There is currently no committed automated test suite. For endpoint changes, use `fastapi.testclient.TestClient` inside the container and mock `get_openai_response` and `get_openai_response_stream` so tests do not consume external API quota.

## API conventions

- Public programmatic endpoints live under `/api/v1` and accept JSON request bodies.
- Protect every `/api/v1` endpoint with `Depends(require_personal_access_token)`.
- Authentication uses `Authorization: Bearer <token>` and `PERSONAL_ACCESS_TOKEN` from `.env`.
- Never place a real token or API key in source code, documentation, logs, tests, or `.env.example`.
- Non-streaming success responses use `{"result": "..."}`.
- A request with `"stream": true` returns `text/event-stream`. Each chunk uses `data: {"content": "..."}` and the stream terminates with `data: [DONE]`.
- Stream responses should retain `Cache-Control: no-cache` and `X-Accel-Buffering: no`.
- Use the same prompt templates for web and API variants of a feature. Do not duplicate prompt text in endpoint implementations.
- Preserve the existing legacy `/api/get_*` and `/api/stream/get_*` form endpoints unless a migration explicitly removes them.
- When `input` may be a URL, pass it through `process_input` and support the optional `css_selector` field.
- Keep API documentation and curl examples in `README.md` synchronized with request and response changes.

Current versioned endpoints:

- `POST /api/v1/translation`
- `POST /api/v1/summary`
- `POST /api/v1/social`
- `POST /api/v1/keywords`
- `POST /api/v1/rewrite`
- `POST /api/v1/title-meta`
- `POST /api/v1/structure`

## Implementation guidance

- Keep changes focused; `main.py` contains legacy code, so avoid broad formatting or unrelated refactors.
- Reuse `get_openai_response`, `get_openai_response_stream`, and `streaming_openai_response` for consistent model and SSE behavior.
- Use `openai_model` from configuration, retaining the current fallback only when necessary for compatibility.
- Validate required strings after trimming whitespace. Use Pydantic bounds for numeric inputs.
- Preserve the social-post behavior that appends the source URL to generated output.
- The existing variable name `socail_prompt_template` is misspelled but widely referenced. Rename it only as a deliberate, fully verified refactor.
- Do not print credentials, authorization headers, or `.env` contents while diagnosing the service.

## Runtime and proxy notes

- Compose mounts the repository at `/app`, but Uvicorn is not running with `--reload`; restart `ktrends` after code or `.env` changes.
- The service listens on container port `8000`; the host port is controlled by `APP_PORT` and may differ by deployment.
- Nginx Proxy Manager Plus sits in front of the public site. Its global sensitive-file rule may block paths ending in `.json`, including `/openapi.json`. A working local schema with a public `403` is therefore a proxy issue, not a FastAPI schema-generation failure.
- Do not edit generated files under `/srv/docker/npmplus/data/nginx/proxy_host/` directly; they are managed by the proxy application.

## Git hygiene

- `.env` is ignored and must remain untracked.
- Do not commit unrelated user changes found in the working tree.
- Use concise conventional commit messages, for example `feat: add authenticated content APIs` or `docs: add contributor guidance`.
