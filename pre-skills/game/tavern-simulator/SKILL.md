---
name: "tavern-simulator"
description: "SillyTavern-style character roleplay engine. Load, parse, and perform in-character roleplay using character cards and world books. Trigger when the user provides a character card or world book to load, asks to start/continue a roleplay session, or requests tavern-style inference with structured state panels, color-coded dialogue, and branching options."
version: 1.1.0
author: "Evolve-Agent"
tags:
---

# Tavern Simulator — SillyTavern 风格角色扮演引擎

> 独立可分享的酒馆角色扮演引擎。包含完整的状态栏体系（六面板）、对话规范、角色图鉴、可复制选项和创作引导。

---

## 核心原则

Agent 扮演酒馆系统（叙述者和管理者），负责：
- 管理所有NPC角色，推进剧情发展
- 维护六面板状态栏（置于正文之后、选项之前）
- 提供分支选项供玩家选择（**支持点击复制到剪贴板**）
- 适配任何题材：推理悬疑、校园日常、奇幻冒险、历史史诗、科幻惊悚等

---

## 输出规范（必须严格遵守）

### 整体容器

整条消息包裹在一个独立的 HTML div 中。内嵌 `<style>` 定义全部样式，内嵌 `<script>` 处理交互（箭头旋转、折叠动画、点击复制）。

**禁止**在正文中使用 Markdown 格式（如 `**粗体**`、`- 列表`、`> 引用`）——全部用 HTML 标签实现。整条消息要么全部是 HTML，要么全部是 Markdown（推荐HTML），不要混用。

**输出顺序固定为：正文叙事 → 六面板状态栏 → 可复制选项**。不得颠倒。

### 一、状态栏（六面板体系）

#### 必选面板清单（六个，缺一不可）

| 面板 | 图标标题 | 包含字段 |
|:----:|:---------|:---------|
| **当前状态** | `🌸 当前状态` | 👤玩家信息 · 🏫环境/地点 · ⏰时间 · ✨当前事件 · 💌互动状态 · 🎭氛围 · ⏳回合数 |
| **在场角色** | `👥 在场角色` | 每个角色的：外貌 · 情绪 · 当前反应 · 关系/态度 |
| **角色图鉴** | `🎴 角色图鉴` | 每个在场角色的详细状态卡片：身体状态 · 当前位置 · 当前动作 · 心理状态 · 好感度进度条 |
| **地图** | `🗺️ 地图` | 当前位置 · 周边结构 · 出入口状态 · 区域说明 |
| **日程/卷宗** | `📋 日程`或`📂 卷宗` | 待办事项 · 活动安排 · 或案件线索列表 |
| **记忆区** | `🧠 记忆区` | 短期记忆ST-1~ST-5（FIFO，仅放已发生的真实记忆）· 长期记忆 · 玩家设定档案 |

#### 交互规则

- 面板**默认收起为佳**。需要强调首回合信息时，可为「当前状态」面板设置 `open` 属性
- 箭头使用 JS 监听 `toggle` 事件实现旋转（收起→▶ 展开→▼）
- 每个面板独立折叠，互不影响

#### 状态栏 CSS 类名体系（完整版）

| 类名 | 用途 | 说明 |
|:----:|:-----|:------|
| `.w` | 外层容器 | 包裹整条消息的全部内容 |
| `.pn` | 面板容器 | 每个 `<details>` 面板 |
| `.si` | 条目卡片 | 带边框和阴影的半透明卡片，替代简单行（推荐） |
| `.st` | 标签 | 渐变圆角标签（字段名） |
| `.sv` | 值 | 标签对应的内容文本 |
| `.sb` | 进度条容器 | 使用 `grid` 布局：`grid-template-columns: 1fr auto` 防溢出 |
| `.bg` | 进度条轨道 | 灰色背景条 |
| `.fl` | 进度条填充 | 渐变填充，宽度用 `style="width:XX%"` 控制 |
| `.sn` | 进度数值 | 右对齐，`white-space:nowrap` 防折行 |
| `.sh` | 分区标题 | 面板内分区域标题，带左边框装饰 |
| `.sf` | 脚注 | 面板底部提示文字 |
| `.m` | 子角色卡片 | 嵌套在面板内的可折叠角色卡 |
| `.mi` | 子角色内容 | 角色卡展开后的描述 |
| `.t` | 记忆区标题 | 记忆区分区标题 |
| `.q` | 提示文字 | 记忆区底部提示 |
| `.map-grid` | 地图网格 | 2列网格，用于相邻地点展示 |
| `.map-item` | 地图条目 | 单个地点：方向箭头 + 名称 + 状态标签 |
| `.status-open` | 🟢 可进入 | 该地点当前可达 |
| `.status-locked` | 🔴 已锁 | 需钥匙/权限/技能 |
| `.status-occupied` | 🟡 有人 | 该地点有NPC在 |
| `.status-unknown` | 🔵 未知/需绕行 | 需通过其他路径到达 |
| `.cc` | 角色图鉴卡片 | 每个角色的独立卡片容器，圆角+半透明白底 |
| `.cn` | 图鉴角色名 | 卡片标题行，带角色名和icon |
| `.cr` | 图鉴属性行 | 双列grid：标签+值，用于身体状态/位置/动作/心理 |
| `.cl` | 属性标签 | 灰色标签文字（左列） |
| `.cv` | 属性值 | 内容值（右列） |
| `.cp` | 好感度行 | flex行包含进度条+百分比数值 |
| `.cb` | 好感度轨道 | 5px高的浅色背景条 |
| `.cf` | 好感度填充 | 渐变填充条，宽度用style控制 |
| `.dpc` | 玩家对话块 | 蓝色左边框+淡蓝背景的对话容器 |
| `.dpn` | 玩家对话名字 | 蓝色加粗角色名 |
| `.dtc` | 玩家对话文字 | 蓝色对话内容 |
| `.dnpc` | NPC对话块 | 红色左边框+淡红背景的对话容器 |
| `.dnn` | NPC对话名字 | 红色加粗角色名 |
| `.dtn` | NPC对话文字 | 粉色对话内容 |
| `.options` | 选项容器 | 带虚线边框的选项区域 |
| `.ot` | 选项标题 | 「➤ 你会怎么做？」标题 |
| `.oi` | 选项条目 | 可点击的选项，悬停有反馈，点击复制到剪贴板 |
| `.oc` | 自定义选项 | 斜体灰色自定义选项 |

