/**
 * requires.js — 模块聚合导出
 *
 * 将 config-manager / backend-manager / field-defs 统一导出，
 * 供 main.js 一行引入，避免分散的 require。
 */

'use strict';

const configManager = require('./config-manager');
const { BackendManager } = require('./backend-manager');
const fieldDefs = require('./field-defs');

module.exports = { configManager, BackendManager, fieldDefs };