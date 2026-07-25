/**
 * config-manager.js — config.json 读写（兼容 easysave 格式）
 *
 * easysave 序列化结构（已通过实际 config.json 验证）：
 * {
 *   "default": {
 *     "__root": {
 *       "__type": "config, Config",
 *       "__value": { field1: value1, field2: value2, ... }
 *     }
 *   },
 *   "other-profile": { ... }
 * }
 *
 * Config 是扁平原始类型（str/int/float/bool），不会出现 __ref token。
 * 直接 JSON 读写 __value 字段即可，__type 必须保持 "config, Config"。
 */

'use strict';

const fs = require('fs');
const path = require('path');

const { FIELD_DEFAULTS, CLI_ARG_MAP, STORE_TRUE_FIELDS } = require('./field-defs');

const EASYSAVE_TYPE = 'config, Config';

// ── 内部工具 ──────────────────────────────────────────────

function _readConfigJson(configPath) {
  try {
    const raw = fs.readFileSync(configPath, 'utf-8');
    return JSON.parse(raw);
  } catch (err) {
    if (err.code === 'ENOENT') return null;
    throw err;
  }
}

function _writeConfigJson(configPath, data) {
  fs.writeFileSync(configPath, JSON.stringify(data, null, 4), 'utf-8');
}

function _getProfileData(data, key) {
  return data?.[key]?.['__root']?.['__value'] ?? null;
}

function _ensureProfileStructure(data, key) {
  if (!data[key]) {
    data[key] = {
      __root: {
        __type: EASYSAVE_TYPE,
        __value: {},
      },
    };
  }
  data[key].__root = data[key].__root || { __type: EASYSAVE_TYPE, __value: {} };
  data[key].__root.__type = EASYSAVE_TYPE;
  data[key].__root.__value = data[key].__root.__value || {};
  return data[key].__root.__value;
}

// ── 公共 API ──────────────────────────────────────────────

/**
 * 列出 config.json 顶层 key 列表。
 * @param {string} configPath — config.json 绝对路径
 * @returns {string[]} profile 名称数组
 */
function listProfiles(configPath) {
  const data = _readConfigJson(configPath);
  if (!data) return [];
  return Object.keys(data);
}

/**
 * 读取指定 profile 的字段值。
 * 缺失字段自动补默认值。
 * @param {string} configPath
 * @param {string} key — profile 名称
 * @returns {Object} { fieldName: value, ... }
 */
function loadProfile(configPath, key) {
  const data = _readConfigJson(configPath);
  if (!data || !(key in data)) {
    return { ...FIELD_DEFAULTS };
  }
  const stored = _getProfileData(data, key) || {};
  return { ...FIELD_DEFAULTS, ...stored };
}

/**
 * 保存字段值到指定 profile（持久化到 config.json）。
 * @param {string} configPath
 * @param {string} key — profile 名称
 * @param {Object} values — { fieldName: value, ... }
 */
function saveProfile(configPath, key, values) {
  let data = _readConfigJson(configPath);
  if (!data) data = {};
  const target = _ensureProfileStructure(data, key);
  Object.assign(target, values);
  _writeConfigJson(configPath, data);
}

/**
 * 新建 profile，使用 FIELD_DEFAULTS 填充全部字段。
 * @param {string} configPath
 * @param {string} key — 新 profile 名称
 */
function createProfile(configPath, key) {
  saveProfile(configPath, key, { ...FIELD_DEFAULTS });
}

/**
 * 生成 CLI 覆盖参数数组。
 * 仅包含用户临时修改的字段（与 profile 存储值不同的字段）。
 *
 * @param {Object} overrides — { fieldName: value } 仅包含与 profile 不同的字段
 * @returns {string[]} ['--llm_model', 'xxx', '--gateway_host', '0.0.0.0', ...]
 */
function buildCliArgs(overrides) {
  const args = [];
  for (const [field, value] of Object.entries(overrides)) {
    const cliArg = CLI_ARG_MAP[field];
    if (!cliArg) continue;
    if (STORE_TRUE_FIELDS.has(field)) {
      if (value === true || value === 'true') {
        args.push(cliArg);
      }
    } else {
      args.push(cliArg, String(value));
    }
  }
  return args;
}

module.exports = {
  listProfiles,
  loadProfile,
  saveProfile,
  createProfile,
  buildCliArgs,
};