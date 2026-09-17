# 故障排查速查表

> 按报错/症状索引。每条给出原因与解法。

## 1. 脚本与上下文

### `RuntimeError: context is None` / `poll() failed` / `context is incorrect`
- 原因：算子依赖 UI 上下文（活动对象、编辑器区域），后台模式没有。
- 解法优先级：
  1. 改用数据 API（`bpy.data.*`、直接改属性）。
  2. 补上下文：对象 `link` 到场景 → `bpy.context.view_layer.objects.active = obj` → `obj.select_set(True)` → `bpy.context.view_layer.update()` 再调算子。
  3. 最后手段：上下文覆盖 `with bpy.context.temp_override(active_object=obj, selected_objects=[obj]): bpy.ops.xxx()`（4.x+ 推荐写法，取代旧的 dict override）。

### 脚本崩了但外层流程显示"成功"
- 没加 `--python-exit-code 1`，或把它写在了 `--` 后面。Python 异常默认不传导到进程退出码；`--` 之后的参数只给脚本，Blender 不会再解析。

### `Unknown argument: --foo`
- 自定义参数必须放在 `--` 之后；脚本里用 `sys.argv.index("--")` 截取。

### argparse 把 Blender 自己的参数吃了
- `parse_args()` 传入了完整 `sys.argv`（含 blender 参数）。必须用 `--` 之后的切片。

## 2. 渲染类

### EEVEE 报 `GPUDevice: No GPU found` / 渲染全黑或秒退
- 无头服务器/虚拟机无 GPU：EEVEE 是光栅化引擎必须 GPU。换 `CYCLES`（CPU 可用）或 `BLENDER_WORKBENCH`（部分环境也需 OpenGL，同样可能失败——纯 CPU 服务器只有 Cycles 稳）。

### Cycles GPU 渲染没走 GPU
- 偏好里没启用后端：见 portable-setup.md 第 5 节。脚本侧设置 `scene.cycles.device = "GPU"` 不够，必须先启用 CUDA/OptiX 设备。
- 驱动太旧：更新 NVIDIA/AMD 驱动。

### `TypeError: enum "BLENDER_EEVEE_NEXT" not found in ('BLENDER_EEVEE', 'CYCLES', ...)`
- 版本标识符不匹配：5.x 用 `BLENDER_EEVEE`，4.2–4.5 用 `BLENDER_EEVEE_NEXT`。用 rendering.md 第 1 节的 `set_engine()` 兼容写法。

### 渲染结果是纯黑
排查顺序：
1. 场景里有没有灯？世界背景强度是不是 0？（EEVEE 默认世界是黑的）
2. 相机是不是对着场景？`scene.camera` 是不是 None（报 `No camera in scene`）？
3. 材质是不是全金属度+无环境反射（纯黑金属）？加个世界环境或 Area 灯。
4. `film_transparent=True` 时查看器背景是透明格子，别误判为黑——保存 PNG 看 alpha。

### 输出路径没生效 / 文件渲到了别处
- `-o` 写在了 `-f`/`-a` 之后（参数顺序问题）。
- `//` 前缀相对的是 blend 文件所在目录，不是当前工作目录。脚本里用 `bpy.path.abspath("//...")` 打出来确认。

### PNG 序列帧号对不上
- `-o` 里 `####` 的数量决定补零位数；`-x 0` 时不自动加扩展名。ffmpeg 合成时 `-start_number` 要匹配起始帧。

## 3. 导入导出类

### `AttributeError: ... has no attribute 'obj_import'`
- 版本 < 4.0 用旧算子 `bpy.ops.import_scene.obj`。用 `hasattr` 分支。

### FBX 导入后模型倒了/躺了
- 轴向约定问题：`forward_axis`/`up_axis` 参数调整（OBJ），或导入后 `transform_apply(rotation=True)`。

### 导入后尺寸差 100 倍
- 厘米/米单位问题。OBJ 导入用 `global_scale=0.01` 或导入后缩放再 apply。FBX 检查 `global_scale` 与源软件单位设置。

### 导出的 GLB 贴图丢失
- `export_format="GLB"` 才会内嵌贴图；`GLTF_SEPARATE` 需要把纹理文件一起分发。
- 贴图节点必须最终连进 Principled BSDF，游离节点不导出。

## 4. 环境/系统类

### 双击 blender.exe 一闪而过
- 正常现象，它是控制台程序。在 PowerShell/终端里带参数调用。

### PowerShell 里 `&` 报错
- `& "路径\blender.exe" -b ...`：`&` 是 PowerShell 的调用运算符；cmd.exe 里直接写带引号的路径。

### 中文路径/文件名渲染失败
- Blender 自身支持 UTF-8 路径，但部分外部库/旧插件不行。自动化管线一律用纯英文路径最稳。

### `msvcp140.dll 缺失` 等 DLL 错误
- 安装 Visual C++ Redistributable；或确认 zip 解压完整（杀软可能隔离了 dll）。

### 沙箱/CI 里 `libGL.so` / `libX11` 缺失（Linux）
- `apt install libgl1 libx11-6 libxi6 libxrender1 libxkbcommon0 libsm6`；无 GL 环境用 Cycles CPU 渲染。

## 5. 性能与内存

### 渲染内存爆炸被杀（OOM）
- `scene.render.use_simplify = True` 并限制细分级数。
- 大图分批：降低 `resolution_percentage` 验证后再渲全尺寸。
- Cycles 贴图换用缩略图或 mip 化纹理；`bpy.data.orphans_purge()` 清孤儿数据。

### 动画越渲越慢
- 几何节点/模拟没缓存：先 bake。
- 开 `scene.render.use_persistent_data = True`（帧间复用场景数据）。

## 6. 版本迁移（4.x → 5.x）速查

| 变化点 | 4.x | 5.x |
|---|---|---|
| EEVEE 引擎 ID | `BLENDER_EEVEE_NEXT` | `BLENDER_EEVEE` |
| Principled 输入名 | `Coat Weight`/`Emission Color`（4.x 后期） | 同名沿用；旧名 `Clearcoat`/`Emission` 已移除 |
| EEVEE Bloom | 已移除（用合成器 Glare） | 同左 |
| 动画 | action/fcurve | 新增 layered slots，`keyframe_insert` 仍兼容 |
| 扩展 | Extensions 体系 | 同左，部分插件 API 有调整 |

排查兼容性问题的万能起手式：

```python
import bpy
print(bpy.app.version_string)                     # "5.2.2"
print(bpy.app.version)                            # (5, 2, 2)
# 查某枚举的有效值：
print([i.identifier for i in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items])
```
