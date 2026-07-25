/**
 * main.js — Electron 主进程入口
 *
 * 职责：
 *   - 窗口管理（配置/日志窗口 + WebView 窗口）
 *   - IPC 注册（config:* + backend:* + settings:*）
 *   - 启动流程编排（拉起后端 → 轮询 /health → 加载 WebView）
 *   - 退出处理（后端退出 → 壳退出；进化重启 → 继续等待）
 *
 * 打包后布局：
 *   EvolveAgent/
 *   ├── EvolveAgent.exe
 *   ├── resources/app.asar       ← 壳代码（__dirname 在此）
 *   ├── run.py
 *   ├── config.json
 *   ├── origin_agent/
 *   ├── third/
 *   ├── venv/                     ← 可选，自动探测
 *   └── workspace/               ← 运行时生成
 */

'use strict';

const { app, BrowserWindow, ipcMain } = require('electron');
const fs = require('fs');
const path = require('path');
const { configManager, BackendManager } = require('./requires');

// ── 路径常量 ──────────────────────────────────────────────

const DESKTOP_DIR = __dirname;

// 打包后: exe 同级目录 = 仓库根目录
// 开发时: desktop/src/ 向上两层 = 仓库根目录
const REPO_ROOT = app.isPackaged
  ? path.dirname(app.getPath('exe'))
  : path.resolve(DESKTOP_DIR, '..', '..');

const RENDERER_DIR = app.isPackaged
  ? path.join(DESKTOP_DIR, '..', 'renderer')   // asar 内
  : path.join(DESKTOP_DIR, '..', 'renderer');

const CONFIG_JSON = path.join(REPO_ROOT, 'config.json');
const SETTINGS_JSON = path.join(REPO_ROOT, 'desktop-settings.json');

// ── Python 路径探测 ───────────────────────────────────────

/**
 * 探测默认 Python 路径。
 * 优先级: venv/Scripts/python.exe → venv/bin/python → 'python'
 */
function detectPythonPath() {
  const venvScripts = path.join(REPO_ROOT, 'venv', 'Scripts', 'python.exe');
  const venvBin = path.join(REPO_ROOT, 'venv', 'bin', 'python');
  if (fs.existsSync(venvScripts)) return venvScripts;
  if (fs.existsSync(venvBin)) return venvBin;
  return 'python';
}

// ── 壳设置 ────────────────────────────────────────────────

const SETTINGS_DEFAULTS = {
  pythonPath: '',   // 空字符串 = 自动探测
};

function loadSettings() {
  try {
    const raw = fs.readFileSync(SETTINGS_JSON, 'utf-8');
    return { ...SETTINGS_DEFAULTS, ...JSON.parse(raw) };
  } catch {
    return { ...SETTINGS_DEFAULTS };
  }
}

function saveSettings(values) {
  const dir = path.dirname(SETTINGS_JSON);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(SETTINGS_JSON, JSON.stringify(values, null, 2), 'utf-8');
}

/**
 * 获取实际使用的 Python 路径。
 * 优先级: 用户显式设置 → venv 自动探测 → 'python'
 */
function getEffectivePythonPath() {
  const settings = loadSettings();
  if (settings.pythonPath && settings.pythonPath.trim()) {
    return settings.pythonPath.trim();
  }
  return detectPythonPath();
}

// ── 全局状态 ──────────────────────────────────────────────

let controlWindow = null;
let webviewWindow = null;
let backend = null;
let backendRunning = false;

// ── 窗口创建 ──────────────────────────────────────────────