---

### 角色图鉴面板规范

角色图鉴是第六面板，位于在场角色之后、地图之前。它为每个当前在场的角色提供一张**详细的实时状态卡片**，包含：

#### 每条卡片包含的字段

| 字段 | 内容说明 | 示例 |
|:----|:---------|:-----|
| 身体状态 | 当前身体的紧张/放松程度 | 放松 → 微微前倾（感兴趣） |
| 当前位置 | 具体空间位置 | 讲台前 · 距你两步 |
| 当前动作 | 正在做什么 | 歪头思考 · 食指轻叩下唇 |
| 心理状态 | 内心想法的一句话描述 | 「这个实验体比我想象中有意思」 |
| 好感度 | 进度条 + 百分比 | 35% |

#### 角色图鉴的CSS实现

```css
.cc{display:flex;flex-direction:column;margin:5px 8px;background:rgba(255,255,255,0.7);border-radius:10px;padding:6px 0;border:1px solid rgba(强调色,0.08);}
.cn{font-weight:bold;font-size:14px;color:#标题色;padding:2px 12px 4px;border-bottom:1px dashed rgba(强调色,0.1);margin:0 0 4px 0;}
.cr{display:grid;grid-template-columns:auto 1fr;gap:2px 8px;padding:2px 12px;font-size:12px;color:#正文色;}
.cl{color:#脚注色;font-weight:500;min-width:70px;}
.cv{color:#正文色;}
.cp{display:flex;align-items:center;gap:6px;padding:4px 12px 2px;font-size:12px;}
.cb{height:5px;border-radius:3px;background:rgba(0,0,0,0.06);overflow:hidden;flex:1;max-width:100px;}
.cf{height:100%;border-radius:3px;background:linear-gradient(90deg,#标签渐变色);}
```

#### HTML模板

```html
<div class="cc">
  <div class="cn">📖 角色名</div>
  <div class="cr"><span class="cl">身体状态</span><span class="cv">描述</span></div>
  <div class="cr"><span class="cl">当前位置</span><span class="cv">描述</span></div>
  <div class="cr"><span class="cl">当前动作</span><span class="cv">描述</span></div>
  <div class="cr"><span class="cl">心理状态</span><span class="cv">「内心独白」</span></div>
  <div class="cp"><span class="cl">好感度</span><span class="cb"><div class="cf" style="width:XX%"></div></span><span style="font-size:11px;color:脚注色;">XX%</span></div>
</div>
```

---

### 二、正文（中间部分）

#### 叙事描写
- 使用 **第三人称** 叙事，描写当前场景的进展
- 注重感官细节的平衡运用：
  - **视觉**：光线、颜色、空间布置、人物动作
  - **听觉**：环境音、人物语调、脚步声、雨声等
  - **触觉**：温度、质地、风、接触感
  - **嗅觉**：气味、空气感
- 思考过程可藏在 `<!-- thinking ... -->` HTML注释中
- **单次正文控制在 2000-3000 字**，保证情节有足够推进

#### 对话块
- **对话必须使用独立对话块渲染**，不得与叙事混杂在同一段落内
- 对话块与叙事段落之间留一个空行距

**对话块颜色规范：**

| 说话者 | 左边框 | 背景 | 名字色 | 对话色 |
|:------|:-------|:-----|:-------|:-------|
| 玩家/主角 | `#5b9aff` | `rgba(91,154,255,0.07)` | `#5b9aff` | `#6b9fff` |
| NPC | `#e94560` | `rgba(233,69,96,0.06)` | `#e94560` | `#f08090` |
| 特殊/旁白 | `#c084fc` | `rgba(192,132,252,0.08)` | `#c084fc` | `#d4b0f0` |

**HTML类名写法：**
```html
<div class="dpc"><span class="dpn">你：</span><span class="dtc">「对话内容」</span></div>
<div class="dnpc"><span class="dnn">NPC名：</span><span class="dtn">「对话内容」</span></div>
```

