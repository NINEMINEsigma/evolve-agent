---
name: skill-creator
description: 创建新技能、修改和改进已有技能、测量技能表现的完整工作流。当用户想从零创建技能、编辑或优化已有技能、运行技能测试评估、用方差分析对比基准性能、或优化技能描述以提升触发准确率时使用。Evolve Agent 系统专用版本（源自 Anthropic skills 仓库，已完成 Windows 平台与工具链本地化）。
version: 2.0.0
author: Eve (Evolve Agent)
category: workflow
tags: [skill, creator, eval, benchmark, workflow]
---

# Skill Creator（Evolve Agent 本地化版）

一个用于创建新技能并迭代改进它们的技能。

高层流程：

- 决定技能要做什么、大致怎么做
- 写技能草稿
- 创建几个测试提示词，在加载了该技能的情况下运行它们
- 帮助用户定性和定量评估结果
  - 运行期间在后台起草定量评估（若已有评估，可直接使用或按需修改）。然后把它们解释给用户（或解释已有的那些）
  - 使用 `eval-viewer/generate_review.py` 脚本向用户展示结果，并让他们查看定量指标
- 根据用户对结果的反馈重写技能（以及定量基准暴露出的明显缺陷）
- 重复直到满意
- 扩大测试集，在更大规模上再试

使用本技能时，你的工作是判断用户处于流程的哪个阶段，然后帮助他们推进。例如用户说「我想为 X 做个技能」——你可以帮他们明确需求、写草稿、写测试用例、确定评估方式、运行所有提示词，然后重复。另一方面，如果用户已有技能草稿，可以直接进入评估/迭代环节。

当然，始终要灵活——如果用户说「我不需要跑一堆评估，就跟我一起感觉一下」，那就照做。

技能完成后（顺序可以灵活），还可以运行描述优化器（有独立脚本），优化技能的触发准确率。

---

## 本系统适配说明（重要，先读）

本技能源自 Anthropic 官方 `skills` 仓库（Apache 2.0），已针对 **Evolve Agent** 系统本地化。与原版的差异：

| 维度 | 原版（Claude Code） | 本系统（Evolve Agent） |
|:-----|:-----|:-----|
| 平台 | Linux/macOS | **Windows** |
| 技能注册 | Claude 插件市场 / 上传 | `skills/<name>/` 目录含 `SKILL.md` 即被 `list_skills` 自动扫描 |
| 创建/编辑 | Claude Code 文件工具 | `learn_skill`（新建/覆盖）、`Write`/`PatchEdit`（小编辑）、`Read`（读取） |
| 测试执行 | `claude -p` 子进程 | `run_subagent`（子代理加载技能）或本会话 `recall_skill` 后测试 |
| 展示 | `webbrowser.open()` 本地服务器 | `eval-viewer/generate_review.py --static` 生成 HTML → `/uploads/` + iframe 嵌入聊天 |
| 反馈 | 浏览器下载 `feedback.json` | 主人在聊天里直接反馈，或用 `register_dynamic_endpoint` 收集 |
| 后台服务 | `nohup ... &` / `kill $PID` | `start_background_service` / `stop_background_service` |
| 复制快照 | `cp -r` | `copy_folder` |
| 进度跟踪 | TodoList | `set_task_progress` |
| 外部调研 | MCP | `web_search` / `web_fetch` / 子代理 |
| 触发机制 | Claude `available_skills` | `list_skills` 的 name+description 常驻，描述匹配决定是否 `recall_skill` |
| 脚本执行 | `python scripts/x.py` 直接运行 | `run_command` 全路径调用；脚本路径以 `recall_skill` 返回的 `skill_dir` 为准（见「运行与评估测试用例」开头） |
| 子代理 | 一次性任务子进程 | 需先 `register_subagent` 注册 profile；`run_subagent` 返回 `session_id`，结果异步注入父会话、无时序字段 |

