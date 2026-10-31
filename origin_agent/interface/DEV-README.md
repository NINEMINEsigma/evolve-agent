# interface/ — System与事件、端点组件契约

本包声明公开接口与公共能力基类，不承载具体业务服务实现，也不创建Application、连接或后台任务。System查询/依赖/装配使用I...接口槽位；实现及资源所有权仍在各业务包，现有21个System槽位不因API端点组件增加。

## APIComponent

`api_component.py::APIComponent`继承framework.AsyncComponent和ABC，是API端点组件契约，不是System槽位，也不继承BaseModel。具体实现均位于gateway/apis，每个具体类独立文件，由唯一GatewaySystem通过add_component持有。

公开能力：
- gateway只读property：通过framework公开parent_system取得并显式核对IGatewaySystem；未绑定/绑定错误直接RuntimeError。
- get_system(system_type)：委托同一父Gateway查询其他已就绪System，不缓存服务或架构镜像。
- display(router)：具体类显式登记原URL、方法、name和响应模型；不根据类名生成路径。
- handler：具体实现提供FastAPI可检查的真实参数/同步或异步签名；不统一包装成async，不修改__signature__。

构造/导入/注册只建立协议元数据，不查询Application或外部资源。Gateway在自身awake完成前装配组件，因此工厂接收已绑定Gateway参数，不能再从Application查询尚未awake的IGatewaySystem，也不读取尚未赋值的fastapi_app。没有额外组件初始化/清理服务；重复装配作为逻辑错误快速失败。

组件不保存当前Request、WebSocket、session_id、订阅、单次Future或结果。原System/TaskOwner负责真实资源和取消交接，组件父关系不会取代生命周期所有权。异常来自entity.error或框架，不在此包复制定义。

## 依赖方向

api_component单向依赖framework、FastAPI APIRouter和gateway_system接口；IGatewaySystem不反向依赖具体API实现。接口包入口显式再导出APIComponent，不建立自动发现或反射。消息前纯类型不反向导入接口实现/业务包；HTTPErrorDetail仅为不持久化的数据契约。

其他接口与ILoggableSystem/IDPRuntimeSystem继承、关闭准备及Logger根依赖保持既有规范，见根DEV-class_relationships和system开发文档。本轮未新增依赖版本、System、持久化模型或easysave key；未运行校验、导入、构建或应用，完整部署和运行验收由用户执行。
