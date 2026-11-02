'use strict';

const crypto = require('crypto');
const path = require('path');
const net = require('net');
const configManager = require('./config-manager');
const { BackendManager } = require('./backend-manager');
const { PythonRuntimeManager } = require('./python-runtime-manager');
const { buildBackendEnv } = require('./runtime-env');
const { runtimeError, sanitize, beforeDeadline } = require('./owned-process');

const CLEANUP_MS = 10000;

/** The sole authority for a desktop launch, from environment preparation through backend close. */
class LauncherController {
  constructor({ repoRoot, configPath, onState, onLog, onReady }) {
    this.repoRoot = repoRoot;
    this.configPath = configPath;
    this.onState = onState;
    this.onLog = onLog;
    this.onReady = onReady;
    this._attempt = null;
    this._closing = false;
    this._shutdownPromise = null;
    this._state = {
      revision: 0, attemptId: null, status: 'idle', phase: null,
      canLaunch: true, canCancel: false, pythonPath: null, errorCode: null, detail: null,
    };
    this.runtime = new PythonRuntimeManager({
      repoRoot,
      onLog: (log) => this.onLog(log),
      onProgress: (phase) => {
        if (this._attempt && !this._attempt.terminationIntent && this._state.status === 'preparing') {
          this._publish({ phase });
        }
      },
    });
  }

  getState() { return { ...this._state }; }

  _publish(changes) {
    this._state = { ...this._state, ...changes, revision: this._state.revision + 1 };
    this.onState(this.getState());
  }

  _log(line, stream = 'stderr') {
    this.onLog({ line: sanitize(line), stream, ts: Date.now() });
  }

  launch(configKey, overrides, pythonPath) {
    if (this._closing || this._attempt || !this._state.canLaunch) {
      throw runtimeError('LAUNCH_BUSY', 'A launch, backend or cleanup activity is already active');
    }
    if (typeof pythonPath !== 'string' || (pythonPath.trim() && !path.isAbsolute(pythonPath.trim()))) {
      throw runtimeError('MANUAL_PYTHON_INVALID', 'Manual Python must be an absolute executable path, or empty for managed Python');
    }
    const prepared = configManager.prepareLaunch(this.configPath, configKey, overrides ?? {});
    const attemptId = crypto.randomUUID();
    this.runtime.beginAttempt(attemptId);
    const attempt = {
      id: attemptId, terminationIntent: null, backend: null, exitResult: null,
      preparationDone: false, error: null, cleanupFailed: false, cleanupError: null,
      portPromise: null, portServer: null, portAbort: null, finishing: null, finishSettled: false,
      work: null, workSettled: false,
    };
    this._attempt = attempt;
    this._publish({
      attemptId, status: 'preparing', phase: 'preflight', canLaunch: false,
      canCancel: true, errorCode: null, detail: null, pythonPath: null,
    });
    attempt.work = this._runAttempt(attempt, prepared, configKey, pythonPath.trim())
      .catch((error) => this._cleanupFailure(attempt, error))
      .finally(() => { attempt.workSettled = true; });
    return { accepted: true, attemptId };
  }

  _assertCurrent(attempt) {
    if (this._attempt !== attempt || attempt.terminationIntent || this._closing || attempt.cleanupFailed) {
      throw runtimeError('CANCELLED', 'The launch is no longer accepting work');
    }
  }