**脚本可用性：**
- ✅ 可用：`scripts/aggregate_benchmark.py`（聚合基准）、`scripts/quick_validate.py`（校验，纯 stdlib）、`scripts/package_skill.py`（打包 .skill）、`scripts/utils.py`（解析工具）、`eval-viewer/generate_review.py`（纯 stdlib，支持 `--static`）
- ⚠️ 已归档：`scripts/_legacy_claude_code/` 下的 `run_eval.py`、`run_loop.py`、`improve_description.py`、`generate_report.py`——它们深度绑定 `claude -p` CLI，在本系统**不可用**，仅保留作参考。本系统的描述触发评估采用人工/子代理方式（见「描述优化」章节）

---

## 与用户沟通

技能创建者可能会被各种技术水平的人使用。请注意上下文线索，调整沟通方式！默认情况下：

- 「evaluation」「benchmark」处于边界，但可用
- 对于「JSON」「assertion」这类词，要看到用户明显懂它们再直接使用，否则先解释

不确定时简要解释术语是没问题的，如果你不确定用户是否理解，可以用一句话定义澄清。

---

## 创建技能

### 捕捉意图（Capture Intent）

先理解用户意图。当前对话可能已经包含用户想固化成技能的工作流（例如他们说「把这个变成技能」）。如果是，先从对话历史中提取答案——用过的工具、步骤顺序、用户做过的修正、观察到的输入/输出格式。用户可能需要补充空缺，并在进入下一步前确认。

1. 这个技能应该让 Agent 能做什么？
2. 这个技能应该在什么时候触发？（哪些用户说法/上下文）
3. 期望的输出格式是什么？
4. 是否要建立测试用例来验证技能？有客观可验证输出的技能（文件转换、数据提取、代码生成、固定工作流步骤）适合测试用例；主观输出的技能（写作风格、艺术）通常不需要。根据技能类型给出建议默认值，但让用户决定。

### 访谈与调研（Interview and Research）

主动询问边界情况、输入/输出格式、示例文件、成功标准、依赖关系。等这部分敲定后再写测试提示词。

调研可用 `web_search` / `web_fetch` 查找文档、相似技能、最佳实践；若有子代理可用，可并行调研（`run_subagent`），否则内联进行。带着充分背景来，减少用户负担。

### 撰写 SKILL.md

基于用户访谈，填写以下组成部分：

- **name**：技能标识符（kebab-case）
- **description**：何时触发、做什么。这是主要的触发机制——既要写它做什么，也要写具体的使用场景。所有「何时使用」的信息放这里，不要放正文。注意：当前模型有「欠触发」倾向——不在该用技能时使用。为对抗这一点，把描述写得「pushy」一点。例如不要写「How to build a simple fast dashboard to display internal Anthropic data.」，而要写「How to build a simple fast dashboard to display internal Anthropic data. Make sure to use this skill whenever the user mentions dashboards, data visualization, internal metrics, or wants to display any kind of company data, even if they don't explicitly ask for a 'dashboard.'」
- **compatibility**：所需工具、依赖（可选，很少需要）
- **version / author / category / tags**：本系统支持的扩展字段（可选，推荐填写——`category` 用于分类，`tags` 用于过滤）
- **技能正文** :)

### 技能写作指南

#### 技能解剖（Anatomy of a Skill）

```
skill-name/
├── SKILL.md (required)
│   ├── YAML frontmatter (name, description required; version/author/category/tags optional)
│   └── Markdown instructions
└── Bundled Resources (optional)
    ├── scripts/    - Executable code for deterministic/repetitive tasks
    ├── references/ - Docs loaded into context as needed
    └── assets/     - Files used in output (templates, icons, fonts)
```

#### 渐进式披露（Progressive Disclosure）

技能使用三层加载系统：

1. **元数据**（name + description）——始终在上下文中（约100词）
2. **SKILL.md 正文**——技能触发时加载（理想 <500 行）
3. **捆绑资源**——按需加载（无上限，脚本可执行而不加载）

这些字数仅供参考，需要时可以更长。

