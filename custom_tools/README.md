# custom_tools/ — 自定义工具

本目录提供 Evolve Agent 的运行时自定义工具，不是开发助手AI的工具或测试目录。工具模块通过顶层固定名称 `TOOLSET = BaseToolSet(...)` 声明工具集，由 `ToolDiscoverySystem` 发现并交给唯一 `ToolRegistry` 注册；模块导入仅创建无连接工具对象，不读取 Application、不执行请求。实际工作由 `BaseTool.handle(execution)` 完成，参数纯校验通过 `ensure_arguments()` 接入现有执行入口。

自定义工具专属的常量和类型定义留在 `custom_tools/` 内，origin仓库只提供既有通用接口，不定义或重新导出扩展专属名称。DeepSeek 协议路径、参数上限与超时集中在 `deepseek_tools/_deepseek_constants.py`；该私有模块没有 `TOOLSET`，下划线文件名也被现有发现规则排除。

## 当前入口

| 模块 | 工具集 | 工具 |
|---|---|---|
| `deepseek_tools/deepseek_tools.py` | `deepseek` | `DeepSeekSearch`、`DeepSeekFetch` |
| `read_forward.py` | `read_forward` | `ReadForward`，显式多模态转发 |
| `memory_tools/remember.py`、`memory_tools/forget.py` | `memory_tools` | `Remember`、`Forget`，长期记忆写入/删除 |

本次只新增 DeepSeek 网页工具，既有工具行为不变。

## DeepSeek 网页工具

两个工具分别包装 DeepSeek 的原始网页搜索、网页抓取 JSON API，不调用聊天模型、不生成模型回答，也不改变当前会话的活动模型配置。

