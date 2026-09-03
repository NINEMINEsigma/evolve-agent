# Evolve Agent

一个具备自我代码进化能力的人工智能代理.Agent 在运行时通过工具链读取自身源码副本、修改进化目标、验证并触发 **fast-slow 热交换**——编排器自动备份当前版本并替换为新代码, 重启后以进化后的形态继续运行.若进化后运行异常, 系统会自动进入 fallback 模式, 由备份修复当前副本.

## 环境要求

- Python 3.10+
- pnpm 或 npm（前端构建依赖, 优先 pnpm, 不存在时回退 npm）
- Windows 上需确保 `pnpm.cmd` 或 `npm.cmd` 在 PATH 中

## 安装

克隆仓库并拉取子模块：

```bash
git clone <repo-url> --recurse-submodules
git submodule update --init --recursive
```

安装 Python 依赖：

```bash
pip install -r requirements.txt
```

## 快速启动

```bash
# 交互式创建或选择配置
python run.py

# 使用 rich TUI 向导选择/编辑配置（分组面板 + 字段校验）
python run.py --interactive

# 加载已保存的配置键
python run.py --load <config_key>

# 保存当前命令行参数为新配置键
python run.py --save <config_key> --llm_model deepseek-v4-flash

# 强制重新初始化 workspace（首次运行或需要重置时）
python run.py --load <config_key> --force_init
```

`--interactive` 模式提供基于 `rich` 的可视化配置向导：列出已有 profile 供选择, 按分组（审批模型 / Workspace / 网关 / 运行时）逐项编辑, 内置字段校验（端口范围、温度区间、枚举值等）, 编辑完成后可选择是否保存.CLI 参数可与 `--interactive` 组合使用, 作为各字段的初始覆盖值.

启动后WebPage URL将被打印在启动日志的末尾.

### 常用 CLI 参数

## 配置项

`config.py` 中的主要字段与默认值：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `gateway_host` | `127.0.0.1` | Web 网关地址 |
| `gateway_port` | `8765` | Web 网关端口 |
| `console_log` | `True` | 是否在控制台输出日志 |
| `force_init` | `False` | 强制重新初始化 workspace |
| `frontend_force_build` | `False` | 强制重新构建前端（跳过签名缓存） |
| `workspace_path` | `workspace` | workspace 根目录 |
| `fast_agent_space_path` | `fast_agent_space` | fast 副本目录 |
| `slow_agent_space_path` | `slow_agent_space` | slow 副本目录 |
| `agentspace_path_name` | `agentspace` | agent 工作目录名 |
| `logs_path_name` | `logs` | 日志目录名 |
| `mcp_config_path_name` | `mcp_config.json` | MCP 配置文件名 |
| `merge_concat_threshold` | `50000` | 会话合并摘要截断阈值 |

> `--load` / `--save` / `--interactive` 三者互斥.无参数时交互式提示输入配置键.

> 审批模型（脱手模式）通过前端「模型配置」抽屉选择一个已有 LLM Profile 作为审批 Profile，无需在启动配置中设置。

## 进化流程

在对话中, agent 可通过对fork空间的变更完成自我进化

验证通过后 agent 以退出码 `-1` 退出, `run.py` 自动执行 slow→fast 交换并重启.前端在检测到 `build_hash` 变化时会自动刷新.

> 实际进化修复案例可参考[导出会话](.docs/c10b894cd4c1_2026-08-09-16-53-02.html), 其中展示了 agent 在运行时自主定位并修复多模态图片传递丢失等 bug 的完整过程.

## 扩展机制

### custom_tools

在 `custom_tools/` 目录下编写 `.py` 文件, 在模块顶层调用 `registry.register()` 注册工具, 启动时由 AST 扫描自动发现并加载（`abstract/tools/discover.py`）.

**发现规则**：

- 递归扫描 `custom_tools/` 下所有 `.py`（支持子目录, 如 `memory_tools/remember.py`）.
- 仅识别**模块顶层**的 `registry.register(...)` 调用, 函数体内的注册不会被检测到.
- 跳过文件名以 `_` 开头的文件（如 `_store.py`, 用作共享逻辑）、`__init__.py` 与 `registry.py`.
- 沙盒命名空间 `custom_tools:` 对 agent 只读.

**`registry.register()` 主要参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | — | 工具唯一名称 |
| `toolset` | `str` | — | 工具集分类（如 `custom`、`memory_tools`） |
| `schema` | `dict` | — | OpenAI 格式, 含 `description`（英文）与 `parameters` |
| `handler` | `Callable` | — | `(args: dict, context=None) -> dict` |
| `is_async` | `bool` | `False` | 为 `True` 时 handler 用 `async def`, 由事件循环 await |
| `danger_level` | `ToolDangerLevel` | `safe` | `safe`/`write`/`dangerous`/`critical`; `dangerous` 及以上需审批, `critical` 只能由用户亲自批准 |
| `availability` | `ToolAvailability` | `EVERY` | 可用范围: `MAIN`(主 agent) / `SUBAGENT`(子 agent) / `EVERY`(全部) |