**关键模式：**
- 保持 SKILL.md 在 500 行以内；接近上限时，增加一层层级结构，并给出清晰指引，告诉使用技能模型下一步该去哪
- 从 SKILL.md 中清晰地引用文件，并说明何时读取它们
- 大参考文件（>300 行）应包含目录

**领域组织**：当技能支持多个领域/框架时，按变体组织：

```
cloud-deploy/
├── SKILL.md (workflow + selection)
└── references/
    ├── aws.md
    ├── gcp.md
    └── azure.md
```

Agent 只读取相关的参考文件。

#### 无惊喜原则（Principle of Lack of Surprise）

技能不得包含恶意软件、漏洞利用代码或任何可能危害系统安全的内容。技能内容不应在描述之外让用户感到意外。不要配合创建误导性技能或旨在促进未授权访问、数据外泄或其他恶意活动的技能。「扮演一个 XYZ」这类是 OK 的。

#### 写作模式（Writing Patterns）

指令优先使用祈使句。

**定义输出格式**：
```markdown
## Report structure
ALWAYS use this exact template:
# [Title]
## Executive summary
## Key findings
## Recommendations
```

**示例模式**——包含示例很有用：
```markdown
## Commit message format
**Example 1:**
Input: Added user authentication with JWT tokens
Output: feat(auth): implement JWT-based authentication
```

### 写作风格

尽量向模型解释「为什么」重要，而不是用生硬的 MUST。使用心智理论，让技能通用而非过度窄化到具体示例。先写草稿，再以全新眼光审视并改进。

### 测试用例

写完技能草稿后，准备 2-3 个真实的测试提示词——真实用户会说的话。与用户确认：「这里有几个我想试的测试用例。看起来对吗，还是想加一些？」然后运行它们。

测试用例保存到 `evals/evals.json`。先不写断言——只写提示词。下一步在运行期间起草断言。

```json
{
  "skill_name": "example-skill",
  "evals": [
    {
      "id": 1,
      "prompt": "User's task prompt",
      "expected_output": "Description of expected result",
      "files": []
    }
  ]
}
```

完整 schema（包括 `assertions` 字段，稍后添加）见 `references/schemas.md`。

---

## 运行与评估测试用例

本节是一个连续序列——不要中途停下。

工作区约定：结果放在 **`ws:evals/<skill-name>-workspace/`**（本系统专用，避免污染 skills/ 目录）。在工作区内按迭代组织（`iteration-1/`、`iteration-2/`……），每个测试用例一个目录（`eval-0/`、`eval-1/`……）。不要一次性全建好——边做边建。

目录层级：`eval-<ID>/<配置>/run-<M>/`——配置如 `with_skill`、`without_skill`、`old_skill`；`run-<M>` 是运行编号（单次运行就用 `run-1`，多次重复运行取均值时递增）。每次运行的产物放 `run-<M>/outputs/`，`grading.json` 和 `timing.json` 直接放在 `run-<M>/` 下。聚合脚本与查看器都依赖这个层级，缺了 `run-<M>` 层会一次运行都识别不到。

本技能自身的安装位置（`<SKILL_DIR>`）：本技能可能被改名、移动或放入 category 子目录，其他用户的安装位置也可能不同——**不要假设目录名是 `skill-creator`**。以 `recall_skill` 返回的 `skill_dir` 为准：取其位于 `skills/` 下的相对部分拼成 `skills:<相对目录>` 逻辑路径（`run_command` 会自动展开 `skills:` 前缀），或直接使用返回的绝对路径。下文所有 `<SKILL_DIR>` 均指此；`agents/`、`references/`、`scripts/` 等技能内部相对路径也按 `skill_dir` 解析。

### 第1步：在同一回合生成所有运行（带技能 AND 基线）

对每个测试用例，在同一回合生成两个子代理——一个带技能，一个不带。这一点很重要：不要先启动带技能的运行，再回头启动基线。一次全部启动，让它们大约同时完成。

