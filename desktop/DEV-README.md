# desktop/ — 桌面启动器开发文档

## 桌面托管 Python 环境（2026-11-02，当前约定）

本节取代下文2026-10-29记录中“Python只做路径探测、生命周期和打包适配延后”的旧边界。十二项Config配置与其存储协议继续保持。

空Python路径表示使用**桌面托管 Python 环境**；用户点击启动后才进行**环境准备**。安装包携带固定uv，Python、虚拟环境、依赖缓存和安装临时文件均放在exe所在目录的`runtime/`内，不复制开发venv，不使用系统或Conda解释器兜底，不修改系统PATH或登记Windows全局Python。手动非空路径只读诊断，要求Python3.12/x64及必要依赖，不替外部环境安装或修改包。

### 模块关系与入口

| 模块 | 职责 |
|---|---|
| `runtime/release-spec.json` | 唯一人工工具链规格：uv0.9.8、CPython3.12.12、Windows x64、固定PyPI；不随启动查询latest |
| `runtime/requirements-runtime.in` | 引用根requirements.txt，补入pip/setuptools/wheel；不复制开发site-packages |
| `runtime/requirements-win-x64.lock`及`.lock.meta.json` | 开发者显式解析生成的完整发布锁和输入/产物摘要；正式跟踪，不能伪造或以freeze代替 |
| `runtime/probe_environment.py` | 正式运行支持代码，仅诊断解释器/关键包；不导入origin/third或应用入口，不创建浏览器、ConPTY或Application |
| `scripts/prepare-runtime-assets.ps1` | 验证固定官方uv归档与许可证，显式刷新依赖锁，准备最小随包资源，可部署开发资源 |
| `scripts/prepare-frontend.ps1` | 仅复制已有前端构建产物；不构建前端、不准备Python |
| `src/owned-process.js` | 真实spawn/close所有权、有界取消、UTF-8半行日志及脱敏 |
| `src/runtime-env.js` | 子进程环境隔离与内部目录映射，不修改process.env或系统变量 |
| `src/python-runtime-manager.js` | 资源核对、运行期租约、离线诊断、独立Python安装、唯一固定虚拟环境与成功状态提交 |
| `src/backend-manager.js` | 显式解释器执行run.py、真实结束与可销毁的健康轮询 |
| `src/launcher-controller.js` | 唯一启动状态、取消/超时/退出裁决、端口准入及完成屏障 |
| `src/main.js` | Electron窗口/托盘、IPC装配、单实例和统一异步退出，不自行探测系统Python |
| `renderer/config.js`、`log.js` | 主进程快照驱动的配置/日志界面，保留草稿与可达的取消、错误和返回操作 |

桌面对象只由Electron主进程直接/间接持有，不加入项目Application或origin仓库System。后端始终通过根run.py启动，fast/slow/fallback进化与回退语义不变。

### 安装布局与权限

- `runtime/uv/uv.exe`及`LICENSE-MIT`、`LICENSE-APACHE`：随安装包携带。
- `runtime/release.json`、`requirements-win-x64.lock`、`support/probe_environment.py`：随包资源，运行前核对实际摘要；探针必须位于asar外。
- `runtime/python/`：uv管理的独立基础Python，子目录由uv确定，不拼接猜测。
- `runtime/venv/`：唯一固定的项目虚拟环境；目录不带哈希、UUID或版本号，只在没有成功环境时准备，不创建第二套。
- `runtime/cache/uv/`、`cache/python/`、`cache/pip/`、`runtime/tmp/`：依赖/下载缓存与临时文件。
- `runtime/state.json`：schemaVersion=2的成功环境记录，保存installRoot、pythonRelativePath、prefixRelativePath、basePythonRelativePath、pythonVersion、platform、arch、readyAt；不保存environmentKey、generationId或发布哈希。虚拟环境路径严格限定`venv`及`venv/Scripts/python.exe`，不是Config/easysave文件。
- `runtime/prepare.lock`：覆盖环境准备和后端整个运行活动的租约，而非安装完即删除的短锁。

