# 预览覆盖与人工验收

状态：源码已编写；以下运行验收全部**待用户执行**。开发助手AI未运行安装、启动、类型检查、构建、测试或截图命令。

## 真实界面来源

正式 `src/main.tsx → App.tsx` 保持原样；Header、Sidebar、Layout、TabRail、TabStage、聊天虚拟列表、消息/工具/Markdown、输入栏、弹窗、初始引导和文件编辑器均引用 origin前端。适配仅发生在 storage、媒体API URL、会话网页ZIP、录音hook和会话导出hook五个明确模块。

## 展示与操作矩阵

| 区域 | 场景/入口 | 操作与数据边界 | 运行验收 |
|---|---|---|---|
| 顶部栏/左侧导航栏/右侧Tab | showcase | 原UI、会话标题/模型/上下文/心跳、搜索/标签/新建/切会话 | 待执行 |
| 主聊天/轮次导航条 | showcase | 全历史骨架/内容页来自同一内存消息表；工具结果配对 | 待执行 |
| 输入栏/流式回复 | showcase或empty | 输入回显、固定回答；中断/重新生成/强制调用工具 | 待执行 |
| 多Agent | multi | 固定参与者、角色可见性、子会话反馈 | 待执行 |
| 手动/脱手/YOLO | 输入栏右侧 | 内存状态与权威模拟回执，无真实审批模型 | 待执行 |
| 审批/提问 | approval/question | 原输入栏变形、允许/拒绝/选择/分页/提交 | 待执行 |
| 空/归档会话 | empty/archived | 原空态和只读状态、归档可分支 | 待执行 |
| 活动大盘 | tab=activity | 原Canvas与24条有限示例事件，不是真实性能数据 | 待执行 |
| 资源 | tab=resources | 本地图片/下载，演示Shell停止、Cron触发/取消 | 待执行 |
| 文件修改 | tab=changes | 严格同revision摘要与目录树，固定记录 | 待执行 |
| 媒体输入 | tab=media | 独立图片实例与本地资源，发送开关只改内存 | 待执行 |
| 会话变量 | tab=variables | 固定数值/进度条/仪表/文本与原始JSON | 待执行 |
| 子会话/角色档案 | tab=subagents/characters | 固定角色和反馈，真实展开/切换 | 待执行 |
| 会话网页 | tab=site | 原首次激活加载/刷新/全屏/新标签页/本地ZIP | 待执行 |
| 模型配置 | tab=llm | 原三个分页/草稿/CRUD/用途/运行配置，全内存 | 待执行 |
| 动态沙盒空间 | tab=sandbox | 原CRUD，目录选择返回固定示例，不访问宿主 | 待执行 |
| 文件编辑器 | /agentspace/ | 原Monaco/目录树/文本保存/冲突/重命名/垃圾桶/固定锁 | 待执行 |
| 会话视觉 | visual | 本地静态stage/site/CSS，默认场景不改产品样式 | 待执行 |
| 初始引导 | onboarding/命令菜单 | 原十一项步骤，预览专属存储 | 待执行 |
| 录音/上传 | 输入栏 | 固定音频无设备请求；主动文件输入不上传 | 待执行 |
| 会话导出 | 命令菜单 | 原弹窗与明确标记的演示ZIP，不冒充正式离线导出 | 待执行 |
| 截图辅助 | controls=1 | 默认隐藏、重置、场景选择、动画/媒体定格 | 待执行 |

## 请求覆盖

实现文件：`src/transport/sessionRoutes.ts`、`configRoutes.ts`、`fileRoutes.ts`、`contracts.ts`；模拟入口：`http.ts`、`websocket.ts`、`eventSource.ts`、`install.ts`。

