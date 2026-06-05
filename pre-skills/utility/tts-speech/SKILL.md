---
name: tts-speech
description: "基于CosyVoice3零样本语音克隆的TTS语音合成技能。从仓库安装到语音播放一条龙"
version: 1.0.0
author: Evolve Agent
category: utility
tags:
  - tts
  - speech
  - voice
  - cosyvoice
  - audio
  - 语音合成
---

# TTS Speech Synthesis Skill

基于 **CosyVoice3** 零样本语音克隆技术的 TTS 语音合成技能。从**仓库安装**到**生成语音**到**用户听到**一条龙。

## 1. 安装（从零开始）

### 1.1 克隆仓库

```bash
# 方式一：GitHub
git clone --recursive https://github.com/NINEMINEsigma/tts3.git
cd tts3

# 方式二：Gitea
git clone --recursive http://gitea.liubai.site/ai/tts3.git
cd tts3
```

如果已克隆但 submodule 未拉取：
```bash
git submodule update --init --recursive
```

### 1.2 创建虚拟环境

```bash
python -m venv venv
# Windows
venv\Scripts\activate
```

### 1.3 安装依赖

根据 Python + CUDA 版本选择：

| 文件 | Python | CUDA |
|------|--------|------|
| `requirements_py3_10_cu121.txt` | 3.10 | 12.1 |
| `requirements_py3_12_cu126.txt` | 3.12 | 12.6 |
| `requirements_py3_12_cu128.txt` | 3.12 | 12.8 |

```bash
pip install -r requirements_py3_12_cu126.txt
```

### 1.4 准备模型

模型自动通过 `modelscope` 下载，也可手动放到 `pretrain/Fun-CosyVoice3-0.5B/`：
```
pretrain/
└── Fun-CosyVoice3-0.5B/
    ├── cosyvoice3.yaml
    ├── campplus.onnx
    ├── speech_tokenizer_v3.onnx
    ├── flow.pt
    ├── hift.pt
    ├── llm.pt
    └── ...
```

### 1.5 准备说话人音频

```
StreamingAssets/
└── vocals/
    └── <speaker_id>/            # 如 "sui"
        ├── vocal.txt            # 音频对应文本
        └── vocal.{wav|mp3}      # 干声音频 (5-30秒)
```

### 1.6 启动服务

```bash
python run.py --port 53342
```

**验证：** `curl http://127.0.0.1:53342/api/health`

---

## 2. 操作指南

### 2.1 启动服务器（在当前环境中）

```python
# 方式一：使用 start_background_service 工具
start_background_service: {
  "command": [
    "cmd", "/c",
    "cd /d D:\\evolve-agent\\workspace\\agentspace\\tts3 && "
    "D:\\evolve-agent\\workspace\\agentspace\\tts3\\venv\\Scripts\\python.exe",
    "run.py", "--port", "53342"
  ],
  "reason": "启动 TTS 语音合成服务"
}
```

```python
# 方式二：使用 skill 脚本
run_python(script="ws:../skills/utility/tts-speech/scripts/tts_start_server.py", 
           args=["--wait"], reason="启动 TTS 服务器")
```

### 2.2 检查服务器状态

```python
run_python(script="ws:../skills/utility/tts-speech/scripts/tts_list_speakers.py",
           reason="查看 TTS 可用说话人")
```

或直接：
```python
web_fetch(url="http://127.0.0.1:53342/api/health")
```

### 2.3 合成语音并播放（核心操作）

**一步到位：**
```python
run_python(script="ws:../skills/utility/tts-speech/scripts/tts_speak.py",
           args=["--speaker","sui","--text","要说的文本"],
           reason="合成语音", timeout=120)
```

脚本会返回 JSON，其中包含：
- `audio_path` — 文件在 `ws:` 下的路径
- `frontend_url` — 前端可访问的 URL
- `publish_cmd` — 调用 `publish_file` 发布给用户的命令

**发布给用户：**
```python
publish_file(path="ws:output/tts_xxx.mp3",
             filename="语音.mp3",
             description="TTS生成的语音")
```

### 2.4 注册新说话人

```python
# 方法一：自动扫描
run_python(script="ws:../skills/utility/tts-speech/scripts/tts_register_speaker.py",
           args=["--auto"], reason="自动注册新说话人")

# 方法二：手动指定（上传音频文件后）
run_python(script="ws:../skills/utility/tts-speech/scripts/tts_register_speaker.py",
           args=["--id","speaker_name","--audio","ws:uploads/vocal.wav","--text","音频文本"],
           reason="注册TTS说话人")
```

---

## 3. API 参考

| 端点 | 方法 | 说明 |
|------|------|------|
| `GET /api/health` | — | 健康检查 + 说话人列表 |
| `POST /api/synthesize` | `{"speaker_id","text","line_id"}` | 合成语音 |
| `POST /api/register-speaker` | `{"speaker_id","vocal_text","vocal_audio_path"}` | 注册说话人 |
| `POST /api/unload-model` | — | 卸载模型释放显存 |

### 合成示例

```python
import requests
r = requests.post("http://127.0.0.1:53342/api/synthesize", json={
    "speaker_id": "sui",
    "text": "你好世界",
    "line_id": "any_id"
})
# r.json() = {"line_id":"any_id","speaker_id":"sui","voice_url":"/static/audio/xxx.wav"}

# 获取音频
audio = requests.get(f"http://127.0.0.1:53342{r.json()['voice_url']}").content
```

---

## 4. 项目文件结构

```
tts3/
├── run.py                          # 服务入口 ← 这是核心
├── CosyVoice/                      # Git submodule (推理引擎)
├── pretrain/Fun-CosyVoice3-0.5B/   # 模型权重
├── StreamingAssets/vocals/<id>/    # 说话人音频
│   ├── vocal.txt
│   └── vocal.wav
├── static/audio/                   # 合成音频输出目录
└── venv/                           # 虚拟环境
```

---

## 5. 已知局限性

| 问题 | 说明 |
|------|------|
| **模型懒加载** | 首次合成需等 5-15 秒加载模型到显存 |
| **显存占用** | CosyVoice3-0.5B 约 3-4GB 显存 |
| **说话人要求** | 干声（无背景音乐），5-30 秒，清晰人声 |
| **语言支持** | 主要支持中文 + 英文 |
| **GPU 必需** | NVIDIA GPU + CUDA，不支持纯 CPU 推理 |
| **Windows 路径** | 路径硬编码 Windows 风格，Linux/macOS 需调整 |

---

## 6. 工作流速查

### 完整流程（首次使用）

```
1. 启动服务器
  → start_background_service(command=[...run.py --port 53342])

2. 检查状态（等待 uvicorn 启动）
  → web_fetch("http://127.0.0.1:53342/api/health")
  → 确认 speakers 列表有数据

3. 合成语音
  → run_python(script="ws:.../tts_speak.py",
               args=["--speaker","sui","--text","你好"])

4. 播放给用户
```

### 快速说话

```python
# Step 1: 确保服务器在运行
# Step 2: 合成
run_python(script="ws:scripts/tts_speak.py",
           args=["--speaker","sui","--text","内容"],
           timeout=120)

# Step 3: 发布
publish_file(path="ws:output/tts_xxx.mp3", filename="语音.mp3")
```