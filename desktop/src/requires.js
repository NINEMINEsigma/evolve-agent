/** Explicit desktop module exports; importing them never starts an application. */
'use strict';

const configManager = require('./config-manager');
const { LauncherController } = require('./launcher-controller');
const { PythonRuntimeManager } = require('./python-runtime-manager');
const fieldDefs = require('./field-defs');

module.exports = { configManager, LauncherController, PythonRuntimeManager, fieldDefs };
