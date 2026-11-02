'use strict';

const fs = require('fs');
const fsp = fs.promises;
const path = require('path');
const crypto = require('crypto');
const { TextDecoder } = require('util');
const { OwnedProcess, runtimeError, sanitize, beforeDeadline } = require('./owned-process');
const { runtimePaths, buildInstallerEnv } = require('./runtime-env');

const STATE_SCHEMA = 2;
const SHORT_MS = 20000;
const INSTALL_MS = 30 * 60 * 1000;
const CLEANUP_MS = 10000;
const JSON_BYTES = 64 * 1024;
const LOCK_BYTES = 32 * 1024 * 1024;
const UV_BYTES = 128 * 1024 * 1024;
const HASH = /^[a-f0-9]{64}$/;
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i;
const RELEASE_FIELDS = [
  'schemaVersion', 'platform', 'arch', 'uvVersion', 'pythonRequest', 'pythonVersion',
  'uvSha256', 'requirementsInputSha256', 'requirementsLockSha256', 'probeSha256',
];
const STATE_FIELDS = [
  'schemaVersion', 'installRoot', 'pythonRelativePath', 'prefixRelativePath',
  'basePythonRelativePath', 'pythonVersion', 'platform', 'arch', 'readyAt',
];
const PROBE_FIELDS = [
  'schemaVersion', 'mode', 'ok', 'errorCode', 'executable', 'prefix', 'basePrefix', 'version', 'architecture',
];
const LEASE_FIELDS = ['schemaVersion', 'attemptId', 'pid', 'installRoot', 'startedAt', 'token'];
const PROBE_ERRORS = Object.freeze({
  10: 'DEPENDENCY_MISSING',
  11: 'PYTHON_VERSION_MISMATCH',
  12: 'PREFIX_MISMATCH',
  13: 'ARCHITECTURE_MISMATCH',
  70: 'PROBE_INTERNAL_ERROR',
});
// 发布规格是唯一人工配置来源；发行资源还会在每次准备时重新核对。
const SPEC = Object.freeze(require('../runtime/release-spec.json'));

function digest(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

function canonical(value) {
  return path.resolve(value).toLowerCase();
}

function samePath(left, right) {
  return canonical(left) === canonical(right);
}

function within(value, root) {
  const relative = path.relative(canonical(root), canonical(value));
  return relative === '' || (relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative));
}

function absolute(value) {
  return typeof value === 'string' && value.length > 0 && !value.includes('\0')
    && path.isAbsolute(value) && /^[a-z]:[\\/]/i.test(value)
    && !/[<>"|?*]/.test(value) && !value.slice(2).includes(':');
}

function exactFields(value, fields, code, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || Object.keys(value).length !== fields.length
    || fields.some((field) => !Object.prototype.hasOwnProperty.call(value, field))) {
    throw runtimeError(code, `${label} has an unsupported schema`);
  }
}

function json(bytes, code, label) {
  try {
    return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
  } catch (error) {
    throw runtimeError(code, `${label} is not a single valid UTF-8 JSON document`, error);
  }
}

function timestamp(value) {
  return typeof value === 'string' && /^\d{4}-\d\d-\d\dT/.test(value) && Number.isFinite(Date.parse(value));
}

function errorDetail(error) {
  return sanitize(error && error.message ? error.message : error);
}

/** Independent of Electron. One instance retains every owned process across launch attempts. */
class PythonRuntimeManager {
  constructor({ repoRoot, onProgress = () => {}, onLog = () => {} }) {
    if (!absolute(repoRoot)) throw runtimeError('RUNTIME_PATH_INVALID', 'An absolute Windows installation directory is required');
    this.repoRoot = path.resolve(repoRoot);
    this.paths = runtimePaths(this.repoRoot);
    this.onProgress = onProgress;
    this.onLog = onLog;
    this.attemptId = crypto.randomUUID();
    this.requestCancelled = false;
    this.commitState = 'not_started';
    this.environmentDisposition = 'uncommitted';
    this._runtimePromise = null;
    this._runtimeSettled = true;
    this._request = null;
    this._currentProcess = null;
    this._ownedProcesses = new Set();
    this._processCancellations = new Map();
    this._fileHandles = new Set();
    this._writeProbeTemporary = null;
    this._lease = null;
    this._releasePromise = null;
    this._cancelPromise = null;
    this._cancelSettled = true;
    this._cancelDeadline = null;
    this._cleanupBlocked = false;
    this._cleanupError = null;
    this._environmentCreated = false;
    this._environmentRemoved = false;
    this._stateTemporary = null;
    this._lastState = null;
    this._installRoot = null;
    this._resources = null;
  }

  /** Synchronous and read-only: metadata readiness never substitutes for this attempt's probe. */
  describe() {
    this._resolveInstallRoot();
    const state = this._readState();
    const currentRoot = state !== null && samePath(state.installRoot, this._installRoot);
    return {
      modeDefault: 'managed',
      runtimeRoot: this.paths.root,
      environmentPath: this.paths.environment,
      pythonVersion: state ? state.pythonVersion : SPEC.pythonVersion,
      managedExecutable: currentRoot ? this._relativeTarget(state.pythonRelativePath) : null,
      ready: currentRoot,
    };
  }

