from contextlib import asynccontextmanager
import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlparse

from fastapi import Depends, FastAPI, HTTPException, Query, Form, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import requests
from pydantic import BaseModel, Field
from bs4 import BeautifulSoup
from charset_normalizer import from_bytes
from dotenv import load_dotenv
import openai
from openai import OpenAI
from pathlib import Path
from typing import Literal
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
import aiofiles
import json
import secrets

import os

logger = logging.getLogger("ktrends")

# Load environment variables from a .env file
# 获取当前文件所在目录
env_path = Path('.') / '.env'
# 加载 .env 文件中的环境变量
load_dotenv(dotenv_path=env_path)

#加载 prompts模板
prompts_path = Path('.') / 'prompts.conf'
load_dotenv(dotenv_path=prompts_path)


openai_api_key = os.getenv("OPENAI_API_KEY")
openai_base_url = os.getenv("OPENAI_BASE_URL")
openai_model = os.getenv("OPENAI_MODEL")
personal_access_token = os.getenv("PERSONAL_ACCESS_TOKEN")
mcp_enabled = os.getenv("MCP_ENABLED", "false").lower() in {"1", "true", "yes"}
mcp_public_url = os.getenv("MCP_PUBLIC_URL", "https://hicms.eu.org/mcp").rstrip("/")
auth0_issuer_value = os.getenv("AUTH0_ISSUER", "").rstrip("/")
auth0_issuer = f"{auth0_issuer_value}/" if auth0_issuer_value else ""
auth0_audience = os.getenv("AUTH0_AUDIENCE", mcp_public_url)
auth0_required_scope = os.getenv("AUTH0_REQUIRED_SCOPE", "ktrends:invoke")
auth0_allowed_subject = os.getenv("AUTH0_ALLOWED_SUBJECT", "")
keywords_prompt_template = os.getenv("KEYWORDS_PROMPT")
summary_prompt_template = os.getenv("SUMMARY_PROMPT")
socail_prompt_template = os.getenv("SOCAIL_POST_PROMPT")
#socail_prompt_template = os.getenv("XHS_POST_PROMPT")
translate_prompt_template = os.getenv("TRANSLATE_POST_PROMPT")
rewrite_prompt_template = os.getenv("REWRITE_PROMPT")
title_meta_prompt_template = os.getenv("TITLE_META_PROMPT")
structure_prompt_template = os.getenv("STRUCTURE_PROMPT")

lang = os.getenv("DEFAULT_LANG")



headers = {
        'User-Agent': os.getenv("DEFAULT_UA")
}

URL_CONNECT_TIMEOUT = float(os.getenv("URL_CONNECT_TIMEOUT", "5"))
URL_READ_TIMEOUT = float(os.getenv("URL_READ_TIMEOUT", "10"))
URL_MAX_RESPONSE_BYTES = int(os.getenv("URL_MAX_RESPONSE_BYTES", str(2 * 1024 * 1024)))
URL_MAX_EXTRACTED_CHARS = int(os.getenv("URL_MAX_EXTRACTED_CHARS", "100000"))
URL_MAX_REDIRECTS = int(os.getenv("URL_MAX_REDIRECTS", "5"))
# print(ua_string,openai_api_key,openai_base_url)


app = FastAPI(title="HiCMS API")
app.mount("/static", StaticFiles(directory="static"), name="static")

bearer_scheme = HTTPBearer(auto_error=False)


def require_personal_access_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    """Authenticate versioned API requests with the token configured in .env."""
    if not personal_access_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication is not configured",
        )

    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not secrets.compare_digest(credentials.credentials, personal_access_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Personal Access Token",
            headers={"WWW-Authenticate": "Bearer"},
        )


class TranslationRequest(BaseModel):
    input: str = Field(..., min_length=1, description="Text to translate")
    from_: str | None = Field(
        default=None,
        alias="from",
        description="Source language; omit to detect automatically",
    )
    to: str = Field(..., min_length=1, description="Target language")
    stream: bool = Field(default=False, description="Return Server-Sent Events")


