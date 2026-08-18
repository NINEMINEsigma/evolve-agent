# Skill Creator

> 创建新技能、改进已有技能、评估技能表现、优化触发描述的完整工作流。

## 目录结构

```
skill-creator/
├── SKILL.md                      ← 主文档（方法论 + 操作指南）
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

1. 技能文件放入 `skills/<name>/`，含 `SKILL.md` 即被 `RecallSkill` 自动注册
2. 用 `RecallSkill("skill-creator")` 加载本技能
3. 按 SKILL.md 的「创建技能 → 测试 → 评估 → 迭代」流程操作
4. 校验技能：`python scripts/quick_validate.py <skill-dir>`
5. 打包分发：`python scripts/package_skill.py <skill-dir> [output-dir]`