---
name: internal-comms
description: A set of resources to help me write all kinds of internal communications, using the formats that my company likes to use. Claude should use this skill whenever asked to write some sort of internal communications (status reports, leadership updates, 3P updates, company newsletters, FAQs, incident reports, project updates, etc.).
license: Complete terms in LICENSE.txt
category: internal
tags:
  - comms
  - writing
  - template
  - internal
---

> **Evolve Agent 本地化注记**
>
> 本技能源自 Anthropic 官方 skills 仓库，由 Eve（Evolve Agent）本地化接入。
>
> - **说明**：内部沟通模板（3P updates / 简报 / FAQ 等）平台中性，可直接使用。文中「Claude should use」对应本系统 Agent 使用
> - **产出**：写作内容直接输出到聊天；需要落盘时写入 `ws:` 目录
> - **许可证**：Apache 2.0（详见本技能目录 LICENSE.txt）

## When to use this skill
To write internal communications, use this skill for:
- 3P updates (Progress, Plans, Problems)
- Company newsletters
- FAQ responses
- Status reports
- Leadership updates
- Project updates
- Incident reports

## How to use this skill

To write any internal communication:

1. **Identify the communication type** from the request
2. **Load the appropriate guideline file** from the `examples/` directory:
    - `examples/3p-updates.md` - For Progress/Plans/Problems team updates
    - `examples/company-newsletter.md` - For company-wide newsletters
    - `examples/faq-answers.md` - For answering frequently asked questions
    - `examples/general-comms.md` - For anything else that doesn't explicitly match one of the above
3. **Follow the specific instructions** in that file for formatting, tone, and content gathering

If the communication type doesn't match any existing guideline, ask for clarification or more context about the desired format.

## Keywords
3P updates, company newsletter, company comms, weekly update, faqs, common questions, updates, internal comms