class ContentRequest(BaseModel):
    input: str = Field(..., min_length=1, description="Text or URL to process")
    lang: str = Field(..., min_length=1, description="Output language")
    css_selector: str | None = Field(
        default=None,
        description="CSS selector used when input is a URL",
    )
    stream: bool = Field(default=False, description="Return Server-Sent Events")


class KeywordsRequest(ContentRequest):
    num_keywords: int = Field(default=5, ge=1, le=20, description="Number of keywords")


class RewriteRequest(ContentRequest):
    style: Literal["polished", "concise", "professional", "conversational", "marketing"] = Field(
        default="polished",
        description="Rewriting style",
    )


class TitleMetaRequest(ContentRequest):
    num_titles: int = Field(default=5, ge=1, le=10, description="Number of title candidates")
    target_keyword: str | None = Field(
        default=None,
        max_length=100,
        description="Optional target keyword to use naturally",
    )


class StructureRequest(ContentRequest):
    format: Literal["article", "faq", "article_and_faq"] = Field(
        default="article_and_faq",
        description="Requested output structure",
    )
    num_faq: int = Field(default=5, ge=1, le=20, description="Number of FAQ items")

@app.get("/", response_class=HTMLResponse)
async def read_home():
    # 异步读取 home.html 文件
    async with aiofiles.open("home.html", mode="r", encoding="utf-8") as f:
        content = await f.read()
    return HTMLResponse(content)