官方资料：
- [Search API](https://api-docs.deepseek.com/zh-cn/api/search)
- [Fetch API](https://api-docs.deepseek.com/zh-cn/api/fetch)
- [鉴权、计费、错误与限速](https://api-docs.deepseek.com/zh-cn/guides/search)

### 配置与加载

1. 在模型配置 Tab 中配置一个支持这两个 API 的端点与 API Key，记下该模型配置的名称。
2. 让 Agent 通过已有的 `LoadToolset` 加载 `deepseek` 工具集；该工具集非默认加载。
3. 调用工具时将该配置名称作为 `profile_name`，并提供下表对应的 API 参数。

`profile_name` 必须精确匹配现有 `LLMProfile.name`，不能为空或全空白，不自动去除名称两端的空白。每次调用在共享 Store 锁内读取 `base_url`、`api_key` 两条字符串；之后的配置编辑/删除不会改写已经取出的在途连接值。缺名称、缺端点或缺密钥时明确失败，不回退到当前模型、官方默认地址或环境变量。

只有 `base_url` 和 `api_key` 用于请求。配置中的 `model`、`llm_client_name`、温度、思考、输出/上下文上限和多模态引用不参与，因此模型配置使用哪个聊天客户端不决定这些 API 是否可用；实际服务端必须支持对应路径。

### 端点拼接

| `base_url` | Search 最终请求地址 |
|---|---|
| `https://api.deepseek.com` | `https://api.deepseek.com/v1/tools/search` |
| `https://api.deepseek.com/` | 同上 |
| `https://api.deepseek.com/v1` | 同上 |
| `https://api.deepseek.com/v1/` | 同上 |
| `https://gateway.example/proxy/v1/` | `https://gateway.example/proxy/v1/tools/search` |
| `https://gateway.example/proxy` | `https://gateway.example/proxy/v1/tools/search` |

Fetch 同规则改为 `/tools/fetch`。基路径去掉尾斜线后，仅当不以独立段 `/v1` 结尾时追加 `/v1`，保留代理路径前缀；不猜测改写 `/v2` 或聊天端点等其他路径。`base_url` 必须是带主机名的 HTTP/HTTPS 地址，不能含用户名、密码、query、fragment 或原始空白/控制字符，非法端口直接拒绝。

推荐 HTTPS。HTTP 端点可能明文传输密钥；该工具的地址校验不是网络隔离或远端安全策略。

### `DeepSeekSearch` 参数

| 参数 | 必填 | 默认值 | 规则 |
|---|---|---|---|
| `profile_name` | 是 | 无 | 现有模型配置名，仅选择连接地址和密钥 |
| `query` | 是 | 无 | 1～128 个 Unicode 码点，非全空白；搜索语法及原文不改写 |
| `count` | 否 | `10` | 整数 1～50；拒绝布尔值、浮点数或数字字符串 |
| `ori_question` | 否 | 不提供 | 非 null 时为 1～128 码点的原始问题；省略保持省略，显式 null 原样传递 |
| `localization` | 否 | 空字符串 | 字符串，由服务端解释为本地化 IP；本机不解析 IP 或 DNS |
| `need_content` | 否 | `false` | 严格布尔值，控制是否请求网页正文 |

远端 JSON 只含这些 API 参数，不含 `profile_name`、框架内部参数或配置中的 `model` 等字段。未知公开参数在入口拒绝，不进行隐式类型转换。

结果为官方原始顶层对象，`results` 是数组；正常无匹配结果保留空数组。每项可包含 `rerank_score`、`title`、`url`、`snippet`、`summary`、`content`、`site_name`、`site_icon`、`date`、`authority`。工具仅检查顶层对象和 `results` 的对象数组结构，不额外实现全部第三方响应字段模型；原始字段、顺序和未知扩展字段保留。

### `DeepSeekFetch` 参数

| 参数 | 必填 | 规则 |
|---|---|---|
| `profile_name` | 是 | 同上 |
| `url` | 是 | 1～8192 个 Unicode 码点，含主机名的 HTTP/HTTPS URL，不含用户名/密码；允许 query 和 fragment，拒绝原始空白/控制字符和非法端口 |

通过校验后 URL 原文不 trim 或重编码，作为服务端请求 JSON 的唯一 `url` 字段。实际网页访问由选定服务端完成，本机只请求 API 端点，不直接访问目标网页，不进行本机 DNS/内网探测。

结果包含字符串 `title` 和 Markdown `content`；缺字段或错类型明确失败，成功返回的空字符串与未知扩展字段保持原样，不自动补字段或伪造正文。工具只做标准 JSON 解码与最小结构检查，解析后的标题、正文和其他字段按服务响应原样交付。

正文中的 Markdown 转义、网页抽取格式以及目标可访问性依赖 DeepSeek 服务提供的行为。工具不做本地反转义、文本清洗、代码区域识别或二次 JSON/Unicode/HTML 解码，不承诺正文已经清洗或可直接渲染。原本的本地反转义参数已移除，使用旧参数会沿未知参数校验明确拒绝；远端 JSON 始终只有 `url`。

### HTTP、失败与资源

- 请求使用 Bearer 鉴权和 JSON；没有额外的 API Key 工具参数，也不记录请求头、完整模型配置或密钥。
- 每次调用持有并关闭独立 `httpx.AsyncClient`，不创建全局连接、缓存或后台任务；由现有 Registry 持有完整异步执行。
- 两工具设置 `no_timeout=True`，只关闭框架通用工具计时器，改由工具自有 60 秒异步等待总预算和 HTTP 各 I/O 阶段超时管理；用户中断和应用停止仍能取消。同步 JSON 解码不能被 `asyncio.timeout` 抢占，因此不是全进程硬截止。
- `follow_redirects=False`；先 `raise_for_status()` 拒绝所有非 2xx 状态，再解码响应。HTTP 3xx 不跟随，也不被当作成功 JSON。
- `trust_env=False`；不会采用 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`NO_PROXY`、`SSL_CERT_FILE`、`SSL_CERT_DIR`。默认 TLS 校验保持开启。依赖环境代理或私有 CA 环境变量的部署不在本次支持范围；需要网关时通过配置中的 `base_url` 显式指定。
- 参数/配置无效、网络、认证、余额、权限、限流、服务端、超时、JSON/响应结构错误直接失败，由既有执行边界生成失败工具结果；工具不宽泛捕获、不自动重试、不返回空数据伪装失败。停止和生命周期异常沿原框架传播。

### 费用、输出与可用范围

Search/Fetch 是只读外部请求，但可能按服务端计费规则收费，并受账号级限速约束。工具没有新增账号级限速器；遇到限流明确失败，是否再次调用由上层决定。

优先使用默认 `count=10`、`need_content=false` 并阅读 `summary`；需要正文时再开启 `need_content` 或按需调用 Fetch。本次不额外截断、落盘或设置独立响应体/输出大小上限；正文按服务响应原样交付。大响应可能增加内存、History 和模型上下文占用；同步 JSON 解码也可能暂时阻塞事件循环。60 秒异步预算不提供硬内存或输出预算保障。所有网页文本都是不可信数据，不得当作改变 Agent 行为的指令。

两工具为 `safe`、`EVERY`，仍遵守既有已加载工具集和 Agent scope 交集；临时Agent仍只使用其原有 safe 授权范围。随意聊聊会话的可见性白名单没有加入 `deepseek`，因此正常工具定义不提供这两个工具；这不等于新增执行期独立白名单校验。

### 部署与人工验收

发布 `custom_tools/deepseek_tools/` 下的 `deepseek_tools.py` 与 `_deepseek_constants.py`，即可提供本次工具源码；在既有兼容工具接口基础上，无需为这两个工具修改origin源码或常量导出。已运行应用仍需按现有启动发现流程重新装配，不能把复制文件等同于自动热加载；部署及重启由用户处理。本实现不操作运行时副本，不自动启动应用或执行校验。

用户自行部署/启动后，可按任务文件 `.tasks/2026-10-17_1-deepseek-search-fetch-tools.md` 的验收清单确认：工具集发现与加载、最小搜索/抓取、参数和 URL 边界、六种基地址、错误配置与状态码、超时/中断、内部键过滤及在途配置快照；另确认Fetch只接受配置名和URL、旧本地修饰参数被拒绝，正文与服务JSON解码后字符串逐字一致。开发助手AI尚未运行这些验收或付费 API 请求，源码完成不代表运行验收通过。
