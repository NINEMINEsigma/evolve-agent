/**
 * backend-manager.js — 后端进程生命周期管理
 *
 * 职责：
 *   - 通过 child_process.spawn 拉起 python run.py（隐藏命令行窗口）
 *   - 捕获 stdout/stderr pipe 按行推送日志
 *   - 轮询 GET /health 检测就绪
 *   - 进程退出回调（区分正常/进化/崩溃）
 *   - 强制终止进程树（taskkill /T /F）
 */

'use strict';

const { spawn, execSync } = require('child_process');
const http = require('http');

const HEALTH_POLL_INTERVAL_MS = 500;
const HEALTH_TIMEOUT_MS = 120000;

class BackendManager {
  constructor() {
    this._proc = null;
    this._logCallbacks = [];
    this._exitCallbacks = [];
    this._healthTimer = null;
    this._healthTimedOut = false;
  }

  /**
   * 拉起后端进程。
   * @param {string} repoRoot — 仓库根目录（CWD，run.py 所在处）
   * @param {string[]} cliArgs — ['run.py', '--load', 'key', '--console_log', 'true', ...]
   * @param {string} pythonPath — python 可执行文件路径（默认 'python'）
   */
  start(repoRoot, cliArgs, pythonPath = 'python') {
    this._killIfNeeded();

    const fullArgs = [pythonPath, ...cliArgs];

    this._proc = spawn(pythonPath, cliArgs, {
      cwd: repoRoot,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: {
        ...process.env,
        PYTHONIOENCODING: 'utf-8',
        PYTHONUTF8: '1',
      },
    });

    // stdout 按行分割推送
    this._proc.stdout.on('data', (chunk) => {
      this._emitLogLines(chunk, 'stdout');
    });

    // stderr 按行分割推送
    this._proc.stderr.on('data', (chunk) => {
      this._emitLogLines(chunk, 'stderr');
    });

    // 进程退出
    this._proc.on('exit', (code, signal) => {
      this._stopHealthPoll();
      const exitCode = signal !== null ? -1 : code;
      this._exitCallbacks.forEach((cb) => cb(exitCode));
    });

    // spawn 错误（如 python 不在 PATH）
    this._proc.on('error', (err) => {
      this._emitLog({
        stream: 'stderr',
        line: `[launcher] 无法启动后端进程: ${err.message}`,
        ts: Date.now(),
      });
      // 触发退出回调，模拟进程退出
      this._exitCallbacks.forEach((cb) => cb(-999));
    });
  }

  /**
   * 注册日志回调，每行 stdout/stderr 触发。
   * @param {(log: {stream, line, ts}) => void} callback
   */
  onLog(callback) {
    this._logCallbacks.push(callback);
  }

  /**
   * 注册退出回调。
   * @param {(exitCode: number) => void} callback
   *   exitCode 语义：
   *     0    → 正常退出
   *     -1   → 进化重启（run.py 内部 while 循环会自动重启）
   *     其他 → 崩溃
   *     -999 → spawn 错误（python 不在 PATH 等）
   */
  onExit(callback) {
    this._exitCallbacks.push(callback);
  }

  /**
   * 轮询 /health，就绪后回调。
   * @param {string} host — 默认 '127.0.0.1'
   * @param {number} port — 默认 8765
   * @param {Function} onReady — 就绪回调
   * @param {Function} [onTimeout] — 超时回调
   */
  waitForHealth(host = '127.0.0.1', port = 8765, onReady, onTimeout) {
    this._stopHealthPoll();
    this._healthTimedOut = false;

    const startTime = Date.now();

    const poll = () => {
      if (this._healthTimedOut) return;

      // 进程已退出则停止轮询
      if (this._proc && this._proc.exitCode !== null) {
        this._stopHealthPoll();
        return;
      }

      // 超时检查
      if (Date.now() - startTime > HEALTH_TIMEOUT_MS) {
        this._healthTimedOut = true;
        this._stopHealthPoll();
        if (onTimeout) onTimeout();
        return;
      }

      const req = http.get(
        { hostname: host, port, path: '/health', timeout: 3000 },
        (res) => {
          if (res.statusCode === 200) {
            this._stopHealthPoll();
            onReady();
          }
          res.resume();
        }
      );

      req.on('error', () => {
        // 连接失败 — 正常，后端还在启动
      });

      req.on('timeout', () => {
        req.destroy();
      });
    };

    this._healthTimer = setInterval(poll, HEALTH_POLL_INTERVAL_MS);
    poll(); // 立即执行一次
  }

  /**
   * 强制终止进程树。
   * Windows 使用 taskkill /T /F /PID。
   */
  kill() {
    this._stopHealthPoll();
    if (!this._proc || this._proc.exitCode !== null) return;

    const pid = this._proc.pid;
    try {
      execSync(`taskkill /T /F /PID ${pid}`, { windowsHide: true });
    } catch {
      // 进程可能已退出
    }
    this._proc = null;
  }

  // ── 内部方法 ──────────────────────────────────────────

  _emitLogLines(chunk, stream) {
    const text = chunk.toString('utf-8');
    const lines = text.split(/\r?\n/);
    for (const line of lines) {
      if (line.length === 0) continue;
      this._emitLog({ stream, line, ts: Date.now() });
    }
  }

  _emitLog(log) {
    for (const cb of this._logCallbacks) {
      cb(log);
    }
  }

  _stopHealthPoll() {
    if (this._healthTimer) {
      clearInterval(this._healthTimer);
      this._healthTimer = null;
    }
  }

  _killIfNeeded() {
    if (this._proc && this._proc.exitCode === null) {
      this.kill();
    }
  }
}

module.exports = { BackendManager };