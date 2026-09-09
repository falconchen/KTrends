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

### 内容摘要接口

`POST /api/v1/summary`，支持文本或 URL：

```bash
curl -X POST 'https://hicms.eu.org/api/v1/summary' \
  -H 'Authorization: Bearer <YOUR_PERSONAL_ACCESS_TOKEN>' \
  -H 'Content-Type: application/json' \
  -d '{"input":"https://example.com/article","lang":"zh-CN","css_selector":"article","stream":false}'
```

### 社交文案接口

`POST /api/v1/social`，当 `input` 是 URL 时，生成结果末尾会附上来源链接：

```bash
curl -X POST 'https://hicms.eu.org/api/v1/social' \
  -H 'Authorization: Bearer <YOUR_PERSONAL_ACCESS_TOKEN>' \
  -H 'Content-Type: application/json' \
  -d '{"input":"介绍我们的新产品","lang":"zh-CN","stream":false}'
```

### 关键词接口

`POST /api/v1/keywords`：

```bash
curl -X POST 'https://hicms.eu.org/api/v1/keywords' \
  -H 'Authorization: Bearer <YOUR_PERSONAL_ACCESS_TOKEN>' \
  -H 'Content-Type: application/json' \
  -d '{"input":"人工智能正在改变内容生产方式","lang":"zh-CN","num_keywords":5,"stream":false}'
```

摘要、社交文案和关键词接口的通用参数：

- `input`：必填，文本或以 `http://`、`https://` 开头的 URL。
- `lang`：必填，输出语系。
- `css_selector`：可选；输入为 URL 时，用于提取指定网页元素。
- `stream`：可选，默认为 `false`；设为 `true` 时返回 SSE 流。

## ChatGPT MCP 服务

KTrends 可以在同一个 FastAPI 进程中提供受 Auth0 保护的 Streamable HTTP MCP
服务。MCP 默认关闭；原有网页、`/api/v1/*` 和旧版表单接口不受影响。

完整的 Auth0 与 ChatGPT 配置流程、验证命令和实际踩坑记录见
[KTrends：Auth0 与 ChatGPT MCP 接入实操手册](docs/chatgpt-auth0-mcp-setup.md)。

MCP 提供四个工具：

- `translate_text`：翻译文本。
- `summarize_content`：总结文本或公开网页。
- `create_social_post`：根据文本或公开网页生成社交文案。
- `extract_keywords`：从文本或公开网页提取关键词。

### 1. 配置 Auth0

1. 在 Auth0 创建 API，Identifier 设置为 `https://hicms.eu.org/mcp`，签名算法使用
   RS256，并添加权限 `ktrends:invoke`。
2. 在 Settings → Advanced 启用 Dynamic Client Registration (DCR)。
3. 将 `Username-Password-Authentication` 提升为 Domain Level connection，并允许
   第三方应用以 user-delegated access 获得 `ktrends:invoke`。
4. 从目标用户的 Auth0 access token 或 Auth0 用户详情取得完整 `sub`，填入
   `AUTH0_ALLOWED_SUBJECT`。服务会拒绝其他 Auth0 用户，即使其 Token 具有相同权限。

本项目使用 DCR，不要求 CIMD，也无需创建传统 Auth0 Application 或手工填写 Allowed
Callback URLs。ChatGPT 中的 CIMD unavailable 提示在选择 DCR 时可以忽略。

在 `.env` 中配置：

```dotenv
MCP_ENABLED=true
MCP_PUBLIC_URL="https://hicms.eu.org/mcp"
AUTH0_ISSUER="https://your-tenant.auth0.com/"
AUTH0_AUDIENCE="https://hicms.eu.org/mcp"
AUTH0_REQUIRED_SCOPE="ktrends:invoke"
AUTH0_ALLOWED_SUBJECT="auth0|your-user-id"
```

`AUTH0_ISSUER` 和 Token 中的 `iss` 必须完全一致。MCP 服务会通过 Auth0 JWKS 验证
签名，并检查 `iss`、`aud`、有效期、scope 和用户 `sub`。OAuth protected resource
metadata 发布在 `/.well-known/oauth-protected-resource/mcp`。

### 2. 部署与反向代理

重新构建镜像以安装 MCP 依赖，然后启动服务：

```bash
docker compose build ktrends
docker compose up -d ktrends
docker compose logs --tail 50 ktrends
```

在 Nginx Proxy Manager Plus 的代理主机界面配置，而不是修改其生成文件：

- `/mcp` 允许 `GET`、`POST` 和长连接，并关闭代理缓冲。
- 转发 `Authorization`、`Accept`、`Content-Type` 和 `Mcp-Session-Id` 请求头。
- 不缓存 `/mcp` 和 `/.well-known/oauth-protected-resource/mcp`。
- 确认全局敏感文件规则没有拦截 `/.well-known/` 路径。

可使用以下 Advanced 配置作为参考：

```nginx
proxy_http_version 1.1;
proxy_buffering off;
proxy_cache off;
proxy_read_timeout 180s;
proxy_send_timeout 180s;
proxy_set_header Authorization $http_authorization;
proxy_set_header Mcp-Session-Id $http_mcp_session_id;
```

### 3. 测试并连接 ChatGPT

先使用 MCP Inspector 验证 OAuth 发现、登录、`tools/list` 和工具调用：

```bash
npx @modelcontextprotocol/inspector@latest
```

然后在 ChatGPT 中：

1. 打开 Settings → Security and login → Developer mode。
2. 打开 Plugins，新增连接，地址填写 `https://hicms.eu.org/mcp`。
3. OAuth 高级设置选择 DCR 和 `ktrends:invoke`，完成 Auth0 登录。
4. 进入连接器详情页点击 Refresh，确认发现四个工具。首次认证后如果显示“尚无可用的
   应用操作”，通常只是工具列表尚未刷新。

若连接失败，依次检查公网 HTTPS、well-known 元数据、Auth0 discovery/JWKS、回调地址、
Token audience、`ktrends:invoke` scope、`AUTH0_ALLOWED_SUBJECT` 和反向代理缓冲设置。
- `num_keywords`：仅关键词接口使用，默认为 `5`，范围为 `1`–`20`。

所有非流式接口均返回 `{"result":"..."}`；流式接口的数据格式与翻译接口相同。

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
