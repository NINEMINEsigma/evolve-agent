# Custom Hooks 上下文扩展教程

在 `custom_hooks/` 目录下放置任意 Python 脚本（文件名不能以下划线开头），即可自动注册为上下文扩展 hook。

## 必备函数

每个脚本必须定义 `hook_tag_name`，并且至少定义 `hook_message` 或 `hook_fixator` 中的一个。

### `hook_tag_name(session_id, workspace, **kwargs) -> str`

返回标识符字符串，用于生成标签名。例如返回 `"turn_time"` 时，最终上下文的标签为 `<|im_turn_time_start|>` 和 `<|im_turn_time_end|>`。

### `hook_message(session_id, workspace, **kwargs) -> str`

返回要附加的扩展上下文内容。这些内容会拼接到**最后一轮** `UserMessage` 的末尾发送给 LLM，但**不会**出现在持久化的历史记录中。下一轮对话也不会保留。

### `hook_fixator(session_id, workspace, **kwargs) -> str`（可选）

与 `hook_message` 逻辑一致，返回内容也会附加到发送消息。区别是：返回的内容会被追加到内存历史 `_histories` 和磁盘 JSONL 中的原始 `user` 消息里，在后续轮次中仍然保留。标签格式为 `<|im_{tag}_fixator_start|>` / `end`。

## 运行时信息

两个函数都支持通过 `**kwargs` 接收额外参数：

```python
runtime_ctx = kwargs.get("runtime_ctx")
```

`runtime_ctx` 是 `RuntimeContext` 单例，可读取 `agentspace`、`fork_path`、`mode`、`llm_model` 等运行时信息。

## 工作流程示例

假设用户发送消息 `"现在几点了"`。

如果只有一个 `time_hook.py`，其 `hook_tag_name` 返回 `"turn_time"`，`hook_message` 返回 JSON 字符串 `{"current_time":"2026-06-26 12:00:00"}`，那么实际发送给 LLM 的消息内容为：

```
现在几点了
<|im_turn_time_start|>{"current_time":"2026-06-26 12:00:00"}<|im_turn_time_end|>
```

如果还定义了 `hook_fixator` 并返回 `{"note":"fixed"}`，则发送内容为：

```
现在几点了
<|im_turn_time_start|>{"current_time":"2026-06-26 12:00:00"}<|im_turn_time_end|>
<|im_turn_time_fixator_start|>
{"note":"fixed"}
<|im_turn_time_fixator_end|>
```

`hook_fixator` 返回的这段内容会被追加到磁盘历史记录中的 user 消息里，下一轮构建历史时仍然存在。

## 注意事项

- 脚本文件名不要以 `_` 开头，否则会被跳过。
- 可以只定义 `hook_message`（不保留），或只定义 `hook_fixator`（保留），或同时定义两者。
- 返回空字符串或 `None` 时，该 hook 不会产生任何上下文。
- 函数签名中的 `session_id` 和 `workspace` 是位置参数，但新签名也支持 `**kwargs` 接收 `runtime_ctx`。旧的两参数签名仍然兼容。