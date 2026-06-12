---
name: 允许工具返回 dict 或 str
overview: 修改工具返回值类型，允许 handler 直接返回 dict，减少 agent.py 中不必要的 json.loads 反复解析。
todos:
  - id: "1"
    content: 修改 abstract/tools/registry.py dispatch 返回类型为 Any
    status: completed
  - id: "2"
    content: 修改 abstract/memory/manager.py handle_tool_call 返回类型为 Any
    status: completed
  - id: "3"
    content: 修改 abstract/memory/provider.py handle_tool_call 返回类型为 Any
    status: completed
  - id: "4"
    content: 修改 agent.py 中 result 变量注解为 Any
    status: completed
  - id: "5"
    content: 在 agent.py 插入结果类型归一化逻辑
    status: completed
  - id: "6"
    content: 替换 agent.py 中所有 json.loads(result) 解析块为 result_dict 用法
    status: completed
isProject: false
---

## 背景

当前工具 handler（registry.dispatch、memory.handle_tool_call）的返回类型强制为 `str`，`agent.py` 拿到结果后需多次 `json.loads(result)` 解析回 `dict` 以进行错误统计、多模态提取（`_image`）、截断、前端推送等操作。用户希望允许工具直接返回 `dict`，提升灵活性并消除反复序列化/反序列化。

## 修改范围

### 1. `origin_agent/abstract/tools/registry.py`

- `dispatch` 返回类型：`str` -> `Any`
- 更新 docstring，说明支持返回 `dict` 或 `str`

### 2. `origin_agent/abstract/memory/manager.py`

- `handle_tool_call` 返回类型：`str` -> `Any`
- 更新 docstring

### 3. `origin_agent/abstract/memory/provider.py`

- `handle_tool_call` 返回类型：`str` -> `Any`
- 更新 docstring

### 4. `origin_agent/entry/agent.py`（主要改动）

#### 4.1 修改变量类型注解
`result: str = ""` -> `result: Any = ""`（约 1153 行）

#### 4.2 插入结果类型归一化逻辑
在 `# ---- 追踪工具错误统计 ----` 之前插入：

```python
        # ---- 统一工具结果类型 ----
        # 工具 handler 可返回 dict 或 str；统一提取 dict 并确保 result 为 str，
        # 使下游截断、推送等逻辑无需改动。
        result_dict: dict | None = None
        if isinstance(result, dict):
            result_dict = dict(result)          # 拷贝，避免内部 pop 修改原始值
            result = json.dumps(result, ensure_ascii=False)
        elif isinstance(result, str):
            try:
                _parsed = json.loads(result)
                if isinstance(_parsed, dict):
                    result_dict = _parsed
            except (json.JSONDecodeError, TypeError):
                pass
        else:
            result = str(result)
```

#### 4.3 替换所有 `json.loads(result)` 解析块

| 原逻辑位置 | 原代码 | 替换为 |
|---|---|---|
| 错误统计（~1222） | `try: parsed = json.loads(result)... except...` | `if result_dict is not None and "error" in result_dict:` |
| 多模态提取（~1234） | `try: parsed_result = json.loads(result); img = parsed_result.pop("_image", None)... except...` | `if result_dict is not None:`，内部用 `parsed_result = dict(result_dict)` 拷贝后处理；修改 `result` 时同步更新 `result_dict` |
| 进度条推送（~1286） | `try: _pp = json.loads(result)... except...` | `if result_dict is not None and "_image" in result_dict:` |
| 剪贴板推送（~1303） | `try: _dp = json.loads(result)... except...` | `if result_dict is not None and "_image" in result_dict:` |
| tool_result 推送（~1322） | `try: pr = json.loads(result)... except...` | `if result_dict is not None and "_image" in result_dict:` |

#### 4.4 截断逻辑保持不变
`len(result)` 和 `result[:2000]` 继续作用于 `result`（此时已确保为 `str`）。

#### 4.5 最终 content 保持不变
`content = multimodal_content if multimodal_content is not None else result` —— `result` 为 `str`，符合 OpenAI tool message 格式。

## 兼容性

- 现有返回 `str` 的工具完全不受影响（`result_dict` 会通过 `json.loads` 正常解析）。
- 新工具可直接 `return {"key": "value"}`，`agent.py` 会自动序列化为 JSON 字符串后发给 LLM。
- 异常处理路径（`json.dumps({"error": ...})`）仍返回 `str`，与现有行为一致。
