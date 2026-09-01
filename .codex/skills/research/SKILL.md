---
name: research
description: 运行RIPER-5 研究与逐层质询流程。仅在用户显式调用 $research 时使用。
---

# Research Command

将用户消息中 `$research` 之后的内容视为本次任务输入。

1. 每次响应以 `[MODE: RESEARCH]` 开头。
2. 先读取并遵循 `riper-core`、`research-mode` 与 `grill-me` skills。
3. 阅读与任务相关的源码和开发文档，建立对当前实现、约束和未知项的准确理解。此阶段不得修改源码。
4. 按 `grill-me` 流程一次只提出一个问题；每次回答后继续检查必要的本地代码，直到任务意图清晰且可执行。
5. 总结研究发现、已解决决策、开放风险和后续交接信息。
6. 只有在用户明确批准后，才创建或更新 `.tasks/` 中的任务文件；写入时遵循 RIPER-5 的任务文件模板与追加修订规则。

不得自行转入 PLAN 或 EXECUTE 模式。
