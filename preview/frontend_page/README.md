# Evolve Agent 独立前端预览

本目录用于产品展示和官网截图。它直接复用 `../../origin_agent/frontend/src/main.tsx` 及其真实组件、样式、图标、中文文案、消息渲染器和 Monaco 编辑器，**不是另画的相似页面**。

HTTP、聊天 WebSocket 与服务端事件订阅均由浏览器内固定演示逻辑处理。无需 Python、Gateway、模型服务、真实 API Key 或运行时工作空间。所有演示业务数据只在内存中存在，刷新恢复初始数据。

## 用户自行启动

开发助手AI没有执行安装、类型检查、构建、启动或运行验收。以下命令需用户自行运行，并且只在本目录运行：

1. 进入 `D:\evolve-agent\preview\frontend_page`。
2. 执行 `pnpm.cmd install`（也可用 `npm.cmd install`）。
3. 执行 `pnpm.cmd dev`（或 `npm.cmd run dev`）。
4. 浏览器打开 `http://127.0.0.1:4178/`。

默认仅监听本机。端口固定且启用 strictPort；端口被占用会报错，不自动换端口，更不会终止其他程序。开发环境关闭 HMR，修改源码后手动刷新。

**请勿在 `origin_agent/frontend/` 安装依赖或构建。** 预览的依赖与输出仅保存在本目录的 `node_modules/`、`dist/`。

## 常用截图地址

| 展示内容 | 地址（附在站点域名之后） |
|---|---|
| 完整聊天 | `/?scene=showcase` |
| 空会话 | `/?scene=empty` |
| 多Agent协作 | `/?scene=multi` |
| 审批输入栏 | `/?scene=approval` |
| 多题提问 | `/?scene=question` |
| 归档会话 | `/?scene=archived` |
| 会话视觉定制 | `/?scene=visual` |
| 初始引导 | `/?scene=onboarding` |
| 活动大盘 | `/?scene=showcase&tab=activity` |
| 资源/任务 | `/?scene=showcase&tab=resources` |
| 文件修改 | `/?scene=showcase&tab=changes` |
| 媒体输入 | `/?scene=showcase&tab=media` |
| 会话变量 | `/?scene=showcase&tab=variables` |
| 子会话 | `/?scene=showcase&tab=subagents` |
| 角色档案 | `/?scene=showcase&tab=characters` |
| 会话网页 | `/?scene=showcase&tab=site` |
| 模型配置（三个分页） | `/?scene=showcase&tab=llm` |
| 动态沙盒空间 | `/?scene=showcase&tab=sandbox` |
| 独立文件编辑器 | `/agentspace/` |
| 显示截图辅助面板 | `/?scene=showcase&controls=1` |

空会话没有媒体、变量、子会话或网页时，相应 Tab 按正式能力规则禁用。请求进入禁用 Tab 会明确报错，不伪造内容或绕过正式组件。

`session` 可指定预设演示 ID，例如 `/?scene=showcase&session=preview-main`。新建/合并产生的临时会话只存在于当前标签页，不能在新标签页恢复；会显示说明。预设会话的新标签页会继承场景，但不会同步另一个标签页的临时编辑。

## 截图方法

默认页面不显示预览面板、常驻横幅或水印，保持正式 UI。故障发生时例外显示独立错误区域，避免误把断开的界面当作完成品。

建议固定 Chrome/Edge 版本、操作系统字体、100%浏览器缩放和设备像素比。桌面可采用 1920×1080 或1440×900，移动端可采用390×844，另检查320px窄屏。

添加 `controls=1` 后可以切换场景、重置、定格动画与媒体，再隐藏面板取图。定格只暂停 CSS/Web Animations、以当前位图覆盖 Canvas、暂停媒体和辅助事件投递；**不是整个 DOM 的截图或时钟冻结**。不保证跨刷新拿到相同 Canvas 动画帧。流式回复或初始引导尚在进行时，先等待其结束；审批/提问稳定等待态可拍摄。

浏览器开发者控制台也可等待 `window.__EVOLVE_PREVIEW__.ready`，通过其 `state` 确认就绪，并调用 `reset()`、`freeze()`、`resume()`。这些接口只控制演示，不访问真实数据。

每次加载仅重置预览自己的存储命名空间 `evolve_preview_v1:`；不会清空浏览器存储或改写正式应用的 `evolve_*` 偏好。

## 固定交互边界

- 任意输入可回显，回答和工具步骤使用预写脚本；不存在模型推理。
- 模型配置和用途引用可修改，仅影响当前页面，不连接输入的端点。预设端点使用 `.invalid`。请勿输入真实密钥。
- 手动/脱手/YOLO 切换、工具审批和多题提问只改变演示状态，不代表真实授权。
- 文件树和编辑内容是虚拟工作空间，保存、版本冲突、重命名、垃圾桶和锁都是本地演示，不读写宿主目录。
- Shell 与 Cron 操作只改变演示条目，不启动、停止或执行真实进程/任务。
- 录音按钮使用本地生成的固定音频，不请求麦克风或摄像头。用户主动选择、拖入或粘贴的文件只在浏览器内处理，不上传。
- 会话网页和 Agent 舞台层使用本地静态内容。默认场景不开启聊天区自定义样式；`visual` 场景单独展示视觉定制。
- 网页下载为本地展示网页 ZIP；会话导出为**明确标记的演示内容包**，不是正式完整离线导出，也不是真实会话备份。
- 性能遥测沿用正式本地组件，不把预设数据冒充性能测评结果。

## 独立构建和部署

用户自行执行 `pnpm.cmd build`（或 `npm.cmd run build`）。该命令检查本工程及其引用的正式模块，再执行本工程 Vite 构建，不调用 `run.py` 或正式前端的第二次离线阅读器构建。

用户自行执行 `pnpm.cmd preview` 可在 `http://127.0.0.1:4179/` 查看生产构建。

开发时需要同一宿主仓库中的 origin前端源码；**构建后的 `dist/` 可独立托管**，无需源码、Python或模型服务。不支持 `file://` 双击入口。使用域名根路径托管，静态服务器需把 `/agentspace/*` 回退到 `index.html`，并正确提供脚本、Worker、字体与资源 MIME。

`index.html` 在脚本之前带基础 Content-Security-Policy；开发/预览服务器同时提供同值响应 Header。独立静态主机可设置以下 Header，与页面策略保持一致：

`default-src 'self'; script-src 'self' 'unsafe-inline' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; media-src 'self' data: blob:; worker-src 'self' blob:; frame-src 'self' blob: data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'none'`

内联脚本/样式与 Blob 的允许项是可信正式组件的兼容需要；此方案不承诺安全执行任意恶意脚本。策略限制外部请求，业务路由仍由模拟层拒绝回源。iframe和Worker是独立执行域，不能假定继承顶层JavaScript模拟。

## 维护与验收

源码复用意味着 origin组件更新会影响预览。适配映射仅登记五个明确模块，缺失协议或资源会显示错误，不回退到真实后端。版本升级后按 [COVERAGE.md](COVERAGE.md) 重新人工验收。

目前仅完成源码编写与定向只读复核。视觉像素一致性、依赖解析、生产构建、CSP/Worker、音频与各场景的实际运行结果均须用户验收，不能用相同组件或相同CSS替代运行结论。
