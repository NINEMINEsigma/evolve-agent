# Technical Notes

本文件补充 `SKILL.md` 中未展开的实现细节与排查方法。

## 运行链路

```
index.html
  ├── 加载 assets/libs/live2dcubismcore.min.js   (Live2D Cubism Core)
  ├── 加载 assets/libs/pixi.min.js               (PixiJS，挂到 window.PIXI)
  ├── 加载 assets/libs/cubism4.min.js            (挂到 PIXI.live2d)
  └── 内联脚本
        ├── 读 CONFIG（由部署脚本注入）
        ├── 创建 PIXI.Application（transparent / backgroundAlpha: 0）
        ├── PIXI.live2d.Live2DModel.from(modelUrl, { autoInteract: false })
        ├── 定位与缩放（按 baseWidth/baseHeight 与画布比例）
        ├── 定时器 A：随机挑一个动作 → motion(group, index, 3)
        └── 定时器 B：随机挑一个表情 → expression(index)
```

待机动作（Idle 组）由 `pixi-live2d-display` 自动循环播放，不需要自行调度；呼吸、眨眼、头发与衣物物理也由模型自带的 `physics3.json` / `pose3.json` 驱动，属于自动行为。

## 为什么非待机动作要关 Loop

样例模型的 `.motion3.json` 里 `Meta.Loop` 普遍为 `true`。若随机动作保持循环：

- 该动作会一直重复，模型被永久占据，看起来像卡死
- 后续 `motion()` 调用虽然能打断，但视觉上不自然
- 动作的起止姿势差异被抹掉，看不出「做了一件事又回到待机」的节奏

因此随机动作池里的动作文件统一改为 `"Loop": false`，让每次随机动作播放一次后自然回到 Idle 循环。

## 为什么优先级用 3

`model.motion(group, index, priority)` 的 `priority` 决定能否打断当前动作：

| 优先级 | 行为 |
|:------:|:-----|
| 0–1 | 不打断正在播放的动作 |
| 2 | 可打断低优先级动作 |
| 3 | 强制打断，保证随机调度立即生效 |

随机调度使用 3，确保每到一个随机间隔点，动作一定会切换。

## 为什么禁止交互

Stage 层由宿主统一设置 `pointer-events: none`，页面内若再绑定鼠标事件，事件根本收不到。同时 `Live2DModel.from(..., { autoInteract: false })` 与 `model.eventMode = 'none'` 会阻止 pixi 注册指针交互逻辑，避免无意义的开销和潜在报错。

如果将来需要交互（点击触发动作），应改用 Session Site 或聊天内嵌 HTML，而不是 Stage。

## 背景层

背景层是可选的，由 `--background` 参数启用：

```html
<img id="stage-bg" alt="" />
<canvas id="live2d-stage"></canvas>
```

```css
#stage-bg {
  position: fixed;
  inset: 0;
  width: 100%;
  height: 100%;
  display: none;
  object-fit: cover;
  pointer-events: none;
  user-select: none;
}
#stage-bg[src] { display: block; }
```

要点：

- `<img>` 必须排在 canvas **之前**，DOM 顺序决定层级，否则背景会盖住角色
- 没有 `src` 属性时 `#stage-bg[src]` 不匹配，元素自动隐藏——不加背景时行为与纯透明版本完全一致
- `object-fit: cover` 让不同比例的背景图都铺满且不变形
- 背景图由脚本复制到 `<stage>/assets/backgrounds/`，保持资源本地化

Stage 层位于聊天气泡之下，所以背景图不会遮住气泡文字，但会替换聊天区原有背景。花哨或高对比的图会干扰阅读，默认不加；用户明确要求时才加，并在交付时说明如何换图或去掉。

如需降低背景对阅读的干扰，可在 `#stage-bg` 之上再叠一层半透明遮罩（例如 `background: rgba(0, 0, 0, .45)`），但那会同时压暗背景与角色，需权衡。

## 加载期闪烁与淡入

Stage 的 iframe 每次打开都会从零加载：3 个渲染库 + moc3 + 贴图 + 动作/表情，总体积可达 10 MB 量级（一个 4096 贴图就可能占 7–8 MB）。加载期间画面是空的，完成后模型"突然出现"，观感上像是一次闪烁。

缓解手段是在 CSS 里给背景层和 canvas 加透明度过渡，元素就绪后再打标记：

```css
#stage-bg { opacity: 0; transition: opacity .45s ease; }
#stage-bg[data-loaded="true"] { opacity: 1; }
#live2d-stage { opacity: 0; transition: opacity .5s ease; }
#live2d-stage[data-ready="true"] { opacity: 1; }
```

- 背景图在 `load` 事件后设 `data-loaded`
- 模型在 `Live2DModel.from()` resolve 后设 `data-ready`

这只是让"出现"变柔和，**不减少加载时间**。

加载时间的大头是贴图解码与纹理上传。如果部署环境的静态文件路由禁用了浏览器缓存（响应头带 `no-store`），每次打开都要重新下载全部资源，闪烁会明显得多。排查顺序：

