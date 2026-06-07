---
name: evolve-long-running-tasks
description: "使用后台任务和定时任务处理超时指令，适用于服务器启动/调试、虚拟环境安装、长时间下载等场景"
version: "1.0.0"
author: "Evolve Agent"
category: evolve
tags:
  - long-running
  - background
  - cron
  - timeout
  - server
  - monitoring
---

# 长时间运行任务处理

## 核心问题

`run_command` 和 `run_python` 都有超时限制：

| 工具 | 超时 |
|------|------|
| `run_command` | 30 秒 |
| `run_python` | 默认 60 秒，最大 300 秒 |

任何超过这些时限的操作都会直接失败。以下场景必然超时：

- 启动 Web 服务器（进程持续运行，不会自行退出）
- `pip install` / `conda install` 等包安装
- 下载大文件（模型权重、数据集等）
- 编译大型项目
- 数据库迁移、数据处理

## 工具全景

两个工具集互补：

```
                    ┌─────────────────────────┐
                    │   需要长时间运行的任务     │
                    └───────────┬─────────────┘
                                │
              ┌─────────────────┴─────────────────┐
              │                                   │
     ┌────────▼────────┐                 ┌────────▼────────┐
     │ 一次性后台任务    │                 │ 周期性监控任务    │
     │                 │                 │                 │
     │ start_          │                 │ schedule_       │
     │ background_     │                 │ cron            │
     │ service         │                 │                 │
     │                 │                 │                 │
     │ stop_           │                 │ list_cron_jobs  │
     │ background_     │                 │ cancel_cron_job │
     │ service         │                 │ run_cron_job_now│
     └────────┬────────┘                 └────────┬────────┘
              │                                   │
     ┌────────▼────────┐                 ┌────────▼────────┐
     │ 一次性启动       │                 │ 定期检查/轮询     │
     │ 完成后手动停止    │                 │ 自动重复执行      │
     │                 │                 │ 支持 max_runs   │
     └─────────────────┘                 └─────────────────┘
```

关键区别：

| 维度 | start_background_service | schedule_cron |
|------|--------------------------|---------------|
| 执行次数 | 一次（持续运行） | 多次（按调度重复） |
| 返回值 | 立即返回 task_id | 立即返回 task_id |
| 进程模型 | 单个后台进程 | 每次执行启动新进程 |
| 日志 | 流式写入（stdout/stderr 合并） | 每次执行追加写入 |
| 持久化 | 不持久化（进程结束即消失） | 持久化到 cron_jobs.json，重启恢复 |
| 典型用途 | 服务器进程、长时间编译 | 健康检查、进度轮询、定期报告 |

## 模式一：一次性后台任务 + 日志轮询

适用于：服务器启动、包安装、文件下载、编译。

### 步骤

**1. 启动后台任务：**

```
start_background_service(
    command=["python", "-m", "http.server", "8080"],
    reason="启动开发服务器以便预览前端构建结果",
    cwd="ws:frontend/dist"
)
→ 返回: { task_id: "a1b2c3d4e5f6", log_path: "ws:logs/background/a1b2c3d4e5f6.log", pid: 12345 }
```

`cwd` 默认是 `ws:`（agentspace 目录）。所有沙箱路径（`ws:`/`fork:`/`fix:`）会被自动解析为真实路径。

**2. 轮询日志确认任务状态：**

使用 `schedule_cron` 注册一个短期监控任务，每秒检查一次日志文件尾部：

```
schedule_cron(
    schedule="10",           # 每 10 秒执行一次
    command=["python", "-c", "
import sys
try:
    with open('ws:logs/background/a1b2c3d4e5f6.log', 'r') as f:
        lines = f.readlines()
        last_10 = lines[-10:] if len(lines) > 10 else lines
        print(''.join(last_10))
except:
    print('[log not ready yet]')
"],
    reason="监控后台任务日志输出",
    name="monitor-log-a1b2c3d4e5f6",
    max_runs=6              # 最多执行 6 次，防止永久运行
)
```

更好的做法：不直接看日志，而是用 cron 执行**验证脚本**来判断任务是否就绪。

**3. 判断完成条件：**

根据任务类型写不同的验证逻辑：

- **服务器启动成功**：curl/httpx 请求健康检查端点
- **pip 安装完成**：检查 `pip list` 是否包含目标包，或检查退出标志文件
- **下载完成**：检查文件是否存在且大小不再增长
- **编译完成**：检查产物文件是否存在或进程是否退出

**4. 清理：**

```
# 停止监控 cron 任务
cancel_cron_job(task_id="<cron_task_id>")

# 停止后台服务（如果需要）
stop_background_service(task_id="<bg_task_id>")
```

### 完整示例：安装 Python 包

