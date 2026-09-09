# KTrends：Auth0 与 ChatGPT MCP 接入实操手册

本文记录 KTrends 通过 Auth0 OAuth 2.1 接入 ChatGPT 开发者模式的完整过程，以及实际配置时最容易踩到的坑。

## 最终架构与固定参数

认证链路如下：

1. ChatGPT 访问 KTrends 的 `https://hicms.eu.org/mcp`。
2. KTrends 返回 `401` 和 OAuth Protected Resource Metadata 地址。
3. ChatGPT 读取元数据，发现 Auth0 issuer、scope 和 OAuth 端点。
4. ChatGPT 通过 Auth0 Dynamic Client Registration（DCR）注册第三方客户端。
5. 用户在 Auth0 Universal Login 登录并同意授权。
6. ChatGPT 用 Access Token 调用 MCP；KTrends 校验 JWT 后返回工具列表或执行工具。

本项目使用以下固定值：

| 配置 | 值 |
| --- | --- |
| MCP URL / Auth0 API Identifier / Audience | `https://hicms.eu.org/mcp` |
| Auth0 tenant domain | `dev-l26qdterskgwcfi7.us.auth0.com` |
| Auth0 issuer | `https://dev-l26qdterskgwcfi7.us.auth0.com/` |
| OAuth scope | `ktrends:invoke` |
| MCP transport | Streamable HTTP |
| ChatGPT client registration | DCR |
| JWT algorithm | RS256 |

注意：issuer 末尾的 `/` 是值的一部分，不能省略。

## 一、在 Auth0 创建 API

进入 **Applications → APIs → Create API**，填写：

- Name：`KTrends MCP`
- Identifier：`https://hicms.eu.org/mcp`
- Signing Algorithm：`RS256`

创建后进入 API 的 Permissions，添加：

- Permission：`ktrends:invoke`
- Description：`Invoke KTrends MCP tools`

Identifier 不是网页地址测试项，而是 OAuth resource/audience；必须与 KTrends 的
`AUTH0_AUDIENCE` 完全一致。

## 二、配置 API 的第三方应用访问权限

ChatGPT 经 DCR 创建的是 Auth0 第三方应用。进入 KTrends API 的访问策略页面，设置：

- User-delegated Access：`All apps allowed`
- Client Access：`No apps allowed`
- Default Permissions for third-party applications：
  - User-delegated Access：`Authorized`
  - 允许 `ktrends:invoke`
  - Client Access：保持 `Unauthorized`

这里授权的是“应用代表登录用户调用 API”。KTrends 不使用 machine-to-machine/client
credentials，因此不必开放 Client Access。

## 三、创建唯一允许登录的用户

进入 **User Management → Users → Create User**：

- Email：自己的邮箱
- Password：设置强密码
- Connection：`Username-Password-Authentication`

创建后打开用户详情，复制 User ID，例如：

```text
auth0|xxxxxxxxxxxxxxxxxxxxxxxx
```

该值写入 `AUTH0_ALLOWED_SUBJECT`。KTrends 除了校验签名、issuer、audience、时间和 scope，
还会检查 Token 的 `sub` 是否等于该 User ID，因此其他 Auth0 用户无法调用模型额度。

不要把 Auth0 密码、Access Token、Client Secret 或 Cookie 写入仓库或故障截图。

## 四、启用 Auth0 DCR

进入 **Settings → Advanced**：

1. 打开 **Dynamic Client Registration (DCR)**。
2. 点击页面底部 **Save**。

Auth0 默认关闭 DCR。如果没有开启，ChatGPT 创建连接器时会报：

```text
Dynamic client registration failed: registration endpoint returned 400
(Bad Request: dynamic client registration is disabled)
```

DCR 是开放动态注册：启用后，外部客户端可以向租户申请创建第三方应用。应配合 Auth0
第三方应用访问策略、用户授权以及 KTrends 的固定 `sub` 白名单使用。这个租户应专用于
KTrends，不要与不相关的生产系统共用。

## 五、把数据库连接提升到 Domain Level

进入 **Authentication → Database → Username-Password-Authentication**，启用：

```text
Promote Connection to Domain Level
```

