from fastapi import FastAPI, HTTPException, Query,Form

import requests
from pydantic import BaseModel, Field
from bs4 import BeautifulSoup
from charset_normalizer import from_bytes
from dotenv import load_dotenv
import openai
from openai import OpenAI
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
import aiofiles

import os

# Load environment variables from a .env file
# 获取当前文件所在目录
env_path = Path('.') / '.env'

# 加载 .env 文件中的环境变量
load_dotenv(dotenv_path=env_path)


openai_api_key = os.getenv("OPENAI_API_KEY")
openai_base_url = os.getenv("OPENAI_BASE_URL")
openai_model = os.getenv("OPENAI_MODEL")
keywords_prompt_template = os.getenv("KEYWORDS_PROMPT")
summary_prompt_template = os.getenv("SUMMARY_PROMPT")
sns_post_prompt_template = os.getenv("SNS_POST_PROMPT")
lang = os.getenv("DEFAULT_LANG")



headers = {
        'User-Agent': os.getenv("DEFAULT_UA")
}
# print(ua_string,openai_api_key,openai_base_url)


app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

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


def fetch_and_parse_url(url, headers,selector=None,timeout=10):
        
        response = requests.get(url, headers=headers,timeout=timeout)
        response.raise_for_status()  # Check if the request was successful

        # Detect the encoding of the response content using charset-normalizer
        result = from_bytes(response.content)
        response.encoding = result.best().encoding

        raw = response.text
        
        # Parse the HTML content using BeautifulSoup
        soup = BeautifulSoup(raw, 'html.parser')
        title = soup.title.string if soup.title else "No title found"

        if selector:
            elements = soup.select(selector)
            content = [element.get_text(strip=True) for element in elements]
        else:
            content = response.text

        return {
            "title": title,            
            "content": content,
            "raw":raw
        }


# 定义 POST 接口，使用 Form 接受表单数据
@app.post("/get_keywords")
async def get_keywords(text: str = Form(..., description="The text from which to extract keywords."),
                       num_keywords: int = Form(5, description="The number of keywords to extract")):
    """
    Extract keywords from provided text using OpenAI's API.

    - **text**: The text from which to extract keywords.
    - **num_keywords**: The number of keywords to extract (default is 5).
    """
        # 打印接收到的请求体以便调试
    

    try:
        # Extract text and num_keywords from the request
        

        # Prepare the prompt using the template and provided parameters
        prompt = keywords_prompt_template.replace("{num_keywords}", str(num_keywords)).replace("{text}", text)
        print(text,num_keywords,prompt)


        openai_client = OpenAI(api_key=openai_api_key, base_url=openai_base_url)

        response = openai_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are a helpful assistant"},
                {"role": "user", "content": prompt},
            ],
            stream=False
        )

        print(response)
        
        keywords = response.choices[0].message.content.strip()

        return {
            "keywords": keywords
        }

    except Exception as e:
        
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.get("/analyze_content")
async def analyze_content(
    url: str = Query(..., description="The URL to fetch"),
    selector: str = Query(None, description="The CSS selector to extract content"),
    num_keywords: int = Query(5, description="Number of keywords to extract")
):
    
    
    

    try:
        # Fetch the content from the URL
        result = fetch_and_parse_url(url, headers, selector)
        
        # 获取 title
        title = result['title']

        # 使用 join 将 content 中的元素连接成一个字符串
        content = "\n".join(result['content'])

        # 将 title 和 content 组合成一个新的字符串 text
        text = f"《{title}》\nContent: {content}\n Source URL: {url}"
                

        # Prepare the prompt using the template and provided parameters
        # prompt = keywords_prompt_template.replace("{num_keywords}", str(num_keywords)).replace("{text}", text)
        prompt = keywords_prompt_template.format(
            num_keywords=num_keywords,
            text=text.strip()  # Strip any leading/trailing whitespace
        )

        openai_client = OpenAI(api_key=openai_api_key, base_url=openai_base_url)

        response = openai_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are a helpful assistant"},
                {"role": "user", "content": prompt},
            ],
            stream=False
        )
        
        keywords = response.choices[0].message.content.strip()


        # Prepare the prompt for summarization using the template and provided parameters
        
        prompt = summary_prompt_template.replace("{text}", text).replace("{lang}", lang)
        response = openai_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are a helpful assistant"},
                {"role": "user", "content": prompt},
            ],
            stream=False
        )
        
        summary = response.choices[0].message.content.strip()

        prompt =  sns_post_prompt_template.replace("{text}", text).replace("{lang}", lang)
        response = openai_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are a helpful assistant"},
                {"role": "user", "content": prompt},
            ],
            stream=False
        )
        sns_post = response.choices[0].message.content.strip()


        return {
            "url":url,
            "title": title,
            "keywords": keywords,            
            "summary": summary,
            "sns_post": sns_post,
            "text":text,
            
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")