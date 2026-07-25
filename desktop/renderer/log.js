/**
 * log.js — 实时日志流显示与状态切换
 *
 * 职责：
 *   - 接收 backend:log-line 推送，按行追加到日志面板
 *   - 接收 backend:status 推送，更新状态徽章
 *   - 后端就绪后切换视图
 *   - 保留最近 2000 行防止内存无限增长
 */

'use strict';

// config.js 已声明 const api，此处直接复用，不重复声明

var MAX_LINES = 2000;

// ── DOM 引用 ───────────────────────────────────────────────

var logOutput = document.getElementById('log-output');
var statusBadge = document.getElementById('status-badge');
var btnBackToConfig = document.getElementById('btn-back-to-config');
var cfgPanel = document.getElementById('config-panel');
var logPanelEl = document.getElementById('log-panel');
var waitingOverlay = document.getElementById('waiting-overlay');
var waitingText = document.getElementById('waiting-text');

// ── 状态映射 ───────────────────────────────────────────────

const STATUS_MAP = {
  idle:      { text: '等待启动', class: 'status-idle' },
  starting:  { text: '启动中', class: 'status-starting' },
  running:   { text: '运行中', class: 'status-running' },
  evolving:  { text: '进化中', class: 'status-evolving' },
  crashed:   { text: '已崩溃', class: 'status-crashed' },
  timeout:   { text: '超时', class: 'status-timeout' },
  stopped:   { text: '已停止', class: 'status-stopped' },
};

// ── 事件注册 ───────────────────────────────────────────────

api.backend.onLog((log) => {
  appendLogLine(log);
});

api.backend.onStatus((status) => {
  updateStatus(status);
});

api.backend.onHealthOk(() => {
  waitingOverlay.classList.add('hidden');
});

// ── 返回配置按钮 ──────────────────────────────────────────

btnBackToConfig.addEventListener('click', () => {
  cfgPanel.classList.add('active');
  logPanelEl.classList.remove('active');
});

// ── 日志追加 ───────────────────────────────────────────────

function appendLogLine(log) {
  const line = document.createElement('div');
  line.className = `log-line ${log.stream}`;
  const ts = new Date(log.ts).toLocaleTimeString('zh-CN', { hour12: false });
  line.textContent = `[${ts}] ${log.line}`;
  logOutput.appendChild(line);

  // 自动滚动到底部
  logOutput.scrollTop = logOutput.scrollHeight;

  // 限制行数
  while (logOutput.children.length > MAX_LINES) {
    logOutput.removeChild(logOutput.firstChild);
  }
}

// ── 状态更新 ───────────────────────────────────────────────

function updateStatus(status) {
  const info = STATUS_MAP[status] || STATUS_MAP.idle;
  statusBadge.textContent = info.text;
  statusBadge.className = `status-badge ${info.class}`;

  // starting 状态显示等待覆盖层
  if (status === 'starting') {
    waitingOverlay.classList.remove('hidden');
    waitingText.textContent = '等待后端就绪...';
  }

  // evolving 状态更新等待文本
  if (status === 'evolving') {
    waitingOverlay.classList.remove('hidden');
    waitingText.textContent = '进化完成，正在重启后端...';
  }

  // running 状态隐藏覆盖层
  if (status === 'running') {
    waitingOverlay.classList.add('hidden');
  }

  // crashed / timeout 显示等待文本
  if (status === 'crashed') {
    waitingOverlay.classList.remove('hidden');
    waitingText.textContent = '后端已崩溃，将在 3 秒后退出...';
  }

  if (status === 'timeout') {
    waitingOverlay.classList.remove('hidden');
    waitingText.textContent = '健康检查超时，后端未就绪';
  }
}