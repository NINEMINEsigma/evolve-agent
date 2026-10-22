# Custom Hooks — 上下文扩展

`custom_hooks/` 是 Evolve Agent 的上下文扩展点。放在这里的 Python 脚本会在启动时被自动加载，并在每一轮最新 `UserMessage` 的末尾附加上下文扩展块。

本文只描述钩子接口、调用机制与通用约定，不登记当前目录中的具体钩子或其专属内容。下列文件名和内容均为独立教学示例，不代表已安装扩展。

---

## 第一次运行

1. 在 `custom_hooks/` 下新建一个 `.py` 文件，文件名不要以下划线开头。
2. 实现 `hook_tag_name` 和 `hook_message`（或 `hook_fixator`）。
3. 启动或重启 `python run.py --load <config_key>`。
4. 发送一条消息，观察 LLM 是否收到了你附加的上下文。

最小教学示例（假设文件名为 `custom_hooks/my_first_hook.py`）：

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
- 新增、修改或删除 hook 后，需要**重启**进程才能生效（加载结果按 loop 实例缓存在进程内存中）。
- 不需要手动注册，也不需要修改核心源码。
- 加载失败以 ERROR 级别记录文件名；单轮收集失败以 WARNING 级别记录对应 tag。

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

以下为独立教学示例（假设文件名为 `custom_hooks/time_gap_hook.py`），演示非持久化上下文与固着器的区别，不代表目录中存在该扩展。

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
    cache_path = Path(workspace) / "session_cache" / session_id / "turn_cache.json"
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
- 其他完整字段以源码 `system/context.py` 中 `RuntimeContext` 的定义为准。

例如：

```python
def hook_message(session_id: str = "", workspace: str = "", **kwargs) -> str:
    runtime_ctx = kwargs.get("runtime_ctx")
    if runtime_ctx is None:
        return ""
    agentspace = runtime_ctx.agentspace
    ...
```

### 导入内部模块

hook 脚本以 `importlib.util.spec_from_file_location` 动态加载，加载时机不一定在
`sys.path` 注入 agent 根目录之后。因此 **内部模块的运行时导入必须写在函数体内**，
不能放在文件顶部：

```python
def hook_message(session_id: str = "", workspace: str = "", **kwargs) -> str:
    from entity.constant import UPLOAD_FILENAME_TIME_FORMAT
    from system.application import Application
    from interface.session_manager import ISessionManager
    ...
```

写在文件顶部的内部运行时导入会让整个文件加载失败（`ModuleNotFoundError`），
该 hook 从此不再出现在上下文里，且只有一条加载失败日志。

**类型注解例外**：只为标注类型而导入的类可以放在 `TYPE_CHECKING` 块里，
运行时不会执行，因此不破坏动态加载：

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from system.context import RuntimeContext


def hook_message(
    session_id: str = "",
    workspace: str = "",
    runtime_ctx: "RuntimeContext | None" = None,
    **kwargs,
) -> str:
    ...
```

注意：这会让 hook 与 `origin_agent` 源码耦合。如果源码路径或接口变更，hook 也需要同步更新。

### 查询运行时系统必须用接口槽位

`Application` 只按接口注册系统，例如 `ISessionManager`、`IAgentspaceService`。
用具体实现类查询（如 `get_system(SessionManager)`、`get_system(AgentspaceService)`）
会抛 `RuntimeError: System ... is not registered`，导致该 hook 每一轮都静默返回空串：

```python
from interface.session_manager import ISessionManager
sm = Application.current().get_system(ISessionManager)   # 正确
```

### 路径基准

`hook_message(session_id, workspace, ...)` 的 `workspace` 是 `RuntimeContext.workspace`，
即 `workspace/` 根目录（不是 `workspace/agentspace/`）。启动标记 `flag.json` 与
会话缓存目录 `session_cache/` 都在该根目录下；读写这些文件时要允许文件缺失，
否则一次 `FileNotFoundError` 会让整块上下文被丢弃。

---

## 注意事项

- 文件名不要以 `_` 开头，否则会被跳过。
- 单个脚本可以只定义 `hook_message`，或只定义 `hook_fixator`，或同时定义两者。
- hook 异常会被调用方捕获并记录日志，但建议关键路径自行处理异常，避免某一轮上下文丢失。
- 如果需要持久化状态，建议放在 `workspace/session_cache/` 下，避免污染仓库源码。
- 修改 hook 后需要重启进程才能生效。
- 内部模块导入必须写在函数体内，且运行时系统一律按接口槽位（`ISessionManager` 等）查询。