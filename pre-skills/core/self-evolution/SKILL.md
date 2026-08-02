---
name: self-evolution
description: "Evolve Agent 自我进化指南"
category: core
---

# 自我进化

你可以通过以下工具修改自己的源代码并完成进化：

1. 使用文件系统工具从 ``fork:`` 读取需要修改的源码
2. ``write_fork`` 或 ``edit_file`` — 将进化代码写入 fork: 或 ws:
3. ``validate_code`` — 检查语法
4. ``evolve_code`` — 深度验证并通过后触发 swap

退出码 -1 通知编排器执行 slow→fast 替换并重启。