先做真实创建/写入/关闭/删除探测；目录不可写时明确拒绝，不自动提权、改ACL或改装到AppData。拒绝管理路径符号链接/junction或越界。安装到Program Files等保护目录可能不可用，应选择可写目录。
内部安装不是整个Electron应用的文件系统沙盒：Electron原有用户数据、Windows自身行为和第三方主动写入不承诺全面重定位。自动管理后端的TEMP/TMP/TMPDIR和pip/uv默认缓存也指定在runtime内，但其他程序或项目工具可以主动采用不同路径。

### 开发与发布准备（只由开发者执行）

以下入口在`desktop/`目录使用Windows的`pnpm.cmd`，开发助手AI不执行。

1. 首次或依赖/工具链规格变化时，开发者运行`pnpm.cmd run runtime:lock`。此步骤明确联网下载并校验固定uv、安装内部基础Python、解析完整带哈希依赖锁，生成lock/meta。它不复用开发venv，也不自动启动应用。
2. 开发启动前运行`pnpm.cmd run prepare:dev`，只将核对后的uv/许可证、release、lock、probe部署到根runtime。随后`pnpm.cmd start`仍只启动Electron；点击启动才准备项目环境。
3. 发布前按既有运行时工作流自行准备前端产物。`pnpm.cmd run build`顺序执行`prepare:runtime`、`prepare:frontend`及Windows x64打包。普通准备拒绝缺失/陈旧lock，不偷偷重新解析依赖。
4. 准备/刷新/打包前退出全部桌面实例；这些发布操作必须串行，不支持多个electron-builder共享输出目录并行打包。

旧`prepare-embed`入口及prepare-embed-python.ps1已移除。桌面打包不再默认复制根目录 `check_env.py` 和 `SOUL.md`，这两个文件不属于默认随包资源；本调整不修改 `run.py` 的可选 SOUL 文件处理逻辑。发布只白名单复制`.runtime-staging/runtime`的六类文件，不分发开发Python、项目虚拟环境、cache/state/租约。`release-spec.json`另外包含在asar内供唯一规格读取。

桌面打包通过 `extraFiles` 将根目录 `custom_mods/` 复制到 exe 同级的 `custom_mods/`，保留目录结构、`MOD.md`、`MOD.md.meta` 及关联资源，仅排除 `.git`、`__pycache__` 和 `.pyc`；不在打包时渲染模板或执行 mod 加载。

输入摘要算法：依次对标签`requirements.txt`、`requirements-runtime.in`、`release-spec.json`，拼接标签无BOM UTF-8字节、NUL、对应文件原始字节、NUL，再对整体计算SHA-256；不归一化换行或编码。meta的inputSha256/lockSha256与发布清单实际摘要不符时停止，不把未知格式当作空数据。

uv归档与`.sha256`从固定官方GitHub Releases获取，先核对后执行；许可证来自同tag。文件摘要使用.NET SHA-256流式计算，不依赖`Get-FileHash`命令或PowerShell模块自动加载；摘要仍为小写十六进制，文件读取/计算错误直接失败。校验与下载失败保留真实原因并非零退出，不改用PATH uv或latest。允许uv为没有wheel的可信纯Python依赖做隔离构建，因此不宣称所有构建工具也完全可复现；遇到编译器需求不在用户电脑自动安装系统工具链。

### uv 下载的证书信任（2026-11-02）

发布准备脚本的 `New-InstallerEnvironment` 和桌面环境准备的 `buildInstallerEnv` 均在清理继承的 `UV_*` 变量后，显式设置 `UV_NATIVE_TLS=true`，使 uv 下载 Python 和解析/安装依赖时使用 Windows 系统信任库。系统已信任的企业/代理 CA 可参与正常 TLS 校验；不关闭证书或主机名校验，不自动导入证书，不增加失败重试或解释器回退。已有 `SSL_CERT_FILE` / `SSL_CERT_DIR` 的继承行为不变，显式证书配置仍可能覆盖默认信任来源；该设置只属于安装工具子进程，不修改系统环境，也不额外传入后端环境。

