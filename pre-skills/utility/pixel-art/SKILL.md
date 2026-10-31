---
name: pixel-art
description: 将现有图片转换为块状像素风格：中心映射降采样、最近邻放大、可选中位切分限色、输出小尺寸画稿。当需要把照片、插画、角色图转换为像素化、马赛克块效果或复古游戏风格素材时使用；不用于从零绘制像素画。
category: utility
tags: [image, pixel-art, pixelate, pillow, numpy]
compatibility: Python 3，Pillow，NumPy；支持 Windows PowerShell 与 Evolve Agent 逻辑命名空间。
version: 1.0.1
---

# 图片像素风格化（Pixel Art）

## 能力与边界

将已有静态图片降采样为小图，再用最近邻放大到原尺寸，得到边界锐利的像素块；也可直接输出小图或限制 RGB 颜色数量。

这是确定性图像变换，不是生成式重绘，不会自动修复轮廓或重新设计角色。原图尺寸不能被小图参数放大；尺寸不是小图尺寸整数倍时，各像素块宽高可能相差一个像素。没有随附参考样例，不声称已经与外部样例逐像素比对。

## 文件与依赖

- 主脚本：本技能目录下 `scripts/pixelate.py`。
- 依赖：Pillow、NumPy。先检查，缺失时获得安装许可后通过当前解释器安装，不随意升级现有包。
- 通过 `RecallSkill(name="pixel-art")` 获取实际 `skill_dir`；不要假设当前工作目录或使用其他平台的 `KIMI_SKILL_DIR`。

加载 shell 工具集，复用现有 Shell；新建时保存 `shell_id`、`namespace_env` 和输出偏移量。使用工具返回的 `EVOLVE_PYTHON` 和命名空间环境变量，不在命令中直接传入 `ws:` 或 `skills:`。

PowerShell 依赖检查及缺失时的安装命令：

```powershell
& $env:EVOLVE_PYTHON -c "import PIL, numpy; print(PIL.__version__, numpy.__version__)"
# 仅在缺少依赖且已获许可时执行：
& $env:EVOLVE_PYTHON -m pip install pillow numpy
```

## 执行流程

1. 确认输入图片、输出位置和需要的粒度。粒度不确定时，先取得使用默认 `-s 8` 试样的许可；不自动迭代生成。
2. 使用 `Write` 创建输出目录；优先输出 PNG。为每次任务选择不冲突的新文件名，避免覆盖源图或既有结果。
3. 校验 `--block >= 1`、`--small` 宽高均为正整数、`--palette` 在 2..256。小图尺寸超过源图时会被裁限到源图尺寸，完成日志显示实际尺寸。
4. 调用脚本，检查退出码、完成日志和输出是否存在。遇到异常如实说明，不宣称成功。
5. 直接用 Markdown 图片向用户展示，并等待用户判断。不用模型读图代替用户评价，也不自动开始下一轮。

当前安装位置下的 PowerShell 示例（新建 Shell 时需核对返回的环境变量引用）：

```powershell
& $env:EVOLVE_PYTHON "$env:EVOLVE_SKILLS\utility\pixel-art\scripts\pixelate.py" "$env:EVOLVE_WS\uploads\input.png" -o "$env:EVOLVE_WS\output\pixel-art\result.png" -s 8
```

若技能目录移动，以实际 `skill_dir` 更新脚本路径。输入、输出路径都加引号，以支持空格和中文。

展示位置示例：`![像素化结果](/files/ws/output/pixel-art/result.png)`。`ws:` 仅用于文件工具，不能放进图片 URL。

## 参数

| 选项 | 说明 | 默认 |
| --- | --- | --- |
| 输入位置参数 | 本地输入图片路径 | 必填 |
| `-s, --block N` | 目标像素块的大致边长，越大越粗；实际大小由源尺寸与取整决定 | `8` |
| `--small WxH` | 小图尺寸，支持 `x` 或 `X`，优先于 block 的尺寸计算 | 按 block 计算 |
| `--small-only` | 仅输出降采样后的小图 | 关闭 |
| `--palette N` | 中位切分限制为至多 N 种 RGB 颜色，保留采样后的 alpha | 关闭 |
| `-o, --output` | 明确输出路径，父目录须先存在 | 源文件同目录的 `.pixel.png`，small-only 时为 `.small.png` |

示例选项：`-s 16` 为更粗像素，`--small 64x64 --small-only` 为小图画稿，`-s 8 --palette 32` 为限色像素化。改变长宽比的小图参数可能产生矩形像素块。

## 透明度与已知限制

- 保留常规 RGBA、灰度带 alpha，以及通过 PNG `transparency` 元数据表示的透明度，包括 P 模式调色板 PNG。
- 限色只限制 RGB 色数；alpha 不量化，因此 RGBA 颜色元组总数可能超过 N。
- 保留原始中位切分调用及其抖动参数，但当前 Pillow 自动生成调色板路径的测试未观察到抖动差异，不保证 Floyd–Steinberg 效果。
- 只处理输入文件当前帧，不保留动画、EXIF、ICC 等元数据，不自动应用 EXIF 旋转；需要这些能力时先确认后续方案。
- 输出格式由扩展名决定，带透明度时优先 PNG；RGBA 不能直接保存为 JPEG。
- 不自动创建输出父目录；损坏图片、不支持的编码、无效输出位置等可能产生 Pillow 异常。

## 采样原理

默认小图宽高分别为 `max(1, round(源尺寸 / block))`，使用 Python 的 round。降采样将目标像素中心映射回源图后向零取整采样，不做平均或平滑；放大使用最近邻索引。因此正常 RGB/RGBA 输入的采样与限色算法保持上传版本行为不变。