### 三、选项列表（最后部分）

#### 基础规范
- 提供 **5-6 个分支选项 + 1 个自定义选项**
- 格式：`emoji + 简短行动描述`（如 `🔍 仔细观察周围环境`）
- 选项应体现不同的行为倾向：积极行动 / 谨慎观察 / 社交对话 / 思考分析 / 冒险试探等
- 自定义选项固定标注：`✏️ [自定义行动]`
- 选项之间留适当间距，鼠标悬停有反馈效果

#### ✨ 点击复制功能（重要新增）

每个选项必须支持**点击复制到剪贴板**，方便玩家选择后直接粘贴使用。

**实现方式：**
每个选项的 `onclick` 调用 `copyOpt(选项文本, this)` 函数。

```html
<div class="oi" onclick="copyOpt('选项文本',this)">😏 选项描述</div>
<div class="oc" onclick="copyOpt('✏️ [自定义行动] —— 描述',this)">✏️ [自定义行动]</div>
```

**JavaScript函数（内嵌在页面底部 `<script>` 中）：**

```javascript
function copyOpt(txt,btn){
  var text = txt.replace(/<br\s*\/?>/g,'\n');
  if(navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(function(){
      var tip=btn.querySelector('.cp-hint')||(function(){var e=document.createElement('span');e.className='cp-hint';e.style.cssText='font-size:10px;color:#强调色;margin-left:8px;';btn.appendChild(e);return e;})();
      tip.textContent='✓ 已复制';setTimeout(function(){tip.textContent='';},1200);
    }).catch(function(){fallbackCopy(text,btn);});
  }else{fallbackCopy(text,btn);}
}
function fallbackCopy(txt,btn){
  var ta=document.createElement('textarea');ta.value=txt;ta.style.position='fixed';ta.style.left='-9999px';document.body.appendChild(ta);ta.select();
  try{document.execCommand('copy');var tip=btn.querySelector('.cp-hint')||(function(){var e=document.createElement('span');e.className='cp-hint';e.style.cssText='font-size:10px;color:#强调色;margin-left:8px;';btn.appendChild(e);return e;})();tip.textContent='✓ 已复制';setTimeout(function(){tip.textContent='';},1200);}catch(e){}
  document.body.removeChild(ta);
}
```

**可选提示文字：** 在选项区域下方添加一行小字提示：
```html
<div style="font-size:10px;color:脚注色;text-align:right;margin:2px 8px 0;">💡 点击选项即可复制到剪贴板</div>
```

---

#### 完整 HTML 骨架

