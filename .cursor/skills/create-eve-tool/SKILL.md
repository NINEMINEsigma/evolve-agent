---
name: create-eve-tool
description: 通过一次一个问题的质询流程引导用户为 evolve-agent 项目创建新工具。结合 grill-me 质询方法论和工具注册规范，逐个决策点澄清工具的 name、toolset、schema、handler、danger_level 等字段，最终生成包含 imports + handler + registry.register 的完整 .py 文件。当用户想创建新工具、注册新工具、添加 agent 工具，或提到"新建工具""create tool""register tool"时使用。
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
   - `emoji` — 图标
   - `danger_level` — 危险级别（readonly / write / destructive）
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
- 按**依赖顺序**遍历：先 `name` → `toolset` → `description` → `parameters` → `danger_level` → `is_async` → `no_timeout` → `emoji`，再进入 `handler` 逻辑。
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

- `is_async` — 默认 `False`，阻塞型工具设为 `True`
- `emoji` — 与工具语义相关的单字符 emoji
- `danger_level` — `readonly` / `write` / `destructive`
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
# handler 函数：_handle_<tool_name>(ctx, params) -> dict
# 注册调用：registry.register(...)
```

文件应：

- 包含所有必要的 import 语句
- handler 函数带完整类型注解
- `registry.register()` 调用位于模块级别（自动发现机制要求）
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

1. **自动发现**：AST 扫描 `.py` 文件，模块级别包含 `registry.register()` 即被自动导入，无需额外注册。
2. **description 字段**：内容用**英文**编写，上方必须附带**中文注释**。
3. **markdown 分段**：description 内按段落写明工具功能、前置条件（Prerequisites）、调用效果（Effect）、返回值（Returns）、何时使用（When to Use）、副作用（Side Effects）。
4. **中文注释位置**：每个 `description` 字段（包括嵌套参数的 description）上方必须有中文注释解释行为。

---

## 示例输出结构

最终生成的 `.py` 文件遵循以下骨架：

```python
"""<tool_name> tool for evolve-agent."""

from typing import Any

# ... 其他必要 imports ...


async def _handle_<tool_name>(ctx: Any, params: dict) -> dict:
    """<工具功能简述>"""
    # ... handler 逻辑 ...
    return {"result": "..."}


registry.register(
    name="<tool_name>",
    toolset="<toolset>",
    schema={
        # <中文注释：工具功能、前置条件、调用效果、返回值、典型场景、副作用>
        "description": """<English description with Prerequisites/Effect/Returns/When to Use/Side Effects>""",
        "parameters": {
            "type": "object",
            "properties": {
                "<param1>": {
                    "type": "string",
                    # <中文注释：参数说明>
                    "description": """<English description>""",
                },
            },
            "required": ["<param1>"],
        },
    },
    handler=_handle_<tool_name>,
    is_async=<True|False>,
    emoji="<emoji>",
    danger_level="<readonly|write|destructive>",
    no_timeout=<True|False>,
)
```

---

## 触发关键词

当用户提到以下内容时激活本 skill：

- "新建工具" / "创建工具" / "create tool"
- "注册工具" / "register tool"
- "添加 agent 工具" / "add tool"
- "create-eve-tool"