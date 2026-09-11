# Model Manifest

本文件记录本 skill 内置模型的动作、表情、许可信息，以及新增模型的操作步骤。

## mao_pro — Niziiro Mao (PRO Version)

| 项目 | 内容 |
|:-----|:-----|
| 模型目录 | `assets/models/mao_pro/` |
| 入口文件 | `runtime/mao_pro.model3.json` |
| 贴图 | `runtime/mao_pro.4096/texture_00.png`（单张 4096） |
| 物理 / 姿势 | `mao_pro.physics3.json` / `mao_pro.pose3.json` |
| 角色特征 | 正面朝向、面部活动范围大，适合 VTuber 用途；含 Blend Shapes、multiply color / screen color 示例 |
| 官方说明 | `assets/models/mao_pro/ReadMe.txt` |

### 动作

| 组名 | 序号 | 文件 | 原始时长 | 本 skill 中的 Loop |
|:-----|:----:|:-----|:--------:|:------------------:|
| `Idle` | 0 | `motions/mtn_01.motion3.json` | 5.57s | `true`（保持待机循环） |
| `""` | 0 | `motions/mtn_02.motion3.json` | 3.47s | `false` |
| `""` | 1 | `motions/mtn_03.motion3.json` | 4.40s | `false` |
| `""` | 2 | `motions/mtn_04.motion3.json` | 4.20s | `false` |
| `""` | 3 | `motions/special_01.motion3.json` | 7.80s | `false` |
| `""` | 4 | `motions/special_02.motion3.json` | 9.37s | `false` |
| `""` | 5 | `motions/special_03.motion3.json` | 9.23s | `false` |

> 注意组名是**空字符串**，因此调用形式为 `model.motion('', index, 3)`。`index` 是空字符串组内的序号，从 0 开始，顺序与 `model3.json` 中 `Motions[""]` 数组一致。

### 表情

`runtime/expressions/exp_01..exp_08.exp3.json`，共 8 个，索引 0–7。

`model_dict.json` 中的情绪映射（供参考，本 skill 不依赖情绪标签）：`neutral→0`、`anger→2`、`disgust→2`、`fear→1`、`joy→3`、`smirk→3`、`sadness→1`、`surprise→3`。

### 许可

Live2D 原创角色（Live2D Original Character）。一般用户与小规模事业者可商用；中大规模事业者仅限内部/监修用途。不得修改角色设计比例。

---

## shizuku — Shizuku (PRO Version)

| 项目 | 内容 |
|:-----|:-----|
| 模型目录 | `assets/models/shizuku/` |
| 入口文件 | `runtime/shizuku.model3.json` |
| 贴图 | `runtime/shizuku.1024/texture_00..04.png`（5 张 1024） |
| 物理 / 姿势 | `shizuku.physics3.json` / `shizuku.pose3.json` |
| 角色特征 | 源自《しずくの時間》，手部细节动作丰富；由 Cubism 2.1 数据转换为 Cubism 4 格式 |
| 官方说明 | `assets/models/shizuku/ReadMe.txt` |

### 动作

| 组名 | 序号 | 文件 | 原始时长 | 本 skill 中的 Loop |
|:-----|:----:|:-----|:--------:|:------------------:|
| `FlickUp` | 0 | `motion/01.motion3.json` | 1.27s | `false` |
| `Tap` | 0 | `motion/02.motion3.json` | 1.27s | `false` |
| `Flick3` | 0 | `motion/03.motion3.json` | 1.50s | `false` |
| `Idle` | 0 | `motion/04.motion3.json` | 1.57s | `true`（保持待机循环） |

> 组名是具名组，调用形式为 `model.motion('FlickUp', 0, 3)`。该模型 `HitAreas` 为空，没有点击热区，不影响自动调度。

### 表情

无 `Expressions` 字段，`expressionCount` 设为 `0`，模板会跳过表情调度。

### 许可

Live2D 原创角色。**必须直接使用，不得修改名称或设定。**

---

## 新增模型步骤

1. 把模型的 runtime 目录整体复制到 `assets/models/<new-name>/`，保留 `ReadMe.txt`（如有）。
2. 打开 `<new-name>.model3.json`，记录：
   - `FileReferences.Motions` 的每个组名与组内文件顺序
   - `FileReferences.Expressions` 的数量
   - `FileReferences.Moc`、`Textures` 的相对路径
3. 逐个打开动作文件，记录 `Meta.Duration`（秒）→ ×1000 得到毫秒时长。
4. 复制 `templates/models/mao_pro.json` 为 `templates/models/<new-name>.json`，修改：
   - `label`：出错提示显示名
   - `modelUrl`：`assets/models/<new-name>/runtime/<new-name>.model3.json`
   - `actions`：按步骤 2、3 的结果填写 `group` / `index` / `duration`
   - `expressionCount`：表情数量，没有则 `0`
   - `layout.*`：初次部署先用默认值，观察后再微调
5. 对**随机动作池中的每个动作文件**，把 `"Loop": true` 改为 `"Loop": false`。`Idle` 组保持 `true`。
6. 部署并检查：

   ```bash
   python <skill_dir>/scripts/install_live2d_stage.py --list-models
   python <skill_dir>/scripts/install_live2d_stage.py --model <new-name> --stage-dir "<stage>" --dry-run
   ```

7. 部署后确认页面无红色错误条，且动作按预期随机切换。

## 模型尺寸与布局调参

`layout` 的比例基于模型 `baseWidth` / `baseHeight`（由 `pixi-live2d-display` 加载后测得）计算，因此不同分辨率的模型都能自适应。常见调整：

| 现象 | 调整 |
|:-----|:-----|
| 模型整体偏小 | 提高 `desktopWidthRatio` / `desktopHeightRatio` |
| 模型超出画布顶部 | 降低 `desktopHeightRatio` |
| 脚部悬浮或穿出底部 | 调整 `bottomY`（>1 表示底部略微下沉） |
| 手机端被裁切 | 调整 `mobileWidthRatio` / `mobileHeightRatio` |
| 想放在左侧 | `desktopX` 改为 0.2 左右 |

## 资源来源与版本

| 资源 | 来源 | 许可 |
|:-----|:-----|:-----|
| `libs/pixi.min.js` | `pixi.js@6.5.10` | MIT |
| `libs/cubism4.min.js` | `pixi-live2d-display@0.4.0` | MIT |
| `libs/live2dcubismcore.min.js` | Live2D Cubism Core | Live2D 专有软件许可协议 |
| `models/mao_pro`、`models/shizuku` | Live2D 官方样例数据（经本地 Open-LLM-VTuber 项目分发） | Live2D 样例数据使用条款 |

`pixi-live2d-display` 需要全局 `PIXI` 先加载，再加载 `cubism4.min.js`，最后才是使用方脚本。三个脚本的顺序不能调整。
