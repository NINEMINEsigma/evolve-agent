---
name: status-panel
description: "可折叠状态面板HTML组件模板系统。支持多主题（粉色甜美/暗黑哥特/简约清爽等）、可折叠details/summary、彩色标签、CSS进度条、角色信息卡、多面板组合。适用于角色扮演、游戏数值、故事设定展示等场景，根据故事氛围自动选择风格"
version: 1.0.0
author: Evolve-Agent
category: ui
tags:
  - status-panel
  - collapsible
  - details
  - ui-component
  - multi-theme
  - eve
---

# 状态面板（Status Panel）Skill

可折叠状态面板 HTML 组件模板系统。支持多主题风格切换，适用于角色扮演、游戏数值、故事设定展示等场景。

## 设计哲学

状态面板应该：
- **可折叠**：默认收起，不占空间，需要时展开
- **风格适配**：根据故事氛围选择主题色，而非固定一种
- **信息分层**：标签+数值+进度条，一目了然
- **可组合**：多个面板可以并排放置，表达完整的状态

## 内置主题

### 1. 🌸 粉色甜美（默认）
```
背景: #fff0f5 → #fef5f9
标题: #d81b60
标签: #ff7eb3 → #ff758c 渐变
进度条: #ff7eb3 → #ff4d6d 渐变
文字: #4a2c40
```
适合：校园恋爱、少女风、轻松日常

### 2. 🌙 暗黑哥特
```
背景: #1a1528 → #0d0b15
标题: #c084fc
标签: #c084fc → #9b59b6 渐变
进度条: #c084fc → #7c3aed 渐变
文字: #e8d4a8
```
适合：奇幻、黑暗、战斗、悬疑

### 3. 🌿 自然清新
```
背景: #f0fdf4 → #ecfdf5
标题: #059669
标签: #34d399 → #10b981 渐变
进度条: #34d399 → #059669 渐变
文字: #064e3b
```
适合：冒险、田园、治愈系

### 4. ⚔️ 沉稳史诗
```
背景: #1e293b → #0f172a
标题: #f59e0b
标签: #f59e0b → #d97706 渐变
进度条: #f59e0b → #b45309 渐变
文字: #fef3c7
```
适合：史诗、战争、中世纪、王道

### 5. 🎴 简约清爽
```
背景: #ffffff
标题: #1e293b
标签: #64748b
进度条: #3b82f6 → #2563eb 渐变
文字: #334155
```
适合：科幻、现代、简洁展示

## 组件结构

```
┌──────────────────────────────────────┐
│ 📋 状态面板                     ▼   │  ← 折叠标题
├──────────────────────────────────────┤
│ 👤 玩家信息                          │  ← 分区标题
│ ┌──────────────────────────────────┐ │
│ │ [标签]  内容值                   │ │  ← 条目卡片
│ ├──────────────────────────────────┤ │
│ │ [体力]  ████████░░  80%          │ │  ← 进度条
│ └──────────────────────────────────┘ │
│ 点击标题可折叠收起                    │  ← 脚注
└──────────────────────────────────────┘
```

## 快速使用（单面板）

直接在消息中嵌入以下 HTML 模板，替换方括号内容：