```
# 1. 在后台安装
start_background_service(
    command=["pip", "install", "transformers", "torch"],
    reason="安装 AI/ML 依赖包，预计需要数分钟",
    cwd="ws:"
)
→ task_id: "bg-001", log_path: "ws:logs/background/bg-001.log"

# 2. Phase 1 — 30s 快速检查 (覆盖前 2 分钟)
schedule_cron(
    schedule="30",
    command=["python", "-c", "
import subprocess, sys
result = subprocess.run([sys.executable, '-c', 'import transformers, torch; print(1)'], capture_output=True, text=True)
if result.returncode == 0:
    print('SUCCESS: pip install complete')
else:
    print('PENDING_STAGE_1')
"],
    reason="安装完成检查 — Phase 1",
    name="check-pip-p1",
    max_runs=4            # 4 × 30s = 2min
)
→ task_id: "cron-p1"

# 3a. 如果 cron 事件通知中出现 PENDING_STAGE_1 且 Phase 1 已耗尽：
cancel_cron_job(task_id="cron-p1")

# 3b. Phase 2 — 60s 中速检查 (覆盖 2~7 分钟)
schedule_cron(
    schedule="60",
    command=["python", "-c", "
import subprocess, sys
result = subprocess.run([sys.executable, '-c', 'import transformers, torch; print(1)'], capture_output=True, text=True)
if result.returncode == 0:
    print('SUCCESS: pip install complete')
else:
    print('PENDING_STAGE_2')
"],
    reason="安装完成检查 — Phase 2",
    name="check-pip-p2",
    max_runs=5            # 5 × 60s = 5min
)
→ task_id: "cron-p2"

# 3c. 如果 Phase 2 也耗尽 → Phase 3 — 180s (覆盖 7~37 分钟)
cancel_cron_job(task_id="cron-p2")

schedule_cron(
    schedule="180",
    command=["python", "-c", "
import subprocess, sys
result = subprocess.run([sys.executable, '-c', 'import transformers, torch; print(1)'], capture_output=True, text=True)
if result.returncode == 0:
    print('SUCCESS: pip install complete')
else:
    print('PENDING_STAGE_3')
"],
    reason="安装完成检查 — Phase 3",
    name="check-pip-p3",
    max_runs=10           # 10 × 180s = 30min
)
→ task_id: "cron-p3"

# 4. 任意阶段看到 SUCCESS 后:
cancel_cron_job(task_id="<当前阶段的 cron task_id>")
# 后台安装进程完成后自动退出，无需手动 stop
```

### 完整示例：启动 Web 服务器并验证

```
# 1. 启动服务器
start_background_service(
    command=["python", "-m", "http.server", "8765"],
    reason="启动文件服务器预览构建产物",
    cwd="ws:dist"
)
→ task_id: "bg-002", log_path: "ws:logs/background/bg-002.log"

# 2. Phase 1 — 5s 密集检查（服务器通常启动很快）
schedule_cron(
    schedule="5",
    command=["python", "-c", "
import urllib.request
try:
    r = urllib.request.urlopen('http://127.0.0.1:8765', timeout=3)
    print(f'READY: HTTP {r.status}')
except Exception as e:
    print(f'WAITING_STAGE_1: {e}')
"],
    reason="服务器就绪检查 — Phase 1",
    name="check-server-p1",
    max_runs=12           # 12 × 5s = 1min
)
→ task_id: "cron-s1"

# 3a. 如果 1 分钟后仍未就绪 → Phase 2 — 30s
cancel_cron_job(task_id="cron-s1")

schedule_cron(
    schedule="30",
    command=["python", "-c", "
import urllib.request
try:
    r = urllib.request.urlopen('http://127.0.0.1:8765', timeout=3)
    print(f'READY: HTTP {r.status}')
except Exception as e:
    print(f'WAITING_STAGE_2: {e}')
"],
    reason="服务器就绪检查 — Phase 2",
    name="check-server-p2",
    max_runs=10           # 10 × 30s = 5min
)
→ task_id: "cron-s2"

# 3b. 仍未就绪 → Phase 3 — 180s
cancel_cron_job(task_id="cron-s2")

schedule_cron(
    schedule="180",
    command=["python", "-c", "
import urllib.request
try:
    r = urllib.request.urlopen('http://127.0.0.1:8765', timeout=3)
    print(f'READY: HTTP {r.status}')
except Exception as e:
    print(f'WAITING_STAGE_3: {e}')
"],
    reason="服务器就绪检查 — Phase 3",
    name="check-server-p3",
    max_runs=10
)

# 4. 服务器就绪后:
cancel_cron_job(task_id="<当前阶段的 cron task_id>")

# 5. 工作完成后停止服务器:
stop_background_service(task_id="bg-002")
```

## 模式二：纯 Cron 周期性监控

