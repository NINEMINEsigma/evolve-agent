---
name: commit
description: 根据仓库既有提交风格与当前差异生成提交摘要。仅在用户显式调用 $commit 时使用。
---

# Commit Summary Command

将用户消息中 `$commit` 之后的内容视为附加要求。

1. 只使用仓库允许的只读 Git 命令：`git diff` 与 `git log`。
2. 根据当前差异识别主要行为变化，并参考近期提交的语言、格式和粒度。
3. 输出一条可直接使用的简洁 commit message；必要时附一段短正文。
4. 不得执行 `git add`、`git commit`、`git push` 或其他 Git 写操作。
