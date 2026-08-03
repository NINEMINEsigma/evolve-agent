/**
 * preload.js — 安全 IPC 桥接
 *
 * 通过 contextBridge.exposeInMainWorld 暴露 electronAPI 对象，
 * renderer 进程通过 window.electronAPI.* 调用主进程功能。
 *
 * 注意：Electron sandbox 环境下 require 只能解析 'electron' 模块，
 * 不能 require 本地文件。因此 field-defs 的数据直接内联于此。
 */

'use strict';

const { contextBridge, ipcRenderer } = require('electron');

// ── 字段定义（从 field-defs.js 内联）──────────────────────

const FIELD_TYPES = {
  console_log:               'bool',
  fast_agent_space_path:     'str',
  slow_agent_space_path:     'str',
  force_init:                'bool',
  frontend_force_build:      'bool',
  gateway_host:              'str',
  gateway_port:              'int',
  llm_base_url:              'str',
  llm_model:                 'str',
  llm_api_key:               'str',
  llm_max_context_tokens:    'int',
  llm_max_output_tokens:     'int',
  llm_temperature:           'float',
  llm_reasoning_effort:      'str',
  llm_client_name:           'str',
  merge_concat_threshold:    'int',
  approval_model:            'str',
  approval_model_n_ctx:      'int',
  approval_model_cuda:       'bool',
  approval_model_port:       'int',
  approval_remote_base_url:  'str',
  approval_remote_api_key:   'str',
  approval_remote_model:     'str',
  workspace_path:            'str',
  agentspace_path_name:      'str',
  logs_path_name:            'str',
  mcp_config_path_name:      'str',
};

const FIELD_DEFAULTS = {
  console_log:               true,
  fast_agent_space_path:     'fast_agent_space',
  slow_agent_space_path:     'slow_agent_space',
  force_init:                false,
  frontend_force_build:      false,
  gateway_host:              '127.0.0.1',
  gateway_port:              8765,
  llm_base_url:              'https://api.deepseek.com',
  llm_model:                 'deepseek-v4-flash',
  llm_api_key:               '',
  llm_max_context_tokens:    1000000,
  llm_max_output_tokens:     384000,
  llm_temperature:           0.95,
  llm_reasoning_effort:      'medium',
  llm_client_name:           'openai_client',
  merge_concat_threshold:    50000,
  approval_model:            '',
  approval_model_n_ctx:      65536,
  approval_model_cuda:       true,
  approval_model_port:       8081,
  approval_remote_base_url:  '',
  approval_remote_api_key:   '',
  approval_remote_model:     '',
  workspace_path:            'workspace',
  agentspace_path_name:      'agentspace',
  logs_path_name:            'logs',
  mcp_config_path_name:      'mcp_config.json',
};

const FIELD_GROUPS = {
  'LLM 核心': [
    'llm_base_url', 'llm_model', 'llm_api_key',
    'llm_max_context_tokens', 'llm_max_output_tokens',
    'llm_temperature', 'llm_reasoning_effort', 'llm_client_name',
  ],
  '审批模型': [
    'approval_model', 'approval_model_n_ctx',
    'approval_model_cuda', 'approval_model_port',
    'approval_remote_base_url', 'approval_remote_api_key',
    'approval_remote_model',
  ],
  'Workspace': [
    'workspace_path', 'agentspace_path_name',
    'logs_path_name', 'mcp_config_path_name',
  ],
  '网关': [
    'gateway_host', 'gateway_port',
  ],
  '运行时': [
    'console_log', 'force_init',
    'frontend_force_build', 'merge_concat_threshold',
  ],
};

function _validatePort(raw) {
  const v = Number(raw);
  if (!Number.isInteger(v) || isNaN(v)) return { valid: false, error: `需要整数, 得到 '${raw}'` };
  if (v < 1 || v > 65535) return { valid: false, error: `端口范围 1-65535, 得到 ${v}` };
  return { valid: true };
}

function _validateRange(raw, min, max) {
  const v = parseFloat(raw);
  if (isNaN(v)) return { valid: false, error: `需要浮点数, 得到 '${raw}'` };
  if (v < min || v > max) return { valid: false, error: `范围 ${min}-${max}, 得到 ${v}` };
  return { valid: true };
}

function _validatePositiveInt(raw) {
  const v = parseInt(raw, 10);
  if (isNaN(v)) return { valid: false, error: `需要正整数, 得到 '${raw}'` };
  if (v < 0) return { valid: false, error: `需要正整数, 得到 ${v}` };
  return { valid: true };
}

function _validateEnum(raw, allowed) {
  const v = raw.trim().toLowerCase();
  if (!allowed.includes(v)) return { valid: false, error: `可选值: ${allowed.join(' / ')}, 得到 '${raw}'` };
  return { valid: true };
}

function _validateUrl(raw) {
  const v = raw.trim();
  if (v && !v.startsWith('http://') && !v.startsWith('https://')) {
    return { valid: false, error: `URL 需以 http:// 或 https:// 开头` };
  }
  return { valid: true };
}

const FIELD_VALIDATORS = {
  gateway_port:              (raw) => _validatePort(raw),
  approval_model_port:       (raw) => _validatePort(raw),
  llm_temperature:           (raw) => _validateRange(raw, 0.0, 2.0),
  llm_max_context_tokens:    (raw) => _validatePositiveInt(raw),
  llm_max_output_tokens:     (raw) => _validatePositiveInt(raw),
  approval_model_n_ctx:      (raw) => _validatePositiveInt(raw),
  merge_concat_threshold:    (raw) => _validatePositiveInt(raw),
  llm_reasoning_effort:      (raw) => _validateEnum(raw, ['low', 'medium', 'high', '']),
  llm_base_url:              (raw) => _validateUrl(raw),
  approval_remote_base_url:  (raw) => _validateUrl(raw),
};

// ── IPC 桥接 ──────────────────────────────────────────────

contextBridge.exposeInMainWorld('electronAPI', {
  config: {
    listProfiles:  ()              => ipcRenderer.invoke('config:list-profiles'),
    loadProfile:   (key)           => ipcRenderer.invoke('config:load-profile', key),
    saveProfile:   (key, values)   => ipcRenderer.invoke('config:save-profile', key, values),
    createProfile: (key)           => ipcRenderer.invoke('config:create-profile', key),
  },

  backend: {
    launch:    (configKey, overrides, pythonPath) => ipcRenderer.send('backend:launch', configKey, overrides, pythonPath),
    kill:      ()                    => ipcRenderer.send('backend:kill'),
    onLog:     (callback)            => ipcRenderer.on('backend:log-line', (e, log) => callback(log)),
    onStatus:  (callback)            => ipcRenderer.on('backend:status', (e, status) => callback(status)),
    onHealthOk:(callback)            => ipcRenderer.on('backend:health-ok', () => callback()),
  },

  settings: {
    load:  ()              => ipcRenderer.invoke('settings:load'),
    save:  (values)        => ipcRenderer.invoke('settings:save', values),
  },

  fieldDefs: {
    FIELD_GROUPS,
    FIELD_TYPES,
    FIELD_DEFAULTS,
    FIELD_VALIDATORS,
  },
});