  /** Called by the controller only after the previous activity has released its lease. */
  beginAttempt(attemptId) {
    if (typeof attemptId !== 'string' || !UUID.test(attemptId)) {
      throw runtimeError('STATE_INVALID', 'A UUID launch attempt identifier is required');
    }
    if (!this._runtimeSettled || !this._cancelSettled || this._lease || this._releasePromise || this._cleanupBlocked
      || this._cleanupError || this._fileHandles.size || this._writeProbeTemporary
      || [...this._ownedProcesses].some((owned) => !owned.isCleanupConfirmed())) {
      throw runtimeError('PROCESS_CLEANUP_FAILED', 'The previous runtime activity has not been explicitly released');
    }
    this.attemptId = attemptId;
    this.requestCancelled = false;
    this.commitState = 'not_started';
    this.environmentDisposition = 'uncommitted';
    this._runtimePromise = null;
    this._request = null;
    this._cancelPromise = null;
    this._cancelSettled = true;
    this._cancelDeadline = null;
    this._environmentCreated = false;
    this._environmentRemoved = false;
    this._stateTemporary = null;
    this._resources = null;
    // _ownedProcesses and cancellation observations intentionally survive retries.
  }

  ensureReady() {
    return this._startPreparation('managed', null);
  }

  probeManual(pythonPath) {
    if (!absolute(pythonPath)) {
      return Promise.reject(runtimeError('MANUAL_PYTHON_INVALID', 'Manual Python must be an absolute executable file path'));
    }
    return this._startPreparation('manual', path.resolve(pythonPath));
  }

  _startPreparation(mode, executable) {
    if (this._runtimePromise) {
      if (this._request.mode !== mode || this._request.executable !== executable) {
        return Promise.reject(runtimeError('PREPARATION_LOCKED', 'This attempt already owns a different Python preparation'));
      }
      return this._runtimePromise;
    }
    if (this._lease || this._releasePromise || this._cleanupBlocked || this.requestCancelled) {
      return Promise.reject(runtimeError('PROCESS_CLEANUP_FAILED', 'Runtime preparation requires a released, uncancelled attempt'));
    }
    this._request = { mode, executable };
    this._runtimeSettled = false;
    this._runtimePromise = this._prepare(mode, executable).catch(async (error) => {
      try {
        await this._cleanupAttempt();
      } catch (cleanupError) {
        this._cleanupError = cleanupError;
        throw runtimeError('PROCESS_CLEANUP_FAILED',
          `Runtime preparation failed: ${errorDetail(error)}; cleanup is incomplete: ${errorDetail(cleanupError)}`, error);
      }
      throw error;
    }).finally(() => { this._runtimeSettled = true; });
    // The controller observes the returned error; retain an observer if its own deadline expires.
    this._runtimePromise.catch(() => {});
    return this._runtimePromise;
  }

  _checkCancelled() {
    if (this.requestCancelled) throw runtimeError('CANCELLED', 'Python preparation was cancelled');
  }

  _progress(phase) {
    this._checkCancelled();
    this.onProgress(phase);
    this._checkCancelled();
  }

  _resolveInstallRoot() {
    try {
      const real = fs.realpathSync.native(this.repoRoot);
      if (!fs.statSync(real).isDirectory()) throw new Error('Installation root is not a directory');
      if (this._installRoot && !samePath(real, this._installRoot)) throw new Error('Installation root changed during the activity');
      this._installRoot = canonical(real);
      // Keep one physical installation root for state ownership and probe comparisons.
      if (!samePath(this.repoRoot, real)) {
        this.repoRoot = path.resolve(real);
        this.paths = runtimePaths(this.repoRoot);
      }
    } catch (error) {
      throw runtimeError('RUNTIME_PATH_INVALID', `Installation root is unavailable: ${this.repoRoot}`, error);
    }
  }

  /** Reject links before descent, including junctions; missing tails are allowed only explicitly. */
  _assertPath(target, allowMissing = false) {
    if (!absolute(target) || !within(target, this.repoRoot)) {
      throw runtimeError('RUNTIME_PATH_INVALID', `Managed path is outside the installation: ${target}`);
    }
    const relative = path.relative(this.repoRoot, path.resolve(target));
    let cursor = this.repoRoot;
    for (const component of relative ? relative.split(path.sep) : []) {
      cursor = path.join(cursor, component);
      let stat;
      try { stat = fs.lstatSync(cursor); } catch (error) {
        if (allowMissing && error.code === 'ENOENT') return false;
        throw error;
      }
      if (stat.isSymbolicLink()) throw runtimeError('RUNTIME_PATH_INVALID', `Managed links and junctions are refused: ${cursor}`);
      const real = fs.realpathSync.native(cursor);
      if (!within(real, this._installRoot)) throw runtimeError('RUNTIME_PATH_INVALID', `Managed real path escapes the installation: ${cursor}`);
    }
    return true;
  }

  _assertRuntimePath(target, allowMissing = false) {
    if (!within(target, this.paths.root)) throw runtimeError('RUNTIME_PATH_INVALID', `Path is outside runtime: ${target}`);
    return this._assertPath(target, allowMissing);
  }

