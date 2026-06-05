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
requires:
  gpu: true
  gpu_vram_gb: 4
  cuda: true
  python: ">=3.10, <=3.12"
  disk_gb: 5
  commands:
    - git
    - python
  notes:
    - "仅支持 NVIDIA GPU + CUDA，不支持纯 CPU 推理"
    - "首次部署需下载模型权重约 2GB"
    - "说话人音频要求干声（无背景音乐），5-30 秒"
setup:
  type: once
  estimated_time: "15-30分钟"
  steps:
    - "克隆 tts3 仓库"
    - "创建 venv 并安装依赖"
    - "准备 CosyVoice3 模型权重"
    - "准备至少一个说话人音频"
---

# TTS Speech Synthesis Skill

基于 **CosyVoice3** 零样本语音克隆技术的 TTS 语音合成技能。从**仓库安装**到**生成语音**到**用户听到**一条龙。

## 0. 前置知识

- **ws:**, 类似前缀代表的是不同的目录, ws:指工作空间
- **本skill路径**, 实际上如果你可以直接调用skill的脚本, 那么你并不需要知道, 依照对应名称去读取或调用脚本即可

## 1. 安装（从零开始） [Setup — 仅首次部署，完成后持续有效]

### 1.1 克隆仓库

你可以询问用户或者安装到工作目录下

```bash
# 方式一：GitHub
git clone --recursive https://github.com/NINEMINEsigma/tts3.git <target>
cd tts3

# 方式二：Gitea
git clone --recursive http://gitea.liubai.site/ai/tts3.git <target>
cd tts3
```

如果已克隆但 submodule 未拉取：
```bash
git submodule update --init --recursive
```

### 1.2 创建虚拟环境

```bash
# 需要python3.10或者3.12
python -m venv venv
# Windows
venv\Scripts\activate
```

### 1.3 安装依赖

需要提前准备cuda环境, 然后才能继续接下来的工作,

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

模型自动通过 `modelscope` 下载，也可手动放到你认为应该放置的目录, 如：
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
    └── <speaker_id>/            # 如 "低沉男声"
        ├── vocal.txt            # 音频对应文本
        └── vocal.{wav|mp3}      # 干声音频 (5-30秒)
```

### 1.6 启动服务

```bash
python run.py --port 53342
```

**验证：** `curl http://127.0.0.1:53342/api/health`

---

## 2. 操作指南 [Runtime — 每次会话按需执行]

### 2.1 启动服务器（在当前环境中）

```python
# 方式一：使用能后台运行的工具, 假设有一个名叫start_background_service的后台启动工具
start_background_service: {
  "command": [
    "cmd", "/c",
    "cd /d ws:tts3 && "
    "venv\\Scripts\\python.exe",
    "run.py", "--port", "53342"
  ],
  "reason": "启动 TTS 语音合成服务"
}
```

```python
# 方式二：使用 skill 脚本
run_python(script="本skill路径/scripts/tts_start_server.py", 
           args=["--wait"], reason="启动 TTS 服务器")
```

### 2.2 检查服务器状态

```python
run_python(script="本skill路径/scripts/tts_list_speakers.py",
           reason="查看 TTS 可用说话人")
```

或直接：
```python
web_fetch(url="http://127.0.0.1:53342/api/health")
```

### 2.3 合成语音并播放（核心操作）

**一步到位：**
```python
run_python(script="本skill路径/scripts/tts_speak.py",
           args=["--speaker","sui","--text","要说的文本"],
           reason="合成语音", timeout=120)
```

脚本会返回 JSON，其中包含：
- `audio_path` — 文件在 `ws:` 下的路径

接着发布给用户或者将路径交给用户

### 2.4 注册新说话人

```python
# 方法一：自动扫描
run_python(script="本skill路径/scripts/tts_register_speaker.py",
           args=["--auto"], reason="自动注册新说话人")

# 方法二：手动指定（上传音频文件后）
run_python(script="本skill路径/scripts/tts_register_speaker.py",
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

