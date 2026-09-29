---
name: character-management
description: "基于文件系统的角色档案管理工作流，用于动态发现、配置和运行子Agent"
category: workflow
tags:
  - character
  - subagent
  - profile
  - 角色管理
  - 模板库
  - subagent-templates
---

# Character Management — 角色档案管理 Skill

## 概述

在 `characters/` 目录下创建和管理子Agent角色档案。Evolve Agent 每次获取子Agent列表或启动子Agent时动态扫描角色目录，不需要调用注册工具。

每个角色目录包含：

- `profile.md`：角色档案，同时作为第一个自定义系统提示词。
- `profile.md.meta`：元数据文件，通过 `[llm_profile]` 直接引用前端「模型配置」中已有的 LLM Profile 名称；可选的 `[profile]` 字段按行声明附加系统提示词文件的沙盒命名空间路径，系统按声明顺序将每个文件作为独立 system message 加载。
- `.es` 历史文件：可选。系统停止子Agent后默认写入 `ws:tmp/<session_id>.es`，Agent 可按需移动到角色目录。

角色名称在 `roleplay` 和 `task` 两类目录之间全局唯一。重复名称会在列表中显示错误，但不能启动。

## 目录结构规范

```text
characters/
├── README.md
├── roleplay/
│   └── <角色名>/
│       ├── profile.md
│       └── profile.md.meta
└── task/
    └── <角色名>/
        ├── profile.md
        └── profile.md.meta
```

路径约定：

| 类型 | 路径 | 说明 |
|---|---|---|
| 角色扮演型 | `ws:characters/roleplay/<角色名>/` | 像真人一样演绎角色 |
| 任务执行型 | `ws:characters/task/<角色名>/` | 聚焦具体任务交付 |

## `profile.md.meta` 格式

`profile.md.meta` 使用项目统一的元数据文件格式。必须提供 `[llm_profile]`，值是 `llm_profiles.es` 中已有的 Profile 名称；可选的 `[profile]` 值按行填写附加系统提示词文件的沙盒命名空间路径：

```text
[llm_profile]
coding-model

[profile]
ws:prompts/common/backend-rules.md
ws:prompts/common/review-checklist.md

[description]
用于后端开发任务的模型配置
```

系统先加载角色目录中的 `profile.md`，再按 `[profile]` 的书写顺序加载这些文件；每个文件对应一个独立 system message。空行会忽略，路径必须是当前模式可读的沙盒命名空间路径。文件不存在、不是文件或无权读取时，角色会在 `ListSubAgents` 中保留错误并被 `RunSubAgent` 拒绝。

LLM 配置不复制到角色目录，也不在角色目录中保存 `base_url`、`api_key` 或模型参数。每次动态获取角色档案时，系统按名称解析当前 Profile。

当元数据文件缺失、格式错误、缺少 `[llm_profile]` 或引用的 Profile 不存在时：

- `ListSubAgents` 保留角色条目并返回错误。
- `RunSubAgent` 拒绝启动并返回错误。
- 进入多Agent模式时，显式指定该角色会失败；无参进入会过滤该角色。

## 创建角色

### 步骤 1：创建角色目录和档案

```text
Write(path="ws:characters/task/BackendDeveloper/")
Write(path="ws:characters/task/BackendDeveloper/profile.md", content="...")
Write(path="ws:characters/task/BackendDeveloper/profile.md.meta", content="[llm_profile]\ncoding-model\n")
```

创建后不需要额外执行注册步骤。下一次 `ListSubAgents` 或 `RunSubAgent` 会自动发现该角色。

### 步骤 2：检查动态发现结果

```text
ListSubAgents()
```

确认以下字段：

- `name`
- `type`
- `profile_path`
- `llm_profile_name`
- `profile_available`
- `error`
- `session`

列表不返回完整 LLM 配置和 `api_key`。需要查看模型配置时，直接读取工作空间中的 LLM Profile 文件。

### 步骤 3：启动角色

```text
RunSubAgent(
    name="BackendDeveloper",
    initial_prompt="请完成后端接口实现。",
    user_name="Eve",
    message_type="direct"
)
```

每次启动都会重新读取 `profile.md`、`profile.md.meta` 和当前引用的 LLM Profile。修改这些文件后不需要重新注册。

