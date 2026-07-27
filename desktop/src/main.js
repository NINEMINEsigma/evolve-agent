/**
 * main.js — Electron 主进程入口
 *
 * 职责：
 *   - 窗口管理（控制窗口 + WebView 窗口 + 系统托盘）
 *   - IPC 注册（config:* + backend:* + settings:*）
 *   - 启动流程编排（拉起后端 → 轮询 /health → 加载 WebView → 最小化到托盘）
 *   - 退出处理（仅托盘右键"退出"才真正退出）
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

const { app, BrowserWindow, ipcMain, Tray, Menu, nativeImage } = require('electron');
const fs = require('fs');
const path = require('path');
const { configManager, BackendManager } = require('./requires');

// ── 路径常量 ──────────────────────────────────────────────

const DESKTOP_DIR = __dirname;

const REPO_ROOT = app.isPackaged
  ? path.dirname(app.getPath('exe'))
  : path.resolve(DESKTOP_DIR, '..', '..');

const RENDERER_DIR = app.isPackaged
  ? path.join(DESKTOP_DIR, '..', 'renderer')
  : path.join(DESKTOP_DIR, '..', 'renderer');

const CONFIG_JSON = path.join(REPO_ROOT, 'config.json');
const SETTINGS_JSON = path.join(REPO_ROOT, 'desktop-settings.json');
const ICON_PATH = app.isPackaged
  ? path.join(REPO_ROOT, 'resources', 'app.asar', 'assets', 'icon.ico')
  : path.join(DESKTOP_DIR, '..', 'assets', 'icon.ico');

// ── Python 路径探测 ───────────────────────────────────────

function detectPythonPath() {
  const venvScripts = path.join(REPO_ROOT, 'venv', 'Scripts', 'python.exe');
  const venvRootExe = path.join(REPO_ROOT, 'venv', 'python.exe');
  const venvBin = path.join(REPO_ROOT, 'venv', 'bin', 'python');
  console.log('[launcher] REPO_ROOT:', REPO_ROOT);
  console.log('[launcher] venvScripts exists:', fs.existsSync(venvScripts), venvScripts);
  console.log('[launcher] venvRootExe exists:', fs.existsSync(venvRootExe), venvRootExe);
  if (fs.existsSync(venvScripts)) return venvScripts;
  if (fs.existsSync(venvRootExe)) return venvRootExe;
  if (fs.existsSync(venvBin)) return venvBin;
  console.warn('[launcher] No venv python found, falling back to system python');
  return 'python';
}

// ── 壳设置 ────────────────────────────────────────────────

const SETTINGS_DEFAULTS = { pythonPath: '' };

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
let tray = null;
let isQuitting = false;

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

  // 关闭按钮 → 最小化到托盘（不退出）
  controlWindow.on('close', (e) => {
    if (!isQuitting) {
      e.preventDefault();
      controlWindow.hide();
    }
  });

  controlWindow.on('closed', () => {
    controlWindow = null;
    updateTrayMenu();
  });

  // 窗口显示/隐藏时刷新托盘菜单文本
  controlWindow.on('show', () => updateTrayMenu());
  controlWindow.on('hide', () => updateTrayMenu());
}

function createWebviewWindow(host, port) {
  if (webviewWindow && !webviewWindow.isDestroyed()) {
    // 已存在 → 显示并聚焦
    webviewWindow.show();
    webviewWindow.focus();
    return;
  }

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

  // 关闭按钮 → 隐藏窗口（不杀后端，不退出）
  webviewWindow.on('close', (e) => {
    if (!isQuitting) {
      e.preventDefault();
      webviewWindow.hide();
    }
  });

  webviewWindow.on('closed', () => {
    webviewWindow = null;
    updateTrayMenu();
  });

  // 窗口显示/隐藏时刷新托盘菜单文本
  webviewWindow.on('show', () => updateTrayMenu());
  webviewWindow.on('hide', () => updateTrayMenu());
}

// ── 系统托盘 ──────────────────────────────────────────────

function createTray() {
  let trayIcon;
  try {
    trayIcon = nativeImage.createFromPath(ICON_PATH);
    if (trayIcon.isEmpty()) trayIcon = nativeImage.createEmpty();
  } catch {
    trayIcon = nativeImage.createEmpty();
  }

  tray = new Tray(trayIcon);
  tray.setToolTip('Evolve Agent');

  // 左键单击 → 切换控制窗口
  tray.on('click', () => {
    if (controlWindow && !controlWindow.isDestroyed()) {
      if (controlWindow.isVisible()) {
        controlWindow.hide();
      } else {
        controlWindow.show();
        controlWindow.focus();
      }
    }
  });

  // 右键单击 → 动态构建菜单（每次右键都重建，确保文本反映实时状态）
  tray.on('right-click', () => {
    updateTrayMenu();
  });
}

function updateTrayMenu() {
  const contextMenu = Menu.buildFromTemplate([
    {
      label: controlWindow && !controlWindow.isDestroyed() && controlWindow.isVisible()
        ? '隐藏控制窗口'
        : '显示控制窗口',
      click: () => {
        if (controlWindow && !controlWindow.isDestroyed()) {
          if (controlWindow.isVisible()) {
            controlWindow.hide();
          } else {
            controlWindow.show();
            controlWindow.focus();
          }
        }
      },
    },
    {
      label: webviewWindow && !webviewWindow.isDestroyed() && webviewWindow.isVisible()
        ? '隐藏会话窗口'
        : '显示会话窗口',
      click: () => {
        if (webviewWindow && !webviewWindow.isDestroyed()) {
          if (webviewWindow.isVisible()) {
            webviewWindow.hide();
          } else {
            webviewWindow.show();
            webviewWindow.focus();
          }
        }
      },
      enabled: backendRunning,
    },
    { type: 'separator' },
    {
      label: '退出',
      click: () => {
        isQuitting = true;
        if (backend) backend.kill();
        app.quit();
      },
    },
  ]);

  tray.setContextMenu(contextMenu);
}

// ── IPC 注册 ──────────────────────────────────────────────

function registerIpc() {
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

  ipcMain.handle('settings:load', () => {
    const settings = loadSettings();
    return {
      pythonPath: settings.pythonPath || '',
      detectedPythonPath: detectPythonPath(),
    };
  });

  ipcMain.handle('settings:save', (event, values) => {
    saveSettings(values);
    return true;
  });

  ipcMain.on('backend:launch', (event, configKey, overrides, pythonPath) => {
    launchBackend(event, configKey, overrides, pythonPath);
  });

  ipcMain.on('backend:kill', () => {
    isQuitting = true;
    if (backend) backend.kill();
    app.quit();
  });
}

// ── 后端启动流程编排 ──────────────────────────────────────

function launchBackend(event, configKey, overrides, pythonPath) {
  backend = new BackendManager();

  const py = (pythonPath && pythonPath.trim()) || getEffectivePythonPath();
  console.log('[launcher] launchBackend | py:', py, '| REPO_ROOT:', REPO_ROOT);
  console.log('[launcher] launchBackend | configKey:', configKey);

  const cliArgs = ['run.py', '--load', configKey, '--console_log', 'true'];
  const overrideArgs = configManager.buildCliArgs(overrides || {});
  cliArgs.push(...overrideArgs);

  backend.onLog((log) => {
    if (controlWindow && !controlWindow.isDestroyed()) {
      controlWindow.webContents.send('backend:log-line', log);
    }
  });

  backend.onExit((exitCode) => {
    backendRunning = false;
    updateTrayMenu();

    if (exitCode === -1) {
      sendStatus(event, 'evolving');
      return;
    }

    if (exitCode === 0) {
      sendStatus(event, 'stopped');
      // 仅在用户主动退出时才真正退出
      if (isQuitting) {
        app.quit();
      } else {
        // 后端自行退出但用户未要求退出 → 显示通知，保持壳运行
        if (controlWindow && !controlWindow.isDestroyed()) {
          controlWindow.webContents.send('backend:log-line', {
            stream: 'stderr',
            line: '[launcher] 后端进程已停止（退出码 0）',
            ts: Date.now(),
          });
        }
      }
      return;
    }

    sendStatus(event, 'crashed');
    if (controlWindow && !controlWindow.isDestroyed()) {
      controlWindow.webContents.send('backend:log-line', {
        stream: 'stderr',
        line: `[launcher] 后端进程退出，退出码: ${exitCode}`,
        ts: Date.now(),
      });
      // 显示控制窗口让用户看到错误
      controlWindow.show();
    }
    // 不再强制退出 — 让用户通过托盘菜单手动退出
  });

  backend.start(REPO_ROOT, cliArgs, py);
  backendRunning = true;
  sendStatus(event, 'starting');

  const profileValues = configManager.loadProfile(CONFIG_JSON, configKey);
  const host = (overrides && overrides.gateway_host) || profileValues.gateway_host || '127.0.0.1';
  const port = (overrides && overrides.gateway_port) || profileValues.gateway_port || 8765;
  const healthHost = host === '0.0.0.0' ? '127.0.0.1' : host;

  backend.waitForHealth(
    healthHost,
    port,
    () => {
      sendStatus(event, 'running');
      if (controlWindow && !controlWindow.isDestroyed()) {
        controlWindow.webContents.send('backend:health-ok');
      }
      createWebviewWindow(healthHost, port);

      // 后端就绪后最小化控制窗口到托盘
      if (controlWindow && !controlWindow.isDestroyed()) {
        controlWindow.hide();
      }

      updateTrayMenu();
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
  createTray();
});

// 窗口全部关闭时不退出（托盘保持运行）
app.on('window-all-closed', () => {
  // 不做任何事 — 窗口隐藏而非销毁
});

// 仅 isQuitting=true 时才真正退出
app.on('before-quit', () => {
  if (backend) backend.kill();
});