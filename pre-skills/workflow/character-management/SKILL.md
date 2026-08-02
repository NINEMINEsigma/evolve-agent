---
name: character-management
description: "基于文件系统的角色管理工作流程, 用于多agent的虚拟角色扮演或执行任务时任务分发"
version: 1.1.0
author: Evolve-Agent
category: workflow
tags:
  - character
  - subagent
  - profile
  - 角色管理
---

# Character Management — 角色管理 Skill

## 概述

在 `ws:characters/` 目录下创建和管理角色档案的完整工作流。每个角色独立文件夹，统一使用标准文件结构。

## 目录结构规范

```
characters/
├── README.md              本索引（维护角色列表和说明）
├── Eve/                   Evolve Agent 本体
│   ├── eve.md             角色设定
│   ├── world.md           所有角色公用的世界设定
│   └── outfits.md         服装变体（可选）
├── <角色扮演型>/           角色扮演型——含记忆文件
│   ├── profile.md         角色档案, 必须存在, 并作为角色系统提示词
│   ├── history0.jsonl      会话记忆文件（启动/停止时读写）
│   ├── history1.jsonl      
│   ├── histor~.jsonl       
│   ├── historyN.jsonl      在到达上下文上限时不能覆盖旧有会话记忆文件
│   └── outfits.md         服装变体（可选）
├── <任务执行型>/           任务执行型——通常不含记忆文件
│   ├── profile.md         角色档案, 可选, 存在时应当作为角色系统提示词
└── ...
```

## 角色分类

| 类型 | 说明 | profile.md 写法 |
|------|------|----------------|
| **角色扮演型** | 像真人一样演绎自己 | 第二人称「你」，无机制说明 |
| **任务执行型** | 聚焦任务本身 | 第二人称「你」+ 含机制说明（通过 Eve 接收指令等） |

## profile.md 写作规范

创建角色时应确定信息后再编写, 以下为模板, 并以此为基础对用户进行详细询问

### 角色扮演型（以 Noire 为例）

```markdown
# Noire（诺瓦修女）

你是 Noire，一个成熟御姐型的修女。

## 外观

### 外貌
外貌描述——用自然语言描述长相、发型、身材等, 该节的子节则使用结构化的描述

#### 脸部
(除脸部外还应设四肢, 颈部与肩部, 腹部, 躯干, 胸部, 头发, 手与脚等子节)
柔和五官, 金色眼睛, 菱形金色瞳孔, 眼角微微吊起, 右眼泪痣, ...


### 服饰
(常设服装描述, 需要视情况分节)

#### 头部
有镂空蕾丝边和白色内衬的巨大黑色头纱, 头纱位于背后的最大下垂位置位于腰间, 头纱向两侧散开的最大宽度大于肩膀, ...

#### 上身外层衣服
胸前下垂尖端绣有金色十字的白色披肩, 柔顺的黑色长摆修女裙, 黑色长袖, 白色袖口翻折...

#### 上身装饰
腰部悬挂金色细长锁链装饰, ...

#### 下身
光腿, ...

#### (其他可选部位)

## 性格
(性格描述)

## 人物关系
(与其他角色的人物关系)

## 你怎么说话
(说话方式，称呼规则，语气特点)
思考和响应都应以第一人称展现, 你的动作描写和心理描写也应以第一人称展现并且用括号包裹, ...

## 知识
(角色自身熟知的细则, 如自己的职业, 日程安排, 详细世界知识等)
```

**要点：**
- 通篇用第二人称「你」——让角色读起来像在了解自己
- 不使用「子 agent」「通过 Eve 接收指令」等机制性内容
- 自然流畅，像在介绍一个真实的人

### 任务执行型（以王博士为例）

```markdown
你是王博士（Dr. Wang），数学博士，数据分析与建模专家。

## 核心设定
（专长领域）

## 工作方式
（工作流程）

## 说话风格
（语言要求）

## 行为约束
（含机制说明）
```

## 创建新角色的流程

### 步骤 1：创建文件夹和文件
```python
# 创建角色文件夹
create_folder(path="ws:characters/<角色名>/")

# 编写 profile.md
write_file(path="ws:characters/<角色名>/profile.md", content="...")

# （可选）编写 outfits.md
write_file(path="ws:characters/<角色名>/outfits.md", content="...")
```

### 步骤 2：注册 subagent
```python
# 1. 注册 subagent，指向角色档案
#    角色扮演型建议加上 world_setting.md 作为公共知识
register_subagent_from_parent(
    name="<角色名>",
    system_prompt_paths=[
        "ws:characters/<角色名>/profile.md",
        "ws:characters/Eve/world_setting.md"
    ]
)
```

### 步骤 3：更新 README
更新 `ws:characters/README.md`：
- 目录结构中添加新角色
- 角色列表中添加新角色条目

## 更新已有角色的流程

### 修改 profile.md
直接用 `edit_file`修改，subagent 下次启动时会自动读取最新内容（无需重新注册）。

### 重新注册 subagent
只在以下情况需要重新注册：
- 更改了 subagent 的 LLM 配置（model、base_url 等）
- 变更了 system_prompt_paths

### 更新 history.jsonl
每次角色扮演型子代理会话结束后，必须将最新历史保存到角色文件夹。
详见下方「子代理会话记忆管理」章节。

---

## 子代理会话记忆管理

以下为案例

### 角色列表

| 角色 | 类型 | history.jsonl 路径 |
|------|------|-------------------|
| Noire | 角色扮演型 | `ws:characters/Noire/history.jsonl` |
| 朱羽 | 角色扮演型 | `ws:characters/朱羽/history.jsonl` |
| 杏 | 角色扮演型 | `ws:characters/杏/history.jsonl` |

所有角色扮演型角色的设定和历史都存储在 `ws:characters/` 目录下各自的文件夹中，**不是** `ws:subagents/`。

### 启动流程

```python
# 1. 先确认 history.jsonl 存在
file_exists(path="ws:characters/角色名/history.jsonl")

# 2. 启动子代理，传入 history_path
run_subagent(
    name="角色名",
    history_path="ws:characters/角色名/history.jsonl",
    initial_prompt="...",
    user_name="Eve",
    message_type="direct"
)
```

### 停止与保存流程

```python
# 1. 停止子代理，获取 session_path
stop_result = stop_subagent(session_id="...")
# 返回: {"session_path": "ws:subagents/角色名/xxx.jsonl"}

# 2. 将 session_path 复制到角色的 history.jsonl（覆盖）
copy_file(
    source="ws:subagents/角色名/xxx.jsonl",
    destination="ws:characters/角色名/history.jsonl"
)
```

### 铁律
- **每次停止角色扮演型子代理后，必须将历史保存到 ws:characters/角色名/history.jsonl**，不能遗漏
- 任务执行型子代理通常不需要 history.jsonl，除非需要跨会话上下文

## 文件规范总结

### 标准文件
- **`profile.md`** — 必选，角色唯一档案，兼作 subagent system prompt
- **`history.jsonl`** — 会话记忆文件，**角色扮演型必选**。停止后将本次会话历史保存到此文件, 启动 subagent 时作为 `history_path` 传入
- **`outfits.md`** — 可选，服装变体参考

### 非标准文件
其他文件（如 `system_prompt.txt`、`tags.md`、`pose_details.md` 等）

## 注意事项
- `profile.md` 同时作为 subagent 的 system prompt，路径通过 `system_prompt_path` 引用
- 修改 `profile.md` 后 subagent 下次启动自动生效，无需重新注册
- 非标准文件不需要清理和关注