## 历史记忆

历史继承必须显式指定。没有 `history_path` 时，子Agent从空历史开始：

```text
RunSubAgent(
    name="BackendDeveloper",
    history_path="ws:tmp/<session_id>.es",
    initial_prompt="继续处理上一次任务。",
    user_name="Eve",
    message_type="direct"
)
```

`StopSubAgent` 停止普通子Agent后，默认返回 `ws:tmp/<session_id>.es`。该文件是临时历史，是否移动到角色目录由 Agent 自行决定：

```text
Move(
    source="ws:tmp/<session_id>.es",
    destination="ws:characters/roleplay/Noire/history.es"
)
```

历史格式始终是 easysave `.es`，不是 JSONL。TaskAgent 不保存历史。

## `profile.md` 写作规范

### 角色扮演型

- 通篇使用第二人称“你”，像在介绍一个真实的人。
- 描述外观、服饰、性格、人物关系、说话方式和知识边界。
- 不写“子Agent”“注册”“通过工具启动”等机制性内容。
- 角色的动作和心理描写按角色自身约定表达。

示例结构：

```markdown
# Noire（诺瓦修女）

你是 Noire，一个成熟御姐型的修女。

## 外观

## 性格

## 人物关系

## 你怎么说话

## 知识

## 边界
```

### 任务执行型

- 使用第二人称“你”。
- 说明专长、工作方式、输入检查、产出规范和验收标准。
- 明确“我不做什么”的边界，避免角色越权。
- 可以包含任务流程和交付约束，但不要包含已经由 Evolve Agent 运行时保证的注册机制。

示例结构：

```markdown
# BackendDeveloper

你是后端开发专家。

## 核心设定

## 输入检查

## 工作流程

## 产出规范

## 验收清单

## 边界：我不做什么
```

## 内置模板库

`skills:workflow/character-management/templates/subagent-templates/` 提供 16 个领域、44 个专业角色模板，可直接复制到角色目录的 `profile.md`：

```text
AI/         AIArchitect · PromptEngineer · MachineLearningEngineer
Product/    ProductManager · UserResearcher
Writing/    Curator · Writer · Editor
Frontend/   Aesthetic · InteractionDesigner · FrontendArchitect · FrontendDeveloper
Backend/    BackendArchitect · DatabaseDesigner · BackendDeveloper · Auditor
Mobile/     MobileDesigner · MobileDeveloper
DevOps/     DevOps · SRE
Design/     Brander · VisualDesigner · Presenter
Data/       DataEngineer · DataAnalyst · DataViz
General/    ProjectManager · CodeReviewer · Localizer · Documentarian
Marketing/  MarketAnalyst · Marketer · Copywriter
Finance/    MacroAnalyst · IndustryResearcher · RiskManager
Legal/      LegalResearcher · ContractReviewer
Research/   LiteratureReviewer · Experimentalist · Academic
Games/      GameDesigner · GameDeveloper
AV/         Director · Producer
```

两种模板风格：

- Grill Me 质询型：适用于策划、设计、架构和研究角色。
- 执行型：适用于开发、撰稿、翻译和制作角色。

推荐流水线：

```text
Software Engineering:
ProductManager → InteractionDesigner → Aesthetic → FrontendArchitect / BackendArchitect
→ DatabaseDesigner → FrontendDeveloper / BackendDeveloper → CodeReviewer → Auditor → DevOps → SRE

Content Creation:
Curator → Writer → Editor

Data Analysis:
DataEngineer → DataAnalyst → DataViz

Research:
LiteratureReviewer → Experimentalist → Academic
```

## 更新已有角色

直接修改 `profile.md` 或 `profile.md.meta`。下一次列表或启动会动态读取新内容，不需要重新注册。

- 修改 `profile.md`：影响下一次子Agent的第一个自定义系统提示词。
- 修改 `[profile]`：影响下一次子Agent加载的附加系统提示词及其顺序。
- 修改 `[llm_profile]`：影响下一次子Agent使用的 LLM Profile。
- 修改其他元数据：只作为角色档案元数据保留，不自动改变运行时配置。
- 角色名称不能通过修改目录名与其他角色冲突；全局同名角色不可运行。