  async _runAttempt(attempt, prepared, configKey, requestedPython) {
    try {
      const selection = requestedPython
        ? await this.runtime.probeManual(requestedPython) : await this.runtime.ensureReady();
      this._assertCurrent(attempt);
      attempt.preparationDone = true;
      this._publish({ status: 'starting', phase: null, pythonPath: selection.executable });
      const { gateway_host: host, gateway_port: port } = prepared.values;
      const healthHost = host === '0.0.0.0' ? '127.0.0.1' : host === '::' ? '::1' : host;
      attempt.portPromise = this._assertPortAvailable(host, port, attempt);
      await attempt.portPromise;
      this._assertCurrent(attempt);
      const backend = new BackendManager();
      attempt.backend = backend;
      backend.onLog((log) => { if (this._attempt === attempt) this.onLog(log); });
      backend.onExit((exitCode, result) => {
        attempt.exitResult = result;
        // Close may beat the continuation of start(). Seal starting immediately.
        if (this._attempt === attempt && !attempt.terminationIntent && !attempt.cleanupFailed) {
          this._publish({
            status: exitCode === 0 ? 'stopped' : 'crashed', phase: null, canCancel: false,
            errorCode: exitCode === 0 ? null : 'BACKEND_EXITED',
            detail: exitCode === 0 ? null : `Backend closed with exit code ${exitCode}`,
          });
        }
      });
      this._assertCurrent(attempt);
      const starting = backend.start(this.repoRoot, ['run.py', '--load', configKey, ...prepared.cliArgs],
        selection.executable, buildBackendEnv(process.env, selection, this.runtime.paths));
      await starting;
      if (this._attempt === attempt && !attempt.terminationIntent && !attempt.cleanupFailed
        && this._state.status === 'starting' && !attempt.exitResult && backend.hasActiveProcess()) {
        backend.waitForHealth(healthHost, port, () => {
          if (this._attempt !== attempt || attempt.terminationIntent || attempt.cleanupFailed || this._closing
            || this._state.status !== 'starting' || !backend.hasActiveProcess()) return;
          this._publish({ status: 'running', canCancel: false, phase: null });
          this.onReady(healthHost, port);
        }, (error) => {
          if (this._attempt !== attempt || attempt.terminationIntent || this._state.status !== 'starting') return;
          if (error) attempt.error = error;
          this._requestTermination(attempt, 'timeout').catch((failure) => this._cleanupFailure(attempt, failure));
        });
      }
      const result = await backend.wait();
      attempt.exitResult = result;
      if (result.spawnError) throw result.spawnError;
    } catch (error) {
      attempt.error = error;
      if (error.code === 'PROCESS_CLEANUP_FAILED') this._cleanupFailure(attempt, error);
      else if (!attempt.terminationIntent && this._attempt === attempt) {
        this._log(error.message || error);
        this._publish({
          status: attempt.preparationDone ? 'crashed' : 'setup_failed', phase: this._state.phase,
          canCancel: false, errorCode: error.code || 'LAUNCH_FAILED', detail: sanitize(error.message || error),
        });
      }
    } finally {
      if (!attempt.cleanupFailed) {
        try { await this._finishAttempt(attempt); } catch (error) { this._cleanupFailure(attempt, error); }
      }
    }
  }

  _assertPortAvailable(host, port, attempt) {
    return new Promise((resolve, reject) => {
      const server = net.createServer();
      const abort = new AbortController();
      attempt.portServer = server;
      attempt.portAbort = abort;
      server.once('error', (error) => reject(abort.signal.aborted
        ? runtimeError('CANCELLED', 'Port availability check was cancelled', error)
        : runtimeError(error.code === 'EADDRINUSE' ? 'PORT_IN_USE' : 'PORT_BIND_FAILED',
          `Backend port is unavailable: ${host}:${port} (${error.code || error.message})`, error)));
      server.once('listening', () => server.close());
      server.once('close', () => {
        if (abort.signal.aborted) reject(runtimeError('CANCELLED', 'Port availability check was cancelled'));
        else resolve();
      });
      // Node的listen signal负责关闭在途监听；取消后的成功回调仍受attempt状态保护。
      server.listen({ host, port, exclusive: true, signal: abort.signal });
    });
  }

  _cancelPortProbe(attempt) {
    if (attempt.portAbort) attempt.portAbort.abort();
    return attempt.portPromise ? attempt.portPromise.then(() => undefined, () => undefined) : Promise.resolve();
  }

  cancel() {
    const attempt = this._attempt;
    if (!attempt || !this._state.canCancel) return Promise.reject(runtimeError('CANCEL_REJECTED', 'Only a preparing or starting launch can be cancelled'));
    return this._requestTermination(attempt, 'cancel');
  }

  _requestTermination(attempt, intent) {
    if (attempt.terminationPromise) return attempt.terminationPromise;
    if (!attempt.terminationIntent) attempt.terminationIntent = intent;
    this._publish({ status: 'cancelling', canCancel: false, canLaunch: false });
    const deadline = Date.now() + CLEANUP_MS;
    const cancelling = this.runtime.cancel();
    const portClosed = this._cancelPortProbe(attempt);
    const stopping = attempt.backend ? attempt.backend.kill() : Promise.resolve();
    attempt.terminationPromise = (async () => {
      await beforeDeadline(Promise.all([cancelling, stopping, portClosed]), deadline, 'Launch cancellation did not finish within ten seconds');
      if (attempt.work) await beforeDeadline(attempt.work, deadline, 'Launch work is still completing after cancellation');
      if (attempt.cleanupFailed) throw attempt.cleanupError;
    })().catch((error) => {
      this._cleanupFailure(attempt, error);
      throw attempt.cleanupError;
    });
    return attempt.terminationPromise;
  }

