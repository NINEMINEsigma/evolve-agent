---
name: create-eve-tool
description: 通过一次一个问题的质询流程引导用户为 Evolve Agent 项目创建新工具。结合 grill-me 质询方法论和对象工具声明协议，逐个决策点澄清工具的 name、toolset、schema、danger_level、accepts_following_calls 等字段以及 before/handle/after 阶段与元数据，最终生成包含 import、BaseTool 子类和顶层 TOOLSET = BaseToolSet(...) 的完整 .py 文件。当用户想创建新工具、注册新工具、添加 Agent 工具，或提到“新建工具”“create tool”“register tool”时使用。
disable-model-invocation: true
---

# Create Evolve Tool — 质询式工具创建 Skill

> **理念**：工具质量的上限取决于意图的清晰度。在写下任何一行工具代码之前，先把工具的语义边界、副作用、危险级别、调用态与批次边界逐个澄清。

本 skill 借用 grill-me 的一次一问质询方法论，沿对象工具声明的决策树逐个澄清字段，最终输出符合对象工具契约的完整 `.py` 文件。

---

## 响应格式要求

本 skill 的所有响应都必须以当前阶段的标注开头：

```
[PHASE: Init]
[PHASE: Interrogate]
[PHASE: Schema]
[PHASE: Phases]
[PHASE: Metadata]
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
   - `toolset` — 工具集归属（core / filesystem / multiagent / browser / ... 或自定义工具集名）
   - `description` — 英文描述 + 上方中文注释
   - `parameters` — JSON Schema 参数定义
   - `handle` — 工具主体逻辑、返回值与错误策略
   - `before_handle` / `after_handle` — 是否需要在工具调用前准备或提交后收尾
   - `is_async` — 是否异步
   - `availability` — 可用范围（ToolAvailability 位掩码）
   - `danger_level` — 危险级别（safe / write / dangerous / critical）
   - `accepts_following_calls` — 同批后续调用接收声明
   - `no_timeout` / `max_result_size_chars` — 超时与结果上限
   - `check_fn` / `requires_env` — 运行期可用性与环境依赖
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
- 按**依赖顺序**遍历：先 `name` → `toolset` → `description` → `parameters` → `danger_level` → `is_async` → `accepts_following_calls` → `no_timeout` → `availability`，再进入 `handle` 逻辑与 `before_handle` / `after_handle` 阶段。
- 当答案可通过检查现有工具获得时，**优先探索代码库**。用 Grep 搜索 `^TOOLSET = ` 或 `BaseTool` 子类找现有工具作为参考。
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

### [PHASE: Phases] 4. 阶段方法设计

对象工具有三个调用阶段，均接收本次调用独有的 `ToolExecution`：

- `handle(execution) -> ToolHandlerResult`（**必须实现**）：工具主体，执行实际业务操作。返回值用 `ToolHandlerResult(result=..., state=...)` 包装，`result` 为 LLM 看到的结果 dict，`state` 为可在 `after_handle` 读取的非持久化调用态。
- `before_handle(execution)`（可选）：在审批通过后、主体之前准备本次调用，默认空实现。
- `after_handle(execution) -> ToolPostprocessEffect`（可选）：**仅在结果提交 History 后**执行，用于提交后收尾（替换结果 payload、发送 UI 事件、请求停止本轮或进化等），默认返回空效果。

澄清每个阶段的：

- 主体逻辑流程（伪代码级别）
- 返回值结构（`tool_result(...)` / `tool_error(...)`）
- 错误处理策略：`handle` 抛出的异常会被分发层转换为 error payload，业务错误应显式返回 `tool_error(...)`
- 副作用与前置条件
- 调用态：跨阶段的材料应放进 `execution.state`，**不得**改共享工具实例、Application 或持久化存储
- 需要的 `after_handle` 效果：`replacement_result`、`suppress_tool_result_event`（必须同时显式 discard 自身 ID）、`stop_current_round`、`loop_replaced`、`evolution_requested`、`completion_message`

### [PHASE: Metadata] 5. 注册元数据确认

确认 `BaseTool.__init__` 的其余元数据（即 `TOOLSET = BaseToolSet(...)` 中工具实例的字段）：

- `is_async` — `handle` / `after_handle` 是 `async def` 时设为 `True`；同步阻塞任务保持 `False`，由 ToolRegistry 唯一执行器持有真实线程任务
- `availability` — 使用 `ToolAvailability` 指定可用范围（`MAIN` / `SUBAGENT` / `MULTI_AGENT` / `TASKAGENT` / `EVERY`）
- `danger_level` — `safe` / `write` / `dangerous` / `critical`；`dangerous` 及以上需审批，`critical` 只能由用户亲自批准
- `accepts_following_calls` — 默认 `True`；设为 `False` 表示同一模型响应中其后的 tool calls 在审批与执行前视为未发生（压缩类边界工具常见）
- `no_timeout` — 长阻塞工具设为 `True`
- `max_result_size_chars` — 结果上限，省略使用工具集默认
- `check_fn` / `requires_env` — 运行期可用性与环境依赖检查
- 工具集 `BaseToolSet(name=..., description=..., usage_guide=..., loaded_by_default=..., check_fn=..., requires_env=...)`，并可用 `preheat()` 做一次注册期可用性检查（不启动重量资源）

### [PHASE: Verify] 6. 事前校验

生成代码前进行 pre-check：

- `name` 是否与现有工具冲突？（Grep 搜索 `name="<tool_name>"`）
- `toolset` 是否与工具所属 `BaseToolSet.name` 一致？（`BaseToolSet` 构造会校验，二者必须相同）
- `description` 是否包含所有必需段落（Prerequisites / Effect / Returns / When to Use / Side Effects）？
- 中文注释是否覆盖了每个 `description` 字段？
- `handle` 是否返回 `ToolHandlerResult`？业务错误是否用 `tool_error(...)` 显式返回？
- 跨阶段材料是否只放在 `execution.state`，未写入共享工具实例？
- `danger_level` 是否与工具实际副作用匹配？`accepts_following_calls` 是否符合批次语义？
- `parameters` 的 `required` 列表是否合理？

发现问题则回到对应 PHASE 追问。

### [PHASE: Output] 7. 生成完整文件

所有决策标记为 `[RESOLVED]` 后，生成完整 `.py` 文件，结构如下：

```python
# 文件头部：imports（只导入必要的）
# BaseTool 子类：__init__ 声明元数据与 schema；handle 实现主体；可选 before_handle / after_handle
# 顶层固定名称声明：TOOLSET = BaseToolSet(name="<toolset>", tools=(<YourTool>(),))
```

文件应：

- 包含所有必要的 import 语句
- 工具类继承 `BaseTool`，`__init__` 调用 `super().__init__(...)` 传入元数据，`handle`（及可选阶段）带完整类型注解
- 导出顶层固定名称 `TOOLSET = BaseToolSet(...)`，一个模块只能声明一个 `TOOLSET`
- 导入只创建无连接工具对象；不得在导入期取得 Application、注册工具（`registry.register` / `register_tool` / `register_toolset`）或创建连接，也不得导入 `abstract.tools.ui_event_router`。需要运行时服务时在 `handle` 内通过 `execution.context.app.get_system(...)` 取得
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

1. **对象声明与自动发现**：工具模块以顶层固定名称 `TOOLSET`（常量 `TOOLSET_DECLARATION_NAME`）声明 `BaseToolSet`，其中持有 `BaseTool` 子类实例。ToolDiscoverySystem 按 AST 只识别顶层 `TOOLSET`，按路径排序导入后交给唯一 `ToolRegistry` 以 `register_toolset(toolset, merge=True)` 注册并对每个声明执行一次 `preheat()`；Python 模块缓存不替代显式对象注册。以下退役协议直接失败：顶层 `register_tools` 函数、`registry.register()`/`register_tool()`/`register_toolset()` 顶层调用、`abstract.tools.ui_event_router` 导入、`abstract.tools.registry` 的 `registry` 全局导入、导入期注册，以及任何读取/语法/导入/注册错误。可选 `custom_tools/` 不存在时跳过；必需内置目录缺失属于错误。
2. **四阶段与调用态**：阶段为工具调用前 `before_handle`、工具主体 `handle`、工具调用后处理 `after_handle`；每次调用携带独立 `ToolExecution`，跨阶段材料只放 `execution.state`，不得写入共享工具实例或持久化。
3. **提交后 after**：`after_handle` 只在主体正常返回且结果提交 History 后执行；主体业务错误仍进入，主体抛出异常转换的 error 不进入。
4. **批次声明**：`accepts_following_calls=False` 时同一模型响应中其后的 tool calls 在审批与执行前视为未发生。
5. **description 字段**：内容用**英文**编写，上方必须附带**中文注释**。
6. **markdown 分段**：description 内按段落写明工具功能、前置条件（Prerequisites）、调用效果（Effect）、返回值（Returns）、何时使用（When to Use）、副作用（Side Effects）。
7. **中文注释位置**：每个 `description` 字段（包括嵌套参数的 description）上方必须有中文注释解释行为。

---

## 示例输出结构

最终生成的 `.py` 文件遵循以下骨架：

```python
"""<tool_name> tool for evolve-agent."""

