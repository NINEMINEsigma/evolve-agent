---
name: blender-ai
description: 通过命令行与 Python API（bpy）自动化操控 Blender。覆盖 Windows 便携包定位/下载、无头（--background）渲染、场景建模、材质灯光相机、动画关键帧、批量格式转换。当任务涉及以下场景时使用：(1) 定位或部署 Blender 便携版；(2) 用 blender.exe 命令行渲染静帧或动画；(3) 编写、调试在 Blender 内运行的 Python（bpy）脚本；(4) OBJ/FBX/glTF/STL/USD/PLY 等 3D 格式批量互转；(5) 无显示器/服务器/CI 环境跑 Blender 任务。典型触发语："下载 Blender 便携包"、"blender 命令行渲染"、"blender python 脚本"、"批量转换 3D 模型"、"无头渲染"、"bpy 教程"。
---

# Blender AI：命令行 + Python API 自动化

用 Blender 可执行文件在后台模式执行 Python 脚本，完成建模、渲染、动画、格式转换。**不要打开 Blender GUI**——一切走命令行。

本技能已在 **Windows + Evolve Agent 工具链**上用 Blender 4.5.0 便携包验证通过。脚本按 4.x/5.x 双引擎兼容写法编写；没有 5.x 时不要默认去下载。

## 1. 定位 Blender（禁止写死路径）

可执行文件位置随时会变。按下面顺序找，**不要**写死盘符、版本号或 `D:\Tools\...`。

1. 环境变量 `BLENDER_EXE`（若用户指定了某一份）。
2. 工作区便携包：`<workspace>/programs/blender-*/blender.exe`（Windows）或同目录下的 `blender`（Linux/macOS）。
3. `PATH` 里的 `blender`。

自带探测脚本：`scripts/locate_blender.py`。在 Evolve Agent 里这样跑：

```powershell
# StartShell 返回的 namespace_env 里，工作区是 $env:EVOLVE_WS，技能目录是 $env:EVOLVE_SKILLS
& $env:EVOLVE_PYTHON (Join-Path $env:EVOLVE_SKILLS 'design\blender-ai\scripts\locate_blender.py')
```

把打印出来的路径存成 `$blender` 再调用。多份便携包并存时，探测脚本按目录名**逆序**取（新版本名通常更大）；要指定某一份就设 `BLENDER_EXE`。

建议的存放约定（灵活，不是硬编码）：

```
<workspace>/programs/blender-<version>-<platform>/blender.exe
```

当前验证过的一份是 `programs/blender-4.5.0-windows-x64/blender.exe`，仅作示例。

Linux/macOS 同样适用：解压官方包后用其中的 `blender` 可执行文件，CLI 参数一致。

## 2. Evolve Agent 执行方式

- 用 `StartShell` / `WriteShell` 调 Blender，不要假设能在宿主机直接开独立终端。
- 命令文本**不会**展开 `ws:` / `skills:`。必须用 `StartShell` 返回的 `namespace_env`：
  - 工作区：`$env:EVOLVE_WS`
  - 技能目录：`$env:EVOLVE_SKILLS`
  - 本解释器：`$env:EVOLVE_PYTHON`（只用于跑 `locate_blender.py` 等宿主机脚本，**不要**拿它 `import bpy`）
- `bpy` 只能在 Blender 内嵌 Python 里跑：`& $blender -b ... -P script.py`。
- 宿主机脚本（定位、下载便携包）用 PowerShell 或 `$env:EVOLVE_PYTHON`。
- 输出文件放到工作区子目录（例如 `tmp/`、`output/`、项目目录），不要写到工作区根目录。
- 一条 `WriteShell` 文本必须是**单行**，不能含 CR/LF。复杂 bpy 逻辑写成 `.py` 文件，用 `-P` 加载。
- 成功判定：**退出码 + 输出文件存在且大小 > 0**。不要只看退出码。

最小可复用片段：

```powershell
$blender = (& $env:EVOLVE_PYTHON (Join-Path $env:EVOLVE_SKILLS 'design\blender-ai\scripts\locate_blender.py')).Trim()
$script  = Join-Path $env:EVOLVE_SKILLS 'design\blender-ai\scripts\blender_scene.py'
$out     = Join-Path $env:EVOLVE_WS 'tmp\blender-out\demo.png'
New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null
& $blender -b --factory-startup --python-exit-code 1 -P $script -- --output $out --engine EEVEE --width 1280 --height 720
```

