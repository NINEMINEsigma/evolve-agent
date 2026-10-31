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

## 模块实例发现与System装配

每个具体类文件在类定义后创建一个无参APIComponent实例。当前统一使用变量名`api`作为源码风格，但发现器只依赖对象类型，不检查名称。包入口与职责子包入口不聚合具体端点，不维护中央导入/类型清单，不在导入时调用add_component/display或查询Application。

`GatewaySystem.display_apis(router)`通过`abstract.discovery.StrictDiscovery`严格遍历本包，再复用framework的类型收集及对象身份去重；同一对象别名或合法重导出只收集一次，不同对象的重复路由另行检查。模块构造只建立framework内存字段，无运行时连接、请求状态或业务初始化。

扫描只支持常规Python源包。每层按名称排序，忽略非.py文件、__pycache__和隐藏目录；合法下划线辅助模块也会导入。其他目录必须是合法非关键字名称的代码包并包含普通__init__.py，不支持namespace/资源目录或目录链接。当前层全部候选结构与完整导入名通过检查后才导入该层子项；foo.py与foo/__init__.py同名直接失败并报告双路径，不能借助对象去重隐藏漏载。读取/stat/导入/回调异常原样传播。这是逐层预检，不是全树导入事务，不回滚先前模块副作用。

普通组件继承priority=0，数值越小越先display，同值保持确定性模块/变量发现顺序；组件可覆写优先级表达具体/参数路径重叠关系。Gateway要求priority为真正int（bool拒绝）、不大于1000且恰好一个1000末尾声明，目前仅SpaFallbackAPI使用该值；其他组件必须小于1000。此策略只属于Gateway，不进入StrictDiscovery，也不自动按URL具体程度排序或验证SPA行为。

System排序后先全部add_component绑定，再按同一有序列表逐个display；所有组件实际父System都是唯一Gateway，没有镜像服务表。`_api_assembly_started`保证同Gateway一次性装配；已绑定模块实例由framework拒绝再次绑定，不清空/reload/克隆/自动解绑继续运行，不支持同进程原地重新装配。

`server.build_router_app(gateway)`创建局部FastAPI与GatewayAPIRoute路由表，只委托gateway.display_apis，完成后include_router、计算build_hash并按原位置挂载assets。Gateway在自身awake完成前显式传self；不能经Application反查未awake的IGatewaySystem，也不能读取尚未赋值的fastapi_app。发现/绑定/display失败直接终止启动，既有资源按原失败启动路径清理，不对外服务部分路由。

`display(router)`继续显式声明原路径、方法、name及response_model；handler保留FastAPI可检查的真实签名。HTTP参数模型运行期导入，不藏在TYPE_CHECKING；不根据类名拼URL，不通过__signature__或统一async包装间接化。仅动态发现允许按类型枚举模块变量，已知业务字段仍显式访问。

`gateway/api_routes.py::validate_api_routes`在include_router前拒绝相同文本路径的同HTTP方法或同WS登记；GET/HEAD、不同方法或不同协议共路径允许，route.name无需全局唯一。它不识别不同参数名的语义等价模板、正则交叠或通配遮蔽，这些仍需明确优先级和人工审阅。组件仅登记APIRoute/APIWebSocketRoute，其他Route/Mount类型拒绝。

GET/HEAD文件服务共用ServeWorkspaceFileAPI，内部仍先HEAD后GET；SPA位于其他组件之后，WS使用独立协议匹配。/assets与FastAPI自带文档入口不计入91组件。ServeWorkspaceFileAPI和DownloadDirectoryZipAPI保持同步def，继续使用框架线程池。91组件/92注册只是本次迁移基线，不是硬编码运行数量限制。

## 请求和资源边界

组件对象无当前session_id、Request、WebSocket、订阅、待处理Future或结果字段；这些是每次调用局部材料。后台任务和真实资源仍交Gateway TaskOwner、FrontendSink、Agentspace、导出叶服务及其他原业务System。成功响应保留原BaseModel/嵌套模型和字段省略规则；显式二进制/文件/流式响应不套JSON成功外壳。

复用`gateway/api_support/`的会话/Loop检查、Profile投影、专属异常映射及有界导出HTTP帮助；仅单端点使用的删除scope、WS初始化和SSE编码保留在该端点文件。通知复用`gateway.notifications`，静态产物定位复用`gateway.frontend_assets`，不得从旧server导入端点或共享函数。

新业务HTTP由原生ASGI中间件在正文前要求RUNNING；提交前若经历await，按原服务接收边界或require_business_http复检，不持admission锁跨await/磁盘/模型。public文件、health与原WS准入例外保持；已建立流不逐次重新执行新入口限制，不破坏History先提交后结束输出的顺序。

请求格式/字段/参数错误为标准422；明确业务拒绝使用business_http_error与稳定code，并保留版本/锁/路径/导出凭证等专属信息。只有前置中间件503有request_accepted=false。在途失败可能已经提交，不能承诺回滚；未知错误直接传播。正常取消、空列表、清理pending和部分结果不统一变异常。

## 新增或维护端点

1. 先核对对应业务服务及本包职责，登记必要术语/常量/纯类型。
2. 在相应职责常规Python包新增一个具体类文件，实现display和精确handler；类定义后创建一个无参实例，变量名不限，不增加请求字段或运行时构造副作用。新职责子目录必须提供__init__.py，不能与同层.py文件映射到同一模块名。
3. 需要控制重叠路径时在组件声明小于1000的整数priority；普通端点使用默认0，无需修改任何中央清单或System。保留显式方法/name/response_model及同步或异步签名。
4. 复用共享边界，不捕获未知错误，不绕过原任务/真实资源所有权。
5. 同步受影响前端、预览、网关文档与用户人工验收项目；开发助手AI不代跑校验/构建/应用。

原路由/文件/类/签名对应表仍见`.tasks/2026-10-31_1_gateway-endpoint-components.md`。本次发现迁移与人工验收见`.tasks/2026-10-31_2_gateway-api-discovery.md` P11/V12；新增实例、别名去重、严格导入失败、优先级、重复路由以及普通页面/文件/WS/SSE需由用户确认。源码和文档已实施，未运行测试、校验、实际导入、构建或应用；无持久化结构、type token、easysave key或System数量变化。

仅启动时发现内置端点，需完整部署并重启，不支持外部目录或运行期热加载。run.py的合并复制会保留目标侧独有旧文件；删除/移动端点后可能继续发现旧副本。用户应先保护本地进化修改，再定向处理残留，force_init对fast仓库亦不保证清除。开发助手AI不操作workspace代码。Python缓存不卸载或重载，进程重启才重新构造实例。