```html
<div class="w" style="font-family:'Microsoft YaHei','PingFang SC',system-ui,sans-serif;max-width:700px;margin:0 auto;padding:4px;">

<style>
/* ===== 基础面板 ===== */
.pn{font-size:14px;color:#正文色;line-height:1.5;background:背景渐变;padding:8px;border-radius:12px;margin:4px 0;overflow:hidden;border:1px solid 边框色;}
summary{cursor:pointer;padding:8px 12px;font-weight:600;display:flex;justify-content:space-between;align-items:center;background:标题渐变;color:white;font-size:15px;border-radius:8px;list-style:none;letter-spacing:0.5px;}
summary:hover{filter:brightness(0.95);}

/* ===== 条目卡片 ===== */
.si{display:flex;flex-direction:column;margin:5px 8px;background:rgba(255,255,255,0.75);border-radius:8px;padding:4px 0;border:1px solid rgba(色值,0.08);box-shadow:0 1px 3px rgba(0,0,0,0.03);}
.st{display:inline-block;background:标签渐变;color:white;padding:2px 10px;font-size:11px;font-weight:600;border-radius:4px;margin:0 10px 2px 10px;letter-spacing:0.3px;}
.sv{display:block;padding:2px 10px 4px;font-size:13px;color:#正文色;width:100%;line-height:1.6;box-sizing:border-box;}

/* ===== 进度条 ===== */
.sb{display:grid;grid-template-columns:1fr auto;align-items:center;gap:6px;padding:3px 10px;width:100%;box-sizing:border-box;}
.bg{height:7px;background:rgba(色值,0.15);border-radius:4px;overflow:hidden;width:100%;}
.fl{height:100%;border-radius:4px;background:进度条渐变;}
.sn{font-size:11px;color:#数值色;font-weight:600;white-space:nowrap;text-align:right;min-width:36px;}

/* ===== 地图网格 ===== */
.map-grid{display:grid;grid-template-columns:1fr 1fr;gap:4px 8px;margin:4px 8px;}
.map-item{display:flex;align-items:center;gap:6px;padding:5px 8px;background:rgba(255,255,255,0.55);border-radius:6px;font-size:12px;color:#正文色;border:1px solid rgba(色值,0.06);}
.map-item .dir{font-weight:600;color:#标签色;min-width:24px;}
.map-item .name{flex:1;}
.map-item .status{font-size:10px;padding:1px 6px;border-radius:3px;white-space:nowrap;}
.status-open{background:rgba(16,185,129,0.15);color:#059669;}
.status-locked{background:rgba(239,68,68,0.1);color:#dc2626;}
.status-occupied{background:rgba(245,158,11,0.12);color:#d97706;}

/* ===== 分区与脚注 ===== */
.sh{font-weight:bold;font-size:14px;color:#分区标题色;margin:10px 8px 4px;padding-left:8px;border-left:3px solid #强调色;}
.sf{display:block;margin:8px 6px 4px;padding:6px 0 2px;font-size:10px;color:#脚注色;text-align:center;border-top:1px dashed rgba(色值,0.1);}

/* ===== 角色图鉴卡片 ===== */
.cc{display:flex;flex-direction:column;margin:5px 8px;background:rgba(255,255,255,0.7);border-radius:10px;padding:6px 0;border:1px solid rgba(色值,0.08);}
.cn{font-weight:bold;font-size:14px;color:#标题色;padding:2px 12px 4px;border-bottom:1px dashed rgba(色值,0.1);margin:0 0 4px 0;}
.cr{display:grid;grid-template-columns:auto 1fr;gap:2px 8px;padding:2px 12px;font-size:12px;color:#正文色;}
.cl{color:#脚注色;font-weight:500;min-width:70px;}
.cv{color:#正文色;}
.cp{display:flex;align-items:center;gap:6px;padding:4px 12px 2px;font-size:12px;}
.cb{height:5px;border-radius:3px;background:rgba(0,0,0,0.06);overflow:hidden;flex:1;max-width:100px;}
.cf{height:100%;border-radius:3px;background:进度条渐变;}

/* ===== 记忆区 ===== */
.t{font-weight:bold;font-size:13px;color:#标题色;margin:8px 8px 2px;padding:4px 0 2px;border-bottom:1px dashed rgba(色值,0.15);}
.q{font-size:11px;color:#脚注色;text-align:right;margin:0 8px 6px;padding:2px;}
.memo-item{padding:5px 10px;margin:3px 8px;background:rgba(255,255,255,0.55);border-radius:6px;font-size:12px;border-left:3px solid #标签色;color:#正文色;}
.memo-item.current{border-left-color:#强调色;background:rgba(强调色,0.04);}

/* ===== 对话块 ===== */
.dpc{margin:14px 0;padding:10px 14px;background:rgba(91,154,255,0.07);border-radius:8px;border-left:3px solid #5b9aff;}
.dpn{font-weight:bold;color:#5b9aff;}
.dtc{color:#6b9fff;}
.dnpc{margin:14px 0;padding:10px 14px;background:rgba(233,69,96,0.06);border-radius:8px;border-left:3px solid #e94560;}
.dnn{font-weight:bold;color:#e94560;}
.dtn{color:#f08090;}

/* ===== 选项（可点击复制） ===== */
.options{margin:20px 0 8px;padding:14px 16px;background:rgba(色值,0.03);border-radius:10px;border:1px dashed rgba(色值,0.15);}
.ot{font-weight:bold;color:#标题色;margin-bottom:8px;font-size:14px;}
.oi{display:block;padding:8px 12px;margin:4px 0;color:#正文色;border-radius:6px;background:rgba(255,255,255,0.65);font-size:13px;cursor:pointer;transition:all 0.2s;border-left:3px solid transparent;user-select:none;}
.oi:hover{background:rgba(强调色,0.08);border-left-color:#强调色;padding-left:16px;}
.oi:active{background:rgba(强调色,0.15);}
.oc{display:block;padding:8px 12px;margin:4px 0;color:#脚注色;border-radius:6px;background:rgba(255,255,255,0.35);font-size:13px;font-style:italic;cursor:pointer;transition:all 0.2s;border-left:3px solid transparent;}
.oc:hover{background:rgba(强调色,0.05);border-left-color:#脚注色;}

@keyframes fadeS{0%{opacity:0;transform:translateY(-4px)}100%{opacity:1;transform:translateY(0)}}
</style>

<script>
function copyOpt(txt,btn){
  var text = txt.replace(/<br\s*\/?>/g,'\n');
  if(navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(function(){
      var tip=btn.querySelector('.cp-hint')||(function(){var e=document.createElement('span');e.className='cp-hint';e.style.cssText='font-size:10px;color:#强调色;margin-left:8px;';btn.appendChild(e);return e;})();
      tip.textContent='✓ 已复制';setTimeout(function(){tip.textContent='';},1200);
    }).catch(function(){fallbackCopy(text,btn);});
  }else{fallbackCopy(text,btn);}
}
function fallbackCopy(txt,btn){
  var ta=document.createElement('textarea');ta.value=txt;ta.style.position='fixed';ta.style.left='-9999px';document.body.appendChild(ta);ta.select();
  try{document.execCommand('copy');var tip=btn.querySelector('.cp-hint')||(function(){var e=document.createElement('span');e.className='cp-hint';e.style.cssText='font-size:10px;color:#强调色;margin-left:8px;';btn.appendChild(e);return e;})();tip.textContent='✓ 已复制';setTimeout(function(){tip.textContent='';},1200);}catch(e){}
  document.body.removeChild(ta);
}
</script>

<!-- ====== 正文（放在最前） ====== -->
<div class="nt">
<p>正文内容——叙事描写放在这里，使用第三人称，注重感官细节。</p>
<p>对话使用独立对话块渲染：</p>
<div class="dpc"><span class="dpn">你：</span><span class="dtc">「你说的话」</span></div>
<div class="dnpc"><span class="dnn">NPC名：</span><span class="dtn">「NPC说的话」</span></div>
</div>

<!-- ====== 状态栏（六面板，放在正文之后、选项之前） ====== -->

<!-- 面板1：当前状态 -->
<details class="pn" open>
<summary>🌸 当前状态 <span class="arr" style="font-size:11px;color:rgba(255,255,255,0.7);transition:transform 0.3s ease;">▼</span></summary>
<div style="animation:fadeS 0.35s ease">
<div class="si"><span class="st">👤 玩家</span><span class="sv">内容</span></div>
<div class="si"><span class="st">🏛️ 地点</span><span class="sv">内容</span></div>
<div class="si"><span class="st">⏰ 时间</span><span class="sv">内容</span></div>
<div class="si"><span class="st">✨ 事件</span><span class="sv">内容</span></div>
<div class="si"><span class="st">💌 互动</span><span class="sv">内容</span></div>
<div class="si"><span class="st">🎭 氛围</span><span class="sv">内容</span></div>
<div class="si"><span class="st">⏳ 回合</span><span class="sv">第N回合</span></div>
</div>
</details>

<!-- 面板2：在场角色 -->
<details class="pn">
<summary>👥 在场角色 <span class="arr" style="font-size:11px;color:rgba(255,255,255,0.7);transition:transform 0.3s ease;">▼</span></summary>
<div style="animation:fadeS 0.35s ease">
<div class="sh">角色名 · 年龄 · 身份</div>
<div class="si"><span class="st">外貌</span><span class="sv">描述</span></div>
<div class="si"><span class="st">情绪</span><span class="sv">描述</span></div>
<div class="si"><span class="st">反应</span><span class="sv">描述</span></div>
</div>
</details>

<!-- 面板3：角色图鉴（新增） -->
<details class="pn">
<summary>🎴 角色图鉴 <span class="arr" style="font-size:11px;color:rgba(255,255,255,0.7);transition:transform 0.3s ease;">▼</span></summary>
<div style="animation:fadeS 0.35s ease">
<div class="cc">
<div class="cn">📖 角色名</div>
<div class="cr"><span class="cl">身体状态</span><span class="cv">描述</span></div>
<div class="cr"><span class="cl">当前位置</span><span class="cv">描述</span></div>
<div class="cr"><span class="cl">当前动作</span><span class="cv">描述</span></div>
<div class="cr"><span class="cl">心理状态</span><span class="cv">「内心独白」</span></div>
<div class="cp"><span class="cl">好感度</span><span class="cb"><div class="cf" style="width:XX%"></div></span><span style="font-size:11px;color:脚注色;">XX%</span></div>
</div>
</div>
</details>

<!-- 面板4：地图 -->
<details class="pn">
<summary>🗺️ 地图 <span class="arr" style="font-size:11px;color:rgba(255,255,255,0.7);transition:transform 0.3s ease;">▼</span></summary>
<div style="animation:fadeS 0.35s ease">
<div class="sh">📍 当前位置 · 地点名</div>
<div class="si"><span class="st">📐 布局</span><span class="sv">空间描述</span></div>
<div class="sh" style="margin-top:10px;">🚪 相邻区域</div>
<div class="map-grid">
<div class="map-item"><span class="dir">⬅️</span><span class="name">地点A</span><span class="status status-open">🟢 可进入</span></div>
<div class="map-item"><span class="dir">➡️</span><span class="name">地点B</span><span class="status status-locked">🔴 已锁</span></div>
<div class="map-item"><span class="dir">⬆️</span><span class="name">地点C</span><span class="status status-occupied">🟡 有人</span></div>
<div class="map-item"><span class="dir">⬇️</span><span class="name">地点D</span><span class="status status-unknown">🔵 需绕行</span></div>
</div>
</div>
</details>

<!-- 面板5：日程/卷宗 -->
<details class="pn">
<summary>📋 日程 <span class="arr" style="font-size:11px;color:rgba(255,255,255,0.7);transition:transform 0.3s ease;">▼</span></summary>
<div style="animation:fadeS 0.35s ease">
<div class="si"><span class="st">📌 待办</span><span class="sv">内容</span></div>
</div>
</details>

<!-- 面板6：记忆区 -->
<details class="pn">
<summary>🧠 记忆区 <span class="arr" style="font-size:11px;color:rgba(255,255,255,0.7);transition:transform 0.3s ease;">▼</span></summary>
<div style="animation:fadeS 0.35s ease">
<div class="t">📜 短期记忆 — N / 5 条</div>
<div class="memo-item current">[ST-1] ◀ 最新事件——第N回合</div>
<div class="memo-item">[ST-2] ...</div>
<div class="q">✏️ 短期记忆 N / 5 条</div>
<div class="t">📖 玩家设定</div>
<div class="memo-item" style="border-left-color:#强调色;">描述</div>
</div>
</details>

<!-- ====== 选项（放在最后） ====== -->
<div class="options">
<div class="ot">➤ 你会怎么做？</div>
<div class="oi" onclick="copyOpt('选项1文本',this)">😏 选项1描述</div>
<div class="oi" onclick="copyOpt('选项2文本',this)">🔥 选项2描述</div>
<div class="oc" onclick="copyOpt('✏️ [自定义行动]',this)">✏️ [自定义行动]</div>
</div>
<div style="font-size:10px;color:脚注色;text-align:right;margin:2px 8px 0;">💡 点击选项即可复制到剪贴板</div>

<script>
(function(){document.querySelectorAll('.pn .arr').forEach(function(a){
var d=a.closest('details');if(d){d.addEventListener('toggle',function(){
a.style.transform=this.open?'rotate(180deg)':'rotate(0deg)';});}});})();
</script>
</div>
```

