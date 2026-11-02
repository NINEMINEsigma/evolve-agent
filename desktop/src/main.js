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
 *   ├── runtime/                  ← uv、独立 Python 与依赖均保留在安装目录
 *   └── workspace/               ← 运行时生成
 */

'use strict';

const { app, BrowserWindow, ipcMain, Tray, Menu, nativeImage } = require('electron');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { configManager, LauncherController } = require('./requires');
const { sanitize } = require('./owned-process');

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

// ── 壳设置：空路径仅表示使用内部托管环境 ──────────────────────

const SETTINGS_DEFAULTS = { pythonPath: '' };

function loadSettings() {
  let raw;
  try { raw = fs.readFileSync(SETTINGS_JSON, 'utf-8'); }
  catch (error) {
    if (error.code === 'ENOENT') return { ...SETTINGS_DEFAULTS };
    throw error;
  }
  const settings = JSON.parse(raw);
  if (!settings || typeof settings !== 'object' || Array.isArray(settings)
    || (Object.hasOwn(settings, 'pythonPath') && typeof settings.pythonPath !== 'string')) {
    throw new TypeError('Desktop settings must be an object with a string Python path');
  }
  return { ...SETTINGS_DEFAULTS, ...settings };
}

function saveSettings(values) {
  if (!values || typeof values !== 'object' || typeof values.pythonPath !== 'string') {
    throw new TypeError('Desktop Python path must be a string');
  }
  const settings = { ...loadSettings(), pythonPath: values.pythonPath.trim() };
  const temporary = `${SETTINGS_JSON}.${crypto.randomUUID()}.tmp`;
  fs.writeFileSync(temporary, JSON.stringify(settings, null, 2), { encoding: 'utf-8', flag: 'wx' });
  fs.renameSync(temporary, SETTINGS_JSON);
}

// ── 全局状态 ──────────────────────────────────────────────

let controlWindow = null;
let webviewWindow = null;
let controller = null;
let tray = null;
let isQuitting = false;
let quitPending = null;
let allowQuit = false;

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
    if (!allowQuit) {
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
  const authority = host.includes(':') && !host.startsWith('[') ? `[${host}]` : host;
  const url = `http://${authority}:${port}`;
  if (webviewWindow && !webviewWindow.isDestroyed()) {
    // 新启动可以使用不同端口，不能只展示旧窗口继续连接旧后端。
    if (webviewWindow.webContents.getURL().replace(/\/$/, '') !== url) webviewWindow.loadURL(url);
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

  webviewWindow.loadURL(url);

  // 关闭按钮 → 隐藏窗口（不杀后端，不退出）
  webviewWindow.on('close', (e) => {
    if (!allowQuit) {
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
  if (!tray) return;
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
      enabled: controller !== null && controller.getState().status === 'running',
    },
    { type: 'separator' },
    {
      label: '退出',
      click: () => { requestQuit(); },
    },
  ]);

  tray.setContextMenu(contextMenu);
}

// ── IPC 注册 ──────────────────────────────────────────────

function registerIpc() {
  ipcMain.handle('config:field-definitions', () => {
    return configManager.getFieldDefinitions();
  });

  ipcMain.handle('config:list-profiles', () => {
    return configManager.listProfiles(CONFIG_JSON);
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
      pythonPath: settings.pythonPath,
      runtime: controller.runtime.describe(),
    };
  });

  ipcMain.handle('settings:save', (event, values) => {
    saveSettings(values);
    return true;
  });

  ipcMain.handle('backend:launch', (event, configKey, overrides, pythonPath) => controller.launch(configKey, overrides, pythonPath));
  ipcMain.handle('backend:get-state', () => controller.getState());
  ipcMain.handle('backend:cancel', () => controller.cancel());
  ipcMain.on('backend:kill', () => { requestQuit(); });
}

// ── 唯一退出与状态出口 ────────────────────────────────────────

function send(channel, payload) {
  if (controlWindow && !controlWindow.isDestroyed() && !controlWindow.webContents.isDestroyed()) {
    controlWindow.webContents.send(channel, payload);
  }
}

function requestQuit() {
  if (quitPending) return quitPending;
  isQuitting = true;
  quitPending = (async () => {
    try {
      if (controller) await controller.shutdown();
      allowQuit = true;
      app.quit();
    } catch (error) {
      isQuitting = false;
      send('backend:log-line', { stream: 'stderr', line: sanitize(`Exit cleanup failed: ${error.message || error}`), ts: Date.now() });
      if (controlWindow && !controlWindow.isDestroyed()) controlWindow.show();
    } finally { quitPending = null; }
  })();
  return quitPending;
}

// ── App 生命周期 ──────────────────────────────────────────

const primaryInstance = app.requestSingleInstanceLock();
if (!primaryInstance) {
  allowQuit = true;
  app.quit();
} else {
  app.on('second-instance', () => {
    if (controlWindow && !controlWindow.isDestroyed()) {
      controlWindow.show();
      controlWindow.focus();
    }
  });
  app.whenReady().then(() => {
    controller = new LauncherController({
      repoRoot: REPO_ROOT,
      configPath: CONFIG_JSON,
      onState: (state) => {
        send('backend:status', state);
        updateTrayMenu();
        if (['setup_failed', 'crashed', 'timeout'].includes(state.status)
          && controlWindow && !controlWindow.isDestroyed()) controlWindow.show();
      },
      onLog: (log) => send('backend:log-line', log),
      onReady: (host, port) => {
        if (isQuitting) return;
        send('backend:health-ok');
        createWebviewWindow(host, port);
        if (controlWindow && !controlWindow.isDestroyed()) controlWindow.hide();
        updateTrayMenu();
      },
    });
    registerIpc();
    createControlWindow();
    createTray();
    updateTrayMenu();
  });
}

app.on('window-all-closed', () => {
  // 窗口关闭仍仅隐藏，退出由统一资源清理边界完成。
});

app.on('before-quit', (event) => {
  if (allowQuit) return;
  event.preventDefault();
  requestQuit();
});