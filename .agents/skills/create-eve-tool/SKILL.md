---
name: create-eve-tool
description: 通过一次一个问题的质询流程引导用户为 Evolve Agent 项目创建新工具。结合 grill-me 质询方法论和显式注册协议，逐个决策点澄清工具的 name、toolset、schema、handler、danger_level 等字段，最终生成包含 imports、handler 和 register_tools(registry, ui_events) 的完整 .py 文件。当用户想创建新工具、注册新工具、添加 Agent 工具，或提到“新建工具”“create tool”“register tool”时使用。
disable-model-invocation: true
---

# Create Evolve Tool — 质询式工具创建 Skill

> **理念**：工具质量的上限取决于意图的清晰度。在写下任何一行注册代码之前，先把工具的语义边界、副作用、危险级别逐个澄清。

本 skill 借用 grill-me 的一次一问质询方法论，沿工具注册的决策树逐个澄清字段，最终输出符合工具注册规范的完整 `.py` 文件。

---

## 响应格式要求

本 skill 的所有响应都必须以当前阶段的标注开头：

```
[PHASE: Init]
[PHASE: Interrogate]
[PHASE: Schema]
[PHASE: Handler]
[PHASE: Register]
[PHASE: Verify]
[PHASE: Output]
```

- 每次响应包含且仅包含一个 PHASE 标签，出现在响应最开头。
- 不得切换 PHASE，除非确实进入下一阶段。

---

## 会话生命周期

### [PHASE: Init] 1. 初始化

会话开始时：

1. 读取用户对工具的初始描述。
2. 构建工具决策树，识别需要澄清的决策点及其依赖顺序：
   - `name` — 工具名称（snake_case，唯一）
   - `toolset` — 工具集归属（core / fs / web / ...）
   - `description` — 英文描述 + 上方中文注释
   - `parameters` — JSON Schema 参数定义
   - `handler` — 处理函数签名与逻辑
   - `is_async` — 是否异步
   - `availability` — 可用范围（ToolAvailability 位掩码）
   - `danger_level` — 危险级别（safe / write / dangerous / critical）
   - `no_timeout` — 是否禁用超时
3. 说明本次质询的范围和预计深度。

### [PHASE: Interrogate] 2. 质询主循环

按依赖顺序处理每个未解决的决策：

```
决策：<正在决定什么>

本地发现：
- <相关代码/配置/现有工具模式，或"本地未回答">

外部校准：
- <项目约定及来源，或"未发现强先例">

推荐：<采纳/改编/否决 + 原因>
可接受的权衡：<成本、风险或未来约束>

问题：<一个精确的问题>
```

**循环规则：**

- 一次只问**一个问题**。
- 每个问题附带**推荐答案**。
- 按**依赖顺序**遍历：先 `name` → `toolset` → `description` → `parameters` → `danger_level` → `is_async` → `no_timeout` → `availability`，再进入 `handler` 逻辑。
- 当答案可通过检查现有工具获得时，**优先探索代码库**。用 Grep 搜索 `registry.register(` 找现有工具作为参考。
- 不接受"待定"或模糊答案——追问到具体为止。
- 整个会话使用**中文**。工具的 `description` 字段内容用**英文**编写（遵循工具注册规范）。

### [PHASE: Schema] 3. 参数 Schema 定义

`description` 和 `toolset` 确定后，逐个参数澄清：

- 参数名称与类型
- 每个参数的 `description`（英文 + 上方中文注释）
- `required` 列表
- 嵌套对象的 `properties` 递归澄清
- `default` 值

每个参数遵循工具注册规范：中文注释在上方，英文 `description` 在下方。

### [PHASE: Handler] 4. Handler 函数设计

澄清 handler 的：

- 函数名（`_handle_<tool_name>`）
- 签名（参数列表）
- 核心逻辑流程（伪代码级别）
- 返回值结构
- 错误处理策略
- 副作用与前置条件

### [PHASE: Register] 5. 注册属性确认

确认 `registry.register()` 的其余属性：

- `is_async` — handler 是 `async def` 时设为 `True`；同步阻塞 handler 保持 `False`，由 ToolRegistry 唯一执行器持有真实线程任务
- `availability` — 使用 `ToolAvailability` 指定可用范围
- `danger_level` — `safe` / `write` / `dangerous` / `critical`
- `no_timeout` — 长阻塞工具设为 `True`

### [PHASE: Verify] 6. 事前校验