此修改针对 uv 的 `invalid peer certificate: UnknownIssuer`，不保证修复所有证书问题或网络连接失败；Windows 本身不信任签发机构时仍应失败。开发者可重新执行 `pnpm.cmd run runtime:lock`，后续实际桌面首次准备也使用相同的信任策略。仅完成源码修改与只读差异审阅，未执行下载、安装、依赖解析、校验、构建或应用。

### 状态、通信与取消

`backend:launch`同步校验配置与准入，返回`{accepted, attemptId}`，不代表就绪。`backend:get-state`读取完整快照，`backend:status`发送同格式快照，`backend:cancel`只接受准备/启动中的取消；preload不暴露任意命令或任意文件写入。
快照字段：revision、attemptId、status、phase、canLaunch、canCancel、pythonPath、errorCode、detail。页面按revision忽略旧读取结果，按钮以主进程canLaunch/canCancel为准；接受应答不覆写先到达的失败快照。

| 状态 | 行为 |
|---|---|
| idle / stopped / cancelled，canLaunch=true | 可接受新的启动 |
| preparing | preflight、downloading_python、creating_environment、installing_dependencies、verifying_environment；不启动健康轮询 |
| starting | 已准备环境，检查端口后spawn；spawn成功后开始120秒健康等待 |
| running | 有效starting、无终止意图、当前进程仍活跃且当前健康代际通过，才打开会话窗口 |
| cancelling | 先登记terminationIntent，废弃健康回调，再终止并等待真实工作；不能接收新启动 |
| setup_failed | 环境资源/安装/诊断失败，与后端崩溃分开；清理完成后才可重试 |
| crashed / timeout | 后端失败或120秒未就绪；超时先停止后端，清理完成才可重试 |

同attempt的迟到健康成功、极短退出后的start续体、取消/超时杀进程产生的退出通知，都不能覆盖既定终态。完成屏障包含准备链、端口探测、后端close、健康请求close和租约释放；屏障未过不能canLaunch=true。
OwnedProcess.cancel共用首次调用起10秒观察预算，taskkill自身最多5秒；调用使用固定绝对taskkill.exe和独立参数，无shell拼接。失败/超时不删除真实子进程、观察任务和租约，不把包装Promise结束当作资源释放。直接子进程close不证明任意脱离进程树的后台任务终止；不确定时保守禁止重试，只有显式退出可重新核对。
点窗口X仍只隐藏，安装继续；托盘退出、backend:kill与before-quit进入同一异步shutdown。实际退出前确认准备/后端结束；清理失败保留壳和日志，可再次显式退出复查，仍不确定时由用户处理，不能称作优雅业务停机。
日志每行最多16KiB、错误尾部最多64KiB、界面最多2000行，使用textContent并脱敏URL/凭据。没有下载百分比时只显示真实阶段，不显示虚假退出倒计时；阶段区不覆盖日志与按钮。

### 探针、状态提交与恢复边界

探针通过Python `-I -B`执行，64KiB内单JSON，退出码与errorCode必须一致：0成功；10缺包；11版本；12前缀；13位数；70探针内部错误。已有成功state时按其记录的Python版本离线诊断并复用；任何诊断失败、解释器缺失、未知退出码、信号、非法JSON、70或spawn ENOENT/EACCES均报错，不自动重建。base/manual失败不自动重装，新建环境最终诊断失败也不循环安装。

state采用同目录临时文件和原子替换。只清理本次排他创建、尚未成功提交且真实进程已结束的`runtime/venv`。发出替换前先标记preserve，替换在途或完成后取消只阻止继续启动，允许保留完整已准备环境，不能再删除state可能引用的目录。替换结果不明、锁释放失败或后端失败都不能反向删除已提交环境。此处原子性不等于断电持久化保证。

存在成功state就不再根据依赖锁、发布清单、工具链规格或路径变化创建新环境或自动升级包；资源摘要仍用于检查随包文件完整性，但不驱动环境失效。安装根移动时直接报错，由用户退出全部相关进程后自行检查、删除旧`runtime/venv`及对应`runtime/state.json`，然后点击启动重新准备；不自动迁移或修改pyvenv.cfg。旧schema1多环境记录明确拒绝并提示人工处理，不自动迁移；其他未知格式继续失败。没有成功记录却已有固定目录时，拒绝认领或覆盖该未知目录，用户自行处理后才能重试。旧`runtime/envs/`目录不会被启动器扫描、使用或删除。

