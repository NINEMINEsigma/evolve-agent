# gateway/apis/ — API端点组件

本包承载网关全部91个具体API端点组件，对应92条路由注册。每个具体类独立文件，继承`interface.api_component.APIComponent`，由唯一GatewaySystem通过framework公开组件关系持有；不是新System、Agent工具或持久化数据模型。

## 模块地图

| 目录 | 职责 |
|---|---|
| pages/ | 首页与SPA兜底 |
| system/ | 健康检查、全局工具循环配置 |
| activity/ | 活动快照与事件SSE |
| sessions/ | 会话列表/标签/元数据、状态/能力、资源、删除/分支/合并及文件记录 |
| characters/ | 头像和角色档案 |
| interactions/ | HTTP审批回答、Ask回答、中断、厌恶 |
| session_export/ | 离线导出快照/资源/复核/阅读器产物 |
| history/ | 骨架/页/资源、媒体实例、消息修改与重新生成/恢复 |
| shells/、cron/ | 会话长期资源的用户操作 |
| dynamic/ | 动态端点调用 |
| uploads/ | 宿主文件选择器 |
| files/ | public文件、字体、下载、目录ZIP |
| sandbox_spaces/ | 动态沙盒空间管理 |
| profiles/ | LLM Profile CRUD、客户端和各全局用途引用 |
| agentspace/ | 版本化文件操作、垃圾桶、锁及独立编辑器SSE |
| skills/ | 技能列表 |
| websocket/ | 聊天连接生命周期，具体消息仍由MessageRouter分发 |

## 显式装配

`register_apis(gateway, router)`显式导入并按既有E01—E91顺序实例化；模块顶层只保存类型清单，不创建组件实例、连接或查询Application。重复装配直接RuntimeError，不重用/清空旧组件继续运行。组件通过framework的parent_system绑定，`gateway`property核对IGatewaySystem，服务查询经`get_system`委托父System，无镜像服务字段。

`server.build_router_app(gateway)`创建局部FastAPI与GatewayAPIRoute路由表，装配组件后include_router、计算build_hash、按原顺序挂载assets。GatewaySystem在awake过程中显式传self；注册时尚未完成awake，不能通过Application.current().get_system(IGatewaySystem)反查自身，也不能读取尚未赋值的fastapi_app。

`display(router)`逐条声明原路径、方法、name及response_model；`handler`为具体原生签名，FastAPI直接检查绑定方法。HTTP签名用到的模型必须运行期导入，不藏在TYPE_CHECKING。保留原name保证operationId生成输入；不根据类名拼URL，不用反射/目录扫描/重载或__signature__技巧。

GET/HEAD文件服务共用ServeWorkspaceFileAPI，但仍分别登记HEAD、GET两条，保持原顺序；SPA兜底在普通HTTP之后，WS按原次序。/assets、FastAPI自带文档入口不计入91组件。ServeWorkspaceFileAPI和DownloadDirectoryZipAPI保持同步def，以继续使用框架线程池，不套统一async handler。

## 请求和资源边界

组件对象无当前session_id、Request、WebSocket、订阅、待处理Future或结果字段；这些是每次调用局部材料。后台任务和真实资源仍交Gateway TaskOwner、FrontendSink、Agentspace、导出叶服务及其他原业务System。成功响应保留原BaseModel/嵌套模型和字段省略规则；显式二进制/文件/流式响应不套JSON成功外壳。

复用`gateway/api_support/`的会话/Loop检查、Profile投影、专属异常映射及有界导出HTTP帮助；仅单端点使用的删除scope、WS初始化和SSE编码保留在该端点文件。通知复用`gateway.notifications`，静态产物定位复用`gateway.frontend_assets`，不得从旧server导入端点或共享函数。

新业务HTTP由原生ASGI中间件在正文前要求RUNNING；提交前若经历await，按原服务接收边界或require_business_http复检，不持admission锁跨await/磁盘/模型。public文件、health与原WS准入例外保持；已建立流不逐次重新执行新入口限制，不破坏History先提交后结束输出的顺序。

请求格式/字段/参数错误为标准422；明确业务拒绝使用business_http_error与稳定code，并保留版本/锁/路径/导出凭证等专属信息。只有前置中间件503有request_accepted=false。在途失败可能已经提交，不能承诺回滚；未知错误直接传播。正常取消、空列表、清理pending和部分结果不统一变异常。

## 新增或维护端点

1. 先核对对应业务服务及本包职责，登记必要术语/常量/纯类型。
2. 在相应职责目录新增一个具体类文件，实现display和精确handler，不新增全局实例或请求字段。
3. 在包入口显式导入并安排唯一匹配顺序，避免被SPA或动态路径遮蔽；同步方法/name/response_model。
4. 复用共享边界，不捕获未知错误，不绕过原任务/真实资源所有权。
5. 同步受影响前端、预览、网关文档与用户人工验收项目；开发助手AI不代跑校验/构建/应用。

本轮完整路由/文件/类/签名对应表及人工验收见`.tasks/2026-10-31_1_gateway-endpoint-components.md` P5/P9/P19。源码已实施，未运行测试、校验、实际导入、构建或应用；运行结论待用户完整部署后检验。无持久化结构、type token、easysave key或System数量变化。
