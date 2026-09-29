# skill-creator

用于创建、修改、评估和迭代技能的工作流。完整流程见 `SKILL.md`。

## 目录结构

```text
skill-creator/
├── SKILL.md
├── agents/
│   ├── grader.md
│   ├── comparator.md
│   └── analyzer.md
├── assets/
│   └── eval_review.html
├── eval-viewer/
│   ├── generate_review.py
│   └── viewer.html
├── references/
│   └── schemas.md
└── scripts/
    ├── aggregate_benchmark.py
    ├── quick_validate.py
    ├── package_skill.py
    └── utils.py
```

## 工作流程

1. 明确技能目标、触发条件、输入和输出。
2. 编写或修改技能的 `SKILL.md`。
3. 为真实使用场景创建评估提示词。
4. 并行运行带技能和基线的评估。
5. 评分、聚合基准并生成查看器。
6. 根据用户反馈和评估结果迭代技能。
7. 必要时优化 frontmatter 中的 `description`，提升触发准确率。

评估结果统一放在 `evals/<skill-name>-workspace/`，按迭代和测试用例分别保存。

## 辅助脚本

- `scripts/quick_validate.py`：检查技能目录和 `SKILL.md` frontmatter。
- `scripts/package_skill.py`：将技能目录打包为 `.skill` 文件。
- `scripts/aggregate_benchmark.py`：聚合评估结果，生成基准数据和报告。
- `eval-viewer/generate_review.py`：生成评估结果查看器。
- `references/schemas.md`：评估文件的 JSON 结构。
- `agents/grader.md`：评分规则。
- `agents/comparator.md`：盲比较规则。
- `agents/analyzer.md`：基准结果分析规则。

创建技能时，先加载 `SKILL.md`，再按其中的流程推进；只在需要时读取对应的参考文件或 Agent 指令。