function createControlWindow() {
  controlWindow = new BrowserWindow({
    width: 900,
    height: 700,
    title: 'Evolve Agent',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(DESKTOP_DIR, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  controlWindow.loadFile(path.join(RENDERER_DIR, 'index.html'));

  controlWindow.on('close', (e) => {
    if (backendRunning) {
      e.preventDefault();
      controlWindow.minimize();
    }
  });

  controlWindow.on('closed', () => {
    controlWindow = null;
  });
}

function createWebviewWindow(host, port) {
  webviewWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    title: 'Evolve Agent',
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  webviewWindow.loadURL(`http://${host}:${port}`);

  webviewWindow.on('closed', () => {
    webviewWindow = null;
    if (backend) backend.kill();
    app.quit();
  });
}

// ── IPC 注册 ──────────────────────────────────────────────

function registerIpc() {
  // ── 配置管理 ──────────────────────────────────────────

  ipcMain.handle('config:list-profiles', () => {
    try {
      return configManager.listProfiles(CONFIG_JSON);
    } catch (err) {
      console.error('[config] listProfiles error:', err);
      return [];
    }
  });

  ipcMain.handle('config:load-profile', (event, key) => {
    return configManager.loadProfile(CONFIG_JSON, key);
  });

  ipcMain.handle('config:save-profile', (event, key, values) => {
    configManager.saveProfile(CONFIG_JSON, key, values);
    return true;
  });

  ipcMain.handle('config:create-profile', (event, key) => {
    configManager.createProfile(CONFIG_JSON, key);
    return true;
  });

  // ── 壳设置 ──────────────────────────────────────────

  ipcMain.handle('settings:load', () => {
    const settings = loadSettings();
    // 如果用户未设置 pythonPath，返回自动探测的值供 UI 显示
    return {
      pythonPath: settings.pythonPath || '',
      detectedPythonPath: detectPythonPath(),
    };
  });

  ipcMain.handle('settings:save', (event, values) => {
    saveSettings(values);
    return true;
  });

  // ── 后端生命周期 ──────────────────────────────────────

  ipcMain.on('backend:launch', (event, configKey, overrides, pythonPath) => {
    launchBackend(event, configKey, overrides, pythonPath);
  });

  ipcMain.on('backend:kill', () => {
    if (backend) backend.kill();
    app.quit();
  });
}

// ── 后端启动流程编排 ──────────────────────────────────────

function launchBackend(event, configKey, overrides, pythonPath) {
  backend = new BackendManager();

  // Python 路径: 用户显式传入 > 壳设置 > venv 探测 > 'python'
  const py = (pythonPath && pythonPath.trim()) || getEffectivePythonPath();

  // 构造 CLI 参数
  const cliArgs = ['run.py', '--load', configKey, '--console_log', 'true'];
  const overrideArgs = configManager.buildCliArgs(overrides || {});
  cliArgs.push(...overrideArgs);

  // 注册日志回调 → 推送到 renderer
  backend.onLog((log) => {
    if (controlWindow && !controlWindow.isDestroyed()) {
      controlWindow.webContents.send('backend:log-line', log);
    }
  });

  // 注册退出回调
  backend.onExit((exitCode) => {
    backendRunning = false;

    if (exitCode === -1) {
      sendStatus(event, 'evolving');
      return;
    }

    if (exitCode === 0) {
      sendStatus(event, 'stopped');
      app.quit();
      return;
    }

    sendStatus(event, 'crashed');
    if (controlWindow && !controlWindow.isDestroyed()) {
      controlWindow.webContents.send('backend:log-line', {
        stream: 'stderr',
        line: `[launcher] 后端进程退出，退出码: ${exitCode}`,
        ts: Date.now(),
      });
    }
    setTimeout(() => app.quit(), 3000);
  });

  // 拉起后端
  backend.start(REPO_ROOT, cliArgs, py);
  backendRunning = true;
  sendStatus(event, 'starting');

  // 从 profile + 临时覆盖中读取 host/port
  const profileValues = configManager.loadProfile(CONFIG_JSON, configKey);
  const host = (overrides && overrides.gateway_host) || profileValues.gateway_host || '127.0.0.1';
  const port = (overrides && overrides.gateway_port) || profileValues.gateway_port || 8765;
  const healthHost = host === '0.0.0.0' ? '127.0.0.1' : host;

  // 轮询 /health
  backend.waitForHealth(
    healthHost,
    port,
    () => {
      sendStatus(event, 'running');
      if (controlWindow && !controlWindow.isDestroyed()) {
        controlWindow.webContents.send('backend:health-ok');
      }
      createWebviewWindow(healthHost, port);
    },
    () => {
      sendStatus(event, 'timeout');
      if (controlWindow && !controlWindow.isDestroyed()) {
        controlWindow.webContents.send('backend:log-line', {
          stream: 'stderr',
          line: '[launcher] 健康检查超时（120s），后端未就绪',
          ts: Date.now(),
        });
      }
    }
  );
}

// ── 工具函数 ──────────────────────────────────────────────

function sendStatus(event, status) {
  if (controlWindow && !controlWindow.isDestroyed()) {
    controlWindow.webContents.send('backend:status', status);
  }
}

// ── App 生命周期 ──────────────────────────────────────────

app.whenReady().then(() => {
  registerIpc();
  createControlWindow();
});

app.on('window-all-closed', () => {
  if (backend) backend.kill();
  app.quit();
});

app.on('before-quit', () => {
  if (backend) backend.kill();
});