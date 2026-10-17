# custom_tools/ — 自定义工具扩展机制

本目录是 Evolve Agent 的运行时工具扩展点，不是开发助手AI的工具或测试目录。本文只描述通用机制与公共接口，不登记本目录当前包含的具体工具、工具集或其专属参数、协议、行为及验收记录。

## 声明与发现

工具模块通过顶层固定名称 `TOOLSET = BaseToolSet(...)` 声明工具集，其中持有 `BaseTool` 子类实例。模块导入仅创建无连接工具对象，不查询 Application、不修改注册表、不执行请求。

`ToolDiscoverySystem` 递归扫描本目录，按 AST 识别模块顶层的 `TOOLSET` 声明，按路径排序导入，再交给唯一 `ToolRegistry` 注册和预热。文件名以 `_` 开头的模块、`__init__.py` 与 `registry.py` 按发现规则跳过，共享实现模块不需要声明工具集。

读取、语法、导入、注册和预热失败直接传播；仅当可选的 `custom_tools/` 目录不存在时跳过。旧 `register_tools` 函数注册协议、导入全局注册表和导入期注册不属于有效声明方式。

## 工具执行接口

- `ensure_arguments()`：接入既有执行入口，负责参数纯校验与规范化。
- `before_handle(execution)`：审批通过后、工具主体前准备本次调用。
- `handle(execution)`：执行实际工作，返回 `ToolHandlerResult`。
- `after_handle(execution)`：工具正常完成并提交 History 后执行后处理，默认返回空效果。
- `BaseToolSet.preheat()`：工具集注册期预热，不替代运行期可用性检查，也不启动重量资源。

`ToolExecution` 保存当前调用的参数、上下文、结果和阶段状态。工具实例与工具集由注册表共享持有，不得在共享对象中保存单次调用材料或 History 引用。

需要运行时服务时，通过 `execution.context.app.get_system(...)` 取得公开接口；导入期不取得服务。异步执行、同步工作及停止收尾由现有注册表和生命周期机制管理，取消等待不代表底层工作已经结束。

## 加载与权限

工具集通过 `BaseToolSet` 元数据声明是否默认加载；非默认工具集通过既有 `LoadToolset` 机制按需加载。实际可用工具受会话已加载工具集、`ToolAvailability`、危险等级、运行期可用性及所属 Loop 策略共同约束，加载工具集本身不扩大授权。

手动、脱手和 YOLO 模式使用既有审批机制；免审批不绕过参数、工具可用范围或沙盒权限校验。`custom_tools:` 沙盒命名空间对项目 Agent 只读。

## 依赖与资源边界

扩展复用 origin仓库已有的工具基类、公共类型、常量和服务接口。自定义工具专属的常量与类型留在所属 custom 目录，origin仓库不定义或重新导出扩展专属名称。

资源须有明确所有者和释放路径，单次调用资源随调用收尾；需要全局生命周期的对象由 Application 直接或间接持有。生命周期失败继续传播，不以空结果或默认值伪装成功。

## 接口参考

工具接口与通用教学示例见根目录 [README.md](../README.md)；注册表、发现与执行契约见 [abstract/DEV-README.md](../origin_agent/abstract/DEV-README.md)。新增或修改扩展后，仍按既有启动发现流程装配，文件变更本身不等同于自动热加载。
