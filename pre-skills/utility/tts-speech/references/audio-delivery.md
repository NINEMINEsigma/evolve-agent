# 语音交付方式

## 前端播放音频

当前前端支持两种方式展示媒体文件：

### 1. publish_file（推荐）

生成语音后，调用 `publish_file` 工具发布音频：

```python
publish_file(
    path="ws:output/tts_xxx.mp3",
    filename="语音.mp3",
    description="TTS语音回复"
)
```

前端会显示一个 **下载按钮**，用户点击下载后可在本地播放器播放。

### 2. Markdown 链接

在回复文本中直接给出链接，用户可点击跳转：

```markdown
[点击播放语音](/downloads/output/tts_xxx.mp3)
```

## 完整工作流示例

```
用户提问 → 需要用语音回复

1. run_python(script="ws:scripts/tts_speak.py",
              args=["--speaker","sui","--text","语音回复内容"],
              reason="合成语音", timeout=120)

2. 从返回结果提取 audio_path

3. publish_file(path=result.audio_path,
                filename="AI回复.mp3",
                description="语音回复")

4. 在文本中告知用户：语音已生成，可点击下载播放
```

## 文件位置

| 路径 | 说明 |
|------|------|
| `ws:output/tts_*.mp3` | 合成的 MP3 语音文件 |
| `ws:tts3/static/audio/*.wav` | TTS 服务器原始 WAV 输出 |
| `/downloads/output/tts_*.mp3` | 前端可访问的下载 URL |