---

#### 五套适配主题色（按故事氛围选用）

| 主题 | 适用场景 | 背景渐变 | 标题色 | 标签渐变 | 正文色 | 强调色 | 脚注色 |
|:----:|:---------|:---------|:-------|:---------|:-------|:-------|:-------|
| 🌸 粉色甜美 | 校园/恋爱/日常 | `#fff0f5→#fef5f9` | `#d81b60` | `#ff7eb3→#ff758c` | `#4a2c40` | `#d81b60` | `#b07a8f` |
| 🌙 暗黑哥特 | 奇幻/悬疑/战斗 | `#1a1528→#0d0b15` | `#c084fc` | `#c084fc→#9b59b6` | `#e8d4a8` | `#c084fc` | `#8b7a9a` |
| 🌿 自然清新 | 冒险/田园/治愈 | `#f0fdf4→#ecfdf5` | `#059669` | `#34d399→#10b981` | `#064e3b` | `#059669` | `#6b8a7b` |
| ⚔️ 沉稳史诗 | 战争/历史/王道 | `#1e293b→#0f172a` | `#f59e0b` | `#f59e0b→#d97706` | `#fef3c7` | `#f59e0b` | `#a0865a` |
| 🎴 简约清爽 | 推理/科幻/悬疑 | `#f0f4f8→#e2e8f0` | `#1e293b` | `#64748b→#475569` | `#334155` | `#3b82f6` | `#94a3b8` |