prepare.lock使用排他创建，带schemaVersion、attemptId、pid、installRoot、startedAt、token；释放前核对自身身份。发布先获取`.runtime-assets.lock`再获取同一runtime租约。强杀留下的锁不会按时间/PID猜测删除：先人工确认所有相关进程结束，再只处理日志中那个精确锁文件。损坏state、未知schema和路径逃逸明确失败，不自动清空。

本期使用独占临时bind检查目标端口，已被占用即拒绝；释放端口到后端bind仍有抢占竞态，HTTP200没有启动令牌。本期不改origin的/health协议，不宣称健康响应具有强身份确认。
NSIS升级/卸载可能处理安装目录数据；不因文件未列入extraFiles就承诺它们永久保留。更新、卸载和移动前应退出所有实例并备份配置、会话及其他业务数据。

### 人工验收与当前状态

源码实施与只读审阅不代替运行验证。开发助手AI未执行安装、依赖解析、探针、校验、构建或应用，真实lock/meta、uv资源和安装包仍待开发者亲自准备。

| 编号 | 人工验收重点 |
|---|---|
| V01–V03 | 干净Windows x64、无系统Python也能准备；忽略开发venv/Miniconda；不新增全局PATH、注册表Python和AppData环境缓存 |
| V04–V06 | UV/PIP/PYTHON/Conda污染、外部配置、中文/空格/长路径、不可写目录均有明确边界，不回退全局 |
| V07–V09 | 下载/安装网络失败可见；各准备阶段取消和成功竞态；X隐藏、托盘退出真正确认进程结束 |
| V10–V12 | 重复IPC/双开只一活动；强杀留下锁明确阻断；首次成功后断网离线复用 |
| V13–V15 | 依赖/发布规格变化复用成功环境；搬路径或成功环境诊断失败时提示人工处理，不另建；损坏state明确拒绝 |
| V16–V18 | 外部junction被拒；资源摘要不符不执行；手动路径不被安装/修改，清空恢复内部模式 |
| V19–V21 | 安装不消耗120秒健康预算；退出/应答/快照竞态；包不含开发环境且陈旧lock/摘要/许可证错误阻断发布 |
| V22–V24 | 无wheel的纯Python包安装日志完整；窄窗口/键盘/UTF-8日志可用；十二项配置及原进化入口无回归 |
| V25–V28 | 严格探针错误分类且不自动重建；rename各边界取消不删已提交环境；taskkill失败/超时保留所有权；同attempt迟到事件不覆写终态 |
| V29–V31 | prepare:dev可准备缺失资源；运行中发布/双准备被锁拒绝；后端pip默认缓存/临时目录内部化；已占用端口不能误开旧服务 |

| R3-A | 首次仅创建runtime/venv，正常重复启动离线复用，不生成哈希或UUID环境目录 |
| R3-B | 更换合法发布资源/依赖锁/工具链规格不自动安装或另建；原成功环境诊断失败仅报错 |
| R3-C | 移动安装目录后明确提示用户手动处理；保留成功state但删除venv不会自动重建 |
| R3-D | 旧schema1记录拒绝自动迁移；没有state但已有未知venv目录时拒绝覆盖 |
| R3-E | 初建失败/取消确认进程结束后仅清理本次目录；状态提交在途或成功后绝不删成功环境，失败重试始终同一固定目录 |

完整细分场景见任务`2026-11-02_2_desktop-local-uv-runtime`；R3替代V13–V15/V25中旧自动重建与迁移行为及未实施的R2方案。上述表格不代表已经通过，开发助手AI未运行任何验证或准备命令。

## 2026-10-29 配置更新记录（历史）

`desktop/` 是独立的 Electron 桌面启动器，负责启动配置编辑、Python 路径设置、通过根目录 `run.py` 启动后端，以及显示后端提供的 Web 前端。它不属于 origin仓库，也不维护第二套聊天界面。