适用于：下载进度报告、系统资源监控、定期健康检查。

无需 `start_background_service`，因为不需要管理一个持续运行的进程。

### 示例：监控文件下载进度（退避版）

```
# Phase 1 — 30s 快速确认下载是否开始
schedule_cron(
    schedule="30",
    command=["python", "-c", "
import os, time
path = 'ws:models/llama-7b.gguf'
if os.path.exists(path):
    size_mb = os.path.getsize(path) / (1024*1024)
    mtime = os.path.getmtime(path)
    age = time.time() - mtime
    print(f'Phase1: {size_mb:.1f} MB, last written {age:.0f}s ago')
    if age > 180:  # 3 分钟没变化 → 可能下载完了
        print('STATUS: likely complete')
    else:
        print('STATUS: downloading')
else:
    print('STATUS: not yet created')
"],
    reason="监控模型下载 — Phase 1",
    name="check-dl-p1",
    max_runs=4            # 4 × 30s = 2min
)

# Phase 1 耗尽 → Phase 2: 60s
# Phase 2 耗尽 → Phase 3: 180s × 20 (= 1 小时覆盖)
```

### 示例：数据库迁移 + 外部任务等待

某些任务你无法直接控制其完成（如外部 API 触发的数据库迁移、CI/CD 流水线），此时用 cron 定期查询状态：

```
schedule_cron(
    schedule="120",
    command=["python", "-c", "
import requests
r = requests.get('https://api.example.com/migration/status', timeout=10)
data = r.json()
print(f'Progress: {data[\"percent\"]}%, Status: {data[\"status\"]}')
if data['status'] == 'completed':
    print('MIGRATION_COMPLETE')
"],
    reason="轮询数据库迁移进度",
    name="check-migration-status",
    max_runs=60            # 轮询 2 小时
)
```

## 自适应轮询（指数退避）

cron 任务的 `schedule` 是固定值，不能动态调整。但一张任务可以**分阶段创建**多个 cron 来模拟退避效果。

### 三段退避策略

默认使用三段式，覆盖短期到长期任务：

```
Phase 1         Phase 2         Phase 3
30s × 4 次      60s × 5 次      180s × 10 次
──────→        ──────────→     ────────────────→
0 ~ 2min        2 ~ 7min         7 ~ 37min

如果 Phase N 耗尽 max_runs 时任务仍未完成，
则取消它并创建 Phase N+1。
```

为什么这样设计：

| 阶段 | 间隔 | 次数 | 覆盖时长 | 适合 |
|------|------|------|----------|------|
| Phase 1 | 30s | 4 | 2 分钟 | 短任务（服务器启动、小包安装） |
| Phase 2 | 60s | 5 | 5 分钟 | 中等任务（中型 pip 安装、编译） |
| Phase 3 | 180s | 10 | 30 分钟 | 长任务（大模型下载、数据库迁移） |

### 实施方法

agent 收到 cron 事件通知时检查 stdout：

- 看到 `SUCCESS` / `READY` / `COMPLETE` → 取消当前阶段 cron，任务完成
- 看到 `PENDING` / `WAITING` / `IN_PROGRESS`，且 cron 已达到 `max_runs` → 取消旧 cron，创建下一阶段
- Phase 3 用完后仍 PENDING → 报告用户，由用户决定是否继续等待

### 退避脚本模板

在每个 cron 的 `python -c` 代码中，用 `$BACKOFF_STAGE` 标记当前阶段，便于 agent 从通知中识别：

**Phase 1 命令（30s × 4）：**

```
schedule_cron(
    schedule="30",
    command=["python", "-c", "
import subprocess, sys
result = subprocess.run([sys.executable, '-c', 'import transformers, torch; print(1)'], capture_output=True, text=True)
if result.returncode == 0:
    print('SUCCESS: packages installed')
else:
    print('PENDING_STAGE_1')
"],
    reason="安装包完成检查 — Phase 1",
    name="check-install-p1",
    max_runs=4
)
```

**Phase 2 命令（60s × 5），在 Phase 1 耗尽时创建：**

```
# cancel Phase 1 first
cancel_cron_job(task_id="<phase1_task_id>")

schedule_cron(
    schedule="60",
    command=["python", "-c", "
import subprocess, sys
result = subprocess.run([sys.executable, '-c', 'import transformers, torch; print(1)'], capture_output=True, text=True)
if result.returncode == 0:
    print('SUCCESS: packages installed')
else:
    print('PENDING_STAGE_2')
"],
    reason="安装包完成检查 — Phase 2",
    name="check-install-p2",
    max_runs=5
)
```

**Phase 3 命令（180s × 10），在 Phase 2 耗尽时创建：**