from __future__ import annotations

from typing import Any

from abstract.tools.tool import (
    BaseTool,
    BaseToolSet,
    ToolExecution,
    ToolHandlerResult,
    ToolPostprocessEffect,
    tool_result,
)
from entity.puretype import ToolAvailability, ToolDangerLevel


class MyTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
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
            is_async=True,
            danger_level=ToolDangerLevel.safe,
            availability=ToolAvailability.MAIN,
            accepts_following_calls=True,
            no_timeout=False,
        )

    async def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        # 仅在执行时读取运行时服务；跨阶段材料写入 execution.state。
        result = await execution.context.app.get_system(SomeSystem).run(execution.arguments)
        return ToolHandlerResult(result=result)

    async def after_handle(self, execution: ToolExecution) -> ToolPostprocessEffect:
        # 仅在结果提交 History 后运行；默认空效果，需要时返回替换/停止/完成效果。
        return ToolPostprocessEffect()


TOOLSET = BaseToolSet(
    name="<toolset>",
    tools=(MyTool(),),
    description="<Short toolset description>",
)
```

---

## 触发关键词

当用户提到以下内容时激活本 skill：

- "新建工具" / "创建工具" / "create tool"
- "注册工具" / "register tool"
- "添加 agent 工具" / "add tool"
- "create-eve-tool"