并保存。DCR 创建的是第三方应用，第三方应用只能使用 domain-level connection。

如果没有提升，用户可能可以看到 Auth0 登录页，但提交用户名和密码后跳到
`/authorize/resume?state=...`，只显示通用错误：

```text
There could be a misconfiguration in the system or a service outage.
Please try again.
```

这个页面不会显示真实原因。真实错误需到 **Monitoring → Logs** 查看。

## 六、配置 KTrends

在本地 `.env` 中设置：

```dotenv
MCP_ENABLED=true
MCP_PUBLIC_URL="https://hicms.eu.org/mcp"
AUTH0_ISSUER="https://dev-l26qdterskgwcfi7.us.auth0.com/"
AUTH0_AUDIENCE="https://hicms.eu.org/mcp"
AUTH0_REQUIRED_SCOPE="ktrends:invoke"
AUTH0_ALLOWED_SUBJECT="auth0|替换为实际用户ID"
```

`AUTH0_ISSUER` 不是 Auth0 控制台里的一个输入框。它来自 Auth0 OpenID discovery 文档：

```text
https://dev-l26qdterskgwcfi7.us.auth0.com/.well-known/openid-configuration
```

复制 JSON 中的 `issuer` 原值，包括末尾 `/`。不需要购买或配置 Auth0 Custom Domain。

配置后重新创建容器，使 Compose 重新读取 `.env`：

```bash
docker compose up -d ktrends
docker compose logs --tail 50 ktrends
```

仅执行 `docker compose restart` 不一定会重新读取变更后的 Compose 环境变量，因此更推荐
`docker compose up -d ktrends`。

## 七、验证公网 OAuth 与 MCP 入口

未认证访问 MCP 应返回 `401`，而不是 `404`、`403` 或 `502`：

```bash
curl -i https://hicms.eu.org/mcp
```

响应的 `WWW-Authenticate` 应包含类似内容：

```text
resource_metadata="https://hicms.eu.org/.well-known/oauth-protected-resource/mcp"
```

检查 Protected Resource Metadata：

```bash
curl https://hicms.eu.org/.well-known/oauth-protected-resource/mcp
```

预期核心字段：

```json
{
  "resource": "https://hicms.eu.org/mcp",
  "authorization_servers": [
    "https://dev-l26qdterskgwcfi7.us.auth0.com/"
  ],
  "scopes_supported": ["ktrends:invoke"]
}
```

检查 Auth0 discovery：

```bash
curl https://dev-l26qdterskgwcfi7.us.auth0.com/.well-known/openid-configuration
```

应包含正确的 `issuer`、`authorization_endpoint`、`token_endpoint`、
`registration_endpoint`，且 `code_challenge_methods_supported` 包含 `S256`。

如果本机正常而公网失败，应在 Nginx Proxy Manager Plus 的界面中检查代理，不要直接修改
其生成文件。`/mcp` 需要允许 GET/POST、关闭代理缓冲、保留长连接并转发 Authorization。

## 八、在 ChatGPT 创建连接器

1. 打开 **Settings → Security and login → Developer mode**。
2. 进入 Plugins 页面并新增连接器。
3. 填写：
   - Name：`KTrends`
   - Description：`提供文本翻译、内容摘要、社交媒体文案生成和关键词提取。`
   - Connection：`Server URL`
   - URL：`https://hicms.eu.org/mcp`
   - Authentication：`OAuth`
4. 打开 Advanced OAuth settings：
   - Registration method：`Dynamic Client Registration (DCR)`
   - Default scope：选择 `ktrends:invoke`
   - Base scopes：留空
5. 勾选自定义 MCP 风险确认并创建。
6. 在 Auth0 页面使用第三节创建的用户登录并同意授权。

如果界面提示“服务器未公布 CIMD 支持，CIMD 不可用”，可以忽略。CIMD 与 DCR 是两种
不同的客户端注册方式；本项目明确选择 DCR，不要求 CIMD，也不需要手工填写传统 Auth0
Application 的 Allowed Callback URLs。

## 九、认证成功后必须刷新工具列表

首次完成 OAuth 后，连接器详情页可能仍显示：