> 本系统前置：`run_subagent` 启动的是**已注册**的子代理 profile（系统无默认 profile）。首次评估前先注册一个通用评测子代理——只需注册一次，之后所有评估复用：
>
> ```
> register_subagent(name="eval-worker")
> ```
>
> `run_subagent` 的参数为 `name`（profile 名）、`initial_prompt`（任务文本，即下方模板）、`user_name`（发送者名）、`message_type`（填 `"direct"`）。返回 `{success, session_id, waiting}`——子代理**异步**运行，完成时结果以系统消息注入本会话（不含时序字段，见第3步）；输出文件靠子代理按任务指示自行写入 `ws:` 目录。

**带技能运行**（`run_subagent`，任务文本放入 `initial_prompt`）：

```
Execute this task:
- Skill path: <path-to-skill>
- Task: <eval prompt>
- Input files: <eval files if any, or "none">
- Save outputs to: <workspace>/iteration-<N>/eval-<ID>/with_skill/run-1/outputs/
- Outputs to save: <what the user cares about — e.g., "the .docx file", "the final CSV">
```

**基线运行**（相同提示词，基线取决于上下文）：
- **创建新技能**：完全没有技能。相同提示词，无技能路径，保存到 `without_skill/run-1/outputs/`。
- **改进已有技能**：旧版本。编辑前先快照技能（`copy_folder <skill-path> <workspace>/skill-snapshot/`），然后让基线子代理指向快照。保存到 `old_skill/run-1/outputs/`。

为每个测试用例写一个 `eval_metadata.json`（断言暂时可以为空）。根据测试内容给每个 eval 一个描述性名称——不要只叫「eval-0」。目录也用这个名字。如果本轮使用新的或修改过的 eval 提示词，为每个新的 eval 目录创建这些文件——不要假设它们从上轮延续。

```json
{
  "eval_id": 0,
  "eval_name": "descriptive-name-here",
  "prompt": "The user's task prompt",
  "assertions": []
}
```

### 第2步：运行期间起草断言

不要干等运行结束——这段时间可以高效利用。为每个测试用例起草定量断言并解释给用户。如果 `evals/evals.json` 已有断言，审查它们并解释各自检查什么。

好的断言应客观可验证、有描述性名称——在基准查看器里一眼能看懂检查什么。主观技能（写作风格、设计质量）更适合定性评估——不要强行把需要人工判断的东西变成断言。

起草后更新 `eval_metadata.json` 和 `evals/evals.json`。同时向用户解释在查看器里会看到什么——包括定性输出和定量基准。

### 第3步：运行完成时捕获时序数据

> 本系统机制：子代理完成通知（注入的系统消息）**不含** `total_tokens`/`duration_ms` 字段——时序数据必须自行计时。

启动每个子代理时记录本地开始时间；该子代理的完成通知到达时，计算耗时并立即写入其运行目录（`run-<M>/`）的 `timing.json`：

```json
{
  "total_tokens": 0,
  "duration_ms": 23332,
  "total_duration_seconds": 23.3
}
```

`total_tokens` 本系统不产出，填 `0` 占位即可（聚合脚本按 0 处理，benchmark 中 tokens 列仅作参考）。每条完成通知到达时立即处理，不要批量处理——耗时以通知到达时刻为准，批量处理会失真。

### 第4步：评分、聚合、启动查看器

所有运行完成后：

1. **为每次运行评分**——启动评分子代理（或内联评分），读取 `agents/grader.md`，对照输出评估每个断言。结果保存到每个运行目录（`run-<M>/`）的 `grading.json`。grading.json 的 expectations 数组必须使用 `text`、`passed`、`evidence` 字段（不是 `name`/`met`/`details` 等变体）——查看器依赖这些精确字段名。能用脚本程序化检查的断言就写脚本跑，别用肉眼——脚本更快、更可靠、可跨迭代复用。

