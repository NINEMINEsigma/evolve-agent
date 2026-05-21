# Evolve Agent

一个从代码层面具备自我进化的agent

# 定义

## origin/源

origin_agent路径中将含有代码原型, 初始化时将被拷贝到fast/slow两个代码目录中, 并启动fast代码目录

## fast-slow-fallback code evolve 自我代码演化

agent将从fast代码目录运行, 并具有修改slow代码目录的能力, 当slow代码目录完成进化后, slow将会在fast备份到fallback代码目录后替换fast, 当slow出现错误时将使用fallback修复此时的fast直至该错误不再出现

## self-evolve 提示词工程演化

agent具有调整自身记忆与技能的能力, 在实际使用中优化自身行为