  _relativeTarget(value) {
    // Both slash forms are accepted, but traversal, alternate streams and Windows aliases are not.
    if (typeof value !== 'string' || !value || path.isAbsolute(value) || value.includes('\0') || /[:<>"|?*]/.test(value)) {
      throw runtimeError('STATE_INVALID', 'State contains an invalid relative runtime path');
    }
    const parts = value.split(/[\\/]/);
    if (parts.some((part) => !part || part === '.' || part === '..' || /[. ]$/.test(part)
      || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(part))) {
      throw runtimeError('STATE_INVALID', 'State contains an unsafe Windows path component');
    }
    const result = path.resolve(this.paths.root, ...parts);
    if (!within(result, this.paths.root)) throw runtimeError('STATE_INVALID', 'State path escapes runtime');
    return result;
  }

  _parseState(bytes) {
    const state = json(bytes, 'STATE_INVALID', 'Runtime state');
    if (state && typeof state === 'object' && !Array.isArray(state) && state.schemaVersion === 1) {
      throw runtimeError('LEGACY_ENVIRONMENT',
        `Legacy multi-environment state is not migrated automatically. Exit the launcher and manually remove the old environment and ${this.paths.state} before preparing ${this.paths.environment}`);
    }
    exactFields(state, STATE_FIELDS, 'STATE_INVALID', 'Runtime state');
    if (state.schemaVersion !== STATE_SCHEMA || !absolute(state.installRoot)
      || state.installRoot.toLowerCase() !== path.normalize(state.installRoot).toLowerCase()
      || state.platform !== SPEC.platform || state.arch !== SPEC.arch
      || typeof state.pythonVersion !== 'string' || !/^3\.12\.\d+$/.test(state.pythonVersion)
      || !timestamp(state.readyAt)) {
      throw runtimeError('STATE_INVALID', 'Runtime state fields are invalid or unsupported');
    }
    const prefix = this._relativeTarget(state.prefixRelativePath);
    const executable = this._relativeTarget(state.pythonRelativePath);
    const basePython = this._relativeTarget(state.basePythonRelativePath);
    if (!samePath(prefix, this.paths.environment) || !samePath(executable, path.join(prefix, 'Scripts', 'python.exe'))
      || !within(basePython, this.paths.python) || samePath(basePython, this.paths.python)
      || path.basename(basePython).toLowerCase() !== 'python.exe') {
      throw runtimeError('STATE_INVALID', 'Runtime state must describe the single fixed virtual environment');
    }
    for (const target of [prefix, executable, basePython]) this._assertRuntimePath(target, true);
    return state;
  }

  _readState() {
    // Only a missing state file is first-run. Every other I/O/schema/path error propagates.
    try {
      this._assertRuntimePath(this.paths.state, true);
      const stat = fs.lstatSync(this.paths.state);
      if (!stat.isFile() || stat.size > JSON_BYTES) throw runtimeError('STATE_INVALID', 'Runtime state is not a bounded regular file');
      const state = this._parseState(fs.readFileSync(this.paths.state));
      this._lastState = state;
      return state;
    } catch (error) {
      if (error.code === 'ENOENT') {
        // A missing referenced interpreter is not allowed to hide a present state file.
        try { fs.lstatSync(this.paths.state); } catch (stateError) {
          if (stateError.code === 'ENOENT') { this._lastState = null; return null; }
          throw runtimeError('STATE_INVALID', 'Runtime state cannot be inspected', stateError);
        }
      }
      if (['STATE_INVALID', 'RUNTIME_PATH_INVALID', 'LEGACY_ENVIRONMENT'].includes(error.code)) throw error;
      throw runtimeError('STATE_INVALID', `Runtime state cannot be read: ${this.paths.state}`, error);
    }
  }

  async _readResource(target, maximum, label) {
    try {
      this._assertRuntimePath(target);
      const stat = await fsp.lstat(target);
      if (!stat.isFile() || stat.size === 0 || stat.size > maximum) throw new Error('Resource is empty, oversized or not a regular file');
      const bytes = await fsp.readFile(target);
      if (!bytes.length || bytes.length > maximum) throw new Error('Resource size changed while reading');
      return bytes;
    } catch (error) {
      if (error.code === 'RUNTIME_PATH_INVALID') throw error;
      throw runtimeError('RELEASE_INVALID', `Desktop runtime resource is missing or invalid: ${label} (${target}); prepare development resources or repair the package`, error);
    }
  }

  async _verifyResources() {
    const specPath = path.join(__dirname, '..', 'runtime', 'release-spec.json');
    let spec;
    try {
      const bytes = await fsp.readFile(specPath);
      if (bytes.length > JSON_BYTES) throw new Error('Release specification is oversized');
      spec = json(bytes, 'RELEASE_INVALID', 'Release specification');
      exactFields(spec, Object.keys(SPEC), 'RELEASE_INVALID', 'Release specification');
      if (Object.keys(SPEC).some((key) => spec[key] !== SPEC[key])) throw new Error('Unsupported fixed toolchain specification');
    } catch (error) {
      throw runtimeError('RELEASE_INVALID', 'The packaged desktop release specification is invalid', error);
    }
    const raw = await this._readResource(this.paths.release, JSON_BYTES, 'release.json');
    const manifest = json(raw, 'RELEASE_INVALID', 'Runtime release');
    exactFields(manifest, RELEASE_FIELDS, 'RELEASE_INVALID', 'Runtime release');
    for (const key of ['schemaVersion', 'platform', 'arch', 'uvVersion', 'pythonRequest', 'pythonVersion']) {
      if (manifest[key] !== spec[key]) throw runtimeError('RELEASE_INVALID', `Runtime release has an unsupported ${key}`);
    }
    for (const key of ['uvSha256', 'requirementsInputSha256', 'requirementsLockSha256', 'probeSha256']) {
      if (typeof manifest[key] !== 'string' || !HASH.test(manifest[key])) throw runtimeError('RELEASE_INVALID', `Runtime release has an invalid ${key}`);
    }
    const uv = await this._readResource(this.paths.uv, UV_BYTES, 'uv.exe');
    const lock = await this._readResource(this.paths.requirements, LOCK_BYTES, 'requirements lock');
    const probe = await this._readResource(this.paths.probe, JSON_BYTES, 'environment probe');
    const lockSha256 = digest(lock);
    const probeSha256 = digest(probe);
    if (digest(uv) !== manifest.uvSha256 || lockSha256 !== manifest.requirementsLockSha256 || probeSha256 !== manifest.probeSha256) {
      throw runtimeError('RELEASE_INVALID', 'Desktop runtime resource SHA-256 verification failed; no resource will be executed');
    }
    if (!lock.toString('utf8').trim() || !probe.toString('utf8').trim()) throw runtimeError('RELEASE_INVALID', 'Desktop runtime resources are empty');
    return { spec, manifest };
  }

  async _mkdir(target) {
    this._assertRuntimePath(target, true);
    if (samePath(target, this.paths.root)) {
      try { await fsp.mkdir(target); } catch (error) { if (error.code !== 'EEXIST') throw error; }
    } else {
      const parent = path.dirname(target);
      if (!samePath(parent, this.paths.root)) await this._mkdir(parent);
      else if (!this._assertRuntimePath(parent, true)) await this._mkdir(parent);
      this._assertRuntimePath(target, true);
      try { await fsp.mkdir(target); } catch (error) { if (error.code !== 'EEXIST') throw error; }
    }
    this._assertRuntimePath(target);
    if (!(await fsp.lstat(target)).isDirectory()) throw runtimeError('RUNTIME_PATH_INVALID', `Managed directory is not a directory: ${target}`);
  }

  async _openFile(target, flags) {
    const handle = await fsp.open(target, flags);
    this._fileHandles.add(handle);
    return handle;
  }

  async _closeFile(handle) {
    try {
      await handle.close();
      this._fileHandles.delete(handle);
    } catch (error) {
      this._cleanupBlocked = true;
      throw runtimeError('PROCESS_CLEANUP_FAILED', 'A runtime file handle did not confirm close', error);
    }
  }

  async _prepareDirectories() {
    try {
      await this._mkdir(this.paths.root);
      const probePath = path.join(this.paths.root, `.write-probe-${crypto.randomUUID()}.tmp`);
      let handle = null;
      let created = false;
      let failure = null;
      try {
        this._assertRuntimePath(probePath, true);
        handle = await this._openFile(probePath, 'wx');
        this._writeProbeTemporary = probePath;
        created = true;
        await handle.writeFile('runtime write probe\n', 'utf8');
        await handle.sync();
      } catch (error) { failure = error; }
      if (handle) {
        try { await this._closeFile(handle); } catch (error) { failure = failure ? new AggregateError([failure, error], 'Write probe failed to close') : error; }
      }
      if (created && !this._fileHandles.has(handle)) {
        try {
          this._assertRuntimePath(probePath);
          await fsp.unlink(probePath);
          this._writeProbeTemporary = null;
        } catch (error) { failure = failure ? new AggregateError([failure, error], 'Write probe cleanup failed') : error; }
      }
      if (failure) throw failure;
      this._checkCancelled();
      for (const target of [this.paths.python, this.paths.cache, this.paths.pythonCache,
        this.paths.pipCache, this.paths.tmp, this.paths.credentials, this.paths.pythonBin, this.paths.tools, this.paths.toolBin]) {
        this._checkCancelled();
        await this._mkdir(target);
      }
    } catch (error) {
      if (['RUNTIME_PATH_INVALID', 'CANCELLED'].includes(error.code)) throw error;
      throw runtimeError('RUNTIME_NOT_WRITABLE', `Internal runtime is not writable: ${this.paths.root}; choose a writable installation directory`, error);
    }
  }

  async _acquireLease() {
    this._checkCancelled();
    this._assertRuntimePath(this.paths.lease, true);
    const identity = {
      schemaVersion: 1, attemptId: this.attemptId, pid: process.pid,
      installRoot: this._installRoot, startedAt: new Date().toISOString(), token: crypto.randomUUID(),
    };
    let handle;
    try { handle = await fsp.open(this.paths.lease, 'wx+'); } catch (error) {
      if (error.code === 'EEXIST') {
        throw runtimeError('PREPARATION_LOCKED', `Runtime activity is occupied or interrupted: ${this.paths.lease}; confirm all related processes have stopped before manually removing this exact lock`, error);
      }
      throw runtimeError('RUNTIME_NOT_WRITABLE', `Runtime lease cannot be created: ${this.paths.lease}`, error);
    }
    // Retain the handle even if writing fails; an incomplete lease is never silently removed.
    this._lease = { handle, identity, handleClosed: false };
    await handle.writeFile(JSON.stringify(identity) + '\n', 'utf8');
    await handle.sync();
    this._assertRuntimePath(this.paths.lease);
    this._checkCancelled();
  }

  async _prepare(mode, manualExecutable) {
    this._progress('preflight');
    if (process.platform !== SPEC.platform || process.arch !== SPEC.arch) {
      throw runtimeError('UNSUPPORTED_PLATFORM', 'Desktop Python preparation requires Windows x64');
    }
    this._resolveInstallRoot();
    this._resources = await this._verifyResources();
    this._checkCancelled();
    await this._prepareDirectories();
    await this._acquireLease();
    // A publisher may have finished between preflight and wx. Recheck under our lease.
    this._resources = await this._verifyResources();
    this._checkCancelled();
    if (mode === 'manual') {
      const diagnostic = await this._probe('manual', manualExecutable);
      this._checkCancelled();
      return this._selection('manual', diagnostic);
    }
    const resources = this._resources;
    const state = this._readState();
    if (state) {
      if (!samePath(state.installRoot, this._installRoot)) {
        throw runtimeError('ENVIRONMENT_INVALID',
          `The successful environment was prepared at a different installation path. Exit the launcher and manually remove ${this.paths.environment} and ${this.paths.state} before rebuilding; automatic migration is disabled`);
      }
      const executable = this._relativeTarget(state.pythonRelativePath);
      const prefix = this._relativeTarget(state.prefixRelativePath);
      const basePython = this._relativeTarget(state.basePythonRelativePath);
      this._progress('verifying_environment');
      // 成功记录优先：按原Python版本诊断，不因新发布规格或依赖摘要改变而重建。
      const diagnostic = await this._probe('environment', executable,
        { prefix, basePython, expectedVersion: state.pythonVersion });
      this._checkCancelled();
      return this._selection('managed', diagnostic);
    }
    if (this._assertRuntimePath(this.paths.environment, true)) {
      throw runtimeError('ENVIRONMENT_EXISTS',
        `The fixed environment directory already exists without a successful state: ${this.paths.environment}. Exit the launcher and inspect or remove it manually; it will not be overwritten or replaced by another environment`);
    }
    this._progress('downloading_python');
    const version = await this._runStep('downloading_python', this.paths.uv, ['--version', '--no-config'], SHORT_MS);
    this._requireSuccess(version, 'UV_UNAVAILABLE', 'Fixed uv version check');
    if (version.stdoutTruncated || (!version.stdout.trim().startsWith(`uv ${resources.spec.uvVersion} `)
      && version.stdout.trim() !== `uv ${resources.spec.uvVersion}`) || /[\r\n]/.test(version.stdout.trim())) {
      throw runtimeError('UV_UNAVAILABLE', `The bundled uv executable did not report version ${resources.spec.uvVersion}`);
    }
    const installed = await this._runStep('downloading_python', this.paths.uv,
      ['python', 'install', resources.spec.pythonRequest, '--no-config', '--managed-python'], INSTALL_MS);
    this._requireSuccess(installed, 'PYTHON_INSTALL_FAILED', 'Internal CPython installation');
    const found = await this._runStep('downloading_python', this.paths.uv,
      ['python', 'find', resources.spec.pythonRequest, '--system', '--managed-python', '--no-python-downloads', '--no-config'], SHORT_MS);
    this._requireSuccess(found, 'PYTHON_INVALID', 'Internal CPython location');
    const basePython = found.stdout.trim();
    if (found.stdoutTruncated || !absolute(basePython) || /[\r\n]/.test(basePython)
      || !within(basePython, this.paths.python) || path.basename(basePython).toLowerCase() !== 'python.exe') {
      throw runtimeError('PYTHON_INVALID', 'uv python find must return one absolute internal Python executable');
    }
    this._assertRuntimePath(basePython);
    const base = await this._probe('base', basePython);
    this._checkCancelled();
    this._progress('creating_environment');
    const prefix = this.paths.environment;
    this._assertRuntimePath(prefix, true);
    this._checkCancelled();
    // 只认领本次排他创建的固定目录，绝不覆盖未知目录或创建第二套环境。
    try { await fsp.mkdir(prefix); } catch (error) {
      if (error.code === 'EEXIST') {
        throw runtimeError('ENVIRONMENT_EXISTS', `The fixed environment was created by another owner: ${prefix}; inspect it manually`, error);
      }
      throw error;
    }
    this._environmentCreated = true;
    this._assertRuntimePath(prefix);
    this._checkCancelled();
    const created = await this._runStep('creating_environment', this.paths.uv,
      ['venv', prefix, '--python', base.executable, '--no-config', '--no-python-downloads'], INSTALL_MS);
    this._requireSuccess(created, 'ENVIRONMENT_INVALID', 'New virtual environment creation');
    const executable = path.join(prefix, 'Scripts', 'python.exe');
    this._assertRuntimePath(executable);
    this._progress('installing_dependencies');
    const synced = await this._runStep('installing_dependencies', this.paths.uv,
      ['pip', 'sync', this.paths.requirements, '--python', executable, '--require-hashes',
        '--default-index', resources.spec.index, '--keyring-provider', 'disabled', '--no-config', '--no-python-downloads'], INSTALL_MS);
    this._requireSuccess(synced, 'DEPENDENCY_INSTALL_FAILED', 'Locked dependency installation');
    this._progress('verifying_environment');
    const checked = await this._runStep('verifying_environment', this.paths.uv,
      ['pip', 'check', '--python', executable, '--no-config', '--no-python-downloads'], SHORT_MS);
    this._requireSuccess(checked, 'ENVIRONMENT_INVALID', 'Installed dependency consistency check');
    const diagnostic = await this._probe('environment', executable, { prefix, basePython: base.executable });
    this._checkCancelled();
    const nextState = {
      schemaVersion: STATE_SCHEMA, installRoot: this._installRoot,
      pythonRelativePath: path.relative(this.paths.root, executable),
      prefixRelativePath: path.relative(this.paths.root, prefix),
      basePythonRelativePath: path.relative(this.paths.root, base.executable),
      pythonVersion: diagnostic.version, platform: SPEC.platform, arch: SPEC.arch,
      readyAt: new Date().toISOString(),
    };
    await this._commit(nextState);
    this._checkCancelled();
    return this._selection('managed', diagnostic);
  }

  _selection(mode, diagnostic) {
    return {
      mode, executable: diagnostic.executable, prefix: diagnostic.prefix,
      basePrefix: diagnostic.basePrefix,
    };
  }

  _requireSuccess(result, code, label) {
    if (result.spawnError || result.code !== 0 || result.signal || result.timedOut || result.cancelled) {
      const detail = result.spawnError ? errorDetail(result.spawnError) : sanitize(result.stderr.trim());
      throw runtimeError(code, `${label} failed (exit ${result.code}${result.timedOut ? ', timed out' : ''}): ${detail || result.signal || 'no diagnostic output'}`,
        result.spawnError || undefined);
    }
  }

  async _runStep(stage, executable, args, timeoutMs) {
    this._progress(stage);
    this._assertRuntimePath(this.paths.probe);
    this._assertRuntimePath(this.paths.uv);
    this._assertPath(this.repoRoot);
    const owned = new OwnedProcess({
      executable, args, cwd: this.repoRoot,
      env: buildInstallerEnv(process.env, this.paths), timeoutMs,
      onLog: (entry) => this.onLog({ ...entry, line: sanitize(entry.line) }),
    });
    this._ownedProcesses.add(owned);
    this._currentProcess = owned;
    let startError = null;
    try {
      // start() is invoked in the same synchronous segment as the cancellation check.
      const starting = owned.start();
      try { await starting; } catch (error) { startError = error; }
      const result = await owned.wait();
      if (result.cancelled || result.timedOut || this.requestCancelled) {
        await this._cancelOwned(owned);
      }
      if (!owned.hasExited() || !owned.isCleanupConfirmed()) {
        throw runtimeError('PROCESS_CLEANUP_FAILED', 'Runtime child process cleanup has not been confirmed');
      }
      this._checkCancelled();
      if (startError && !result.spawnError && !result.cancelled && !result.timedOut) throw startError;
      return result;
    } catch (error) {
      if (error.code === 'PROCESS_CLEANUP_FAILED' || !owned.isCleanupConfirmed()) this._cleanupBlocked = true;
      throw error;
    } finally {
      // Keep ALL ownership records. A failed wait may precede actual close.
      if (this._currentProcess === owned && owned.hasExited() && owned.isCleanupConfirmed()) this._currentProcess = null;
    }
  }

  _cancelOwned(owned) {
    if (!this._processCancellations.has(owned)) {
      const cancellation = owned.cancel();
      this._processCancellations.set(owned, cancellation);
      cancellation.catch(() => {});
    }
    return this._processCancellations.get(owned);
  }

  async _probe(mode, executable, { prefix = null, basePython = null, expectedVersion = SPEC.pythonVersion } = {}) {
    const code = mode === 'manual' ? 'MANUAL_PYTHON_INVALID' : mode === 'base' ? 'PYTHON_INVALID' : 'ENVIRONMENT_INVALID';
    if (mode !== 'manual') this._assertRuntimePath(executable, true);
    let stat;
    try { stat = await fsp.lstat(executable); } catch (error) {
      throw runtimeError(code, `Python executable cannot be inspected: ${executable}. A recorded successful environment is never rebuilt automatically; remove the old environment and its state manually if rebuilding is intended`, error);
    }
    if (!stat.isFile() && !(mode === 'manual' && stat.isSymbolicLink())) {
      throw runtimeError(code, `Python executable is not a regular file: ${executable}`);
    }
    const args = ['-I', '-B', this.paths.probe, '--mode', mode, '--expected-version', expectedVersion];
    if (mode !== 'manual') args.push('--expected-base-root', this.paths.python);
    if (prefix) args.push('--expected-prefix', prefix);
    const result = await this._runStep('verifying_environment', executable, args, SHORT_MS);
    // An existing executable with spawn ENOENT is an execution failure, never a rebuild signal.
    if (result.spawnError || result.signal || result.timedOut || result.cancelled) {
      this._requireSuccess(result, code, `${mode} Python diagnostic`);
    }
    if (result.stdoutTruncated || Buffer.byteLength(result.stdout, 'utf8') > JSON_BYTES) {
      throw runtimeError(code, 'Python diagnostic JSON exceeded its output limit');
    }
    const diagnostic = json(Buffer.from(result.stdout, 'utf8'), code, 'Python diagnostic');
    exactFields(diagnostic, PROBE_FIELDS, code, 'Python diagnostic');
    if (diagnostic.schemaVersion !== 1 || diagnostic.mode !== mode || typeof diagnostic.ok !== 'boolean'
      || !absolute(diagnostic.executable) || !absolute(diagnostic.prefix) || !absolute(diagnostic.basePrefix)
      || typeof diagnostic.version !== 'string' || !/^\d+\.\d+\.\d+$/.test(diagnostic.version)
      || ![32, 64].includes(diagnostic.architecture)) {
      throw runtimeError(code, 'Python diagnostic fields are invalid');
    }
    const success = result.code === 0 && diagnostic.ok === true && diagnostic.errorCode === null;
    const failure = Object.prototype.hasOwnProperty.call(PROBE_ERRORS, result.code)
      && diagnostic.ok === false && diagnostic.errorCode === PROBE_ERRORS[result.code];
    if (!success && !failure) throw runtimeError(code, 'Python diagnostic exit status and JSON disagree');
    if (failure) {
      if (result.code === 70) throw runtimeError('PROBE_INTERNAL_ERROR', `Python diagnostic reported an internal error: ${sanitize(result.stderr.trim())}`);
      throw runtimeError(code, `Python diagnostic failed: ${diagnostic.errorCode}; ${sanitize(result.stderr.trim())}`);
    }
    try {
      const actualExecutable = await fsp.realpath(executable);
      const reportedExecutable = await fsp.realpath(diagnostic.executable);
      const actualPrefix = await fsp.realpath(diagnostic.prefix);
      const actualBasePrefix = await fsp.realpath(diagnostic.basePrefix);
      if (!samePath(actualExecutable, reportedExecutable) || diagnostic.architecture !== 64) throw new Error('Executable identity or architecture disagrees');
      if (!(await fsp.stat(actualPrefix)).isDirectory() || !(await fsp.stat(actualBasePrefix)).isDirectory()) throw new Error('Reported prefixes are not directories');
      if (mode === 'manual') {
        if (!/^3\.12\.\d+$/.test(diagnostic.version)) throw new Error('Manual Python must be >=3.12 and <3.13');
      } else {
        if (diagnostic.version !== expectedVersion) throw new Error('Managed CPython version disagrees with its successful state or initial installation request');
        for (const target of [diagnostic.executable, diagnostic.prefix, diagnostic.basePrefix]) this._assertRuntimePath(target);
        if (!within(actualBasePrefix, this.paths.python)) throw new Error('Base prefix is outside managed Python');
        if (mode === 'base') {
          if (!samePath(actualPrefix, actualBasePrefix) || !within(actualExecutable, actualBasePrefix)) throw new Error('Base Python identity disagrees');
        } else {
          if (!prefix || !samePath(actualPrefix, await fsp.realpath(prefix)) || !within(actualExecutable, actualPrefix)
            || samePath(actualPrefix, actualBasePrefix)) throw new Error('Virtual environment identity disagrees');
          this._assertRuntimePath(basePython);
          if (!samePath(actualBasePrefix, await fsp.realpath(path.dirname(basePython)))) throw new Error('Base Python identity differs from the recorded interpreter');
        }
      }
      // Preserve the invoked virtual-environment path, never replace it by its base interpreter.
      return { ...diagnostic, executable: path.resolve(executable), prefix: actualPrefix, basePrefix: actualBasePrefix };
    } catch (error) {
      throw runtimeError(code, `Successful Python diagnostic has inconsistent real paths or constraints: ${executable}`, error);
    }
  }

  async _commit(state) {
    this._checkCancelled();
    this._parseState(Buffer.from(JSON.stringify(state), 'utf8'));
    const temporary = path.join(this.paths.root, `.state-${this.attemptId}-${crypto.randomUUID()}.tmp`);
    this._assertRuntimePath(temporary, true);
    let handle = null;
    try {
      handle = await this._openFile(temporary, 'wx');
      this._stateTemporary = temporary;
      await handle.writeFile(JSON.stringify(state, null, 2) + '\n', 'utf8');
      await handle.sync();
      await this._closeFile(handle);
      handle = null;
      this._assertRuntimePath(temporary);
      this._assertRuntimePath(this.paths.state, true);
      this._checkCancelled();
      // No await between final cancellation check, preserve disposition and rename invocation.
      this.commitState = 'in_flight';
      this.environmentDisposition = 'preserve';
      await fsp.rename(temporary, this.paths.state);
      this.commitState = 'committed';
      this._stateTemporary = null;
      this._lastState = state;
    } catch (error) {
      if (this.commitState === 'in_flight') this.commitState = 'failed';
      if (error.code === 'CANCELLED') throw error;
      throw runtimeError('STATE_COMMIT_FAILED', `Runtime state could not be committed: ${this.paths.state}; preserve the fixed environment for diagnosis`, error);
    } finally {
      if (handle) {
        try { await this._closeFile(handle); } catch (error) {
          this._cleanupBlocked = true;
          throw runtimeError('PROCESS_CLEANUP_FAILED', `State temporary file did not close: ${temporary}`, error);
        }
      }
    }
  }

  _assertCleanupSafe(explicit = false, deadline = null) {
    if (deadline !== null && Date.now() >= deadline) {
      throw runtimeError('PROCESS_CLEANUP_FAILED', 'Explicit cleanup deadline expired; keep remaining objects and the lease');
    }
    if (this._fileHandles.size) {
      throw runtimeError('PROCESS_CLEANUP_FAILED', 'Runtime file handles have not all confirmed close');
    }
    if ([...this._ownedProcesses].some((owned) => !owned.hasExited() || !owned.isCleanupConfirmed())) {
      throw runtimeError('PROCESS_CLEANUP_FAILED', 'Owned runtime processes have not all confirmed close and cancellation completion');
    }
    if (!explicit && (this._cleanupBlocked || (this._cancelDeadline !== null && Date.now() >= this._cancelDeadline))) {
      throw runtimeError('PROCESS_CLEANUP_FAILED', 'Cleanup observation expired; preserve runtime objects and the lease until explicit shutdown rechecks them');
    }
  }

  async _removeEnvironmentTree(target, explicit, deadline) {
    this._assertCleanupSafe(explicit, deadline);
    this._assertRuntimePath(target);
    const stat = await fsp.lstat(target);
    if (!stat.isDirectory()) {
      this._assertCleanupSafe(explicit, deadline);
      this._assertRuntimePath(target);
      await fsp.unlink(target);
      return;
    }
    // 只遍历本次排他创建且尚未成功提交的固定环境，不跟随重解析路径。
    for (const entry of await fsp.readdir(target, { withFileTypes: true })) {
      await this._removeEnvironmentTree(path.join(target, entry.name), explicit, deadline);
    }
    this._assertCleanupSafe(explicit, deadline);
    this._assertRuntimePath(target);
    await fsp.rmdir(target);
  }

  async _cleanupAttempt(explicit = false, deadline = null) {
    this._assertCleanupSafe(explicit, deadline);
    if (this._writeProbeTemporary) {
      if (this._assertRuntimePath(this._writeProbeTemporary, true)) {
        this._assertCleanupSafe(explicit, deadline);
        await fsp.unlink(this._writeProbeTemporary);
      }
      this._writeProbeTemporary = null;
    }
    if (this._stateTemporary) {
      const temporary = this._stateTemporary;
      if (this._assertRuntimePath(temporary, true)) {
        this._assertCleanupSafe(explicit, deadline);
        await fsp.unlink(temporary);
      }
      this._stateTemporary = null;
    }
    if (!this._environmentCreated || this._environmentRemoved || this.environmentDisposition === 'preserve') return;
    const prefix = this.paths.environment;
    // 只要存在成功state，就保留唯一环境；不得因后续取消、退出或未知错误反向删除。
    const state = this._readState();
    if (state) {
      this.environmentDisposition = 'preserve';
      return;
    }
    if (this._assertRuntimePath(prefix, true)) await this._removeEnvironmentTree(prefix, explicit, deadline);
    this._environmentRemoved = true;
  }

  /** Shared ten-second observation budget; never called by the preparation chain itself. */
  cancel() {
    this.requestCancelled = true;
    if (this._cancelPromise) return this._cancelPromise;
    this._cancelDeadline = Date.now() + CLEANUP_MS;
    this._cancelSettled = false;
    const deadline = this._cancelDeadline;
    this._cancelPromise = (async () => {
      const cancellations = [...this._ownedProcesses]
        .filter((owned) => !owned.hasExited() || !owned.isCleanupConfirmed())
        .map((owned) => this._cancelOwned(owned));
      await beforeDeadline(Promise.all(cancellations), deadline, 'Runtime process cancellation did not complete within ten seconds');
      if (this._runtimePromise) {
        const outcome = this._runtimePromise.then(() => null, (error) => error);
        const error = await beforeDeadline(outcome, deadline, 'Python preparation or file operations have not finished before cancellation deadline');
        if (error && error.code !== 'CANCELLED') throw error;
      }
      this._assertCleanupSafe();
    })().catch((error) => {
      this._cleanupBlocked = true;
      throw error;
    }).finally(() => { this._cancelSettled = true; });
    this._cancelPromise.catch(() => {});
    return this._cancelPromise;
  }

  /** The controller calls this only AFTER backend close. It also serves explicit shutdown rechecks. */
  releaseLease() {
    const deadline = Date.now() + CLEANUP_MS;
    if (!this._releasePromise) {
      const work = this._releaseLeaseUntil(deadline).catch((error) => {
        this._cleanupBlocked = true;
        if (error.code === 'PROCESS_CLEANUP_FAILED') throw error;
        throw runtimeError('PROCESS_CLEANUP_FAILED', `Runtime lease cleanup failed: ${errorDetail(error)}`, error);
      });
      // Retain the REAL release work when its observer expires; do not clear ownership on timeout.
      this._releasePromise = work.finally(() => { this._releasePromise = null; });
      this._releasePromise.catch(() => {});
    }
    return beforeDeadline(this._releasePromise, deadline, 'Runtime lease release is still pending').catch((error) => {
      this._cleanupBlocked = true;
      throw error;
    });
  }

  async _releaseLeaseUntil(deadline) {
    if (this._runtimePromise && !this._runtimeSettled) {
      await beforeDeadline(this._runtimePromise.then(() => undefined, () => undefined), deadline, 'Preparation is still active; keep the lease');
    }
    if (this._cancelPromise && !this._cancelSettled) {
      await beforeDeadline(this._cancelPromise.then(() => undefined, () => undefined), deadline, 'Runtime cancellation observation is still active');
    }
    // A rejected wait/cancel observer never clears ownership; query the retained real objects again.
    for (const cancellation of this._processCancellations.values()) {
      await beforeDeadline(cancellation.then(() => undefined, () => undefined), deadline, 'A runtime cancellation operation is still active');
    }
    for (const handle of [...this._fileHandles]) {
      await beforeDeadline(this._closeFile(handle), deadline, 'A runtime file handle is still closing');
    }
    this._assertCleanupSafe(true, deadline);
    await this._cleanupAttempt(true, deadline);
    this._assertCleanupSafe(true, deadline);
    if (!this._lease) {
      this._cleanupBlocked = false;
      this._cleanupError = null;
      return;
    }
    const lease = this._lease;
    this._assertRuntimePath(this.paths.lease);
    const stat = await fsp.lstat(this.paths.lease);
    if (!stat.isFile() || stat.size > JSON_BYTES) throw runtimeError('PROCESS_CLEANUP_FAILED', 'Runtime lease is not a bounded regular file');
    const stored = json(await fsp.readFile(this.paths.lease), 'PROCESS_CLEANUP_FAILED', 'Runtime lease');
    exactFields(stored, LEASE_FIELDS, 'PROCESS_CLEANUP_FAILED', 'Runtime lease');
    const expected = lease.identity;
    if (stored.schemaVersion !== 1 || stored.token !== expected.token || stored.attemptId !== expected.attemptId
      || !absolute(stored.installRoot) || !samePath(stored.installRoot, expected.installRoot)
      || stored.pid !== expected.pid || stored.startedAt !== expected.startedAt) {
      throw runtimeError('PROCESS_CLEANUP_FAILED', `Runtime lease ownership mismatch; leaving it untouched: ${this.paths.lease}`);
    }
    if (!lease.handleClosed) {
      await lease.handle.close();
      lease.handleClosed = true;
    }
    this._assertCleanupSafe(true, deadline);
    this._assertRuntimePath(this.paths.lease);
    // Recheck after closing the handle; never unlink a replaced owner's lease.
    const current = json(await fsp.readFile(this.paths.lease), 'PROCESS_CLEANUP_FAILED', 'Runtime lease');
    exactFields(current, LEASE_FIELDS, 'PROCESS_CLEANUP_FAILED', 'Runtime lease');
    if (current.token !== expected.token || current.attemptId !== expected.attemptId
      || !absolute(current.installRoot) || !samePath(current.installRoot, expected.installRoot)) {
      throw runtimeError('PROCESS_CLEANUP_FAILED', 'Runtime lease was replaced before release; keep it untouched');
    }
    this._assertCleanupSafe(true, deadline);
    await fsp.unlink(this.paths.lease);
    this._lease = null;
    this._cleanupBlocked = false;
    this._cleanupError = null;
  }
}

module.exports = { PythonRuntimeManager };
