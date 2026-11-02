'use strict';

const path = require('path');

function runtimePaths(repoRoot) {
  const root = path.join(repoRoot, 'runtime');
  return Object.freeze({
    root,
    uv: path.join(root, 'uv', 'uv.exe'),
    release: path.join(root, 'release.json'),
    requirements: path.join(root, 'requirements-win-x64.lock'),
    probe: path.join(root, 'support', 'probe_environment.py'),
    python: path.join(root, 'python'),
    environment: path.join(root, 'venv'),
    state: path.join(root, 'state.json'),
    lease: path.join(root, 'prepare.lock'),
    cache: path.join(root, 'cache', 'uv'),
    pythonCache: path.join(root, 'cache', 'python'),
    pipCache: path.join(root, 'cache', 'pip'),
    tmp: path.join(root, 'tmp'),
    credentials: path.join(root, 'credentials'),
    pythonBin: path.join(root, 'uv', 'python-bin'),
    tools: path.join(root, 'tools'),
    toolBin: path.join(root, 'tools', 'bin'),
  });
}

function cleanEnvironment(baseEnv) {
  const env = {};
  for (const [key, value] of Object.entries(baseEnv)) {
    const name = key.toUpperCase();
    if (/^(UV_|PIP_|PYTHON|CONDA|_CONDA|_OLD_VIRTUAL_)/.test(name)
      || ['VIRTUAL_ENV', 'VIRTUAL_ENV_PROMPT', '_CE_CONDA', '_CE_M', '__PYVENV_LAUNCHER__'].includes(name)) continue;
    // Windows treats environment names case-insensitively, including mixed-case Path.
    if (name === 'PATH' || ['TEMP', 'TMP', 'TMPDIR'].includes(name)) env[name] = value;
    else env[key] = value;
  }
  return env;
}

function internalEnvironment(baseEnv, paths) {
  return {
    ...cleanEnvironment(baseEnv),
    UV_PYTHON_INSTALL_DIR: paths.python,
    UV_CACHE_DIR: paths.cache,
    UV_PYTHON_CACHE_DIR: paths.pythonCache,
    UV_CREDENTIALS_DIR: paths.credentials,
    UV_PYTHON_BIN_DIR: paths.pythonBin,
    UV_TOOL_DIR: paths.tools,
    UV_TOOL_BIN_DIR: paths.toolBin,
    UV_PYTHON_INSTALL_BIN: 'false',
    UV_PYTHON_INSTALL_REGISTRY: 'false',
    UV_NO_CONFIG: 'true',
    UV_HTTP_TIMEOUT: '30',
    UV_HTTP_RETRIES: '2',
    UV_KEYRING_PROVIDER: 'disabled',
    PIP_CONFIG_FILE: 'NUL',
    PIP_DISABLE_PIP_VERSION_CHECK: '1',
    PIP_CACHE_DIR: paths.pipCache,
    PYTHONNOUSERSITE: '1',
    PYTHONIOENCODING: 'utf-8',
    PYTHONUTF8: '1',
    TEMP: paths.tmp,
    TMP: paths.tmp,
    TMPDIR: paths.tmp,
  };
}

function buildInstallerEnv(baseEnv, paths) {
  const env = internalEnvironment(baseEnv, paths);
  env.UV_MANAGED_PYTHON = 'true';
  // 与发布准备脚本一致，使用 Windows 系统信任库，保留 TLS 证书校验。
  env.UV_NATIVE_TLS = 'true';
  env.PYTHONDONTWRITEBYTECODE = '1';
  const pollutedRoots = Object.entries(baseEnv)
    .filter(([key, value]) => /^(VIRTUAL_ENV|CONDA_PREFIX(?:_\d+)?|_?CONDA_ROOT|PYTHONHOME)$/i.test(key) && path.isAbsolute(value))
    .map(([, value]) => path.resolve(value));
  if (env.PATH) {
    env.PATH = env.PATH.split(path.delimiter).filter((entry) => {
      const candidate = entry.replace(/^"|"$/g, '');
      if (!path.isAbsolute(candidate) || path.basename(candidate).toLowerCase() === 'condabin') return false;
      return !pollutedRoots.some((root) => {
        const relative = path.relative(root, candidate);
        return relative === '' || (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative));
      });
    }).join(path.delimiter);
  }
  return env;
}

function buildBackendEnv(baseEnv, selection, paths) {
  const env = internalEnvironment(baseEnv, paths);
  env.PATH = [path.dirname(selection.executable), env.PATH || ''].filter(Boolean).join(path.delimiter);
  if (selection.prefix !== selection.basePrefix) env.VIRTUAL_ENV = selection.prefix;
  if (selection.mode === 'managed') env.UV_MANAGED_PYTHON = 'true';
  return env;
}

module.exports = { runtimePaths, buildInstallerEnv, buildBackendEnv };
