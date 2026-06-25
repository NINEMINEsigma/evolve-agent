---
name: 工具 description 优化计划
overview: 逐文件优化 origin_agent 所有工具的 description，统一使用 markdown 格式的三引号字符串，中文注释在上、英文 description 在下。
todos:
  - id: code-evolve
    content: code.py — evolve_code
    status: completed
  - id: frontend-validate
    content: frontend.py — validate_frontend
    status: completed
  - id: read-image
    content: read_image.py — read_image
    status: completed
  - id: list-uploads
    content: list_uploads.py — list_uploads
    status: completed
  - id: progress-tools
    content: progress_tools.py — set_task_progress, clear_task_progress
    status: completed
  - id: probe-vision
    content: probe_vision.py — probe_vision_capability
    status: completed
  - id: run-python
    content: run_python.py — run_python
    status: completed
  - id: shell-command
    content: shell.py — run_command
    status: completed
  - id: skills
    content: skills.py — 7 个工具
    status: completed
  - id: filesystem
    content: filesystem.py — 19 个工具全部完成 ✅（含新增 copy_folder、delete_file 不删目录、resolve_path 约束）
    status: completed
  - id: constant-refactor
    content: constant.py — 常量文件重新分区整理
    status: completed
  - id: extools
    content: component/extools/ — 全部 extools 工具描述已按规范重写完成
    status: completed
  - id: multiagent
    content: component/mutliagenttools/ — 全部多 Agent 工具
    status: completed
isProject: false
---

# 工具 description 优化计划

## 初始

阅读所有工具的使用方法和当前的description, 接下来我们需要优化description的内容, 使其更好的描述调用前置条件, 如何调用, 参数意义, 参数范围, 调用效果, 如何返回, 可被用作什么, 有什么副作用等等

## 已完成

- `list_tools.py` — `list_tools`
- `ask_question.py` — `ask_question`
- `clipboard_display_tools.py` — `set_clipboard_display`, `clear_clipboard_display`
- `code.py` — `write_fork`, `validate_code`, `evolve_code`
- `frontend.py` — `validate_frontend`
- `read_image.py` — `read_image`
- `list_uploads.py` — `list_uploads`

## 格式规范

每个工具的 `schema` 遵循以下格式：

### description 字段

- 使用 `"""..."""` 三引号字符串（不用 `()` 拼接）
- 内容为英文 markdown，按以下结构组织：

```
One-line summary.

## Prerequisites
What must be true before calling this tool.

## Effect / Parameters / Modes / ... (按需选用)
Detailed explanation of behavior, modes, limits.

## Returns
```json
{ "key": "value", ... }
```

## When to Use
- Scenario 1
- Scenario 2

## Side Effects / Notes
Any non-obvious side effects or caveats.
```

- 标题层次：`##` 二级标题，不使用 `#` 一级标题
- 可用元素：表格、代码块、无序列表
- 中文注释（`# ` 行注释）放在 `"description"` 上方，概括所有关键信息

### parameters 字段

- 每个参数的 `description` 也用三引号字符串
- 中文注释（`# ` 行注释）放在每个参数上方
- 内容简洁，覆盖：含义、类型、值域、默认值、与其他参数的互斥关系

### 危险等级理解

- `readonly` — 操作完全限定在沙箱内，不影响沙箱外系统
- `write` — 可能间接产生影响（写入脚本代码等，不会自动执行但内容可能含高风险操作）
- `dangerous` — 错误调用能直接对整台机器或重要内容造成毁灭性打击

## 工作流

每个工具的处理流程：

1. 读取文件，分析 handler 逻辑和当前 schema
2. 报告当前问题 + 建议改法
3. 用户确认后执行修改
4. 一次只讨论一个工具

## 待处理清单

### 第一层：`component/tools/`（10 个文件，约 34 个工具）

| # | 文件 | 工具 |
|---|------|------|
| 1 | `code.py` | `evolve_code` |
| 2 | `frontend.py` | `validate_frontend` |
| 3 | `read_image.py` | `read_image` |
| 4 | `list_uploads.py` | `list_uploads` |
| 5 | `progress_tools.py` | `set_task_progress`, `clear_task_progress` |
| 6 | `probe_vision.py` | `probe_vision_capability` |
| 7 | `run_python.py` | `run_python` |
| 8 | `shell.py` | `run_command` |
| 9 | `skills.py` | `learn_skill`, `list_skills`, `forget_skill`, `recall_skill`, `write_skill_file`, `read_skill_file`, `run_skill_script` |
| 10 | `filesystem.py` | `read_file`, `write_file`, `append_file`, `list_directory`, `delete_file`, `edit_file`, `file_exists`, `copy_file`, `move_file`, `rename_file`, `search_files`, `grep`, `resolve_path`, `create_folder`, `delete_folder`, `is_file`, `is_directory`, `count_lines` |

### 第二层：`component/extools/`（约 18 个文件，50+ 个工具）

浏览器、SSH、cron、GUI、web、文档、图表、diff、pip、excel、csv、docx、pdf、display、archive、background、diagram、mermaid

### 第三层：`component/mutliagenttools/`（约 7 个文件，7 个工具）

`run_subagent`, `approval_subagent`, `chat_subagent`, `register_subagent`, `register_subagent_from_parent`, `unregister_subagent`, `stop_subagent`, `list_subagents`
