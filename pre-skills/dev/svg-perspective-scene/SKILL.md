---
name: svg-perspective-scene
description: 在手写 SVG 中构建几何正确的透视场景（单点/两点透视的房间、街道、室内），并用浏览器截图 + DOM 诊断 + 自动点击回归组成的循环进行验证。当任务涉及手绘 SVG 室内/空间场景、透视错误修正（门浮在房间中央、窗户与墙不平行、物体漂浮、纵深边不收束）、SVG 交互场景（点选解谜、房间探索类游戏）的构建或重构，以及需要对纯前端页面做浏览器截图目检和自动回归测试时使用。典型触发语："SVG 房间透视不对"、"画一个可以点的房间"、"这个空间看起来是假的"、"帮我验证这个网页游戏的流程"。
category: utility
tags: ["svg", "perspective", "geometry", "browser-screenshot", "testing", "visual-design"]
---

# SVG 透视场景构建与验证

目标：手绘 SVG 场景做到**几何自洽**（所有纵深线共享灭点、物件贴墙落地），并用**可重复的自动化验证**替代"肉眼看上去差不多"。

## 核心原则：先定投影系统，再画任何物件

透视错误的根源几乎总是同一件事——墙体用了一套投影（如向中心汇聚的假透视），物件却用另一套（平贴正面图）。**墙体和物件必须共享同一个灭点**，否则必然出现"门浮在房间中央"、"窗户与墙不平行"。

工作流程：

1. 定灭点与进深参数 → 2. 按公式推出房间五个面 → 3. 按物件与墙面的关系选画法 → 4. 浏览器截图目检（**无视觉能力时改为展示截图给用户目检**）→ 5. DOM/回归验证 → 6. 逐项对照失败模式清单。

## 第一步：几何构建（公式速查）

完整推导与坐标配方见 [references/perspective-math.md](references/perspective-math.md)。核心公式两条：

**后墙（与画面平行的矩形）**：给定画布四角、灭点 VP=(vx,vy) 与进深 d（0~1，越大房间越深）：

```
后墙角点 = 画布角点 + d × (VP − 画布角点)
```

四个角点算出来天然构成矩形（顶边、底边水平，侧边竖直），门窗挂在上面就是标准矩形——**直接根治"窗户与墙不平行"**。

**任意纵深边**：从点 P 向灭点收束比例 s（0~0.35 为宜）：

```
P' = P + s × (VP − P)
```

柜体、桌体、窗台的深度边、踢脚线、地板缝、檐口线全部由这条公式生成，天然全部指向同一灭点。

## 第二步：按物件与墙面的关系选画法

| 物件位置 | 画法 |
|---|---|
| 后墙上（门、窗、挂钟） | 标准矩形/正圆，零变形；底部对齐墙脚线 |
| 侧墙上（挂画、壁柜） | 竖边保持竖直；顶边/底边必须是**过 VP 的直线段**；墙上文字按该处纵深线倾角 `rotate(atan((y−vy)/(x−vx)))` |
| 落地靠墙（柜子） | 三点盒体：正面矩形 + 顶面/侧面（深度边用公式收束 s≈0.15~0.2），底部画排线接地阴影 |
| 房间中央（桌子、地毯） | 桌面平行四边形（后角收束 s≈0.25~0.3），腿竖直，脚部落椭圆阴影；地毯用扁椭圆（地板上圆的透视） |
| 天花板上（吊灯） | 放在画面中轴线上则零透视问题，竖直下垂即可 |

绘制顺序 = 空间从远到近：墙 → 地板 → 地毯 → 家具 → 家具上的物件。后画的腿压先画的地毯 = 腿站在地毯上，遮挡关系免费得到。

## 第三步：失败模式清单（目检时逐项对照）

- 物件平贴、与所在墙面投影不一致（最常见，门浮在房间中央即此类）
- 纵深边不收束到灭点（侧墙上的画四边斜率随手画）
- 物体漂浮：底部与墙面/地板之间没有接触线或接触阴影
- 剪裁溢出：窗外景物（灯塔、光束）超出窗框 clipPath 被切掉半个
- 绘制顺序错误导致遮挡反了（远处的腿盖住近处的地毯）
- 描边粗细无层级：外轮廓应最粗（3.4~4），结构线次之（2.5~3），细节最细（1.5~2）

