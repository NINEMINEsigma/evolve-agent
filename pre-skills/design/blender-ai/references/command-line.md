# Blender 命令行完全手册

> Blender 的 CLI 是所有自动化的入口。官方文档：`blender --help` 或 https://docs.blender.org/manual/en/latest/advanced/command_line/ 。本文件按任务组织常用参数，并解释最容易踩的坑。

## 0. 最重要的概念：参数是"按顺序执行的动作"

Blender **不是**先解析全部参数再执行，而是从 argv[1] 开始**逐条处理**，遇到"动作型"参数（`-f`、`-a`、`-P`、`--python-expr`）就**当场执行**。因此：

```
# 错误：-o 在 -f 之后，渲染已经开始，输出路径没生效
blender -b scene.blend -f 1 -o //out/frame_####

# 正确：先设置输出，再触发渲染
blender -b scene.blend -o //out/frame_#### -F PNG -f 1
```

推荐参数顺序口诀：**`blender -b <文件.blend> [引擎/线程等全局设置] -o <输出> -F <格式> [帧范围] [动作]`**。

## 1. 运行模式

| 参数 | 作用 |
|---|---|
| `-b` / `--background` | 后台模式：不加载 UI，自动化必用。几乎所有任务都加它 |
| `--factory-startup` | 跳过用户启动文件与偏好，保证可重复性（写脚本时强烈建议加） |
| `blender scene.blend` | 启动时打开指定 .blend |
| `--python-expr "<代码>"` | 执行一段 Python 表达式/语句 |
| `-P <脚本.py>` / `--python <脚本.py>` | 执行 Python 脚本文件 |
| `--python-exit-code <n>` | Python 抛未捕获异常时以退出码 n 退出。**自动化必须加，且必须放在 `--` 之前**。放到 `--` 之后会变成脚本参数，Blender 看不到 |
| `--` | 分隔符：之后的参数原样传给脚本（`sys.argv` 读取） |
| `-noaudio` | 禁用音频（后台渲染建议加，省一点初始化麻烦） |

## 2. 渲染控制

| 参数 | 作用 | 示例 |
|---|---|---|
| `-E <引擎>` | 指定渲染引擎 | `-E BLENDER_EEVEE`（5.x）/ `-E BLENDER_EEVEE_NEXT`（4.2–4.5）/ `-E CYCLES` / `-E BLENDER_WORKBENCH` |
| `-o <路径>` | 输出路径；`#` 表示帧号占位（`####` = 4 位补零）；`//` 开头 = 相对 blend 文件 | `-o "//out/frame_####"` |
| `-F <格式>` | 输出格式 | `PNG` `JPEG` `OPEN_EXR` `TIFF` `FFMPEG`(视频) `MPEG` 等 |
| `-x <0/1>` | 是否自动补扩展名 | `-x 1` |
| `-f <帧>` | 渲染单帧（动作型，立即执行） | `-f 1`；连续帧 `-f 1 -f 2 -f 5` |
| `-a` | 渲染整段动画（动作型） | `-a` |
| `-s <帧>` `-e <帧>` | 设置动画起止帧 | `-s 1 -e 120 -a` |
| `-j <步长>` | 每隔 N 帧渲一帧 | `-j 2` |
| `-t <线程数>` | 覆盖线程数（0=自动） | `-t 16` |

### 静帧

```powershell
& $blender -b scene.blend -E BLENDER_EEVEE -o "//out/still" -F PNG -f 1
```

### 整段动画（PNG 序列，推荐而不是直接出视频）

```powershell
& $blender -b scene.blend -o "//out/frames/frame_####" -F PNG -s 1 -e 120 -a
```

> 为什么出 PNG 序列而不是直接 FFMPEG：中断后可以从断点续渲（脚本里跳过已存在帧），单帧失败不污染整段。合成视频再单独用 ffmpeg 或 Blender 的 sequencer。

### 只改渲染设置不改文件

```powershell
& $blender -b scene.blend --python-expr "import bpy; s=bpy.context.scene; s.render.resolution_x=3840; s.render.resolution_y=2160" -o "//out/4k" -F PNG -f 1
```

## 3. Python 执行模式

### 3.1 行内表达式（适合一行小任务）

```powershell
& $blender -b --factory-startup --python-expr "import bpy; print(len(bpy.data.objects))"
```

### 3.2 脚本文件 + 自定义参数（主力模式）

命令行：
```powershell
& $blender -b --factory-startup --python-exit-code 1 -P task.py -- --input $inPath --output $outPath
```

脚本内解析（固定范式）：

```python
import sys, argparse
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args(argv)
```

注意：没有 `--` 时 Blender 会尝试解析未知参数并报 `Unknown argument`（通常不致命但污染日志）；脚本里要做兼容。

### 3.3 加载 blend 后再跑脚本

```powershell
& $blender -b $blendPath -P modify.py --python-exit-code 1 -- --scale 2.0
```

### 3.4 脚本里保存/另存

```python
bpy.ops.wm.save_as_mainfile(filepath=r"D:\out\result.blend")   # 保存
bpy.ops.wm.save_as_mainfile(filepath=..., copy=True)           # 另存副本，不切换当前文件
```

## 4. 日志与调试

| 参数 | 作用 |
|---|---|
| `--log "<匹配>"` | 按类别开日志，如 `--log "bpy.*"` |
| `--log-level <n>` | 日志级别 -1..2（0=warning 等） |
| `--debug-all` / `--debug-python` | 全量/Python 调试输出 |
| `--debug-memory` | 渲染结束时打印内存统计 |
| `-d` | `--debug-all` 简写 |

后台模式下脚本里的 `print()` 直接进 stdout，用 PowerShell 捕获：

```powershell
& $blender -b --factory-startup --python-exit-code 1 -P task.py -- --output $outPath 2>&1 | Tee-Object run.log
```

## 5. 退出码约定

- `0`：成功。
- 非 0：崩溃、参数错误，或脚本异常（仅在加了 `--python-exit-code <n>` 时）。
- **判定成功不要只看退出码**：再检查预期输出文件是否存在且大小 > 0（渲染被 killed 时也可能留半截文件，必要时校验文件可读/图像尺寸）。

## 6. 杂项实用参数

| 参数 | 作用 |
|---|---|
| `-noaudio` | 禁用音频子系统 |
| `--python-console` | 启动交互式 Python 控制台（调试用） |
| `--app-template <名>` | 使用应用模板 |
| `--command extension <子命令>` | 扩展管理（装/卸/列） |
| `-y` | 启动时自动执行 blend 内嵌的"自动运行脚本"（默认禁用，安全考虑） |
| `--open-last` | 打开最近一次会话（自动化勿用） |

## 7. 常用任务配方

**批量渲染多台机器分片（渲染农场手工版）**：每台机器渲染不同帧段，输出到共享目录，PNG 序列 + 跳过已存在帧：

```powershell
# 机器 A: 1-60, 机器 B: 61-120
& $blender -b scene.blend -o "\\share\frames\frame_####" -F PNG -s 1 -e 60 -a
```

**把 blend 缩成最小（去未用数据）再保存**：

```powershell
& $blender -b scene.blend --python-expr "import bpy; bpy.ops.outliner.orphans_purge(do_recursive=True) if hasattr(bpy.ops.outliner,'orphans_purge') else None; bpy.ops.wm.save_mainfile()" --python-exit-code 1
```

**无 blend 文件从零建场景并渲染**：见 ../scripts/blender_scene.py。

**批量格式转换**：见 ../scripts/batch_convert.py。