| 接口组 | 正式调用方 | 返回/写入约束 |
|---|---|---|
| /sessions、/tags及会话元数据 | useSessionStore/useWebSocket | SessionInfo、固定标题/标签/摘要；内存归档/删除/合并 |
| /sessions/:id/status、llm-profile | useWebSocketConnection/useMainSessionActivityPolling/useSessionLlmSelection | SessionRuntimeStatus、SessionLlmProfileState |
| history/skeleton、page、resources | features/chat/historyApi | 原History*ResponseDto，同一History索引 |
| messages、regenerate、resume、interrupt、disgust | useWebSocket | 原变更回执、history_updated/regenerate_trim，有限脚本 |
| confirm、ask | useSessionStore | 固定待办幂等消费，不执行模型/工具 |
| tool-resources、subagents、shells、cron-tasks | useWebSocket、ResourcesTab | 原资源DTO、配对所属会话 |
| tab-capabilities、file-changes | useSessionTabCapabilities/useSessionFileChanges | 原严格解码器，不添加非约定字段 |
| history/media、variables | useSessionMedia/useSessionVariables | 原媒体/变量DTO；媒体content改为本地资源URL |
| llm/profiles、llm/clients | useLlmProfiles | 原Profile目录与CRUD回执，密钥不写存储 |
| approval/metadata/toolchain-summary/modality profile | useLlmProfiles | 原用途状态、模拟广播，不连模型 |
| agent-loop/settings | features/agentLoopSettings/api | 原三字段AgentLoopSettingsState |
| characters、sandbox-spaces、skills | 对应正式hook/API | 原角色/沙盒DTO，技能固定 |
| activity overview与事件 | useActivityDashboard/activityEventBus | 原ActivityOverview/ActivityEvent，有限序列 |
| agentspace CRUD/trash/locks/SSE | agentspaceApi/useAgentspace/RichInput | 原文件DTO与版本，虚拟内容不落盘 |
| file-picker、file_upload | useUploadManager | 固定选择回执或用户本地文件内存处理 |
| 会话视觉HEAD | useSessionVisualResource | 最终本地URL、版本Header，未部署404 |
| /ws/chat | useWebSocketConnection | 内存握手/消息/心跳/关闭，非原生网络连接 |
| /api/activity/events、/api/agentspace/events | 两个正式SSE客户端 | 内存EventTarget，关闭撤销订阅 |

未知接口、外部fetch、未知WebSocket/SSE与未登记导航均拒绝并显示预览故障，不以空响应伪装成功。会话export REST被适配hook替代，出现此类请求属于漏接错误。

## 用户人工验收步骤

1. origin目录与宿主根都没有node_modules时，仅本目录安装依赖，执行构建，确认TS与Vite分别解析正确、只有一份React/Zustand。
2. 未启动Python/Gateway/模型时打开所有截图地址，确认无业务HTTP/WS/SSE实际回源，无外网请求；本地静态模块/字体/Worker/图片加载正常。
3. 同浏览器、视口、字体、数据和展开状态下与正式前端对照截图，检查尺寸、留白、颜色、图标、工具卡片、浮层、换行与移动布局。
4. 检查会话切换/重置/新标签页/快速切Tab/StrictMode，防止重复消息、错误会话归属、过期响应或订阅残留。
5. 发送、中断、重新生成、审批、提问、模型、媒体、沙盒和文件操作逐项执行；刷新恢复种子，不影响真实存储/文件/服务。
6. 检查所有资源下载、站点ZIP、演示导出ZIP、录音按钮，不出现真实设备授权或后端访问；ZIP内容明确标记演示。
7. 默认页面无辅助面板/水印；隐藏controls后仍显示故障；动画定格不改变布局、心跳健康或声称冻结DOM。
8. 生产dist单独HTTPS托管，确认CSP实际生效，SafeHtml/KaTeX/Monaco Worker可用，/agentspace/刷新不404。

## 已声明的演示限制

- 固定回答和有限状态转换，不复刻全部后端规则。
- 临时会话不能跨标签页恢复；预设会话可以。
- 只有图片媒体种子，不预置伪造视频波形或远程音视频。
- Cron/子会话不设运行中的倒计时种子；动画定格不是DOM快照。
- 会话导出是演示包，不是正式完整离线阅读器。
- 默认无自定义聊天CSS；visual场景显示的样式是会话视觉扩展效果。
- 源码直接跟随origin变化；未经人工验收不能宣称像素一致或可发布。
