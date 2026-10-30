/**
 * 沙盒预加载脚本只提供 IPC 桥接，配置定义与校验不在此重复维护。
 */
'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  config: {
    getFieldDefinitions: () => ipcRenderer.invoke('config:field-definitions'),
    listProfiles: () => ipcRenderer.invoke('config:list-profiles'),
    loadProfile: (key) => ipcRenderer.invoke('config:load-profile', key),
    saveProfile: (key, values) => ipcRenderer.invoke('config:save-profile', key, values),
    createProfile: (key) => ipcRenderer.invoke('config:create-profile', key),
  },

  backend: {
    launch: (configKey, overrides, pythonPath) => ipcRenderer.invoke('backend:launch', configKey, overrides, pythonPath),
    kill: () => ipcRenderer.send('backend:kill'),
    onLog: (callback) => ipcRenderer.on('backend:log-line', (event, log) => callback(log)),
    onStatus: (callback) => ipcRenderer.on('backend:status', (event, status) => callback(status)),
    onHealthOk: (callback) => ipcRenderer.on('backend:health-ok', () => callback()),
  },

  settings: {
    load: () => ipcRenderer.invoke('settings:load'),
    save: (values) => ipcRenderer.invoke('settings:save', values),
  },
});
