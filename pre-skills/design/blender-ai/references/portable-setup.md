# Blender Windows 便携包：下载、校验、部署、配置

> 适用场景：在没有安装 Blender、或需要固定版本/干净环境的 Windows 机器上，用"解压即用"的 zip 便携包部署 Blender，供命令行/bpy 自动化使用。
> 截至 2026-09：当前 LTS 为 **Blender 5.2（补丁 5.2.2）**；旧 LTS 为 4.5（维护至 2027）。下文以 5.2.2 为例，替换版本号即可用于其他版本。

## 1. 下载地址

**官方发布目录（所有正式版都按 `BlenderX.Y/` 分目录存放）：**

```
https://download.blender.org/release/Blender5.2/blender-5.2.2-windows-x64.zip
```

- Windows 便携包命名规律：`blender-<版本>-windows-x64.zip`（ARM 设备为 `windows-arm64.zip`）。
- 同目录下还有 `blender-<版本>.md5` / `.sha256` 校验文件。
- 官网下载页 https://www.blender.org/download/ 提供 "Windows Portable (.zip)" 选项；但程序化下载直接拼上面 release 目录的 URL 更可靠。
- 每日构建/尝鲜版在 https://builder.blender.org/download/ （非正式版，自动化勿用）。

**国内镜像（官网慢或被拦截时优先用）：**

| 镜像 | URL 前缀 |
|---|---|
| 清华 TUNA | `https://mirrors.tuna.tsinghua.edu.cn/blender/release/` |
| 阿里云 | `https://mirrors.aliyun.com/blender/release/` |
| 荷兰 NLUUG（官方镜像，海外快） | `https://ftp.nluug.nl/pub/graphics/blender/release/` |

拼接示例：`https://mirrors.tuna.tsinghua.edu.cn/blender/release/Blender5.2/blender-5.2.2-windows-x64.zip`

> 注意：`download.blender.org` 有 CDN 人机校验，裸 `curl`/脚本直连可能拿到 403 HTML 页面；镜像站无此限制。下载后务必校验文件大小与哈希——约 390 MB，若只有几十 KB 说明下载到的是拦截页。

## 2. 一键部署脚本

skill 自带 [../scripts/setup_portable.ps1](../scripts/setup_portable.ps1)，在 **Windows PowerShell** 中执行（不是 Blender 里）。目标目录由调用方传入，推荐工作区 `programs/`：

```powershell
$dest = Join-Path $env:EVOLVE_WS "programs"
powershell -ExecutionPolicy Bypass -File setup_portable.ps1 -Version 4.5.0 -DestDir $dest
# 指定镜像：-Mirror "https://mirrors.tuna.tsinghua.edu.cn/blender/release"
```

它做的事（手动执行的等价步骤）：

### 2.1 下载（PowerShell）

```powershell
$ver = "4.5.0"
$major = ($ver -split '\.')[0..1] -join '.'          # "4.5"
$dest = Join-Path $env:EVOLVE_WS "programs"
$base = "https://mirrors.tuna.tsinghua.edu.cn/blender/release/Blender$major"
$zip = "blender-$ver-windows-x64.zip"
$zipPath = Join-Path $dest $zip
curl.exe -L --fail -o $zipPath "$base/$zip"
```

### 2.2 校验 MD5

```powershell
Invoke-WebRequest -Uri "$base/blender-$ver.md5" -OutFile "blender-$ver.md5"
# .md5 文件里每行格式: "<md5>  <文件名>"
$expected = (Get-Content "blender-$ver.md5" | Select-String $zip).ToString().Split()[0]
$actual = (Get-FileHash $zip -Algorithm MD5).Hash.ToLower()
if ($actual -ne $expected) { throw "哈希校验失败：$actual != $expected" }
```

### 2.3 解压

```powershell
Expand-Archive -Path $zipPath -DestinationPath $dest
# 得到 <dest>\blender-<ver>-windows-x64\blender.exe
```

解压后的目录结构（以 4.5.0 为例，5.x 则是 `5.2/` 这类主版本目录）：