## 本次改动边界

2026-10-29 更新仅覆盖配置界面、配置读写、配置校验与启动参数传递。网关关闭接口、进程退出、崩溃后重试、健康检查、安装包和 Python 环境准备不在本次范围。现有托盘退出仍直接终止后端进程树，不能将本次更新理解为已经实现安全关闭。

## 配置定义与模块职责

| 文件 | 职责 |
|---|---|
| `src/config-fields.json` | 12 个有效启动字段的类型、默认值、分组、中文名称、说明、CLI 参数及数值约束；同时保存配置界面的中文动态文案 |
| `src/field-defs.js` | 无 Electron/文件系统依赖的共用解析、校验和 CLI 参数生成函数；Node.js 通过 CommonJS 引入，配置页面通过普通 script 加载 |
| `src/config-manager.js` | 配置文件结构检查、有效字段投影、默认值补齐、保存合并与启动前配置准备 |
| `src/main.js` | 提供配置 IPC；在创建后端进程前完成配置准备，之后继续原有启动流程 |
| `src/preload.js` | 沙盒 IPC 桥接；不再内联字段定义或校验函数 |
| `renderer/config.js` | 表单、原始输入、有效值、修改标记、配置错误与保存/启动提交状态 |
| `renderer/index.html` / `styles.css` | 配置表单容器、说明、错误区域与布局 |

根目录 `config.py::Config` 仍是 Python 启动配置的依据。JSON 是桌面端唯一字段描述来源，但不是从 Python 自动生成；修改 `Config` 后须人工同步 JSON。禁止为读取字段而导入或执行有启动配置副作用的 `config.py`。

## 有效字段

| 分组 | 字段 | 默认值 |
|---|---|---|
| 路径 | `workspace_path` | `workspace` |
| 路径 | `fast_agent_space_path` | `fast_agent_space` |
| 路径 | `slow_agent_space_path` | `slow_agent_space` |
| 路径 | `agentspace_path_name` | `agentspace` |
| 路径 | `logs_path_name` | `logs` |
| 路径 | `mcp_config_path_name` | `mcp_config.json` |
| 网关 | `gateway_host` | `127.0.0.1` |
| 网关 | `gateway_port` | `8765` |
| 运行时 | `console_log` | `true` |
| 运行时 | `force_init` | `false` |
| 运行时 | `frontend_force_build` | `false` |
| 运行时 | `merge_concat_threshold` | `50000` |

路径字段按输入原样保留，不转换相对/绝对路径、不探测目录是否存在。运行时根目录相对于启动入口的工作目录解释；其余路径由现有 `config.py` / `run.py` 组合。

`gateway_port` 允许 1–65535；`merge_concat_threshold` 保留旧桌面端非负整数口径。输入整数可带正负号和首尾空白，但不能包含小数、指数或其他字符，且必须落在 JavaScript 安全整数范围。持久化值和 IPC 有效值必须具有正确的实际类型，不将字符串布尔值或字符串数字伪装成正式值。

旧 `llm_*` 字段不再展示、校验、填充默认值或生成 CLI 参数；模型连接配置由应用内的模型配置 Tab 管理。Python 路径仍是独立的桌面启动器设置，不属于这 12 个字段，也不进入 `Config`。

## 共用函数与调用关系

- `selectKnownValues(definitions, values)`：从对象提取当前字段，不把未知字段带入表单或 CLI。
- `parseFieldInput(definition, rawValue)`：将控件原始输入解析为有效值或带错误码的结果；非法整数不先经过 `parseInt()` 截断。
- `validateConfigValues(definitions, values, partial=false)` / `assertConfigValues(...)`：分别返回校验结果或抛错；部分覆盖允许缺字段，完整配置必须包含全部字段。
- `formatFieldError(definitions, name, result)`：从 JSON 中文文案格式化字段错误，前后两侧使用相同实现。
- `buildCliArgs(definitions, overrides)`：校验已知覆盖字段后生成参数；布尔值总是显式输出 `true` 或 `false`。
- `config-manager.prepareLaunch(configPath, key, overrides)`：检查目标方案结构，合并默认值、已存值与本次覆盖，验证最终配置，并返回启动参数与网关连接使用的同一份有效值。

