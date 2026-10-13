# dev_helpers/ — 开发辅助代码

本目录服务于开发者与开发助手AI，不属于 origin仓库，不会派生到运行时仓库。脚本可配置导入路径，复用 origin仓库数据模型与无启动副作用的库接口，以及只读 third库；这与直接启动 origin仓库应用不同，不允许导入/执行 `run.py`、`config.py`、应用入口或创建 Application，也不读取运行时仓库代码。导入依赖前禁写Python字节码，避免在源码目录生成 `__pycache__`。

## History辅助读取

`read_history.py` 复用 `third/easysave.raw_load()`、`origin_agent/entity/typeref.py::make_config()`、正式 `History` / 媒体类型和 `History_Version`，读取指定 `.es`（或显式指定的 `.es.bak`），还原真正的项目 `History` 实例，再生成媒体占位JSON。辅助代码仅负责展示：通过 BaseModel公开迭代接口保留当前模型字段与嵌套类型，不复制模型字段表，不重写 easysave引用/容器/枚举协议。依赖项目现有Python环境（包含Pydantic），不是纯标准库脚本。

原History和媒体块保持不变，占位符只出现在新生成的输出字典中；该字典不是可回写历史格式。`load_history()` 返回真正的History供开发辅助代码复用，其媒体仍是原载荷，因此不要直接打印返回模型；应调用 `build_view()` 或使用命令行。

开发助手AI应先读取摘要，再按消息索引读取小范围正文，避免直接读取原始 `history.es`。以下命令在仓库根目录执行，也可以使用脚本的绝对路径从其他目录执行：

```powershell
python dev_helpers/read_history.py --session cc5108dd59ca --summary
python dev_helpers/read_history.py --session cc5108dd59ca --start 8 --limit 1
python dev_helpers/read_history.py --session cc5108dd59ca --start 17 --limit 1
```

`--session` 是精确的会话目录名，不扫描目录、不猜测前缀；默认会话根为相对于脚本位置的 `workspace/sessions/`，与当前命令目录无关。自定义部署可通过 `--sessions-root` 指定会话根，或通过 `--path` 指定主会话/子会话/备份的单个文件：

```powershell
python dev_helpers/read_history.py --path "D:\__TEMP__\evolve-agent\workspace\sessions\cc5108dd59ca\history.es" --summary
```

### 输出约定

- easysave负责还原共享引用、容器和枚举；项目类型映射负责稳定名解析。输出类型名也复用easysave的 `type_format()`（当前定义于 `private.util`），不维护第二套类型格式逻辑。保留消息/块的 `__type`，保持磁盘消息顺序及未配对工具调用。`last_user_message` 以消息索引输出，避免重复正文。
- `ImageBlock.image_url`、`VideoBlock.video_url`、`AudioBlock.data` 均替换为占位对象，包括媒体类型、编码、MIME类型及原载荷字符数；普通远程媒体URL同样不输出。`media_id`、来源、工具关联、发送开关、可信描述标记及文字描述仍保留。
- 普通文本中的内联 data URL 也替换为短标记。它不是通用秘密脱敏器：任意文本/字典中的无前缀Base64、密钥和用户正文不保证被识别，输出仍可能含敏感信息。
- `media_counts` / `media_inventory` 描述整份 History中的媒体块出现位置，不按URL或内容去重，也不再次计算 `last_user_message` 的引用。库存不包含图片/音视频的真实载荷。
- `range` 使用原消息的 0-based 半开区间 `[start, stop)`，`remaining` 是该区间后的消息数。`--summary` 不输出正文；它仍统计全历史媒体。
- 默认 `--start 0 --limit 10`。每个文字字段默认最多4000字符，可通过 `--max-text-chars` 调整；超限追加明确标记，并在 `truncated_fields` 列出字段位置。工具参数/结果中的JSON字符串被截断后不能作为完整JSON使用。需要全文时显式提高有限上限并缩小消息范围。
- 总JSON输出默认最多24000字符，由 `--max-output-chars` 调整；超预算直接失败，不打印正文，也不截出无效JSON。媒体清单过大时摘要也可能超预算，需明确提高上限。
- `source` 包含输入路径、ES key、读取字节数及SHA-256，方便比较不同读取是否使用相同内容。默认 key 直接取项目 `History_Version`（当前为 `v1`），根类型必须是正式 `History`；类型兼容性遵循项目 `make_config()` 和easysave的规则，不在辅助脚本中硬编码版本/稳定名白名单。

### 安全与失败行为

脚本只读指定文件、只向stdout输出，不写入任何会话文件，不恢复备份、不生成派生历史、不启动应用、不调用模型。easysave读取的是同一次 `read_bytes()` 得到的JSON快照，指纹对应相同字节；调用正式 `raw_load()` 还原真实模型而不是维护第二套解码器。已有文件损坏、类型不支持、引用缺失或模型结构错误直接失败，不忽略未知字段，不返回空历史掩盖错误。它不调用 `SessionStore.read_history()`，因该业务接口会清理未配对工具调用。

**只读取受信任的本地项目历史。** 官方easysave会按存储类型导入模块并重建实例，因此该工具不是处理任意外来 `.es` 的安全沙盒。预期History类型的导入不创建Application或启动服务；不要把文件扩展名和加载后的根类型检查误当作反序列化安全隔离。

脚本会完整读取并还原输入对象图，降低的是开发助手AI的上下文占用，不是文件读取量或内存占用。`last_user_message` 与messages中的共享引用由easysave保留；若待展示消息字段存在循环，展示逻辑明确失败，避免无限展开。遇到新增、不受支持的 `MediaBlock` 子类会快速失败，必须显式定义其载荷占位规则后才能输出，不能静默泄漏媒体。

开发助手AI执行本脚本仍须遵守用户授权与运行时目录保护规则：不得借此扫描 `workspace/` 或读取代码文件。用户授权读取具体会话时，输入应限定到该会话非代码持久化文件；自动化校验、构建与应用启动仍需单独授权。

### 已授权实际读取记录（2026-10-14）

用户授权开发助手AI自行测试读取 `cc5108dd59ca` 会话。实际读到：23条消息（user 9、assistant 10、tool 4），两张PNG图片位于索引8、17；图片Base64分别为1,160,256和3,422,772字符，均在输出中替换为占位符。两条消息的 `forward_result_content` 保留，并在1000字符展示上限下明确标注截断；发送开关分别为开启、关闭。原文件4,720,963字节，多次读取指纹一致。摘要JSON仅1723字符；另读取索引6–8，确认工具调用、工具结果及其后图片消息的顺序和关联保留。以100字符总输出上限读取同一会话摘要时，脚本明确失败且未打印历史正文。后续会话变化后这些计数和指纹可能改变。

复用修订后再次执行同一会话的摘要读取，以及索引8、17的单消息读取（文字上限200字符）：正式 `History` 已还原，两张图片仍正确占位，23条消息、末条用户消息索引21、媒体身份及发送开关均与此前结果一致，输入文件SHA-256仍为 `d61b8009cd101c74244fd231738de4dd2b5f8f0c7c125af791d5566543959cc7`。辅助代码的 `load_history()` 现在返回真实History；原独立对象图解码器已移除。

该记录仅证明已授权会话的实际读取路径与两张图片占位输出；未声称音频、视频、损坏文件或其他部署场景已经运行验证，未执行构建、类型检查或应用启动。
