---
name: promo-video-maker
description: 使用 Remotion、React 和 TypeScript 制作产品宣传片、产品介绍视频、研究报告可视化视频、教学动态图解或预告片；支持 Windows 本地化工程、16:9/9:16、底部字幕/SRT、静音/配乐/旁白、真实素材、网页播放版、音频混音和成片校验。用户提到“做宣传片”“产品介绍视频”“推广视频”“研究可视化视频”“教学动画”“Remotion 视频”或要求把报告做成视频时使用；即使用户没有明确说 Remotion，只要任务需要可编辑、可渲染的动态图解视频，也应优先加载本技能。
---

# 本地化视频制作技能

完整规范在同目录的 `AGENTS.md`。开始任务前先用文件读取工具完整阅读它；按任务类型再读取 `references/` 中对应文档。

## 本地化约定

- 本技能面向 Windows 上的 Evolve Agent；命令使用 `python`、`npm.cmd` 和 Node 脚本，不假设 Bash、`python3`、`mkdir -p` 或 `/tmp/`。
- 原始仓库只作为来源，不在本技能目录内写项目产物。项目放在当前工作区的 `projects/` 或主人指定的独立子目录中。
- 使用当前工具时：结构化提问使用 `Ask`，问题标题简短、说明放 `detail`；文件读取使用 `Read`；文件修改使用 `Write`/`PatchEdit`；浏览器验证优先使用 Browser 工具。
- 不要把 API key 写进聊天或代码。ElevenLabs key 只从工作区 `.env` 或环境变量读取。
- 交付前必须告诉主人哪些内容需要亲耳试听或亲自审美，不把波形和自动检测冒充主观验收。

## 第一条规则

没有完成需求确认前，不开始制作。确认至少包括：主题/报告、受众、时长、画幅、风格、叙事、字幕、声音模式、导出规格和是否需要网页播放版。用户明确确认后，才复制模板、安装项目依赖和生成产物。

## 两类工作模式

- `promo`：产品/网站/App/项目宣传片。真实界面和真实作品是主角，保留产品卖点、CTA、素材出处和试听环节。
- `research` / `teaching`：研究报告或教学动态图解。允许纯 SVG、公式、数据图、代码绘制和示意动画；不强制真实截图配额、CTA 或快切蒙太奇。事实、数学、引用和字幕可读性优先。

## 声音模式

在 `src/timing.json` 的 `audio.mode` 中声明：

- `silent`：完全静音，跳过音频文件和音频时钟。
- `music`：配乐/音效，无旁白。
- `voice`：配乐/音效/旁白，使用模板 `scripts/elevenlabs.py vo` 和 `check-mix`。

画面、字幕、音频都必须从同一份 `timing.json` 读取，避免改了分镜后音效或字幕错位。

## 标准流程

1. **回看经验与加载参考**：读取本技能、`references/踩坑记录.md`、对应的需求/素材/音乐/校验文档；把历史错误转成检查项。
2. **环境体检**：在新工程外运行 `python template/scripts/doctor.py`；建立工程后再在工程目录运行一次。它只检查，不安装。
3. **预调研**：报告模式先读报告并核实关键事实；宣传模式先核实产品状态、第一手素材、受众和卖点。
4. **需求问询**：用 `Ask` 一次批量询问相关问题，给出针对主题的推荐项；风格方向需要样帧或代码示意。把结论写入 `需求确认.md`，等待明确确认。
5. **创建工程**：复制 `template/` 到独立项目的 `工程/`，使用模板自带的 lockfile 安装依赖；不要在技能模板目录运行会生成文件的命令。
6. **设计时间轴**：编辑 `src/timing.json`，确定 `fps/width/height/duration/scenes/subtitles/audio`。字幕列表可由 `python scripts/srt.py` 导出为独立 SRT。
7. **实现视觉系统**：重写 `theme.ts`，为每个场景建组件，使用 `anim.ts` 的时间插值和缓动；研究/教学视频用图解和公式，宣传片用真实界面/作品容器。
8. **准备素材与声音**：字体运行 `npm.cmd run fonts`；宣传模式按素材文档登记来源；音乐模式先分析节拍并让主人试听，旁白模式先试听音色再全量生成；静音模式不创建音频占位文件。
9. **分层验证**：按“类型检查 → 内容/数学断言 → 关键帧 → 联系表 → 网页构建/浏览器 → 低分辨率试片 → 正式渲染 → ffprobe/全解码/帧差/音频”顺序执行。浏览器失败要如实记录，不能虚报。
10. **交付**：至少整理 MP4、SRT（若有字幕）、源码、README、需求确认、调研/事实笔记和校验记录；网页产物放项目的 `网页版/` 或部署到当前 Session Site。
11. **改版**：先把主人的原话写进修改记录；按改动范围只重做必要步骤；旧成片先放进工程 `out/版本备份/`；模板同步先比较差异再应用。

## Windows 命令基线

在工程目录执行：

```powershell
npm.cmd ci --no-audit --no-fund
npm.cmd run lint
npm.cmd run fonts
npm.cmd run check:assets
npm.cmd run stills -- --scenes
npm.cmd run sheet
npm.cmd run render:preview
npm.cmd run render:1080
npm.cmd run validate:video -- out/final-1080p.mp4
npm.cmd run web:build
npm.cmd run web:serve
```

`render.mjs` 负责创建 `out/`、转发渲染日志并正确传播退出码；网页服务端口通过环境变量或临时服务脚本配置，不能假设 Gateway 的地址、端口或其他启动参数。

## 输出与验证原则

- 研究/教学视频可以没有真实网页截图、配乐或 CTA，但必须有清晰的主线、可读字幕和事实/数学验证。
- 不把低分辨率试片当正式交付。
- `freezedetect` 只表示低动态，不等于画面冻结；结合实际帧差和联系表判断。
- 交付网页必须使用相对资源路径，真实浏览器访问 `serve.mjs` 输出的实际 URL；不要用 `file://` 代替交付验证，也不要假设 Gateway 的地址或端口。
- 网页声音只有在 `music`/`voice` 模式启用；静音模式不可因缺少 `mix.wav` 失败。静音网页的帧时钟必须依据实际经过时间计算，且 Player 设置 `numberOfSharedAudioTags={0}`。
- 新项目复制模板后，先清理或隔离不再使用的示例场景文件，避免旧的 `keyof timing.scenes` 类型约束让 `tsc` 失败；同时用 `tsconfig.web.json` 单独检查网页入口。
- `render.mjs` 和 `stills.mjs` 支持 `PROMO_BROWSER_EXECUTABLE`；本机已有 Playwright Chromium 时优先传入其路径，避免重复下载浏览器内核。
- 只有一个播放源；测试页播放后立即暂停并关闭，避免叠音。

## 参考文档索引

- `references/需求问询.md`：需求问题、风格样帧、确认模板。
- `references/风格方向.md`：视觉和叙事菜单，不能机械套用。
- `references/素材获取.md`：真实素材、网页截图、字体和图片处理。
- `references/音乐与卡点.md`：曲库/ElevenLabs、节拍网格、混音。
- `references/配音.md`：音色试听、旁白生成、转写和换音轨。
- `references/校验清单.md`：自动闸门、审图和交付检查。
- `references/踩坑记录.md`：先读，尤其是网页音频、Windows、字体和渲染问题。
- `references/案例复盘.md`：只学习方法，不复制既有项目的风格。

原仓库的 MIT 许可保留在本技能包的 `LICENSE` 中。