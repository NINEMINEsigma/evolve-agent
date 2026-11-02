'use strict';

const { spawn } = require('child_process');
const { StringDecoder } = require('string_decoder');
const path = require('path');

const LINE_BYTES = 16 * 1024;
const CAPTURE_BYTES = 64 * 1024;
const CLEANUP_MS = 10000;
const TASKKILL_MS = 5000;

function runtimeError(code, message, cause) {
  return Object.assign(new Error(message, cause ? { cause } : undefined), { code });
}

function sanitize(text) {
  return String(text)
    .replace(/\u001b\[[0-9;?]*[ -/]*[@-~]/g, '')
    .replace(/[a-z][a-z\d+.-]*:\/\/[^\s<>"']+/gi, '[redacted-url]')
    .replace(/["']?(?:proxy-)?authorization["']?\s*[:=]\s*[^\r\n]*/gi, 'authorization=[redacted]')
    .replace(/["']?(password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret)["']?\s*[:=]\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\r\n]*)/gi, '$1=[redacted]');
}

function beforeDeadline(promise, deadline, message) {
  let timer;
  const expired = new Promise((resolve, reject) => {
    timer = setTimeout(() => reject(runtimeError('PROCESS_CLEANUP_FAILED', message)), Math.max(0, deadline - Date.now()));
  });
  return Promise.race([promise, expired]).finally(() => clearTimeout(timer));
}

/** Owns a real child until close, including after an observer has timed out. */
class OwnedProcess {
  constructor({ executable, args, cwd, env, timeoutMs = null, onLog = () => {} }) {
    this.options = { executable, args, cwd, env, timeoutMs, onLog };
    this.child = null;
    this.result = null;
    this.spawnError = null;
    this.cancelled = false;
    this.timedOut = false;
    this.stdout = '';
    this.stderr = '';
    this.stdoutTruncated = false;
    this.stderrTruncated = false;
    this._started = false;
    this._exited = false;
    this._cancelPromise = null;
    this._cancelSettled = false;
    this._deadline = null;
    this._cleanupFailure = null;
    this._taskkill = null;
    this._taskkillSucceeded = false;
    this._taskkillClosed = false;
    this._timer = null;
    this._completion = new Promise((resolve) => { this._resolveCompletion = resolve; });
    this._spawnOutcome = new Promise((resolve) => { this._resolveSpawn = resolve; });
    this._failure = new Promise((resolve, reject) => { this._rejectFailure = reject; });
    this._failure.catch(() => {}); // 等待者可有界退出，但真实资源与异常仍由本对象持有。
    this._streams = {
      stdout: { decoder: new StringDecoder('utf8'), buffer: '', truncated: false },
      stderr: { decoder: new StringDecoder('utf8'), buffer: '', truncated: false },
    };
  }

  start() {
    if (this._startPromise) return this._startPromise;
    if (this.cancelled) {
      this._finish(null, null);
      return Promise.reject(runtimeError('CANCELLED', 'Process start was cancelled'));
    }
    this._started = true;
    try {
      this.child = spawn(this.options.executable, this.options.args, {
        cwd: this.options.cwd,
        env: this.options.env,
        windowsHide: true,
        shell: false,
        stdio: ['ignore', 'pipe', 'pipe'],
      });
    } catch (error) {
      this.spawnError = error;
      this._resolveSpawn({ error });
      this._finish(null, null);
    }
    if (this.child) {
      this.child.once('spawn', () => this._resolveSpawn({ error: null }));
      this.child.once('error', (error) => {
        this.spawnError = error;
        this._resolveSpawn({ error });
      });
      this.child.once('exit', () => { this._exited = true; });
      this.child.once('close', (code, signal) => this._finish(code, signal));
      for (const stream of ['stdout', 'stderr']) {
        this.child[stream].on('data', (chunk) => this._consume(stream, chunk));
        this.child[stream].on('error', (error) => this._failCleanup(error));
      }
      if (this.options.timeoutMs !== null) {
        this._timer = setTimeout(() => {
          this.timedOut = true;
          this.cancel().catch((error) => this._failCleanup(error));
        }, this.options.timeoutMs);
      }
    }
    this._startPromise = this._spawnOutcome.then(({ error }) => {
      if (error) throw error;
      if (this.cancelled) throw runtimeError('CANCELLED', 'Process start was cancelled');
    });
    return this._startPromise;
  }

  wait() {
    return Promise.race([this._completion, this._failure]);
  }

  waitForClose() {
    return this._completion;
  }

  hasExited() {
    return this.result !== null;
  }

  hasActiveProcess() {
    return this.child !== null && !this._exited && this.result === null;
  }

  isCleanupConfirmed() {
    if (this.result === null || (this._cancelPromise && !this._cancelSettled)) return false;
    if (!this._cleanupFailure) return true;
    return this._taskkillSucceeded && this._taskkillClosed;
  }

  cancel() {
    if (this._cancelPromise) return this._cancelPromise;
    this.cancelled = true;
    this._deadline = Date.now() + CLEANUP_MS;
    this._cancelPromise = this._cancelUntil(this._deadline).catch((error) => {
      this._failCleanup(error);
      throw this._cleanupFailure;
    }).finally(() => { this._cancelSettled = true; });
    return this._cancelPromise;
  }

  async _cancelUntil(deadline) {
    if (!this._started) {
      this._resolveSpawn({ error: runtimeError('CANCELLED', 'Process was cancelled before spawn') });
      this._finish(null, null);
      return this.result;
    }
    if (this.result) {
      if (!this.isCleanupConfirmed()) throw this._cleanupFailure;
      return this.result;
    }
    const outcome = await beforeDeadline(this._spawnOutcome, deadline, 'Spawn outcome did not settle before cancellation deadline');
    if (outcome.error) return beforeDeadline(this._completion, deadline, 'Failed spawn did not close');
    if (this.result) return this.result;
    if (this._exited) {
      const result = await beforeDeadline(this._completion, deadline, 'Exited process pipes did not close');
      if (result.code !== 0 || result.signal) {
        throw runtimeError('PROCESS_CLEANUP_FAILED', 'Process tree termination is uncertain after an abnormal exit');
      }
      return result;
    }
    if (!Number.isInteger(this.child.pid)) {
      throw runtimeError('PROCESS_CLEANUP_FAILED', 'Cancellation has no confirmed child process identifier');
    }
    await this._killTree(this.child.pid, deadline);
    return beforeDeadline(this._completion, deadline, 'Terminated process did not close before cancellation deadline');
  }

  async _killTree(pid, deadline) {
    const systemRootKey = Object.keys(process.env).find((key) => key.toUpperCase() === 'SYSTEMROOT');
    if (!systemRootKey || !path.isAbsolute(process.env[systemRootKey])) {
      throw runtimeError('PROCESS_CLEANUP_FAILED', 'An absolute Windows SystemRoot is required to terminate the process tree');
    }
    const executable = path.join(process.env[systemRootKey], 'System32', 'taskkill.exe');
    const completion = new Promise((resolve, reject) => {
      try {
        this._taskkill = spawn(executable, ['/T', '/F', '/PID', String(pid)], {
          windowsHide: true, shell: false, stdio: 'ignore',
        });
      } catch (error) { reject(error); return; }
      this._taskkill.once('error', reject);
      this._taskkill.once('close', (code, signal) => {
        this._taskkillClosed = true;
        this._taskkillSucceeded = code === 0 && signal === null;
        if (this._taskkillSucceeded) resolve();
        else reject(runtimeError('PROCESS_CLEANUP_FAILED', `taskkill failed with exit code ${code}; process tree state is uncertain`));
      });
    });
    this._taskkillCompletion = completion;
    completion.catch(() => {});
    await beforeDeadline(completion, Math.min(deadline, Date.now() + TASKKILL_MS), 'taskkill did not finish before its deadline');
  }

  _failCleanup(error) {
    if (this._cleanupFailure) return;
    this._cleanupFailure = runtimeError('PROCESS_CLEANUP_FAILED', sanitize(error.message || error), error);
    this._rejectFailure(this._cleanupFailure);
  }

  _consume(stream, chunk) {
    const text = this._streams[stream].decoder.write(chunk);
    const capture = Buffer.from(this[stream] + text, 'utf8');
    if (capture.length > CAPTURE_BYTES) {
      this[`${stream}Truncated`] = true;
      this[stream] = (stream === 'stderr' ? capture.subarray(-CAPTURE_BYTES) : capture.subarray(0, CAPTURE_BYTES)).toString('utf8');
    } else this[stream] = capture.toString('utf8');
    this._lines(stream, text);
  }

  _lines(stream, text) {
    const state = this._streams[stream];
    const pieces = text.split(/([\r\n])/);
    for (const piece of pieces) {
      if (piece === '\r' || piece === '\n') {
        this._emitLine(stream);
      } else if (!state.truncated) {
        const bytes = Buffer.from(state.buffer + piece, 'utf8');
        state.buffer = bytes.subarray(0, LINE_BYTES).toString('utf8');
        state.truncated = bytes.length > LINE_BYTES;
      }
    }
  }

  _emitLine(stream) {
    const state = this._streams[stream];
    if (state.buffer || state.truncated) {
      this.options.onLog({ stream, line: sanitize(state.buffer) + (state.truncated ? ' [truncated]' : ''), ts: Date.now() });
    }
    state.buffer = '';
    state.truncated = false;
  }

  _finish(code, signal) {
    if (this.result) return;
    clearTimeout(this._timer);
    for (const stream of ['stdout', 'stderr']) {
      this._lines(stream, this._streams[stream].decoder.end());
      this._emitLine(stream);
    }
    this.result = {
      code, signal, spawnError: this.spawnError, cancelled: this.cancelled, timedOut: this.timedOut,
      stdout: this.stdout, stderr: this.stderr,
      stdoutTruncated: this.stdoutTruncated, stderrTruncated: this.stderrTruncated,
    };
    this._resolveCompletion(this.result);
  }
}

module.exports = { OwnedProcess, runtimeError, sanitize, beforeDeadline };