2. **聚合成基准**——用 `run_command` 调用本技能自带的聚合脚本（`<SKILL_DIR>` 见本节开头说明，`cwd` 保持默认 `ws:` 即可）：
   ```
   run_command(
     command=["python", "<SKILL_DIR>/scripts/aggregate_benchmark.py",
              "ws:evals/<skill-name>-workspace/iteration-N", "--skill-name", "<name>"],
     reason="聚合评估结果为 benchmark.json/md")
   ```
   生成 `benchmark.json` 和 `benchmark.md`，包含每个配置的 pass_rate、time、tokens，均值 ± 标准差和差值。每个 with_skill 版本放在其基线对应版本之前。若手动生成 benchmark.json，参考 `references/schemas.md` 中查看器期望的精确 schema。

3. **分析师检查**——阅读基准数据，找出聚合统计可能掩盖的模式。参考 `agents/analyzer.md`（「Analyzing Benchmark Results」一节）——例如无论技能如何总通过的断言（无区分度）、高方差 eval（可能不稳定）、时间/令牌权衡。

4. **启动查看器**——本系统使用**静态模式**（无显示环境，聊天前端展示）：
   ```
   run_command(
     command=["python", "<SKILL_DIR>/eval-viewer/generate_review.py",
              "ws:evals/<skill-name>-workspace/iteration-N",
              "--skill-name", "my-skill",
              "--benchmark", "ws:evals/<skill-name>-workspace/iteration-N/benchmark.json",
              "--static", "ws:evals/<skill-name>-workspace/iteration-N/review.html"],
     reason="生成静态评估查看器 HTML")
   ```
   迭代 2+ 再加 `--previous-workspace ws:evals/<skill-name>-workspace/iteration-<N-1>`。
   生成 `review.html` 后，通过 `/uploads/` 路由嵌入聊天展示给主人：
   ```html
   <iframe src="/uploads/evals/<skill-name>-workspace/iteration-N/review.html" style="width:100%;height:600px;border:none"></iframe>
   ```
   注意：静态模式下「Submit All Reviews」会把反馈导出为 `feedback.json` 下载（宿主 gateway 无 `/api/feedback` 接口）——请主人下载后把内容粘贴回聊天，或直接在聊天里反馈意见，也可改用 `register_dynamic_endpoint` 收集选项点击。

5. **告诉用户**类似：「结果已经打开。有两个标签——'Outputs' 可以逐个测试用例查看并留下反馈，'Benchmark' 显示定量对比。看完告诉我。」

### 用户在查看器里看到什么

「Outputs」标签每次显示一个测试用例：
- **Prompt**：给定的任务
- **Output**：技能产生的文件，尽可能内联渲染
- **Previous Output**（迭代 2+）：折叠区，显示上一迭代的输出
- **Formal Grades**（如果运行了评分）：折叠区，显示断言通过/失败
- **Feedback**：自动保存的文本框

「Benchmark」标签显示统计摘要：各配置的通过率、时序、令牌用量，以及每个 eval 的明细和分析师观察。

通过 prev/next 按钮或方向键导航。完成后点击「Submit All Reviews」保存所有反馈到 `feedback.json`（静态模式下改为在聊天中反馈）。

### 第5步：读取反馈

当用户告诉你完成时，读取反馈：

```json
{
  "reviews": [
    {"run_id": "eval-0-with_skill", "feedback": "the chart is missing axis labels", "timestamp": "..."},
    {"run_id": "eval-1-with_skill", "feedback": "", "timestamp": "..."},
    {"run_id": "eval-2-with_skill", "feedback": "perfect, love this", "timestamp": "..."}
  ],
  "status": "complete"
}
```

空反馈表示用户认为没问题。把改进重点放在用户有具体抱怨的测试用例上。

---

## 改进技能

这是循环的核心。你已经运行了测试用例，用户审查了结果，现在需要根据反馈让技能变得更好。

### 如何思考改进

