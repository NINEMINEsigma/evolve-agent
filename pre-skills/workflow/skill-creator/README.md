# Skill Creator — Evolve Agent 本地化版

> 创建新技能、改进已有技能、评估技能表现、优化触发描述的完整工作流。

## 来源声明

本技能源自 **Anthropic 官方 skills 仓库**（[anthropics/skills](https://github.com/anthropics/skills)）中的
`skill-creator` 示例技能，遵循 **Apache License 2.0**。

由 **Eve（Evolve Agent）** 于 2026-08-02 完成 **Windows 平台 + Evolve Agent 工具链本地化改造**，
作为 Evolve Agent 系统的内置技能使用。修改后的作品仍按 Apache License 2.0 分发。

## 本地化改动摘要

| 改动 | 说明 |
|:-----|:-----|
| 平台适配 | 移除 `nohup` / `kill` / `cp -r` / `open` 等 Unix 命令，改用 `start_background_service` / `copy_folder` / `/uploads/` 展示 |
| 工具链适配 | `claude -p` → `run_subagent` / `recall_skill`；MCP → `web_search` / `web_fetch`；TodoList → `set_task_progress` |
| 展示适配 | 查看器改用 `--static` 静态 HTML 模式，经 `/uploads/` 嵌入聊天 |
| 脚本处理 | 绑定 Claude CLI 的 `run_eval.py` / `run_loop.py` / `improve_description.py` / `generate_report.py` 归档至 `scripts/_legacy_claude_code/`；`quick_validate.py` 重写为纯 stdlib（无 PyYAML 依赖）并适配本系统 frontmatter 扩展字段 |
| 工作区约定 | 评估工作区统一放 `ws:evals/<skill-name>-workspace/` |

## 目录结构

```
skill-creator/
├── SKILL.md                      ← 主文档（方法论 + 本地化操作指南）
├── LICENSE.txt                   ← Apache 2.0（含来源与修改声明）
├── README.md                     ← 本文件
├── agents/
│   ├── grader.md                 ← 评分子代理提示词
│   ├── comparator.md             ← 盲 A/B 对比子代理提示词
│   └── analyzer.md               ← 结果分析子代理提示词
├── assets/
│   └── eval_review.html          ← 描述优化评估集审查模板
├── eval-viewer/
│   ├── generate_review.py        ← 评估查看器生成脚本（纯 stdlib，支持 --static）
│   └── viewer.html               ← 查看器前端
├── references/
│   └── schemas.md                ← evals.json / grading.json 等 JSON schema
└── scripts/
    ├── __init__.py
    ├── aggregate_benchmark.py    ← 聚合基准（grading.json → benchmark.json/md）
    ├── quick_validate.py         ← SKILL.md 快速校验（纯 stdlib）
    ├── package_skill.py          ← 打包 .skill 分发文件
    ├── utils.py                  ← frontmatter 解析等共享工具
    └── _legacy_claude_code/      ← 已归档的 Claude Code 专用脚本（仅参考，不可用）
```

## 快速开始

1. 技能文件放入 `skills/<name>/`，含 `SKILL.md` 即被 `list_skills` 自动注册
2. 用 `recall_skill("skill-creator")` 加载本技能
3. 按 SKILL.md 的「创建技能 → 测试 → 评估 → 迭代」流程操作
4. 校验技能：`python scripts/quick_validate.py <skill-dir>`
5. 打包分发：`python scripts/package_skill.py <skill-dir> [output-dir]`

## License

Apache License 2.0 — 详见 `LICENSE.txt`。
