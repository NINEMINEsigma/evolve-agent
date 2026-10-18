# 本地化视频制作器

这是基于 `ai-promo-video-maker` 的 Windows / Evolve Agent 本地化版本，核心渲染技术仍是 **Remotion + React + TypeScript**，并保留原仓库 MIT 许可。

## 支持范围

- 产品宣传片：真实界面、真实作品、配乐、旁白、CTA、网页播放器。
- 研究报告可视化与教学动态图解：公式、SVG、数据图、纯代码动画、底部字幕。
- `silent` 完全静音、`music` 配乐/音效、`voice` 配乐/旁白三种音频模式。
- 16:9、9:16 或自定义画幅；Remotion MP4、独立 SRT 和网页版。
- Windows 命令与路径：`python`、`npm.cmd`、Node 渲染脚本、运行时选择的临时网页端口。

## 使用方法

作为技能调用时，先读 `SKILL.md` 和 `AGENTS.md`。项目文件放在当前工作区的 `projects/` 子目录，不写入技能目录。

```powershell
# 复制 template 后，在项目工程目录执行
npm.cmd ci --no-audit --no-fund
python scripts/doctor.py
npm.cmd run lint
npm.cmd run test:content
npm.cmd run fonts
npm.cmd run check:assets
npm.cmd run stills -- --scenes --scale 0.5
npm.cmd run sheet
npm.cmd run render:preview
npm.cmd run render:1080
npm.cmd run validate:video -- out/final-1080p.mp4
npm.cmd run web:build
npm.cmd run web:serve  # 输出实际临时 URL；不要假设 Gateway 或固定端口
```

如果本机已有 Playwright Chromium，可先设置 `PROMO_BROWSER_EXECUTABLE`，避免 `stills.mjs` 或 Remotion 重复下载浏览器内核。复制模板后清理/隔离未使用的示例场景，并用 `tsconfig.web.json` 检查网页入口。网页播放器的音频和字体资源使用相对路径，确保子目录部署有效。

修改 `src/timing.json` 的 `audio.mode`：

```json
{"audio":{"mode":"silent"}}
```

静音项目不需要 `public/audio/mix.wav`；有音乐或旁白时才运行 `python scripts/mix.py`。字幕写入 `subtitles` 后运行 `python scripts/srt.py` 导出 SRT。

## 目录说明

- `SKILL.md`：技能入口与触发范围。
- `AGENTS.md`：完整工作规范。
- `references/`：需求、风格、素材、音乐、配音、校验、踩坑和案例方法。
- `template/`：每个新项目的唯一工程骨架。
- `LICENSE`：原仓库 MIT 许可。

不要把 `.env`、API key、`node_modules`、渲染缓存或正式成片写进本技能目录。