```text
尚无可用的应用操作
```

这通常是 ChatGPT 创建连接器、OAuth 完成和 MCP `tools/list` 更新之间的时序/缓存问题，
不代表服务端没有工具。在连接器详情页点击 **Refresh/刷新**，让 ChatGPT 重新执行 MCP
初始化和 `tools/list`。

刷新后应看到：

- `translate_text`
- `summarize_content`
- `create_social_post`
- `extract_keywords`

以后修改工具名称、描述、Schema、注解、权限或认证元数据，也必须重启/部署服务并在
ChatGPT 连接器详情页点击刷新。

## 十、冒烟测试

新建 ChatGPT 对话，从工具菜单启用 KTrends，然后分别测试：

```text
使用 KTrends 把“今天天气很好”翻译成英文。
```

```text
使用 KTrends 总结 https://example.com 的内容，使用中文。
```

```text
使用 KTrends 为以下文字生成中文社交媒体文案：……
```

```text
使用 KTrends 从以下文字提取 8 个中文关键词：……
```

同时测试一句与四项能力无关的普通问题，确认模型不会无故调用 KTrends。

## 故障排查速查表

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| DCR endpoint 返回 400 / disabled | Auth0 默认关闭 DCR | Settings → Advanced 开启 DCR，并 Save |
| 显示 CIMD unavailable | Auth0 discovery 未声明 CIMD | 已选 DCR 时忽略，不是失败 |
| 输入账号密码后 `/authorize/resume` 通用错误 | 数据库连接未对第三方应用开放，或 API 权限不足 | Promote Connection to Domain Level；检查第三方应用默认权限 |
| 登录成功但 Token 缺少 scope | API 的第三方应用默认权限未授权 | 将 User-delegated 默认权限设为 Authorized，并允许 `ktrends:invoke` |
| MCP 返回 401 missing scope | Access Token 没有 `ktrends:invoke` | 修复 Auth0 权限后断开并重新授权 |
| MCP 返回 401 wrong audience | Auth0 API Identifier、resource 和 `AUTH0_AUDIENCE` 不一致 | 三处统一为 `https://hicms.eu.org/mcp` |
| MCP 返回 401 subject not allowed | 登录用户不是白名单用户 | 将真实 Auth0 User ID 填入 `AUTH0_ALLOWED_SUBJECT` |
| 连接成功但显示无操作 | ChatGPT 尚未刷新工具缓存 | 连接器详情页点击 Refresh |
| 本机 metadata 正常、公网 403/404 | 反向代理规则拦截 `/.well-known/` | 在 NPM Plus UI 中调整规则 |
| 网页可访问但 MCP 502/超时 | 代理缓冲、超时或长连接配置不合适 | 关闭缓冲，提高 read/send timeout |

Auth0 的通用错误页信息不足时，到 **Monitoring → Logs** 找对应时间的失败事件，重点查看
`type`、`description`、`error`、`error_description`、`client_id`、`connection`、`audience`
和 `scope`。分享日志时应删除 Token、Cookie、密码及完整 state URL。

## 安全与维护提醒

- `.env` 必须保持未跟踪，不要提交真实 Token、User ID 以外的凭据或模型 API Key。
- `AUTH0_ALLOWED_SUBJECT` 是本项目个人使用限制的关键配置，不要删除该检查。
- 不要把 `/api/v1/*` 的 `PERSONAL_ACCESS_TOKEN` 与 Auth0 Token 混用。
- DCR 会创建 `tpc_` 前缀的第三方应用；反复删除并新增 ChatGPT 连接器可能产生多个客户端，
  可定期在 Auth0 Applications 中清理不再使用的旧客户端。
- 工具元数据变更后执行测试，并在 ChatGPT 中刷新连接器。

## 参考资料

- [OpenAI：Authentication](https://developers.openai.com/plugins/build/auth)
- [OpenAI：Connect and test your plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt)
- [Auth0：Dynamic Client Registration](https://auth0.com/docs/get-started/applications/dynamic-client-registration)
- [Auth0：Configure Third-Party Applications](https://auth0.com/docs/get-started/applications/third-party-applications/configure-third-party-applications)