## 3. 版本速览

| 版本 | 状态 | 说明 |
|---|---|---|
| Blender 5.2 LTS | 上游当前 LTS | API 默认按 5.x 写，没有再下载 |
| Blender 4.5 LTS | **本机已验证** | 4.5.0 Windows x64 便携包：场景渲染、批量 glTF 导出、逐帧渲染、原生 `-f` 静帧全部通过 |

**关键 API 差异：**

| 项 | 5.x | 4.2–4.5 | ≤4.1 |
|---|---|---|---|
| EEVEE 引擎标识 | `BLENDER_EEVEE` | `BLENDER_EEVEE_NEXT` | `BLENDER_EEVEE` |
| OBJ/STL/PLY 导入 | `bpy.ops.wm.obj_import` 等新算子 | 同左 | 旧 Python 插件算子 |
| 默认色彩管理 | AgX | AgX | Filmic |

写脚本时按 5.x 优先，并在脚本内用 `bpy.app.version` / try-except 做兜底（见 `scripts/blender_scene.py` 的 `set_engine()`）。4.5.0 实测：`BLENDER_EEVEE` 赋值会抛 `TypeError`，`set_engine()` 会落到 `BLENDER_EEVEE_NEXT`。

本机 4.5.0 还确认可用：`CYCLES`、`BLENDER_WORKBENCH`、`wm.obj_import/export`、`wm.stl_*`、`wm.ply_*`、`wm.usd_*`、`import_scene.fbx` / `export_scene.fbx`、`import_scene.gltf` / `export_scene.gltf`、AgX。

## 4. 核心工作流

1. **定位 Blender**：先跑 `scripts/locate_blender.py`。找不到再按 [references/portable-setup.md](references/portable-setup.md) 下载便携包到 `<workspace>/programs/`。
2. **验证可用**：`& $blender --version` 与 `& $blender -b --factory-startup --python-exit-code 1 --python-expr "import bpy; print(bpy.app.version_string)"`。
3. **写脚本**：任务逻辑写成 `.py`，自定义参数一律放在 `--` **之后**；Blender 自己的开关一律放在 `--` **之前**。
4. **执行**：`& $blender -b --factory-startup --python-exit-code 1 -P task.py -- <args>`，再检查退出码与输出文件。
5. **排错**：报错先查 [references/troubleshooting.md](references/troubleshooting.md)。

## 5. `--python-exit-code` 必须在 `--` 前面

Blender 从左到右执行参数。`--` 之后的东西原样交给脚本的 `argparse`，**不会**再被 Blender 解析。

```powershell
# 正确：退出码开关是 Blender 的，放在 -- 之前
& $blender -b --factory-startup --python-exit-code 1 -P task.py -- --output $out --engine EEVEE

# 错误（原技能多处示例）：开关被脚本吃掉
# 1) 脚本没有这个参数 → argparse 直接退出（实测 blender_scene.py 返回 2）
# 2) 脚本碰巧忽略未知参数 → 异常时进程仍返回 0，外层以为成功（实测 boom.py：错位=0，正位=1）
```

`blender_scene.py` / `batch_convert.py` / `render_frames.py` 都用 argparse。把 `--python-exit-code 1` 写在 `--` 后面，轻则参数解析失败，重则失败被当成成功。

## 6. 五条铁律

1. **参数按顺序执行**：`-f` / `-a` / `-P` / `--python-expr` 是动作，遇到就立刻执行。`-o` 必须写在 `-f`/`-a` 前面。
2. **必须带 `--python-exit-code 1`，且放在 `--` 之前**。否则脚本抛异常时 Blender 仍返回 0。
3. **`//` 前缀**相对当前 `.blend`；后台模式不带文件时指向 cwd。脚本里用 `bpy.path.abspath(...)` 打出绝对路径再写文件。
4. **后台模式没有 UI 上下文**：依赖编辑器的 `bpy.ops` 容易 `context is None`。优先 `bpy.data`；必须用算子时先 link、设 active/selected（见 troubleshooting）。
5. **可重复性**：跑脚本加 `--factory-startup`，避免被本机用户配置污染。

