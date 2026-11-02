'use strict';

const http = require('http');
const { OwnedProcess, runtimeError } = require('./owned-process');

const HEALTH_INTERVAL_MS = 500;
const HEALTH_TIMEOUT_MS = 120000;
const HEALTH_REQUEST_MS = 3000;

/** Owns one backend and all of its health requests, without choosing Python or installing it. */
class BackendManager {
  constructor() {
    this._process = null;
    this._logCallbacks = [];
    this._exitCallbacks = [];
    this._healthGeneration = 0;
    this._healthTimer = null;
    this._pollTimer = null;
    this._requests = new Map();
  }

  start(repoRoot, cliArgs, pythonPath, env) {
    if (this._process) return Promise.reject(runtimeError('LAUNCH_BUSY', 'A backend manager cannot be reused for another process'));
    this._process = new OwnedProcess({
      executable: pythonPath, args: cliArgs, cwd: repoRoot, env, timeoutMs: null,
      onLog: (log) => this._logCallbacks.forEach((callback) => callback(log)),
    });
    const starting = this._process.start();
    this._process.waitForClose().then((result) => {
      this.stopHealthPoll();
      const exitCode = result.spawnError ? -999 : result.signal !== null ? 1 : result.code;
      for (const callback of this._exitCallbacks) callback(exitCode, result);
    });
    return starting;
  }

  onLog(callback) { this._logCallbacks.push(callback); }
  onExit(callback) { this._exitCallbacks.push(callback); }

  wait() {
    if (!this._process) return Promise.reject(runtimeError('LAUNCH_BUSY', 'The backend has not been created'));
    return this._process.wait();
  }

  hasActiveProcess() {
    return this._process !== null && this._process.hasActiveProcess();
  }

  isCleanupConfirmed() {
    return (!this._process || this._process.isCleanupConfirmed()) && this._requests.size === 0;
  }

  waitForHealth(host, port, onReady, onTimeout) {
    this.stopHealthPoll();
    const generation = this._healthGeneration;
    const active = () => generation === this._healthGeneration && this.hasActiveProcess();
    const poll = () => {
      if (!active()) return;
      let request;
      try {
        request = http.get({ hostname: host, port, path: '/health', timeout: HEALTH_REQUEST_MS }, (response) => {
          response.on('error', () => {}); // 网络请求失败由下一次轮询处理，不是应用逻辑恢复。
          response.resume();
          if (response.statusCode === 200 && active()) {
            this.stopHealthPoll();
            onReady();
          }
        });
      } catch (error) {
        this.stopHealthPoll();
        onTimeout(error);
        return;
      }
      let close;
      const closed = new Promise((resolve) => { close = resolve; });
      this._requests.set(request, closed);
      request.once('close', () => {
        this._requests.delete(request);
        close();
        if (active()) this._pollTimer = setTimeout(poll, HEALTH_INTERVAL_MS);
      });
      request.on('error', () => {});
      request.once('timeout', () => request.destroy());
    };
    this._healthTimer = setTimeout(() => {
      if (generation !== this._healthGeneration) return;
      this.stopHealthPoll();
      onTimeout();
    }, HEALTH_TIMEOUT_MS);
    poll();
  }

  /** Invalidate callbacks synchronously; the returned promise confirms request close. */
  stopHealthPoll() {
    this._healthGeneration += 1;
    clearTimeout(this._healthTimer);
    clearTimeout(this._pollTimer);
    this._healthTimer = null;
    this._pollTimer = null;
    const closed = [...this._requests.values()];
    for (const request of this._requests.keys()) request.destroy();
    return Promise.all(closed).then(() => undefined);
  }

  async kill() {
    const healthClosed = this.stopHealthPoll();
    if (this._process) await this._process.cancel();
    await healthClosed;
    if (!this.isCleanupConfirmed()) {
      throw runtimeError('PROCESS_CLEANUP_FAILED', 'Backend process or health requests have not confirmed cleanup');
    }
  }
}

module.exports = { BackendManager };
