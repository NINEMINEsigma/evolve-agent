/** Sandboxed bridge: no arbitrary commands, installation paths or filesystem writes. */
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
    getState: () => ipcRenderer.invoke('backend:get-state'),
    cancel: () => ipcRenderer.invoke('backend:cancel'),
    kill: () => ipcRenderer.send('backend:kill'),
    onLog: (callback) => ipcRenderer.on('backend:log-line', (event, log) => callback(log)),
    onStatus: (callback) => ipcRenderer.on('backend:status', (event, state) => callback(state)),
    onHealthOk: (callback) => ipcRenderer.on('backend:health-ok', () => callback()),
  },
  settings: {
    load: () => ipcRenderer.invoke('settings:load'),
    save: (values) => ipcRenderer.invoke('settings:save', values),
  },
});