@app.get("/fetch_url")
async def fetch_url(
    url: str = Query(..., description="The URL to fetch"),
    selector: str = Query(None, description="The CSS selector to extract content")
):

    try:
        result = fetch_and_parse_url(url, headers, selector)
        return result
    except requests.RequestException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _validate_public_url(url: str) -> None:
    """Reject URLs that can reach local, private, or otherwise special networks."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Only public HTTP(S) URLs are allowed")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="URLs containing credentials are not allowed")
    if parsed.hostname.lower() == "localhost":
        raise HTTPException(status_code=400, detail="Private network URLs are not allowed")

    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port)}
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail="URL hostname could not be resolved") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise HTTPException(status_code=400, detail="Private network URLs are not allowed")


def fetch_and_parse_url(url, headers, selector=None, timeout=None):
        html = fetch_html(url=url, headers=headers, timeout=timeout)
        return parse_html(html, selector)

def fetch_html(url, headers, timeout=None):
        current_url = url
        request_timeout = timeout or (URL_CONNECT_TIMEOUT, URL_READ_TIMEOUT)
        with requests.Session() as session:
            for redirect_count in range(URL_MAX_REDIRECTS + 1):
                _validate_public_url(current_url)
                with session.get(
                    current_url,
                    headers=headers,
                    timeout=request_timeout,
                    allow_redirects=False,
                    stream=True,
                ) as response:
                    if response.is_redirect or response.is_permanent_redirect:
                        if redirect_count >= URL_MAX_REDIRECTS:
                            raise HTTPException(status_code=400, detail="Too many URL redirects")
                        location = response.headers.get("location")
                        if not location:
                            raise HTTPException(status_code=400, detail="Redirect is missing a location")
                        current_url = urljoin(current_url, location)
                        continue

                    response.raise_for_status()
                    chunks = []
                    size = 0
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        size += len(chunk)
                        if size > URL_MAX_RESPONSE_BYTES:
                            raise HTTPException(status_code=413, detail="URL response is too large")
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    detected = from_bytes(content).best()
                    encoding = detected.encoding if detected else "utf-8"
                    return content.decode(encoding, errors="replace")

        raise HTTPException(status_code=400, detail="Unable to fetch URL")
        

def parse_html(html, selector=None):
    # Parse the HTML content using BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.title.string if soup.title else "No title found"
    if not selector:
        selector = "body"
        
    elements = soup.select(selector)
    content = [element.get_text(" ", strip=True) for element in elements]
    extracted_length = sum(len(item) for item in content)
    if extracted_length > URL_MAX_EXTRACTED_CHARS:
        remaining = URL_MAX_EXTRACTED_CHARS
        truncated = []
        for item in content:
            if remaining <= 0:
                break
            truncated.append(item[:remaining])
            remaining -= len(truncated[-1])
        content = truncated
    # if selector:
    #     elements = soup.select(selector)
    #     content = [element.get_text(strip=True) for element in elements]
    # else:
        
    #     #使用llm
    #     content = html


    return {
        "title": title,            
        "content": content,
        "raw":html
    }


def process_input(input,css_selector=None):

    text = input.strip()

    if text.startswith("http://") or text.startswith("https://"):
        url = text
        result = fetch_and_parse_url(url, headers, selector=css_selector)
        
        # 使用 join 将 content 中的元素连接成一个字符串
        content = "\n".join(result['content'])

        # 将 title 和 content 组合成一个新的字符串 text            
        text = "《{title}》\n Content: {content}\n Source URL: {url}".format(title=result['title'],content=content,url=url)
        
    return text


def prepare_form_content(input_value: str, output_language: str, css_selector: str | None):
    input_value = input_value.strip()
    output_language = output_language.strip()
    css_selector = css_selector.strip() if css_selector else None
    if not input_value or not output_language:
        raise HTTPException(status_code=422, detail="input and lang must not be blank")
    return input_value, output_language, css_selector


def get_openai_response(prompt):

        openai_client = OpenAI(api_key=openai_api_key, base_url=openai_base_url)
        response = openai_client.chat.completions.create(
            model=openai_model or "deepseek-chat",
            messages=[
                {"role": "system", "content": "You are a helpful content assistant"},
                {"role": "user", "content": prompt},
            ],
            stream=False
        )

        return response.choices[0].message.content.strip()


def get_openai_response_stream(prompt):
        openai_client = OpenAI(api_key=openai_api_key, base_url=openai_base_url)
        response = openai_client.chat.completions.create(
            model=openai_model or "deepseek-chat",
            messages=[
                {"role": "system", "content": "You are a helpful content assistant"},
                {"role": "user", "content": prompt},
            ],
            stream=True
        )

        return response


# 定义 POST 接口，使用 Form 接受表单数据
@app.post("/api/get_keywords")
async def get_keywords(input: str = Form(..., description="The text or url from which to extract keywords."),
                       lang: str = Form(..., description="The language of the text ai responds."),
                       num_keywords: int = Form(5, description="The number of keywords to extract"),
                       css_selector: str = Form(None, description="CSS selector to extract content from HTML, optional")
                       ):
    
    try:
        #if input is url        
        text = process_input(input,css_selector)

        # Prepare the prompt using the template and provided parameters        
        prompt = keywords_prompt_template.format(
            num_keywords=num_keywords,
            text=text,  # Strip any leading/trailing whitespace
            lang=lang
        )        
        return {
            "result": get_openai_response(prompt)
        } 

    except Exception as e:        
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.post("/api/get_social")
async def get_social(input: str = Form(..., description="The text from which to get content for social media post."),
                       lang: str = Form(..., description="The language of the text ai responds."),                       
                       css_selector: str = Form(None, description="CSS selector to extract content from HTML, optional")
                       ):
                       
    
    try:
        #if input is url        
        text = process_input(input,css_selector)

        # Prepare the prompt using the template and provided parameters        
        prompt = socail_prompt_template.format(            
            text=text,  # Strip any leading/trailing whitespace
            lang=lang

        )   
        
        result = get_openai_response(prompt)

        if input.startswith("http://") or input.startswith("https://"):
            result  =f"{result}\n\n{input}"
            

        return {
            "result": result
        } 

    except Exception as e:        
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")
    

@app.post("/api/get_summary")
async def get_summary(input: str = Form(..., description="The text or urlfrom which to get_summary"),
                       lang: str = Form(..., description="The language of the text ai responds."),                       
                       css_selector: str = Form(None, description="CSS selector to extract content from HTML, optional")
                       ):
                       
    
    try:
        #if input is url        
        text = process_input(input,css_selector)
        # Prepare the prompt using the template and provided parameters        
        
        prompt = summary_prompt_template.format(            
            text=text,  # Strip any leading/trailing whitespace
            lang=lang
        )   
        
        result = get_openai_response(prompt)
        return {
            "result": result
        } 

    except Exception as e:        
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.post("/api/get_rewrite")
async def get_rewrite(
    input: str = Form(..., min_length=1, description="The text or URL to rewrite"),
    lang: str = Form(..., min_length=1, description="The output language"),
    style: Literal["polished", "concise", "professional", "conversational", "marketing"] = Form(
        "polished", description="The rewriting style"
    ),
    css_selector: str = Form(None, description="CSS selector for URL input, optional"),
):
    try:
        input_value, output_language, css_selector = prepare_form_content(input, lang, css_selector)
        return {"result": run_rewrite(input_value, output_language, style, css_selector)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.post("/api/get_title_meta")
async def get_title_meta(
    input: str = Form(..., min_length=1, description="The text or URL to create titles for"),
    lang: str = Form(..., min_length=1, description="The output language"),
    num_titles: int = Form(5, ge=1, le=10, description="Number of title candidates"),
    target_keyword: str = Form(None, max_length=100, description="Optional target keyword"),
    css_selector: str = Form(None, description="CSS selector for URL input, optional"),
):
    try:
        input_value, output_language, css_selector = prepare_form_content(input, lang, css_selector)
        return {
            "result": run_title_meta(
                input_value,
                output_language,
                num_titles,
                target_keyword.strip() if target_keyword else None,
                css_selector,
            )
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.post("/api/get_structure")
async def get_structure(
    input: str = Form(..., min_length=1, description="The text or URL to structure"),
    lang: str = Form(..., min_length=1, description="The output language"),
    format: Literal["article", "faq", "article_and_faq"] = Form(
        "article_and_faq", description="The requested output format"
    ),
    num_faq: int = Form(5, ge=1, le=20, description="Number of FAQ items"),
    css_selector: str = Form(None, description="CSS selector for URL input, optional"),
):
    try:
        input_value, output_language, css_selector = prepare_form_content(input, lang, css_selector)
        return {
            "result": run_structure(
                input_value, output_language, format, num_faq, css_selector
            )
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")
    
@app.post("/api/extract_content")
async def extract_content(input: str = Form(..., description="The html codes.")):

    try:
        openai_client = OpenAI(api_key=openai_api_key, base_url=openai_base_url)
        response = openai_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                
                {
                "role": "user",
                "content": "You will act like a \"read it later\" function, extracting the main content of the webpage from the HTML I provide (excluding HTML tags). If no content is found, return NULL."
                },
                {
                "role": "assistant",
                "content": "Sure, please provide the HTML content of the webpage, and I will extract the main content for you."
                },
                {"role": "user", "content": input.strip()},
            ],
            stream=False
        )

        content = response.choices[0].message.content.strip()

        return {
            "result": content
        }
    
    except Exception as e:
        
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")
    


def build_translation_prompt(input_text: str, source_language: str | None, target_language: str):
    prompt = translate_prompt_template.format(text=input_text, lang=target_language)
    if source_language:
        prompt = f"The source language is {source_language}.\n{prompt}"
    return prompt


def streaming_openai_response(prompt: str, suffix: str | None = None):
    def generate():
        try:
            response = get_openai_response_stream(prompt)
            for chunk in response:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
            if suffix:
                yield f"data: {json.dumps({'content': suffix}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            error = json.dumps({"error": f"Internal error: {str(e)}"}, ensure_ascii=False)
            yield f"event: error\ndata: {error}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def prepare_content_request(request: ContentRequest):
    input_value = request.input.strip()
    output_language = request.lang.strip()
    css_selector = request.css_selector.strip() if request.css_selector else None
    if not input_value or not output_language:
        raise HTTPException(status_code=422, detail="input and lang must not be blank")
    return input_value, output_language, css_selector


def run_summary(input_value: str, output_language: str, css_selector: str | None = None) -> str:
    text = process_input(input_value, css_selector)
    prompt = summary_prompt_template.format(text=text, lang=output_language)
    return get_openai_response(prompt)


def run_social_post(input_value: str, output_language: str, css_selector: str | None = None) -> str:
    text = process_input(input_value, css_selector)
    prompt = socail_prompt_template.format(text=text, lang=output_language)
    result = get_openai_response(prompt)
    if input_value.startswith(("http://", "https://")):
        result += f"\n\n{input_value}"
    return result


def run_keywords(
    input_value: str,
    output_language: str,
    num_keywords: int = 5,
    css_selector: str | None = None,
) -> str:
    text = process_input(input_value, css_selector)
    prompt = keywords_prompt_template.format(
        num_keywords=num_keywords,
        text=text,
        lang=output_language,
    )
    return get_openai_response(prompt)


def run_rewrite(
    input_value: str,
    output_language: str,
    style: str = "polished",
    css_selector: str | None = None,
) -> str:
    text = process_input(input_value, css_selector)
    prompt = rewrite_prompt_template.format(text=text, lang=output_language, style=style)
    return get_openai_response(prompt)


def run_title_meta(
    input_value: str,
    output_language: str,
    num_titles: int = 5,
    target_keyword: str | None = None,
    css_selector: str | None = None,
) -> str:
    text = process_input(input_value, css_selector)
    prompt = title_meta_prompt_template.format(
        text=text,
        lang=output_language,
        num_titles=num_titles,
        target_keyword=target_keyword or "None specified",
    )
    return get_openai_response(prompt)


def run_structure(
    input_value: str,
    output_language: str,
    output_format: str = "article_and_faq",
    num_faq: int = 5,
    css_selector: str | None = None,
) -> str:
    text = process_input(input_value, css_selector)
    prompt = structure_prompt_template.format(
        text=text,
        lang=output_language,
        format=output_format,
        num_faq=num_faq,
    )
    return get_openai_response(prompt)


def run_translation(input_text: str, target_language: str, source_language: str | None = None) -> str:
    return get_openai_response(build_translation_prompt(input_text, source_language, target_language))


@app.post(
    "/api/v1/summary",
    dependencies=[Depends(require_personal_access_token)],
    tags=["Content"],
)
async def summarize(request: ContentRequest):
    """Summarize text or webpage content."""
    try:
        input_value, output_language, css_selector = prepare_content_request(request)
        if request.stream:
            text = process_input(input_value, css_selector)
            prompt = summary_prompt_template.format(text=text, lang=output_language)
            return streaming_openai_response(prompt)
        return {"result": run_summary(input_value, output_language, css_selector)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.post(
    "/api/v1/social",
    dependencies=[Depends(require_personal_access_token)],
    tags=["Content"],
)
async def create_social_post(request: ContentRequest):
    """Create a social-media post from text or webpage content."""
    try:
        input_value, output_language, css_selector = prepare_content_request(request)
        source_suffix = f"\n\n{input_value}" if input_value.startswith(("http://", "https://")) else None
        if request.stream:
            text = process_input(input_value, css_selector)
            prompt = socail_prompt_template.format(text=text, lang=output_language)
            return streaming_openai_response(prompt, source_suffix)
        return {"result": run_social_post(input_value, output_language, css_selector)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.post(
    "/api/v1/keywords",
    dependencies=[Depends(require_personal_access_token)],
    tags=["Content"],
)
async def extract_keywords(request: KeywordsRequest):
    """Extract keywords from text or webpage content."""
    try:
        input_value, output_language, css_selector = prepare_content_request(request)
        if request.stream:
            text = process_input(input_value, css_selector)
            prompt = keywords_prompt_template.format(
                num_keywords=request.num_keywords,
                text=text,
                lang=output_language,
            )
            return streaming_openai_response(prompt)
        return {
            "result": run_keywords(input_value, output_language, request.num_keywords, css_selector)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.post(
    "/api/v1/rewrite",
    dependencies=[Depends(require_personal_access_token)],
    tags=["Content"],
)
async def rewrite_content(request: RewriteRequest):
    """Rewrite or polish text or webpage content in a selected style."""
    try:
        input_value, output_language, css_selector = prepare_content_request(request)
        if request.stream:
            text = process_input(input_value, css_selector)
            prompt = rewrite_prompt_template.format(
                text=text,
                lang=output_language,
                style=request.style,
            )
            return streaming_openai_response(prompt)
        return {
            "result": run_rewrite(input_value, output_language, request.style, css_selector)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.post(
    "/api/v1/title-meta",
    dependencies=[Depends(require_personal_access_token)],
    tags=["Content"],
)
async def create_title_meta(request: TitleMetaRequest):
    """Create title candidates and a search-friendly meta description."""
    try:
        input_value, output_language, css_selector = prepare_content_request(request)
        target_keyword = request.target_keyword.strip() if request.target_keyword else None
        text = process_input(input_value, css_selector)
        prompt = title_meta_prompt_template.format(
            text=text,
            lang=output_language,
            num_titles=request.num_titles,
            target_keyword=target_keyword or "None specified",
        )
        if request.stream:
            return streaming_openai_response(prompt)
        return {
            "result": get_openai_response(prompt)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.post(
    "/api/v1/structure",
    dependencies=[Depends(require_personal_access_token)],
    tags=["Content"],
)
async def structure_content(request: StructureRequest):
    """Turn text or webpage content into a structured article, FAQ, or both."""
    try:
        input_value, output_language, css_selector = prepare_content_request(request)
        text = process_input(input_value, css_selector)
        prompt = structure_prompt_template.format(
            text=text,
            lang=output_language,
            format=request.format,
            num_faq=request.num_faq,
        )
        if request.stream:
            return streaming_openai_response(prompt)
        return {"result": get_openai_response(prompt)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.post(
    "/api/v1/translation",
    dependencies=[Depends(require_personal_access_token)],
    tags=["Translation"],
)
async def translate(request: TranslationRequest):
    """Translate text, optionally returning incremental output as SSE."""
    text = request.input.strip()
    target_language = request.to.strip()
    source_language = request.from_.strip() if request.from_ else None

    if not text or not target_language:
        raise HTTPException(status_code=422, detail="input and to must not be blank")

    prompt = build_translation_prompt(text, source_language, target_language)

    if not request.stream:
        try:
            return {"result": run_translation(text, target_language, source_language)}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")

    return streaming_openai_response(prompt)


@app.post("/api/get_translation")
async def get_translation(input: str = Form(..., description="The text from which to get translate"),
                       lang: str = Form(..., description="The target language of the text ai translate to.")
                       ):


    try:

        text = input.strip()

        # Prepare the prompt using the template and provided parameters
        prompt = translate_prompt_template.format(
            text=text,  # Strip any leading/trailing whitespace
            lang=lang
        )

        result = get_openai_response(prompt)

        return {
            "result": result
        }

    except Exception as e:
        logger.exception("Legacy translation failed")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


# 流式输出API
@app.post("/api/stream/get_keywords")
async def stream_get_keywords(input: str = Form(..., description="The text or url from which to extract keywords."),
                       lang: str = Form(..., description="The language of the text ai responds."),
                       num_keywords: int = Form(5, description="The number of keywords to extract"),
                       css_selector: str = Form(None, description="CSS selector to extract content from HTML, optional")
                       ):

    try:
        text = process_input(input,css_selector)
        prompt = keywords_prompt_template.format(
            num_keywords=num_keywords,
            text=text,
            lang=lang
        )

        def generate():
            response = get_openai_response_stream(prompt)
            for chunk in response:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    yield f"data: {json.dumps({'content': content})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.post("/api/stream/get_social")
async def stream_get_social(input: str = Form(..., description="The text from which to get content for social media post."),
                       lang: str = Form(..., description="The language of the text ai responds."),
                       css_selector: str = Form(None, description="CSS selector to extract content from HTML, optional")
                       ):

    try:
        text = process_input(input,css_selector)
        prompt = socail_prompt_template.format(
            text=text,
            lang=lang
        )

        def generate():
            response = get_openai_response_stream(prompt)
            full_text = ""
            for chunk in response:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_text += content
                    yield f"data: {json.dumps({'content': content})}\n\n"

            # 如果是URL，在末尾添加链接
            if input.startswith("http://") or input.startswith("https://"):
                url_append = f"\n\n{input}"
                yield f"data: {json.dumps({'content': url_append})}\n\n"

            yield "data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.post("/api/stream/get_summary")
async def stream_get_summary(input: str = Form(..., description="The text or urlfrom which to get_summary"),
                       lang: str = Form(..., description="The language of the text ai responds."),
                       css_selector: str = Form(None, description="CSS selector to extract content from HTML, optional")
                       ):

    try:
        text = process_input(input,css_selector)
        prompt = summary_prompt_template.format(
            text=text,
            lang=lang
        )

        def generate():
            response = get_openai_response_stream(prompt)
            for chunk in response:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    yield f"data: {json.dumps({'content': content})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.post("/api/stream/get_rewrite")
async def stream_get_rewrite(
    input: str = Form(..., min_length=1, description="The text or URL to rewrite"),
    lang: str = Form(..., min_length=1, description="The output language"),
    style: Literal["polished", "concise", "professional", "conversational", "marketing"] = Form(
        "polished", description="The rewriting style"
    ),
    css_selector: str = Form(None, description="CSS selector for URL input, optional"),
):
    try:
        input_value, output_language, css_selector = prepare_form_content(input, lang, css_selector)
        text = process_input(input_value, css_selector)
        prompt = rewrite_prompt_template.format(text=text, lang=output_language, style=style)
        return streaming_openai_response(prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.post("/api/stream/get_title_meta")
async def stream_get_title_meta(
    input: str = Form(..., min_length=1, description="The text or URL to create titles for"),
    lang: str = Form(..., min_length=1, description="The output language"),
    num_titles: int = Form(5, ge=1, le=10, description="Number of title candidates"),
    target_keyword: str = Form(None, max_length=100, description="Optional target keyword"),
    css_selector: str = Form(None, description="CSS selector for URL input, optional"),
):
    try:
        input_value, output_language, css_selector = prepare_form_content(input, lang, css_selector)
        text = process_input(input_value, css_selector)
        prompt = title_meta_prompt_template.format(
            text=text,
            lang=output_language,
            num_titles=num_titles,
            target_keyword=target_keyword.strip() if target_keyword else "None specified",
        )
        return streaming_openai_response(prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.post("/api/stream/get_structure")
async def stream_get_structure(
    input: str = Form(..., min_length=1, description="The text or URL to structure"),
    lang: str = Form(..., min_length=1, description="The output language"),
    format: Literal["article", "faq", "article_and_faq"] = Form(
        "article_and_faq", description="The requested output format"
    ),
    num_faq: int = Form(5, ge=1, le=20, description="Number of FAQ items"),
    css_selector: str = Form(None, description="CSS selector for URL input, optional"),
):
    try:
        input_value, output_language, css_selector = prepare_form_content(input, lang, css_selector)
        text = process_input(input_value, css_selector)
        prompt = structure_prompt_template.format(
            text=text,
            lang=output_language,
            format=format,
            num_faq=num_faq,
        )
        return streaming_openai_response(prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.post("/api/stream/get_translation")
async def stream_get_translation(input: str = Form(..., description="The text from which to get translate"),
                       lang: str = Form(..., description="The target language of the text ai translate to.")
                       ):

    try:
        text = input.strip()
        prompt = translate_prompt_template.format(
            text=text,
            lang=lang
        )

        def generate():
            response = get_openai_response_stream(prompt)
            for chunk in response:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    yield f"data: {json.dumps({'content': content})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    except Exception as e:
        logger.exception("Legacy streaming endpoint failed")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


if mcp_enabled:
    from mcp_service import create_mcp_app

    mcp_asgi_app = create_mcp_app(
        public_url=mcp_public_url,
        issuer=auth0_issuer,
        audience=auth0_audience,
        required_scope=auth0_required_scope,
        allowed_subject=auth0_allowed_subject,
        summarize=run_summary,
        social_post=run_social_post,
        keywords=run_keywords,
        translate=run_translation,
        rewrite=run_rewrite,
        title_meta=run_title_meta,
        structure=run_structure,
        max_concurrency=int(os.getenv("MCP_MAX_CONCURRENCY", "4")),
        timeout_seconds=float(os.getenv("MCP_TOOL_TIMEOUT_SECONDS", "120")),
        rate_limit_calls=int(os.getenv("MCP_RATE_LIMIT_CALLS", "30")),
        rate_limit_window=int(os.getenv("MCP_RATE_LIMIT_WINDOW_SECONDS", "60")),
    )

    @asynccontextmanager
    async def app_lifespan(_app):
        async with mcp_asgi_app.router.lifespan_context(mcp_asgi_app):
            yield

    app.router.lifespan_context = app_lifespan
    # Mount last so the existing website and REST routes keep precedence.
    app.mount("/", mcp_asgi_app)