  _finishAttempt(attempt) {
    if (!attempt.finishing) {
      const deadline = Date.now() + CLEANUP_MS;
      attempt.finishing = (async () => {
        if (attempt.terminationIntent) await this.runtime.cancel();
        if (attempt.backend) await attempt.backend.kill();
        if (attempt.portPromise) await attempt.portPromise.then(() => undefined, () => undefined);
        if (attempt.backend && !attempt.backend.isCleanupConfirmed()) {
          throw runtimeError('PROCESS_CLEANUP_FAILED', 'Backend cleanup is not confirmed');
        }
        await this.runtime.releaseLease();
        if (attempt.cleanupFailed || this._attempt !== attempt) return;
        this._attempt = null;
        const status = attempt.terminationIntent === 'timeout' ? 'timeout'
          : attempt.terminationIntent === 'cancel' ? 'cancelled'
            : attempt.terminationIntent === 'shutdown' ? 'stopped'
              : attempt.error ? (attempt.preparationDone ? 'crashed' : 'setup_failed')
                : attempt.exitResult && attempt.exitResult.code !== 0 ? 'crashed' : 'stopped';
        this._publish({ status, phase: null, canCancel: false, canLaunch: !this._closing,
          ...(attempt.terminationIntent === 'cancel' || attempt.terminationIntent === 'shutdown' ? { errorCode: null, detail: null } : {}),
          ...(attempt.terminationIntent === 'timeout' ? { errorCode: 'HEALTH_TIMEOUT', detail: 'Backend did not become ready within 120 seconds; it has been stopped' } : {}),
        });
      })().finally(() => { attempt.finishSettled = true; });
      attempt.finishing.catch(() => {});
      attempt.finishDeadline = deadline;
    }
    return beforeDeadline(attempt.finishing, attempt.finishDeadline, 'Launch completion or lease release exceeded its cleanup deadline');
  }

  _cleanupFailure(attempt, error) {
    attempt.cleanupFailed = true;
    attempt.cleanupError = runtimeError('PROCESS_CLEANUP_FAILED', sanitize(error.message || error), error);
    if (this._attempt !== attempt) return;
    this._log(`Cleanup remains incomplete: ${attempt.cleanupError.message}`);
    this._publish({
      status: attempt.preparationDone ? 'crashed' : 'setup_failed', canLaunch: false, canCancel: false,
      errorCode: 'PROCESS_CLEANUP_FAILED', detail: attempt.cleanupError.message,
    });
  }

  shutdown() {
    this._closing = true;
    if (this._shutdownPromise) return this._shutdownPromise;
    this._shutdownPromise = this._shutdown().catch((error) => {
      if (this._attempt) this._cleanupFailure(this._attempt, error);
      this._shutdownPromise = null; // 显式再次退出可重新核对真实资源，但不会自动重启准备。
      throw error;
    });
    return this._shutdownPromise;
  }

  async _shutdown() {
    const attempt = this._attempt;
    if (!attempt) return;
    if (!attempt.terminationIntent) attempt.terminationIntent = 'shutdown';
    this._publish({ status: 'cancelling', canCancel: false, canLaunch: false });
    const deadline = Date.now() + CLEANUP_MS;
    const cancellation = this.runtime.cancel().then(() => null, (error) => error);
    const portClosed = this._cancelPortProbe(attempt);
    let backendError = null;
    if (attempt.backend && !attempt.backend.isCleanupConfirmed()) {
      try { await beforeDeadline(attempt.backend.kill(), deadline, 'Backend is still stopping'); }
      catch (error) { backendError = error; }
    }
    await beforeDeadline(cancellation, deadline, 'Runtime cancellation is still active');
    await beforeDeadline(portClosed, deadline, 'Port availability check is still closing');
    if (attempt.work && !attempt.workSettled) {
      await beforeDeadline(attempt.work, deadline, 'Launch completion is still active');
    }
    if (attempt.finishing && !attempt.finishSettled) {
      await beforeDeadline(attempt.finishing.then(() => undefined, () => undefined), deadline, 'Previous cleanup is still active');
    }
    if (attempt.backend && !attempt.backend.isCleanupConfirmed()) {
      throw backendError || runtimeError('PROCESS_CLEANUP_FAILED', 'Backend close or process-tree cleanup remains uncertain');
    }
    // This is an explicit recheck; only the retained real objects may authorize lease release.
    await beforeDeadline(this.runtime.releaseLease(), deadline, 'Runtime lease cleanup is still active');
    if (attempt.portPromise) await beforeDeadline(attempt.portPromise.then(() => undefined, () => undefined), deadline, 'Port probe has not finished');
    if (this._attempt === attempt) this._attempt = null;
    this._publish({ status: 'stopped', phase: null, canLaunch: false, canCancel: false });
  }
}

module.exports = { LauncherController };