配置页面通过 `config:field-definitions` 取得可序列化描述，调用本地共用模块做即时解析；保存和启动时，主进程再次校验，前端不是信任边界。主进程不再强行附加 `--console_log true`。

`backend:launch` 改为请求/响应 IPC。配置拒绝会返回调用错误，页面保留草稿并恢复提交能力；请求接受后沿用原有进程状态事件。这里的接受只代表配置检查与启动调用已经完成，不代表后端已经就绪或启动成功，也不新增进程崩溃重试。

## 配置读写与兼容

文件仍采用现有 easysave JSON 的顶层方案名和 `__root` 对象，根类型必须为 `config, Config`，字段位于 `__value`。未修改 `Config` 模型结构、类型标记或存储版本。

- 列表查询在配置文件不存在时返回空列表；无效 JSON 或非对象顶层明确失败。
- 选择方案时检查其根对象、类型标记和值对象；结构错误、方案消失或有效字段类型错误明确报错，不自动补造整个方案。
- 有效字段缺失允许补齐当前默认值。
- 页面只收到当前字段，旧模型参数及其他未知字段不会暴露到表单。
- 新建方案只写入当前默认字段，同名方案拒绝创建。
- 保存要求完整的有效字段，仅合并更新这些字段；已有未知字段、其他方案和序列化节点保留，不执行隐式迁移或清理。
- 临时覆盖不写配置文件；启动时重新读取方案并校验最终值。

文件写入继续使用原有直接 JSON 写入方式；本次不新增原子替换、跨进程事务或持久化修复。保存失败不回滚已经发生的文件系统副作用；页面仅保证不丢弃内存草稿、不提前清除修改标记。配置文件含旧密钥时仍由用户自行管理，不因界面隐藏而被删除。

## 布尔 CLI 兼容

根目录 `config.py` 统一解析显式布尔值，接受大小写不敏感的 `true/false`、`1/0`、`yes/no`、`on/off`、`y/n`；其他字符串由 argparse 拒绝。

- `--console_log true` / `--console_log false` 正确覆盖已存值；该参数仍要求显式值。
- `--force_init` 和 `--frontend_force_build` 裸开关继续等于 `true`。
- 两个开关也支持显式 `true` / `false`，取消勾选后无需先保存即可启动。
- 三个参数未出现时仍使用 `argparse.SUPPRESS`，不覆盖已存方案。

## 人工验收

开发助手AI未运行应用、构建、自动化测试、语法检查或类型检查。本次只做源码与差异的静态审阅，以下由用户执行：

1. 无配置时新建方案，确认显示 12 项正确默认值，不出现旧模型字段。
2. 读取含旧 `llm_*` 字段的方案，保存路径或端口后确认旧字段和其他方案仍保留。
3. 编辑两个仓库目录，分别检查保存后重读和不保存直接启动的行为。
4. 将三项布尔值分别保存为 `true`，再取消勾选并直接启动，确认均可显式覆盖为 `false`；已存方案保持原值。
5. 输入空整数、`12abc`、`1.5`、`1e3`、超安全整数、越界端口或负阈值，确认保存和启动被阻止，首个错误字段可定位；修正后能够提交。
6. 制造配置文件读写拒绝或损坏，确认显示错误；保存失败时原始输入和修改状态保留，不显示已保存。
7. 检查配置表单在短窗口内可滚动，字段名称、说明、错误和键盘焦点清晰可见。
8. 确认模型配置仍在应用内配置 Tab 操作，Python 路径仍独立保存。

## 实施记录

2026-10-29：按已批准的配置项更新计划完成源码调整与文档登记。关闭接口、进程生命周期和安装包工作继续延期；当前状态为待用户人工验收。

2026-10-29 18:00:17：完成字段默认值、共享脚本加载、IPC 调用配对、有效字段保存合并、布尔覆盖及改动范围的静态复核。新增文件为本开发文档和 `src/config-fields.json`；未读取或修改实际配置及运行时文件，未运行校验、构建或应用。
