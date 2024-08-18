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

#加载 prompts模板
prompts_path = Path('.') / 'prompts.conf'
load_dotenv(dotenv_path=prompts_path)


openai_api_key = os.getenv("OPENAI_API_KEY")
openai_base_url = os.getenv("OPENAI_BASE_URL")
openai_model = os.getenv("OPENAI_MODEL")
keywords_prompt_template = os.getenv("KEYWORDS_PROMPT")
summary_prompt_template = os.getenv("SUMMARY_PROMPT")
socail_prompt_template = os.getenv("SOCAIL_POST_PROMPT")
translate_prompt_template = os.getenv("TRANSLATE_POST_PROMPT")

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
        
        html = fetch_html(url=url, headers=headers, timeout=timeout)                
        return parse_html(html, selector)

def fetch_html(url, headers,timeout=10):
        
        response = requests.get(url, headers=headers,timeout=timeout)
        response.raise_for_status()  # Check if the request was successful

        # Detect the encoding of the response content using charset-normalizer
        result = from_bytes(response.content)
        response.encoding = result.best().encoding

        return response.text
        

def parse_html(html, selector=None):
    # Parse the HTML content using BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.title.string if soup.title else "No title found"
    if not selector:
        selector = "body"
        
    elements = soup.select(selector)
    content = [element.get_text(strip=True) for element in elements]
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


def get_openai_response(prompt):
        
        openai_client = OpenAI(api_key=openai_api_key, base_url=openai_base_url)
        response = openai_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are a helpful content assistant"},
                {"role": "user", "content": prompt},
            ],
            stream=False
        )

        print(prompt,response)
        
        return response.choices[0].message.content.strip()

           


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
        print(result)

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
        print(result)
        return {
            "result": result
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
        print(result)

        return {
            "result": result
        } 

    except Exception as e:        
        print(f"Internal error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")