```html
<details style="font-family:'Microsoft YaHei','PingFang SC',system-ui,sans-serif;
        font-size:14px; color:[正文色]; line-height:1.5;
        background:linear-gradient(135deg,[背景色1],[背景色2]);
        padding:8px; border-radius:12px; margin:4px 0; overflow:hidden;">
  <summary style="cursor:pointer; padding:8px 12px; font-weight:600;
          display:flex; justify-content:space-between; align-items:center;
          background:linear-gradient(90deg,[标题渐变]);
          color:[标题色]; font-size:15px; border-radius:8px; list-style:none;">
    📋 [面板标题] <span id="s1-arrow" style="font-size:11px; color:[箭头色];
                     opacity:0.7; transition:transform 0.3s ease;">▼</span>
  </summary>
  <div style="animation:fadeS 0.35s ease">
    <style>
      @keyframes fadeS{0%{opacity:0;transform:translateY(-4px)}100%{opacity:1;transform:translateY(0)}}
      .si{display:flex;flex-direction:column;margin:5px 10px;
          background:[卡片底色];border-radius:6px;padding:4px 0;
          border:1px solid [卡片边框]}
      .st{display:inline-block;background:linear-gradient(135deg,[标签色1],[标签色2]);
          color:white;padding:2px 10px;font-size:12px;font-weight:600;
          border-radius:4px;margin:0 10px 2px 10px}
      .sv{display:block;padding:2px 10px 4px;font-size:13px;color:[正文色];width:100%}
      .sb{display:flex;align-items:center;gap:8px;padding:2px 10px 4px;width:100%}
      .bg{flex:1;height:8px;background:[轨道色];border-radius:4px;overflow:hidden}
      .fl{height:100%;border-radius:4px;background:linear-gradient(90deg,[进度条1],[进度条2])}
      .sn{font-size:12px;color:[数值色];font-weight:600;min-width:30px;text-align:right}
      .sh{font-weight:bold;font-size:14px;color:[标题色];margin:12px 10px 4px;
          padding-left:8px;border-left:3px solid [强调色]}
      .sf{display:block;margin:12px 10px 8px;padding:8px 0 4px;font-size:11px;
          color:[脚注色];text-align:center;border-top:1px dashed [虚线色]}
    </style>
    <!-- 内容区域 -->
    <div class="sh">👤 [分区标题]</div>
    <div class="si"><span class="st">[标签]</span><span class="sv">[内容]</span></div>
    <div class="sh">📊 数值</div>
    <div class="si">
      <span class="st">[名称]</span>
      <div class="sb"><div class="bg"><div class="fl" style="width:[百分比]%"></div></div>
      <span class="sn">[百分比]%</span></div>
    </div>
    <div class="sf">点击标题可折叠收起</div>
  </div>
</details>
<script>
  (function(){var a=document.getElementById('s1-arrow');
  a.closest('details').addEventListener('toggle',function(){
    a.style.transform=this.open?'rotate(180deg)':'rotate(0deg)';})})();
</script>
```

## 多面板组合

当需要表达完整状态时，使用多个面板组合，每个面板聚焦一个维度：

```html
<!-- 面板1：角色状态 -->
<details open>...📋 角色状态...</details>
<!-- 面板2：装备/技能 -->
<details>...⚔️ 技能装备...</details>
<!-- 面板3：人际关系 -->
<details>...💕 人际关系...</details>
```

建议最多 5-8 个面板，避免信息过载。

## 核心 CSS 类名速查

| 类名 | 用途 |
|------|------|
| `.si` | 条目卡片容器（白色半透明圆角） |
| `.st` | 标签（渐变底色，白字） |
| `.sv` | 内容值 |
| `.sb` | 进度条容器（flex 横排） |
| `.bg` | 进度条轨道 |
| `.fl` | 进度条填充（渐变） |
| `.sn` | 进度数值 |
| `.sh` | 分区小标题 |
| `.sf` | 脚注 |

## 风格选择指南

| 故事氛围 | 推荐主题 |
|---------|---------|
| 校园/恋爱/日常 | 🌸 粉色甜美 |
| 奇幻/魔法/战斗 | 🌙 暗黑哥特 |
| 冒险/旅行/田园 | 🌿 自然清新 |
| 战争/史诗/中世纪 | ⚔️ 沉稳史诗 |
| 科幻/现代/极简 | 🎴 简约清爽 |
| 不确定时 | 粉色甜美（默认，最百搭） |

## 在消息气泡中渲染要点

1. **直接用 `<details>` 标签** — 收起时一行标题，展开全尺寸，气泡自动适配
2. **不要固定外边框** — `<details>` 自身的背景和圆角就是容器
3. **箭头用 JS 控制旋转** — `toggle` 事件监听，▼↔▲ 切换
4. **数据用进度条** — CSS 渐变填充，比字符拼凑美观
5. **标签+内容分离** — 信息结构化，一眼可读