## 第四步：验证循环（三层，逐层收紧）

> 截图与诊断改用**内置浏览器工具集**（`browser_*`）替代无头 chromium 命令行。浏览器按**真实时间**运行（无 `--virtual-time-budget` 快进），CSS transition 会真实播放——这对终态验证是利好，但长动画需留足等待时间。

### 层 1：浏览器截图目检

> ⚠️ **前置：视觉能力自检（必须）**。截图目检依赖 `Read` 的图片分支，前提是当前模型具备视觉能力。
> 开始前先 `probe_modality_capability` 确认：
> - `vision_capable=true` → 可继续走下方自主目检流程；
> - `vision_capable=false` → **跳过步骤 6–7 的自主读图**，截图后直接把 `saved_to` 路径展示给用户，请用户亲自判断（重点看：墙线收束、物件落地、遮挡、剪裁），等用户反馈后再继续层 2/层 3。

1. 首次使用：`browser_launch` 启动带调试端口的 Edge → `browser_connect` 接管（后续同一会话复用连接）。
2. 打开页面：`browser_open_tab(url="file:///<HTML 绝对路径>")`。若 file:// 被拒或相对资源失效，改用本地静态服务器托管：`start_background_service(command=["python","-m","http.server","8765"], cwd="ws:output")`，再 `browser_open_tab(url="http://localhost:8765/index.html")`。
3. `browser_list_tabs` 取新标签页下标 `idx`。
4. 等动画/定时器沉淀：`browser_wait(tab=idx, timeout_ms=4000)`（真实等待，非虚拟快进）。
5. `browser_screenshot(tab=idx, full_page=true)` → 截图存到 `ws:logs/browser_screenshots/{uuid}.png`（返回 `saved_to`）。
6. （仅 `vision_capable=true`）`Read` 该 `saved_to` 路径（image 分支）**亲自看图**，重点看：墙线收束、物件落地、遮挡、剪裁。
7. （仅 `vision_capable=true`）局部放大复查：`run_python` 调 [scripts/shot.py](scripts/shot.py) 对 `saved_to` 路径按相对坐标裁剪。

### 层 2：DOM 状态诊断（验证动画/状态机的终态）

CSS transition 在真实浏览器里会正常播放，截图能反映真实终态。但状态机终态仍建议用注入脚本读 DOM 验证：

- 把诊断 `<script>`（收集全局 error + 末尾把结果写进 `document.title`）注入 HTML 副本，写入 `ws:output`。
- `browser_open_tab` 打开 → `browser_wait(tab=idx, timeout_ms=<诊断时刻>)` → `browser_query(tab=idx, selector="title")` 读 title 文本作为回传通道。
- 或直接 `browser_query` 用选择器定位元素，读其 text/属性验证状态。

把诊断结果写进 `document.title` 是最省事的回传通道（注入示例见原脚本注释）。

### 层 3：自动点击回归（交互链路全通）

按复杂度两条路径：

**A. 简单链路**：直接用浏览器工具——`browser_query` 定位元素 → `browser_click` 按真实用户路径依次点击（含模态框按钮）→ `browser_wait` 留余量 → `browser_query` 读终态/查 error。

**B. 复杂时序链路**：保留 click-driver 注入——用 [scripts/playthrough_test.py](scripts/playthrough_test.py)（已改为注入器）生成带 driver 的 HTML 副本（`dispatchEvent(new MouseEvent('click',{bubbles:true}))` 按时刻表触发），`browser_open_tab` 打开 → `browser_wait` 等到 report 时刻 → `browser_query(selector="title")` 读结果。链路里任何一步断了（选择器失效、状态前提不满足），报告里立即可见。无 error 且链路全 OK 即通过。

注意时序：被测页面若用 setTimeout 串联剧情，driver 的点击时刻表要留出余量；末尾诊断时刻要晚于最后一个状态变更。

## 交付前检查单

- [ ] 所有纵深边延长后过同一灭点（抽 3 条心算验证）
- [ ] 每个物体底部有接触线或阴影，无漂浮
- [ ] 浏览器截图目检通过（含局部裁剪放大）——**无视觉能力（vision_capable=false）时由用户目检，不得自称通过**
- [ ] DOM 诊断无 JS error，终态样式正确
- [ ] 自动回归链路全 OK
- [ ] 深/浅两套主题各截一张图确认