生成代码前进行 pre-check：

- `name` 是否与现有工具冲突？（Grep 搜索 `name="<tool_name>"`）
- `description` 是否包含所有必需段落（Prerequisites / Effect / Returns / When to Use / Side Effects）？
- 中文注释是否覆盖了每个 `description` 字段？
- `handler` 函数名是否与 `_handle_` 前缀一致？
- `danger_level` 是否与工具实际副作用匹配？
- `parameters` 的 `required` 列表是否合理？

发现问题则回到对应 PHASE 追问。

### [PHASE: Output] 7. 生成完整文件

所有决策标记为 `[RESOLVED]` 后，生成完整 `.py` 文件，结构如下：

```python
# 文件头部：imports（只导入必要的）
# handler 函数：_handle_<tool_name>(args, context) -> dict
# 唯一同步声明入口：register_tools(registry, ui_events) -> None
# registry.register(...) 与 ui_events.register(...) 只能在显式声明入口中调用
```

文件应：

- 包含所有必要的 import 语句
- handler 函数带完整类型注解
- 导出顶层同步 `register_tools(registry: ToolRegistry, ui_events: UIEventRouter) -> None`，所有工具与事件注册都放在该入口中
- 导入只定义函数、常量和类型；不得在导入期取得 Application、注册工具或创建连接。handler 执行时通过 ToolContext 的 app 或 `Application.current().get_system(T)` 取得唯一 System
- `description` 字段按工具注册规范：中文注释在上方，英文内容在下方
- markdown 分段：Prerequisites / Effect / Returns / When to Use / Side Effects

---

## 决策跟踪协议

在线跟踪每个字段的状态：

```
[OPEN] 字段已识别但未解决
[RESOLVED] 字段已确认
[DEFERRED] 字段有意推迟，附带触发条件
```

用户可随时要求**进度快照**——展示带状态标记的当前决策树。

---

## 注册规范要点

生成代码时必须遵守以下规则：

1. **自动发现**：AST 扫描顶层同步 `register_tools` 函数，按路径排序导入后显式传入唯一 ToolRegistry/UIEventRouter 调用。同一次发现每个模块只调用一次；已有 Python 模块缓存不影响显式注册。旧模块级注册、读取/语法/导入/注册错误直接失败，不能用吞错或修改 `sys.modules` 修补。可选 `custom_tools/` 不存在时跳过；必需内置目录缺失属于错误。
2. **description 字段**：内容用**英文**编写，上方必须附带**中文注释**。
3. **markdown 分段**：description 内按段落写明工具功能、前置条件（Prerequisites）、调用效果（Effect）、返回值（Returns）、何时使用（When to Use）、副作用（Side Effects）。
4. **中文注释位置**：每个 `description` 字段（包括嵌套参数的 description）上方必须有中文注释解释行为。

---

## 示例输出结构

最终生成的 `.py` 文件遵循以下骨架：

```python
"""<tool_name> tool for evolve-agent."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from abstract.tools.registry import ToolRegistry
from abstract.tools.ui_event_router import UIEventRouter
from entity.puretype import ToolAvailability, ToolDangerLevel

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext


async def _handle_<tool_name>(args: dict[str, Any], context: ToolContext) -> dict:
    """Execute the requested operation."""
    # 仅在 handler 执行时读取 context.app.get_system(...)。
    return {"result": "..."}


def register_tools(registry: ToolRegistry, ui_events: UIEventRouter) -> None:
    registry.register(
        name="<tool_name>",
        toolset="<toolset>",
        schema={
            # 工具功能、前置条件、调用效果、返回值、典型场景、副作用。
            "description": "<English description with Prerequisites/Effect/Returns/When to Use/Side Effects>",
            "parameters": {
                "type": "object",
                "properties": {
                    "<param1>": {
                        "type": "string",
                        # 参数说明。
                        "description": "<English description>",
                    },
                },
                "required": ["<param1>"],
            },
        },
        handler=_handle_<tool_name>,
        is_async=True,
        danger_level=ToolDangerLevel.safe,
        availability=ToolAvailability.MAIN,
        no_timeout=False,
    )
    # 有 UI 事件时在此调用 ui_events.register(...)，不要导入全局实例。
```

---

## 触发关键词

当用户提到以下内容时激活本 skill：

- "新建工具" / "创建工具" / "create tool"
- "注册工具" / "register tool"
- "添加 agent 工具" / "add tool"
- "create-eve-tool"