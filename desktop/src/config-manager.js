/**
 * 配置方案读写：保留 easysave 的 config, Config 结构及已有未知字段。
 * 对外只提供当前启动字段；结构损坏或有效字段类型错误直接拒绝。
 */
'use strict';

const fs = require('fs');
const definitions = require('./config-fields.json');
const fields = require('./field-defs');
const EASYSAVE_TYPE = 'config, Config';

function requireRecord(value, label) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object`);
  }
}

function requireProfileKey(key) {
  if (typeof key !== 'string' || !key.trim()) {
    throw new TypeError('Configuration profile name must be a non-empty string');
  }
}

function readConfigJson(configPath) {
  let raw;
  try {
    raw = fs.readFileSync(configPath, 'utf-8');
  } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  }
  const data = JSON.parse(raw);
  requireRecord(data, 'Configuration file');
  return data;
}

function writeConfigJson(configPath, data) {
  fs.writeFileSync(configPath, JSON.stringify(data, null, 4), 'utf-8');
}

function getProfileData(data, key) {
  requireProfileKey(key);
  if (data === null || !Object.hasOwn(data, key)) {
    throw new Error(`Configuration profile not found: ${key}`);
  }
  const profile = data[key];
  requireRecord(profile, `Configuration profile ${key}`);
  if (!Object.hasOwn(profile, '__root')) {
    throw new TypeError(`Configuration profile has no root: ${key}`);
  }
  const root = profile.__root;
  requireRecord(root, `Configuration root ${key}`);
  if (root.__type !== EASYSAVE_TYPE) {
    throw new TypeError(`Unsupported configuration profile type: ${key}`);
  }
  if (!Object.hasOwn(root, '__value')) {
    throw new TypeError(`Configuration profile has no values: ${key}`);
  }
  requireRecord(root.__value, `Configuration values ${key}`);
  return root.__value;
}

function completeValues(stored) {
  const values = {
    ...fields.getDefaultValues(definitions),
    ...fields.selectKnownValues(definitions, stored),
  };
  fields.assertConfigValues(definitions, values);
  return values;
}

function listProfiles(configPath) {
  const data = readConfigJson(configPath);
  if (data === null) return [];
  // 列表可以展示损坏的单个方案，但选择、保存或启动时必须明确报错。
  return Object.keys(data);
}

function loadProfile(configPath, key) {
  return completeValues(getProfileData(readConfigJson(configPath), key));
}

function saveProfile(configPath, key, values) {
  const selected = fields.selectKnownValues(definitions, values);
  fields.assertConfigValues(definitions, selected);
  const data = readConfigJson(configPath);
  const target = getProfileData(data, key);
  Object.assign(target, selected);
  writeConfigJson(configPath, data);
}

function createProfile(configPath, key) {
  requireProfileKey(key);
  const data = readConfigJson(configPath) ?? {};
  if (Object.hasOwn(data, key)) {
    throw new Error(`Configuration profile already exists: ${key}`);
  }
  // 显式定义自有属性，配置名称不会触发 __proto__ 等对象原型行为。
  Object.defineProperty(data, key, {
    value: {
      __root: {
        __type: EASYSAVE_TYPE,
        __value: fields.getDefaultValues(definitions),
      },
    },
    enumerable: true,
    configurable: true,
    writable: true,
  });
  writeConfigJson(configPath, data);
}

function buildCliArgs(overrides) {
  return fields.buildCliArgs(definitions, overrides);
}

function prepareLaunch(configPath, key, overrides) {
  const stored = getProfileData(readConfigJson(configPath), key);
  const selected = fields.selectKnownValues(definitions, overrides);
  fields.assertConfigValues(definitions, selected, true);
  // 先合并再校验；本次覆盖可修正文件中已失效的有效字段值。
  const values = completeValues({ ...stored, ...selected });
  return { values, cliArgs: buildCliArgs(selected) };
}

module.exports = {
  getFieldDefinitions: () => definitions,
  listProfiles,
  loadProfile,
  saveProfile,
  createProfile,
  buildCliArgs,
  prepareLaunch,
};