```
blender-4.5.0-windows-x64/
├── blender.exe            ← 可执行文件（所有命令行操作的对象）
├── blender.pdb / *.dll
├── 4.5/                   ← 版本号目录
│   ├── scripts/           ← 内置 Python 模块与插件（addons/、modules/、startup/）
│   ├── datafiles/         ← 字体、图标、HDRI 等
│   └── python/            ← 内嵌 Python 解释器（blender.exe 用的就是它）
└── ...
```

## 3. 便携化：隔离配置与插件（重要）

默认情况下，即使是 zip 解压版，Blender 也会把配置写到用户目录 `%APPDATA%\Blender Foundation\Blender\5.2\`。**要真正做到"便携、多版本互不污染"：**

在版本号目录下手动建一个 `config` 文件夹：

```
blender-<version>-windows-x64/
└── <major>/               # 例如 4.5 或 5.2
    └── config/            ← 新建这个空目录
```

此后该副本的用户配置、启动文件、扩展仓库全部落在 `<major>\config\` 内，不再读写 `%APPDATA%`。多版本并存、U 盘携带、CI 环境全靠这一招。

> 自动化任务还建议每次运行加 `--factory-startup`，从出厂状态启动，彻底排除配置干扰。

## 4. 验证部署

```powershell
$blender = (& $env:EVOLVE_PYTHON (Join-Path $env:EVOLVE_SKILLS 'design\blender-ai\scripts\locate_blender.py')).Trim()
& $blender --version
& $blender -b --factory-startup --python-exit-code 1 --python-expr "import bpy,sys; print(bpy.app.version_string); print(sys.version)"
```

预期输出 `Blender 5.2.2` 与内嵌 Python 版本。第一条命令若报"不是内部或外部命令"，说明路径写错或用了 cmd 的 `&` 语法（`&` 是 PowerShell 调用运算符；cmd 里直接写路径即可）。

## 5. GPU 渲染后端（Cycles）

CPU 开箱即用。GPU 需要在**首选项**里选后端（CUDA / OptiX / HIP / oneAPI / Metal），对应配置文件 `5.2\config\userpref.blend`。纯命令行环境的两种做法：

**做法 A（推荐）**：先在有显示器的机器上打开一次 GUI，Edit → Preferences → System 选好后端并保存，整个目录拷走（便携配置会一起带走）。

**做法 B**：用脚本写入偏好（后台模式也可行）：

```python
import bpy
prefs = bpy.context.preferences.addons["cycles"].preferences
prefs.compute_device_type = "OPTIX"   # 或 "CUDA"/"HIP"/"ONEAPI"
for d in prefs.get_devices_for_type(prefs.compute_device_type):
    d.use = True
prefs.save_preferences()
```

脚本内也可直接指定渲染设备：`bpy.context.scene.cycles.device = "GPU"`。

## 6. 命令行安装插件 / 扩展

4.2+ 使用扩展（Extensions）体系，zip 插件用：

```powershell
& $blender -b --factory-startup --command extension install-file "D:\addons\some_addon.zip" --repo user_default
```

旧式手动安装：把插件解压到 `5.2\config\scripts\addons\`（便携模式），然后在脚本里 `bpy.ops.preferences.addon_enable(module="some_addon")`。

## 7. 升级与多版本并存

- 升级 = 下载新版本 zip 解压到新目录，旧目录原样保留；要迁移配置就把旧 `5.2\config\` 复制过去。
- 不要在覆盖安装时直接解压到同一目录（残留旧 dll 会导致玄学崩溃）。

## 8. 常见问题速查

- **下载只有几十 KB / 解压报错**：下载到 CDN 拦截页，换镜像站重新下载并校验大小。
- **双击 blender.exe 闪一下就没了**：这是控制台程序特性；自动化一律用 `-b` 后台模式在 PowerShell/终端里调用。
- **公司电脑限制执行**：便携版不需要管理员权限；若被杀软拦截，将目录加入白名单。
- **中文/空格路径**：所有路径加引号；Blender 对非 ASCII 路径兼容性良好，但输出路径建议纯英文以减少第三方工具链问题。
