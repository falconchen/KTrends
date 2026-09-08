#	KTrends

## 创建项目和虚拟py环境

```
virtualenv -p /Library/Frameworks/Python.framework/Versions/Current/bin/python KTrends
cd /Users/falcon/projects/python/
source KTrends/bin/activate
```

## 运行，默认在8000端口监听
```
uvicorn main:app --reload --port 8000
```

## API 使用方式

在 `.env` 中配置 Personal Access Token。请使用自己的随机 Token，不要提交真实 Token：

```dotenv
PERSONAL_ACCESS_TOKEN="replace-with-a-long-random-token"
```

调用 API 时通过 `Authorization` 请求头传递：

```http
Authorization: Bearer <YOUR_PERSONAL_ACCESS_TOKEN>
```

### 翻译接口

`POST /api/v1/translation`，请求体为 JSON：

```bash
curl -N -X POST 'https://hicms.eu.org/api/v1/translation' \
  -H 'Authorization: Bearer <YOUR_PERSONAL_ACCESS_TOKEN>' \
  -H 'Content-Type: application/json' \
  -d '{"input":"Hello from API","from":"en","to":"zh-CN","stream":false}'
```

参数：

- `input`：必填，要翻译的文本。
- `from`：可选，源语系；省略时由模型自动判断。
- `to`：必填，目标语系，如 `zh-CN`、`en`。
- `stream`：可选，是否使用流式输出，默认为 `false`。

非流式响应：

```json
{"result":"来自 API 的问候"}
```

启用流式输出时，将 `stream` 设为 `true`。响应类型为 `text/event-stream`，每个数据块格式如下，并以 `data: [DONE]` 结束：

```text
data: {"content":"来自"}

data: {"content":" API 的问候"}

data: [DONE]
```

Token 缺失或无效时接口返回 `401`；服务端未配置 `PERSONAL_ACCESS_TOKEN` 时返回 `503`。

## 传参数：如v2ex

```
url：https://v2ex.com/t/1056911
选择器：div.topic_content,div[id^="r_"]
```

```
curl -X 'GET' \
  'http://localhost:8000/fetch_url?url=https%3A%2F%2Fv2ex.com%2Ft%2F1056911&selector=div.topic_content%2Cdiv%5Bid%5E%3D%22r_%22%5D' \
  -H 'accept: application/json'
  ```

## freeze

``` 
pip freeze >requirements.txt
```

## 部署到服务器
```
pip install -r requirements.txt
```

## 对 serv00
部分包需要特殊安装 orjson, pydantic_core, uvloop, watchfiles

```
cpuset -l 0 pip install -r requirements.txt

```

参考：<https://forum.serv00.com/d/170-no-support-for-python-libraries>
```
cpuset -l 0 pip install numpy
cpuset -l 0 pip install pandas

cpuset -l 0 pip install  orjson
cpuset -l 0 pip install uvloop
cpuset -l 0 pip install pydantic_core
cpuset -l 0 pip install watchfiles

```

## 构建docker 镜像（多架构交叉编译）

```
docker buildx build --platform linux/amd64,linux/arm64 -t falconchen/ktrends:latest --push .

```
文章：
<https://d.cellmean.com/p/caa450dbab14>