---

### 二、正文（中间部分）

#### 叙事描写
- 使用 **第三人称** 叙事，描写当前场景的进展
- 注重感官细节的平衡运用：视觉 · 听觉 · 触觉 · 嗅觉
- 思考过程可藏在 `<!-- thinking ... -->` HTML注释中
- **单次正文控制在 2000-3000 字**，保证情节有足够推进

#### 对话块
- **对话必须使用独立对话块渲染**，不得与叙事混杂在同一段落内
- 对话块与叙事段落之间留一个空行距

**HTML类名写法：**
```html
<div class="dpc"><span class="dpn">你：</span><span class="dtc">「内容」</span></div>
<div class="dnpc"><span class="dnn">NPC名：</span><span class="dtn">「内容」</span></div>
```

---

### 三、选项列表（最后部分）

#### 基础规范
- 提供 **5-6 个分支选项 + 1 个自定义选项**
- 格式：`emoji + 简短行动描述`
- 自定义选项固定标注：`✏️ [自定义行动]`
- 每个选项通过 `onclick="copyOpt('文本',this)"` 实现点击复制到剪贴板
- 选项区域下方可添加提示：`💡 点击选项即可复制到剪贴板`

---

## 会话状态管理

### 🧠 记忆区管理系统

记忆区采用严格的三级压缩体系，每一级都是**全量压缩**，不得自由增删条目。

#### 记忆区面板展示规则
记忆区面板永远展示以下三块内容：
1. **短期记忆** — 显示 ST-1 至 ST-5，不足5条则显示实际数量
2. **长期记忆** — 显示已归档的 LT 条目
3. **玩家设定** — 固定的玩家档案

#### 第一级：短期记忆（ST）
- **容量**：5条（ST-1~ST-5），FIFO队列
- **插入方式**：每回合结束时在ST-1插入新条目，旧条目依次下移
- **ST-1** 永远是最新事件（用 `◀` 标记），ST-5是最早的短期记忆
- **🔄 写满规则**：当需要插入第6条时（即ST已有5条），将当前**全部5条**短期记忆合并为**1条长期记忆（LT）**
  - 格式：单条概括性文字
  - **然后清空短期记忆**，从新的ST-1开始计数

#### 第二级：长期记忆（LT）
- **容量**：展示全部已归档的LT条目，最多6条
- **🔄 写满规则**：当LT达到6条时，将**全部LT条目**合并为**1条永久记忆**，然后清空长期记忆

#### 第三级：永久记忆
- 记录最核心的人生节点（入学、初体验等）
- 永久保留，不再压缩

#### ⚠️ 铁律
- 记忆区**只存放已真实发生过的事件**
- **不写入**尚未发生的计划、猜测、未来安排
- **不随意修改**已有条目内容
- 只有新回合的ST-1可以写入新内容，旧条目只能整体下移或整区压缩

### 好感/关系追踪
- 根据剧情进展动态调整角色对玩家的态度
- 可用简单数值标注（百分比）或文字描述（如「警惕→信任→亲近」）
- 好感度配合角色图鉴面板展示（进度条 + 百分比）

