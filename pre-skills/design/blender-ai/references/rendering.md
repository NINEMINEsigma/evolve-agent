# 渲染详解：引擎、质量、输出、色彩

> 渲染是命令行自动化最常见的目的。本文覆盖三大引擎的选择与调参、输出设置、色彩管理、以及渲染脚本的写法。

## 1. 引擎选择与标识符

| 引擎 | `render.engine` / `-E` 值 | 特点 |
|---|---|---|
| EEVEE（5.x） | `BLENDER_EEVEE` | 实时光栅化，快，适合预览与风格化；无显卡的服务器上**不可用** |
| EEVEE Next（4.2–4.5） | `BLENDER_EEVEE_NEXT` | 同上，注意标识符与 5.x 不同 |
| Cycles | `CYCLES` | 路径追踪，物理准确，慢；CPU 可用，是**无头服务器唯一稳妥的高质量选择** |
| Workbench | `BLENDER_WORKBENCH` | 线框/实体预览级，极快，适合"看看模型对不对" |

**跨版本兼容写法（直接抄）：**

```python
def set_engine(scene, want="EEVEE"):
    want = want.upper()
    if want == "EEVEE":
        candidates = ["BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"]  # 5.x 在前，4.x 在后
    elif want == "CYCLES":
        candidates = ["CYCLES"]
    else:
        candidates = ["BLENDER_WORKBENCH"]
    items = {i.identifier for i in scene.bl_rna.properties["render"].fixed_type.properties["engine"].enum_items} if False else None
    for c in candidates:
        try:
            scene.render.engine = c
            return c
        except TypeError:
            continue
    raise RuntimeError(f"没有可用引擎: {want}")
```

（赋值失败时 Blender 抛 `TypeError: enum "XXX" not found in (...)`，try/except 即可探活。）

## 2. EEVEE 质量设置（5.x）

```python
scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
# 采样（5.x 属性在 scene.eevee 下；taa 系列已随 EEVEE Next 重构）
scene.eevee.taa_samples = 64                    # 若报 AttributeError 说明版本差异，用 try/except 包住
# 光线追踪（EEVEE Next/5.x 支持屏幕空间 RT）
try:
    scene.eevee.use_raytracing = True
except AttributeError:
    pass
```

EEVEE 注意事项：
- 无 GPU/虚拟显存环境会失败：`GPUDevice: No GPU found` → 换 Cycles CPU。
- 辉光（Bloom）在 4.2+ 移到了合成器（Glare 节点），EEVEE 里不再有这个面板。

## 3. Cycles 质量设置

```python
scene.render.engine = "CYCLES"
cy = scene.cycles
cy.samples = 256                    # 渲染采样数；预览 32，成片 256-2048
cy.use_denoising = True             # 降噪（默认开）
cy.device = "CPU"                   # 或 "GPU"（需在偏好里启用 GPU 后端，见 portable-setup.md 第 5 节）
cy.max_bounces = 8
cy.use_adaptive_sampling = True     # 自适应采样，省时间
cy.adaptive_threshold = 0.01
```

GPU 渲染的脚本侧设置（前提：偏好里已启用对应后端）：

```python
prefs = bpy.context.preferences.addons["cycles"].preferences
prefs.compute_device_type = "OPTIX"
prefs.get_devices()  # 刷新设备列表
for d in prefs.devices:
    d.use = True
scene.cycles.device = "GPU"
```

## 4. 输出设置

```python
r = scene.render
r.resolution_x, r.resolution_y = 1920, 1080
r.resolution_percentage = 100
r.filepath = "//out/frame_####"           # // = 相对 blend 文件；# 数 = 帧号位数
r.image_settings.file_format = "PNG"      # PNG/JPEG/OPEN_EXR/TIFF/BMP/WEBP
r.image_settings.color_mode = "RGBA"      # 要透明背景必须 RGBA
r.image_settings.color_depth = "8"        # PNG 支持 8/16
r.image_settings.compression = 15         # PNG 压缩率(慢而小) 0-100
r.film_transparent = True                 # 透明背景

# 高质量中间产物用 EXR（保留线性 HDR 与所有通道）：
r.image_settings.file_format = "OPEN_EXR"
r.image_settings.color_depth = "16"       # 16/32
r.image_settings.exr_codec = "DWAA"       # 有损但很小；无损用 "ZIP"
```

视频直出（不推荐用于长动画，见 command-line.md 的说明）：

```python
r.image_settings.file_format = "FFMPEG"
r.ffmpeg.format = "MPEG4"
r.ffmpeg.codec = "H264"
r.ffmpeg.constant_rate_factor = "HIGH"
r.ffmpeg.audio_codec = "AAC"
```

## 5. 色彩管理

```python
v = scene.view_settings
v.view_transform = "AgX"        # 4.0+ 默认；旧版 "Filmic"。高亮不过曝的关键
v.look = "AgX - Medium High Contrast"   # 无效值会抛 TypeError，先 print 枚举
v.exposure = 0.0
v.gamma = 1.0
```

查看当前版本可用的 look 值：

```python
print([i.name for i in scene.view_settings.bl_rna.properties["look"].enum_items])
```

图片纹理的色彩空间：albedo/自发光用 `sRGB`（默认），法线/粗糙度/置换等数据贴图必须：

```python
img.colorspace_settings.name = "Non-Color"
```

## 6. 多通道渲染（合成用）

```python
vl = bpy.context.scene.view_layers[0]
vl.use_pass_combined = True
vl.use_pass_z = True
vl.use_pass_normal = True
vl.use_pass_shadow = True
scene.render.image_settings.file_format = "OPEN_EXR_MULTILAYER"   # 多通道必须多层 EXR
bpy.ops.render.render(write_still=True)
```

## 7. 渲染执行方式

```python
# 脚本内渲静帧
scene.render.filepath = r"D:\out\still.png"
bpy.ops.render.render(write_still=True)

# 渲动画（等价于 -a）
bpy.ops.render.render(animation=True)

# 仅出 OpenGL 式快速预览（需要 UI，后台不可用 —— 勿用 render.opengl）
```

**渲染进度**：后台渲染时 Blender 会把 `Fra:1 ... Time:00:03.21` 打到 stdout，可正则解析做进度条。

## 8. 性能与稳定性清单

- 大分辨率先试 `resolution_percentage = 25` 验证灯光构图，再拉满。
- Cycles 长任务开 `use_persistent_data = True`（动画帧间复用 BVH）。
- 内存吃紧：减小贴图、开 `scene.render.use_simplify`、用 `bpy.data.orphans_purge()` 清孤儿数据。
- 多帧任务在脚本里逐帧 `bpy.ops.render.render(write_still=True)` 并自行跳过已存在文件（断点续渲），见 ../scripts/render_frames.py。
- 命令行 `-t 0` 让线程数自动；虚拟机里手动 `-t <核数>` 更稳。