## 7. 30 秒上手（Evolve Agent / PowerShell）

```powershell
$blender = (& $env:EVOLVE_PYTHON (Join-Path $env:EVOLVE_SKILLS 'design\blender-ai\scripts\locate_blender.py')).Trim()
$skill   = Join-Path $env:EVOLVE_SKILLS 'design\blender-ai'
$outDir  = Join-Path $env:EVOLVE_WS 'tmp\blender-out'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

# 1) 验证
& $blender -b --factory-startup --python-exit-code 1 --python-expr "import bpy; print('OK', bpy.app.version_string)"

# 2) 模板建场景并渲染静帧
& $blender -b --factory-startup --python-exit-code 1 -P (Join-Path $skill 'scripts\blender_scene.py') -- --output (Join-Path $outDir 'demo.png') --engine EEVEE --width 1280 --height 720

# 3) 渲染已有 .blend 的第 1 帧
& $blender -b $blendPath -o (Join-Path $outDir 'frame_####') -F PNG -f 1
```

## 8. References（按需读取，勿一次全读）

| 文件 | 何时读 |
|---|---|
| [references/portable-setup.md](references/portable-setup.md) | 下载/部署/升级便携包；国内镜像；校验哈希；便携化配置隔离；GPU 后端；命令行装插件 |
| [references/command-line.md](references/command-line.md) | CLI 参数手册：渲染控制、Python 执行、调试日志、退出码、参数顺序 |
| [references/bpy-scripting.md](references/bpy-scripting.md) | bpy 数据模型、对象/网格/曲线、修改器、材质节点、灯光、相机、从零建场景 |
| [references/rendering.md](references/rendering.md) | EEVEE/Cycles/Workbench、采样、输出格式、色彩管理、透明背景、多通道 |
| [references/animation.md](references/animation.md) | 关键帧、fcurve、驱动器、NLA、相机路径、动画渲染与断点续渲 |
| [references/import-export.md](references/import-export.md) | OBJ/FBX/glTF/STL/PLY/USD 导入导出、批量转换、清理与单位 |
| [references/troubleshooting.md](references/troubleshooting.md) | context 错误、GPU 不可用、路径/编码、闪退、版本迁移 |

## 9. Scripts

| 脚本 | 在哪运行 | 用途 |
|---|---|---|
| [scripts/locate_blender.py](scripts/locate_blender.py) | 宿主机 Python（`$env:EVOLVE_PYTHON`） | 按 env / programs / PATH 定位 blender 可执行文件 |
| [scripts/setup_portable.ps1](scripts/setup_portable.ps1) | 宿主机 PowerShell | 下载 + 校验 + 解压便携包。目标目录用参数传入，不要写死 |
| [scripts/blender_scene.py](scripts/blender_scene.py) | Blender `-P` | 场景构建模板：地面、几何体、材质、三点光、相机取景、静帧；`--` 参数解析与 4.x/5.x 引擎兼容 |
| [scripts/batch_convert.py](scripts/batch_convert.py) | Blender `-P` | 批量格式转换，单文件失败不中断整批 |
| [scripts/render_frames.py](scripts/render_frames.py) | Blender `-P` | 动画分段渲染、跳过已存在帧 |

自定义脚本骨架：

```python
import bpy, sys, argparse

def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    # ...add_argument...
    return p.parse_args(argv)

def main():
    args = parse_args()
    # 任务逻辑，尽量用 bpy.data

if __name__ == "__main__":
    main()
```

调用时 Blender 开关在 `--` 前，脚本参数在 `--` 后。

## 10. 没装 Blender 时

只有探测失败才下载。便携包解压到 `<workspace>/programs/`（或用户指定目录），不要默认 `D:\Tools`。下载、镜像、校验见 [references/portable-setup.md](references/portable-setup.md) 与 `scripts/setup_portable.ps1`。

纯自动化还可以 `pip install bpy`（走 PyPI，wheel 绑 Python 小版本）。加载后自带默认立方体，空场景用 `bpy.ops.wm.read_factory_settings(use_empty=True)`。这种模式没有 `--threads` / `--log` 等 CLI 功能，本技能默认仍走 `blender.exe -b`。