1. 确认静态资源响应头。`no-store` 表示完全禁缓存，`no-cache` 只表示必须验证（配合 ETag 时未变更会返回 304）。
2. 若确认是 `no-store` 且无法修改服务端，考虑降低贴图分辨率或换用更小的模型。
3. 检查是否存在**第二个**渲染同一模型的页面（例如聊天消息里内嵌的预览 iframe），重复实例会争抢 GPU 并加剧闪烁。

## 尺寸与定位计算

```js
const isNarrow = width < layout.narrowBreakpoint;
const widthRatio  = isNarrow ? layout.mobileWidthRatio  : layout.desktopWidthRatio;
const heightRatio = isNarrow ? layout.mobileHeightRatio : layout.desktopHeightRatio;
const scale = Math.min((width * widthRatio) / baseWidth, (height * heightRatio) / baseHeight);
model.scale.set(scale);
model.position.set(width * (isNarrow ? layout.mobileX : layout.desktopX), height * layout.bottomY);
```

要点：

- 用 `Math.min` 同时满足宽高预算，保证模型不会被裁切
- `anchor.set(0.5, 1)` 把原点定在模型底部中心，便于贴住画布下沿
- `bottomY` 略大于 1（如 1.015）让底部略微下沉，避免视觉上「漂浮」
- 窗口尺寸变化时重新计算，不要只在启动时算一次

## 性能与生命周期

- `resolution` 上限设为 2，避免高分屏上像素数翻倍导致 GPU 压力
- `autoDensity: true` 让 canvas 的 CSS 尺寸与渲染分辨率解耦
- `document.hidden` 时 `app.stop()` 并让定时器延后重试；恢复可见时 `app.start()` 并重新排期，避免后台标签页持续渲染
- `beforeunload` 时清理定时器，防止回调在销毁后执行

## 排查表

| 现象 | 可能原因 | 处理 |
|:-----|:---------|:-----|
| 页面全空且无提示 | 三个渲染库 404，或加载顺序错误 | 检查 `assets/libs/` 文件是否存在；确认顺序为 core → pixi → cubism4 |
| 右上角红色错误条 | 模型加载失败 | 读错误文本，多数是 `modelUrl` 写错或 `.moc3` 缺失 |
| `PIXI.live2d is undefined` | `cubism4.min.js` 未加载或版本不匹配 | 确认 `cubism4.min.js` 存在，且 `pixi.min.js` 是 6.x |
| 模型显示但完全静止 | 缺少 Idle 动作组，或 `Groups.EyeBlink` 参数 ID 与模型不符 | 检查 `model3.json` 的 `Motions` 与 `Groups` |
| 动作播放一次后停住 | 动作仍是 `"Loop": true`，或 `duration` 与实际时长差距过大 | 改为 `false`；重新核对 `Meta.Duration` |
| 动作切换过于频繁/稀疏 | `motionPause` 不合适 | 长动作（>7s）用 4500–10500ms，短动作（~1.3s）用 3000–7500ms |
| 模型过大、超出画布 | `layout` 比例过大 | 降低 `desktopHeightRatio` |
| 脚部悬空 | `bottomY` 偏小 | 增大到 1.01–1.03 |
| 手机竖屏被裁切 | 未走窄屏分支或比例过大 | 检查 `narrowBreakpoint` 与 `mobile*` 参数 |
| 表情不切换 | `expressionCount` 为 0 或与模型不符 | 核对 `model3.json` 的 `Expressions` 数量 |
| 背景遮挡聊天 | 某处设置了不透明底色 | 确认 `html` / `body` / canvas 均透明，`backgroundAlpha: 0` |

## 部署脚本行为

`scripts/install_live2d_stage.py`：

| 参数 | 说明 |
|:-----|:-----|
| `--list-models` | 列出配置中的模型与已安装的资产目录 |
| `--model` | 模型名，对应 `templates/models/<name>.json` |
| `--stage-dir` | 目标 stage 目录绝对路径（必须绝对，防止误写到当前目录） |
| `--background` | 可选。内置背景 id/label（如 `room-interior`、`房间室内`）或图片绝对路径 |
| `--list-backgrounds` | 列出 `templates/backgrounds.json` 中的内置背景模板 |
| `--force` | 覆盖已存在的 `index.html` 与资产文件 |
| `--dry-run` | 只打印计划，不写任何文件 |

默认拒绝覆盖已存在的 `index.html` 并返回退出码 3。脚本只用标准库，可在任意 Python 3 环境运行。

渲染时会把 `templates/models/<name>.json` 序列化为 `const CONFIG = {...};` 注入模板的 `/*__STAGE_CONFIG__*/` 位置，并替换标题、aria 标签与版权提示文本。

## 验证清单

部署后按顺序检查：

1. `<stage>/index.html` 存在，且包含 `const CONFIG =`
2. `<stage>/assets/libs/` 含三个 `.js`
3. `<stage>/assets/models/<model>/` 含 `.moc3`、`.model3.json`、贴图目录、动作目录
4. `<stage>/assets/LICENSE-Live2D.md` 存在
5. 页面底部版权提示可见
6. 需要浏览器验证时：`document.documentElement.dataset.stageStatus === 'ready'`，且无红色错误条