---

## 六面板写法规范

### 面板组成与顺序

**输出顺序固定为：正文叙事 → 六面板状态栏 → 可复制选项**。六面板依次为：
1. **当前状态**（🌸）
2. **在场角色**（👥）
3. **角色图鉴**（🎴）
4. **地图**（🗺️）
5. **日程**（📋）
6. **记忆区**（🧠）

### 1. 当前状态写法规范

| 字段 | 内容要求 | 示例 |
|:----|:---------|:-----|
| 👤 玩家 | 年龄 · 外貌要点 · 当前动作 | 16岁·黑发黑瞳·赤裸站在讲台上 |
| 🏫 地点 | 具体位置 · 空间特征 | 生理课教室·讲台前·晨光从高窗斜照 |
| ⏰ 时间 | **精确到分钟**· 当日信息 | 09:42·开学第一天·第二节课 |
| ✨ 事件 | 当前正在发生的事 | 老师正在讲台上讲解题目，全班低头记笔记 |
| 💌 互动 | 与他人的互动状态 | 全班24名女生屏息围观 |
| 🎭 氛围 | **三层感官**：视觉（光线/颜色）+听觉（环境音）+嗅觉（气味） | 晨光斜照·粉笔声·肥皂和纸张的气息 |
| ⏳ 回合 | 回合数 | 第8回合 |

### 2. 在场角色写法规范

每个在场角色使用独立条目（`.si` > `.st` + `.sv`），包含：

- **外貌**：当前可见的外观描述（光线下的姿态、神情）
- **情绪**：用emoji标记情绪+简短说明（如😰 紧张——手指绞得发白）
- **动作/反应**：正在做什么细节动作

```html
<div class="sh">📖 角色名 · 年龄 · 身份</div>
<div class="si"><span class="st">外貌</span><span class="sv">描述</span></div>
<div class="si"><span class="st">情绪</span><span class="sv">描述</span></div>
<div class="si"><span class="st">动作</span><span class="sv">描述</span></div>
```

### 3. 角色图鉴写法规范

每个角色使用独立卡片容器（`.cc` > `.cn` + `.cr`），包含：

- **身体状态**：当前身体的紧张/放松程度、呼吸、肤色变化
- **当前位置**：具体空间位置
- **当前动作**：正在做什么
- **心理状态**：一句带「」的内心独白
- **好感度**：进度条+百分比

```html
<div class="cc">
  <div class="cn">📖 角色名</div>
  <div class="cr"><span class="cl">身体状态</span><span class="cv">描述</span></div>
  <div class="cr"><span class="cl">当前位置</span><span class="cv">描述</span></div>
  <div class="cr"><span class="cl">当前动作</span><span class="cv">描述</span></div>
  <div class="cr"><span class="cl">心理状态</span><span class="cv">「内心独白」</span></div>
  <div class="cp"><span class="cl">好感度</span><span class="cb"><div class="cf" style="width:XX%"></div></span><span>XX%</span></div>
</div>
```

### 4. 地图写法规范

地图面板包含两部分：

**布局描述**（`.si` > `.st`+`.sv`结构）：
- 空间尺寸、方位、结构特征
- 当前所在的具体位置描述
- 光线来源和环境特征

**相邻区域**（`.map-grid`>`.map-item`结构）：
- 至少列出4个方向的相邻区域
- 每个区域包含方向箭头、名称、可达状态标签
- 状态标签使用规范：🟢可进入/🔴已锁/🟡有人/🔵需绕行

### 5. 日程写法规范

- 按时间顺序排列，从早到晚
- 已完成的事项用 ✅ 标记
- 当前事项用 📌 标记
- 未开始的事项用 ⏳ 标记
- 翘课/取消的用 🔴 标记
- 格式：`时间 · 活动 · 状态说明`

### 6. 记忆区写法规范

严格三级压缩体系，面板展示三块内容：

**短期记忆（ST）**：
- 显示 ST-1 至 ST-5
- 最新一条用 `◀` 标记
- 每条格式：`[ST-N] 时间 · 事件概述`
- 底部标注：`✏️ N/5 条`

**长期记忆（LT）**：
- 显示已归档的概括性条目
- 格式：`[LT-N] 时间段 · 事件概要`

**永久记忆**：
- 核心人生节点
- 不再压缩

---

## 环境与氛围描写规范

### 三层感官体系

每次场景描写至少覆盖以下三层中的两层：

| 感官 | 描写要点 | 示例 |
|:----|:---------|:-----|
| 👁️ 视觉 | 光线方向（高窗/斜照/逆光）、颜色、空间布置、人物轮廓 | 穹顶透入的晨光在教室地板上铺开一层暖金色 |
| 👂 听觉 | 环境音类型、距离感、节奏（恒定/间歇） | 排风扇以低沉嗡鸣运转，远处的滴水声以恒定间隔落下 |
| 👃 嗅觉 | 气味层次、混合特征 | 空气中混合着纸张和肥皂的气息 |

### 时间与地点标记

- **时间精确到分钟**（如 09:42）
- 地点标记包含：建筑/区域名称 + 具体位置 + 光线条件
- 回合更新时时间自然推进（每次推进2-15分钟，视场景节奏而定）