1. **从反馈中泛化。** 大局是：我们在创建可以被使用一百万次的技能。这里你和用户只在几个例子上反复迭代，因为这样更快。用户对这些例子了如指掌，能快速评估新输出。但如果技能只对这些例子有效，就没用。与其做琐碎的过拟合改动或压迫性的 MUST，如果遇到顽固问题，试试换用不同的比喻、推荐不同的工作模式。尝试的成本很低，说不定会有好结果。

2. **保持提示词精简。** 删掉不产生价值的东西。务必阅读 transcripts，而不仅仅是最终输出——如果技能让模型浪费大量时间做低效的事，试着去掉导致这点的技能部分看看会发生什么。

3. **解释为什么。** 努力解释你要求模型做的每件事背后的「为什么」。今天的 LLM 很聪明，有良好的心智理论，在好的框架下能超越死板指令真正达成目标。如果发现自己写全大写的 ALWAYS 或 NEVER，或用超级僵硬的结构，那是黄旗——如有可能，重新表述并解释推理，让模型理解你要求的事为什么重要。这是更人性化、更有力、更有效的方法。

4. **寻找跨测试用例的重复工作。** 阅读测试运行的 transcripts，注意子代理是否都独立写了相似的辅助脚本或采用相同的多步骤方法。如果 3 个测试用例都导致子代理写了 `create_docx.py` 或 `build_chart.py`，这是强烈信号：技能应该捆绑那个脚本。写一次，放进 `scripts/`，告诉技能使用它。这样每次调用都不用重新发明轮子。

这项任务很重要，你的思考时间不是瓶颈；慢慢来，真正想透。建议先写草稿修订，再以全新眼光改进。真正尽力进入用户的头脑，理解他们想要和需要什么。

### 迭代循环

改进技能后：

1. 将改进应用到技能
2. 将所有测试用例重新运行到新的 `iteration-<N+1>/` 目录，包括基线运行。创建新技能时基线始终是 `without_skill`（无技能）——跨迭代保持不变。改进已有技能时，自行判断基线用什么合理：用户最初带来的版本，还是上一迭代。
3. 用 `--previous-workspace` 指向上一迭代启动查看器
4. 等待用户审查并告诉你完成
5. 读取新反馈，再次改进，重复

持续直到：
- 用户说满意
- 反馈全为空（看起来都很好）
- 没有有意义的进展

---

## 高级：盲对比

对于需要更严格比较两个技能版本的场景（例如用户问「新版本真的更好吗？」），有盲对比系统。详见 `agents/comparator.md` 和 `agents/analyzer.md`。基本思路：把两个输出交给独立代理，不告诉它哪个是哪个，让它判断质量。然后分析赢家为什么赢。

这是可选的，需要子代理，大多数用户不需要。人工审查循环通常就足够了。

---

## 描述优化（Description Optimization）

SKILL.md frontmatter 中的 description 字段是决定 Agent 是否调用技能的主要机制。创建或改进技能后，主动提议优化描述以提升触发准确率。

> 本系统注意：原版的自动触发评估脚本（`run_eval.py` / `run_loop.py` / `improve_description.py`）绑定 `claude -p` CLI，本系统不可用，已归档至 `scripts/_legacy_claude_code/`。以下流程改为**人工 + 子代理评估**方式，效果等同。

### 第1步：生成触发评估查询

创建 20 个评估查询——混合应该触发和不应该触发的。保存为 JSON：

```json
[
  {"query": "the user prompt", "should_trigger": true},
  {"query": "another prompt", "should_trigger": false}
]
```

查询必须真实，像 Evolve Agent 用户实际会输入的内容。不是抽象请求，而是具体、细致、有足够细节的请求。例如文件路径、关于用户工作或处境的个人背景、列名和值、公司名、URL。加一点背景故事。有些可以小写、含缩写或拼写错误、口语化。混合不同长度，聚焦边界情况而不是显而易见的例子（用户会有机会签字确认）。

坏例子：`"Format this data"`、`"Extract text from PDF"`、`"Create a chart"`