**handler 签名**：首参 `args` 为 LLM 传入的参数 dict; 若 handler 声明了 `context` 形参, 框架会注入 `ToolContext`（含 `session_id`、`runtime_context`、`loop` 等, 见 `entry/base_agent_loop.py`）. handler 抛出的异常会被捕获并转为 `{"error": "..."}`.

**结果辅助函数**（`abstract/tools/registry.py`）：

- `tool_result(**kwargs)` 或 `tool_result(dict)` — 返回成功结果 dict.
- `tool_error(message, **extra)` — 返回 `{"error": message, **extra}`.

**完整示例**：

```python
from typing import Any

from abstract.tools.registry import registry, tool_result
from entity.puretype import ToolDangerLevel


# 将给定文本翻译为目标语言
def _handle_translate(args: dict[str, Any], context=None) -> dict:
    text = args["text"]
    target = args.get("target_lang", "en")
    # ... 翻译逻辑 ...
    return tool_result(success=True, translated=f"[{target}] {text}")


registry.register(
    name="translate",
    toolset="custom",
    schema={
        # 将给定文本翻译为目标语言。
        "description": "Translate the given text into the target language.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text to translate."},
                "target_lang": {"type": "string", "description": "Target language code.", "default": "en"},
            },
            "required": ["text"],
        },
    },
    handler=_handle_translate,
    is_async=False,
    danger_level=ToolDangerLevel.safe,
)
```

> 工具 schema 的 `description` 用英文, 紧邻其上的注释用中文. 仓库内置的记忆工具 `custom_tools/memory_tools/`（`remember` / `forget`）可作为参考实现.

### custom_llm_client

在 `custom_llm_client/` 目录下编写 `.py` 文件, 暴露 `create_llm_client(runtime_context, profile)` 工厂函数, 返回 `BaseLLMClient` 子类实例.启动时由 `abstract/llm/loader.py` 动态加载.内置 `openai_client.py`、`anthropic_client.py` 和 `kscc_client.py`.

```python
from abstract.llm.client import BaseLLMClient

class MyClient(BaseLLMClient):
    async def chat(self, messages, tools=None, response_format=None, character=""):
        ...
    async def chat_stream(self, messages, tools=None, response_format=None, character=""):
        ...

def create_llm_client(runtime_context, profile=None):
    return MyClient(...)
```

### custom_models

放置 `.gguf` 模型文件, 可作为审批模型加载.配置项 `approval_model` 指向该目录下的模型文件名.

### custom_hooks

`custom_hooks/` 下文件名不以 `_` 开头的 `.py` 脚本在启动时自动加载.每个脚本必须定义 `hook_tag_name(**kwargs)`（返回标签字符串, 用于生成 `<|im_{tag}_start|>` / `<|im_{tag}_end|>` 标记）, 并至少定义 `hook_message` 或 `hook_fixator` 之一：

- `hook_message`：返回**非持久化**上下文, 仅追加到最新一轮 `UserMessage` 末尾, 不写入历史记录, 下一轮即失效.
- `hook_fixator`：返回**持久化**上下文, 追加到磁盘历史与内存历史, 后续轮次仍保留.标签格式为 `<|im_{tag}_fixator_start|>` / `<|im_{tag}_fixator_end|>`.

两个函数均以关键字形式接收 `session_id`、`workspace`, 并可通过 `kwargs["runtime_ctx"]` 获取 `RuntimeContext` 单例.

完整编写指南见[上下文扩展块hook说明](custom_hooks/README.md).

### skills

运行时 `skills/` 目录用于存放技能.

`pre-skills/` 目录是推荐并且兼容的技能, 初次运行时如果没有skills目录会自动拷贝.

### MCP

配置文件位于 agentspace 目录下, 默认路径 `workspace/agentspace/mcp_config.json`（文件名由 `mcp_config_path_name` 配置项控制）.`mcp` Python 包为可选依赖, 未安装时自动跳过.支持 stdio 与 HTTP/SSE 传输：

```json
{
  "filesystem": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
    "env": {},
    "timeout": 120,
    "connect_timeout": 60
  },
  "remote_api": {
    "url": "https://example.com/mcp",
    "headers": {"Authorization": "Bearer sk-..."}
  },
  "sse_server": {
    "url": "http://localhost:8000/sse",
    "transport": "sse"
  }
}
```

每个条目以名称为键, 必须包含 `command`（stdio）或 `url`（HTTP/SSE）.可选字段：`args`、`env`（环境变量, 支持 `${VAR}` 插值）、`headers`、`timeout`（工具调用超时）、`connect_timeout`（连接超时）、`enabled`（设为 `false` 可临时禁用）.`component/mcp_tools.py` 在启动时连接所有 server 并注册其工具.配置文件不存在时自动创建空配置, agent 可通过 `ws:` 命名空间编辑后调用 `mcp_refresh` 工具热重载, 无需重启.