```
# cancel Phase 2 first
cancel_cron_job(task_id="<phase2_task_id>")

schedule_cron(
    schedule="180",
    command=["python", "-c", "
import subprocess, sys
result = subprocess.run([sys.executable, '-c', 'import transformers, torch; print(1)'], capture_output=True, text=True)
if result.returncode == 0:
    print('SUCCESS: packages installed')
else:
    print('PENDING_STAGE_3')
"],
    reason="安装包完成检查 — Phase 3",
    name="check-install-p3",
    max_runs=10
)
```

### 退避参数速查表

根据任务预估时长，选择不同的退避起点和深度：

| 预估时长 | 退避配置 | 总覆盖 |
|----------|----------|--------|
| < 2 分钟 | Phase 1 only: 10s × 12 | 2 min |
| 2 ~ 10 分钟 | Phase 1 → 2 | 7 min |
| 10 ~ 60 分钟 | Phase 1 → 2 → 3 | 37 min |
| > 1 小时 | Phase 1 → 2 → 3(ex): 180s × 30 | 97 min |
| 不确定 | Phase 1 → 2 → 3（默认） | 37 min |

## 完整决策流程（含退避）

```
收到一个可能超时的命令
        │
        ▼
  命令是否有明确的完成条件？
   (服务器就绪 / 文件生成 / 包已安装)
        │
   ┌────┴────┐
   │ 有      │ 无（纯监控类）
   ▼         ▼
┌──────────────────┐   ┌─────────────────┐
│ 模式一：          │   │ 模式二：          │
│ background + cron │   │ 纯 cron 定期检查  │
│                  │   │                 │
│ 1. 用 background  │   │ 1. Phase 1      │
│    启动任务        │   │   schedule=30s  │
│ 2. Phase 1 cron   │   │   max_runs=4    │
│   快速验证         │   │                 │
│ 3. 完成→清理      │   │ 2. 耗尽→Phase 2  │
│    未完成→Phase 2  │   │   schedule=60s  │
│ 4. 完成→清理      │   │   max_runs=5    │
│    未完成→Phase 3  │   │                 │
│ 5. Phase 3 耗尽   │   │ 3. 耗尽→Phase 3  │
│    → 报告用户      │   │   schedule=180s │
│                  │   │   max_runs=10    │
│                  │   │                 │
│                  │   │ 4. Phase 3 耗尽  │
│                  │   │   → 报告用户      │
└──────────────────┘   └─────────────────┘
```

## 重要原则

### 1. 始终使用三段退避，永远设 max_runs

绝不要创建无限执行的 cron 任务。没有 `max_runs` 的任务会永久运行并持续持久化，占用资源。

默认三段退避：`30s × 4 → 60s × 5 → 180s × 10`。短任务在 Phase 1 就能捕获，长任务有 Phase 2/3 兜底。每阶段都设 `max_runs`，耗尽时由 agent 收到通知后取消旧任务、创建下一阶段。

### 2. 用 python -c 而非脚本文件

Cron 的命令在子进程中执行，沙箱路径解析与 agent 环境一致。直接用 `python -c "..."` 写内联代码即可，无需先写脚本文件。

### 3. Cron 间隔最小 10 秒

`schedule` 的最小间隔是 10 秒。不要设置更小的值。

### 4. 从 cron 日志读取结果

Cron 任务的 stdout 写入 `ws:logs/cron/<session_id>/<task_id>.log`。`list_cron_jobs` 返回每个任务的 `log_path`。

cron 通知的回调会将 stdout 推送给 agent（当输出 ≤5000 字符时），但大输出会被截断。检查日志文件获取完整内容。

### 5. 任务完成后的清理清单

- [ ] `cancel_cron_job` — 取消所有相关的定时监控任务
- [ ] `stop_background_service` — 停止不再需要的后台进程（仅适用于持续运行的进程）
- [ ] 如果需要保留日志，告知用户 `log_path` 位置

### 6. 区分"持续运行"和"终将退出"

- 服务器进程（持续运行）→ 必须用 `stop_background_service` 手动停止
- `pip install`、编译、下载（终将退出）→ 进程退出后自动释放，只需取消 cron 监控

## 反模式

**不要**用 `run_command` 启动服务器然后期待它返回。它会阻塞 30 秒后超时失败。

**不要**用 `run_command` 执行 `pip install` 大型包。即使没到超时，长时间阻塞 agent 也是浪费。

**不要**创建无限执行的 cron 任务（`max_runs=0` 且无限等待外部条件）。

**不要**在循环中反复调用 `run_command` 来做轮询——这正是 `schedule_cron` 的用途。

**不要**用固定大间隔做全程轮询（如全程 180s × 120）。短任务会被浪费等待，应该从 30s 开始退避。

**不要**忘记在任务完成后清理 cron 任务和后台服务。