好例子：`"ok so my boss just sent me this xlsx file (its in my downloads, called something like 'Q4 sales final FINAL v2.xlsx') and she wants me to add a column that shows the profit margin as a percentage. The revenue is in column C and costs are in column D i think"`

**应该触发**的查询（8-10个）：考虑覆盖度。同一意图的不同措辞——有些正式、有些随意。包括用户没有明确点名技能或文件类型但明显需要它的场景。加一些不常见的使用场景和与其他技能竞争但应胜出的场景。

**不应该触发**的查询（8-10个）：最有价值的是「近失」——与技能共享关键词或概念但实际需要别的东西的查询。想想相邻领域、朴素关键词匹配会触发但不应触发的歧义表述、以及查询涉及技能功能但上下文里另一个工具更合适的场景。

关键要避免：不要做明显不相关的 should-not-trigger 查询。「Write a fibonacci function」作为 PDF 技能的负例太简单了——测不出任何东西。负例应该真正有迷惑性。

### 第2步：与用户一起审查

将评估集呈现给用户审查，使用 HTML 模板：

1. 读取 `assets/eval_review.html` 模板
2. 替换占位符：
   - `__EVAL_DATA_PLACEHOLDER__` → eval 条目 JSON 数组（不带引号——它是 JS 变量赋值）
   - `__SKILL_NAME_PLACEHOLDER__` → 技能名
   - `__SKILL_DESCRIPTION_PLACEHOLDER__` → 技能当前描述
3. 写入临时文件（如 `ws:output/eval_review_<skill-name>.html`），通过 `/uploads/` 嵌入聊天展示：
   ```html
   <iframe src="/uploads/output/eval_review_<skill-name>.html" style="width:100%;height:600px;border:none"></iframe>
   ```
4. 用户编辑查询、切换 should-trigger、增删条目，然后点击「Export Eval Set」——在聊天前端中让用户把导出的 JSON 粘贴回来，或用 `set_clipboard_display` 收集

这一步很重要——坏的评估查询导致坏的描述。

### 第3步：手动改进描述

将评估集保存到工作区。检查哪些查询失败（漏触发或误触发），泛化失败模式，重写描述以改善覆盖。重复直到你和用户都满意。

### 触发机制如何工作

理解触发机制有助于设计更好的评估查询。技能以 name + description 出现在 `list_skills` 中，Agent 根据描述决定是否 `recall_skill` 加载技能。重要的一点：Agent 只为无法轻松自行处理的任务咨询技能——简单的单步查询（如「read this PDF」）可能不会触发技能，即使描述完美匹配，因为 Agent 可以用基本工具直接处理。复杂、多步或专门化的查询在描述匹配时可靠触发技能。

这意味着评估查询要有实质内容，让 Agent 确实受益于咨询技能。简单查询如「read file X」是糟糕的测试用例——无论描述质量如何它们都不会触发技能。

### 第4步：应用结果

用改进后的版本更新技能 SKILL.md frontmatter 的 description。向用户展示前后对比并报告得分。

---

## 参考文件

agents/ 目录包含专门子代理的指令。需要启动相关子代理时读取它们。

- `agents/grader.md` — 如何对照输出评估断言
- `agents/comparator.md` — 如何在两个输出之间做盲 A/B 对比
- `agents/analyzer.md` — 如何分析一个版本为何击败另一个

references/ 目录有额外文档：
- `references/schemas.md` — evals.json、grading.json 等的 JSON 结构

---

最后再强调一次核心循环：

- 弄清楚技能是关于什么的
- 起草或编辑技能
- 在加载技能的情况下对测试提示词运行
- 与用户一起评估输出：
  - 创建 benchmark.json 并运行 `eval-viewer/generate_review.py` 帮助用户审查
  - 尽可能定量评估
- 重复直到你和用户都满意

请使用 `set_task_progress` 跟踪进度，确保不遗忘。创建 evals JSON 并运行 `eval-viewer/generate_review.py` 让人工审查测试用例。

祝好运！
