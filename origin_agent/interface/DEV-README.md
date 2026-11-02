# interface/ — System与事件、端点组件契约

## 审批叶类型注解来源（2026-11-02）

`IApprovalSystem`的`ToolAllowlistStore/ApprovalBackendManager/ApprovalModeStore`类型注解来源随审批包迁移至`system.approval`各子模块，仍仅在`TYPE_CHECKING`中导入，不增加运行期实现导入、接口基类或属性/方法签名变化。`ApprovalSystem`仍按原接口槽位装配，完整归属见[审批系统文档](../system/approval/DEV-README.md)。本次仅来源同步与文本审阅，未运行校验、实际导入、测试、构建或应用。

## 工具结果内容契约（2026-11-02）

`IAgentSink.emit_tool_result` 的 `content` 参数为 `entity.puretype.MessageContent`：字符串或序列化媒体块列表。其余参数、默认值、工具调用 ID、独立耗时与嵌入消息通道保持不变。`FrontendSink` 将完整内容放在 `tool_result.result`，`ParentAgentSink` 将其放在子会话 `tool_result` 事件的 `content`；两个实现都不在接口边界把媒体转换成占位文本。

内容来自已提交工具消息的共享展示投影，日志文本视图仍独立。没有新增 System、服务依赖、事件名称或持久化字段；父Agent纯文本反馈与关闭/发送所有权保持。前后端需同步更新，实际运行、校验与构建未由开发助手AI执行。

本包声明公开接口与公共能力基类，不承载具体业务服务实现，也不创建Application、连接或后台任务。System查询/依赖/装配使用I...接口槽位；实现及资源所有权仍在各业务包，现有21个System槽位不因API端点组件增加。

## APIComponent

`api_component.py::APIComponent`继承framework.AsyncComponent和ABC，是API端点组件契约，不是System槽位，也不继承BaseModel。具体实现均位于gateway/apis，每个具体类独立文件，由唯一GatewaySystem通过add_component持有。

公开能力：
- priority类级元数据：`ClassVar[int]`，默认使用GATEWAY_API_DEFAULT_PRIORITY（0）；数值小者先display，同值保留发现顺序。Gateway应用保留1000作为唯一末尾声明，普通组件必须小于1000；通用发现入口不检查优先级。
- gateway只读property：通过framework公开parent_system取得并显式核对IGatewaySystem；未绑定/绑定错误直接RuntimeError。
- get_system(system_type)：委托同一父Gateway查询其他已就绪System，不缓存服务或架构镜像。
- display(router)：具体类显式登记原URL、方法、name和响应模型；不根据类名生成路径。
- handler：具体实现提供FastAPI可检查的真实参数/同步或异步签名；不统一包装成async，不修改__signature__。

构造/导入/注册只建立协议元数据，不查询Application或外部资源。Gateway在自身awake完成前装配组件，因此工厂接收已绑定Gateway参数，不能再从Application查询尚未awake的IGatewaySystem，也不读取尚未赋值的fastapi_app。没有额外组件初始化/清理服务；重复装配作为逻辑错误快速失败。

组件不保存当前Request、WebSocket、session_id、订阅、单次Future或结果。原System/TaskOwner负责真实资源和取消交接，组件父关系不会取代生命周期所有权。异常来自entity.error或框架，不在此包复制定义。

## IGatewaySystem装配契约

`display_apis(self, router: APIRouter) -> None`是同步一次性装配入口。server工厂创建局部路由表后委托此接口，GatewaySystem收集模块级实例、稳定排序，全部绑定后再逐个display，并在include_router前检查重复路由。接口只依赖APIRouter，不反向导入APIComponent或具体发现实现。

模块内实例变量名不限，收集按类型并按身份去重；组件创建发生在模块导入时，构造仅建立framework内存字段，不取得运行时依赖。GatewaySystem的一次性状态拒绝重复装配，模块缓存中的已绑定实例也由framework拒绝再次绑定；不自动解绑、克隆、reload或复位重试，不承诺同进程第二次装配。

## 依赖方向

api_component单向依赖framework、FastAPI APIRouter和gateway_system接口；IGatewaySystem不反向依赖具体API实现。接口包入口显式再导出APIComponent，自身不执行发现或反射；按类型实例发现由独立StrictDiscovery承担，装配和display由GatewaySystem承担。消息前纯类型不反向导入接口实现/业务包；HTTPErrorDetail仅为不持久化的数据契约。

其他接口与ILoggableSystem/IDPRuntimeSystem继承、关闭准备及Logger根依赖保持既有规范，见根DEV-class_relationships和system开发文档。本轮未新增依赖版本、System、持久化模型或easysave key；未运行校验、导入、构建或应用，完整部署和运行验收由用户执行。
