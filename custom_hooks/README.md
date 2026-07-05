# Custom Hooks — 上下文扩展

`custom_hooks/` 是 Evolve Agent 的上下文扩展点。放在这里的 Python 脚本会在启动时被自动加载，并在每一轮最新 `UserMessage` 的末尾动态附加一段上下文，供 LLM 感知当前时间、最近上传、会话间隔等实时信息。

---

## 第一次运行

1. 在 `custom_hooks/` 下新建一个 `.py` 文件，文件名不要以下划线开头。
2. 实现 `hook_tag_name` 和 `hook_message`（或 `hook_fixator`）。
3. 启动或重启 `python run.py --load <config_key>`。
4. 发送一条消息，观察 LLM 是否收到了你附加的上下文。

最小示例 `custom_hooks/my_first_hook.py`：

```python
from datetime import datetime


def hook_tag_name(**kwargs) -> str:
    return "turn_time"


def hook_message(session_id: str = "", workspace: str = "", **kwargs) -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
```

如果当前只有这一个 hook，用户发送 `"现在几点了"` 时，实际发给 LLM 的内容会变成：

```text
现在几点了
<|im_turn_time_start|>2026-07-05 12:00:00<|im_turn_time_end|>
```

---

## 后续如何运行

- 启动时，`origin_agent/entry/agent_support/messages.py` 会自动扫描 `custom_hooks/*.py` 并加载所有合法 hook。
- 新增、修改或删除 hook 后，需要**重启**进程才能生效。
- 不需要手动注册，也不需要修改核心源码。

---

## 如何修改

### 必备函数

每个 hook 脚本必须定义：

- `hook_tag_name(...)` —— 返回一个字符串标识符，用于生成标签 `<|im_{tag}_start|>` / `<|im_{tag}_end|>`。
- `hook_message(...)` 或 `hook_fixator(...)` 至少一个 —— 返回要附加的上下文字符串。

### 推荐签名

```python
def hook_tag_name(**kwargs) -> str:
    ...


def hook_message(session_id: str = "", workspace: str = "", **kwargs) -> str:
    runtime_ctx = kwargs.get("runtime_ctx")
    ...
```

调用方会优先以关键字参数形式调用：`fn(session_id=..., workspace=..., runtime_ctx=...)`。因此推荐用默认参数 + `**kwargs` 接收 `runtime_ctx`。

旧的两参数签名 `def hook_message(session_id, workspace)` 仍然兼容：当关键字调用失败时，调用方会自动回退到位置调用。

### `hook_message` 与 `hook_fixator` 的区别

| 函数 | 是否发送给 LLM | 是否持久化到历史 |
|---|---|---|
| `hook_message` | 是 | 否，只在最新一轮生效 |
| `hook_fixator` | 是 | 是，追加到磁盘 JSONL 和内存历史，后续轮次仍保留 |

`hook_fixator` 的标签格式为 `<|im_{tag}_fixator_start|>` / `<|im_{tag}_fixator_end|>`。

### 返回值约定

- 返回非空字符串：附加该内容。
- 返回空字符串或 `None`：该 hook 本轮不产生上下文。

---

## 完整示例

`custom_hooks/time_gap_hook.py`：在每轮对话中提示与上一条消息的间隔，并把首次启动标记持久化到历史。

```python
import json
from datetime import datetime
from pathlib import Path


def hook_tag_name(**kwargs) -> str:
    return "turn_time"


def hook_fixator(session_id: str = "", workspace: str = "", **kwargs) -> str:
    # 仅示例：把首次启动标记写进持久化历史
    flag_path = Path(workspace) / "flag.json"
    if flag_path.exists():
        runtime_flag = json.loads(flag_path.read_text(encoding="utf-8"))
        if __file__ not in runtime_flag:
            return "This is the first message after the program started."
    return ""


def hook_message(session_id: str = "", workspace: str = "", **kwargs) -> str:
    cache_path = Path(workspace) / "session_cache" / session_id / "time_hook.json"
    now = datetime.now()

    if not cache_path.exists():
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"last_turn_time": now.isoformat()}, ensure_ascii=False))
        return "this is the first message of the conversation, or session cache is been cleared"

    cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
    last_time = datetime.fromisoformat(cache_data["last_turn_time"])
    interval_seconds = int((now - last_time).total_seconds())

    cache_data["last_turn_time"] = now.isoformat()
    cache_path.write_text(json.dumps(cache_data, ensure_ascii=False))

    if interval_seconds > 3600:
        hours = interval_seconds // 3600
        minutes = (interval_seconds % 3600) // 60
        return f"This conversation is {hours}h {minutes}m after the last one."
    return f"This message between the previous one is {interval_seconds} seconds."
```

---

## 运行时信息

通过 `kwargs.get("runtime_ctx")` 可以拿到 `RuntimeContext` 单例，常用字段包括：

- `workspace` —— 工作区根目录。
- `agentspace` —— 当前 agent 的命名空间路径（`Path`）。
- `fork_path` —— 当前 fork 路径。
- `mode` —— 当前运行模式。
- `llm_model` —— 当前使用的 LLM 模型名。

例如：

```python
def hook_message(session_id: str = "", workspace: str = "", **kwargs) -> str:
    runtime_ctx = kwargs.get("runtime_ctx")
    if runtime_ctx is None:
        return ""
    agentspace = runtime_ctx.agentspace
    ...
```

`recent_uploads_hook.py` 中展示了实际用法：通过 `runtime_ctx.agentspace` 定位 `uploads/` 目录。

### 导入内部模块

hook 脚本执行时位于 `origin_agent` 的运行时环境中，因此可以直接导入内部模块获取常量或类型：

```python
from entity.constant import UPLOAD_FILENAME_TIME_FORMAT
from system.context import RuntimeContext
```

注意：这会让 hook 与 `origin_agent` 源码耦合。如果源码路径或接口变更，hook 也需要同步更新。

---

## 注意事项

- 文件名不要以 `_` 开头，否则会被跳过。
- 单个脚本可以只定义 `hook_message`，或只定义 `hook_fixator`，或同时定义两者。
- hook 异常会被调用方捕获并记录日志，但建议关键路径自行处理异常，避免某一轮上下文丢失。
- 如果需要持久化状态，建议放在 `workspace/session_cache/` 下，避免污染仓库源码。
- 修改 hook 后需要重启进程才能生效。