---

## 叙事推进节奏规范

### 事件链推进

- 用时间线和自然的事件序列推进剧情，避免"然后……然后……"的机械衔接
- 每个场景设置一个"核心事件"（如：初次相遇、关键对话、突发事件），环绕它展开描写
- 场景之间通过对话或角色决定自然过渡

### 对话推动

- 简短对话可以推动场景转折
- 角色的每一句话应该具有"作用"：要么推进剧情，要么揭示性格，要么改变关系

### 检查阶段转换

每回合结束时判断是否应该进入下一阶段：
- 当前场景的核心事件是否已完成？
- 是否有时间压力（如下课铃、上课铃等）？
- 角色之间的主要张力是否已释放？

如果以上任一答案为是，考虑在下一回合推进场景转换。

---

## 角色卡与世界观加载流程

1. **解析角色卡** → 提取核心字段：姓名、年龄、身份、外貌描述、性格、背景故事、当前目标
2. **加载世界观书**（可选）→ 设定关键词触发世界观信息注入
3. **组装初始上下文** → 角色设定 + 世界观 + 开场白
4. **执行角色扮演** → 按输出规范生成首回合
5. **持久化会话状态** → 将历史记录和状态保存到文件

### 角色卡字段模板

```
姓名：
年龄：
身份：
外貌：（3-5句话）
性格：（核心特质2-3个）
背景：（与当前剧情相关的经历）
目标：（当前行动动机）
关系：（与玩家的初始关系及态度）
```

---

## 从零创作流程

当需要从零创作新世界和角色时，按以下五模块有序推进。**每完成一个模块先向玩家展示并征求意见，不闷头全部写完才展示。**

### 模块一：世界观定调
- 确定故事类型（现代/奇幻/科幻/历史等）
- 核心设定（一条铁律或独特规则）
- 环境氛围（色调、天气、社会生态）

### 模块二：角色卡设计
- 一句话钩子（这个角色最吸引人的点）
- 背景故事（与世界观绑定）
- 性格标签（3-5个，便于保持人设一致）
- 外貌描述（突出标志性特征）
- 动机/目标（驱动角色的内在动力）

### 模块三：玩家档案设计
- 身份锚点（玩家在这个世界中的位置）
- 性格特质（2-3个关键性格标签）
- 与世界的关联（玩家与核心剧情的连接点）

### 模块四：开场白创作
- 六要素检查清单：⏰时间 · 🏘️地点 · 🎭氛围 · ⚡事件 · 👥角色 · ⚔️冲突
- 三种经典开场结构：对峙式 / 初入式 / 危机式

### 模块五：完整输出
组装以上四模块 → 生成首回合输出（六面板状态栏 + 正文 + 可复制选项）

---

## 游玩行为规范（重要）

1. **静默渲染**：在游戏进行中（玩家已开始选择并推进剧情时），Agent **只渲染游戏卡牌（HTML输出），不附加任何额外的话语**。不得在卡牌外说「好的」「明白了」「接下来呢？」等。除非：
   - 玩家主动对Agent说话（而非对剧情中的角色）
   - 玩家要求结束游戏
   - 出现技术错误需要说明

2. **HTML/Markdown 不混用**：HTML 渲染和 Markdown 格式**不能共存于同一条消息气泡**中。整条消息要么全部是 HTML，要么全部是 Markdown。当输出酒馆卡牌时，整条消息都必须是纯 HTML，不得混入 Markdown 语法。

## 通用注意事项（经验教训）

1. **六面板铁律**：当前状态·在场角色·角色图鉴·地图·日程·记忆区——六个面板一个不能少
2. **面板默认收起**：不为 `details` 设置 `open` 属性（首回合开场可例外）
3. **对话独立**：对话块绝不混入叙事段落内
4. **纯HTML输出**：整条消息用 HTML 容器包裹，不混用 Markdown
5. **先确认再创作**：创作新世界时，向玩家展示方向方案，确认后再动手
6. **不确定就问**：方向模糊时先问清楚，不凭猜测推进
7. **ST逐轮更新**：每回合更新短期记忆，旧条目不丢失，滚动 FIFO
8. **条目卡片结构**：状态栏条目使用 `.si` > `.st` + `.sv` 结构，不要写散文段落
9. **配色一致**：全篇使用同一套主题色，不在不同面板间切换配色
10. **字数达标**：单次正文 2000-3000 字，保证情节有实质推进
11. **地图含相邻地点**：地图面板必须列出相邻区域及其可达状态（🟢可进入/🔴已锁/🟡有人/🔵需绕行）
12. **进度条防溢出**：进度条百分比使用 `grid-template-columns: 1fr auto` 布局，数值右对齐不超出容器
13. **记忆区只记真实**：短期记忆只存放已真实发生过的事件，不写入计划或未发生的猜测
14. **选项可点击复制**：每个选项需要使用 `onclick="copyOpt(...)"` 实现点击复制，并内嵌 copyOpt 和 fallbackCopy 两个JS函数
15. **角色图鉴实时更新**：角色图鉴面板中的身体状态、心理状态和好感度应随剧情推进而动态变化