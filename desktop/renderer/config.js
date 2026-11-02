/**
 * 配置界面：原始输入与有效值分离，共用字段解析、校验与启动参数定义。
 * 模型连接配置由应用内模型配置 Tab 管理；本页只编辑启动配置。
 */
'use strict';

const api = window.electronAPI;
const configFields = window.launcherConfigFields;
let fieldDefinitions = null;
let currentProfile = null;
let profileValues = {};
let rawValues = {};
let workingValues = {};
let dirtyFields = new Set();
let launcherState = null;
let runtimeDescription = null;
let launchPending = false;
let formBusy = false;
let editingProfile = false;
let saveSucceeded = false;
let savePending = false;
let profileLoadSequence = 0;

const profileSelect = document.getElementById('profile-select');
const btnNewProfile = document.getElementById('btn-new-profile');
const btnSaveProfile = document.getElementById('btn-save-profile');
const btnLaunch = document.getElementById('btn-launch');
const fieldsContainer = document.getElementById('fields-container');
const configPanel = document.getElementById('config-panel');
const logPanel = document.getElementById('log-panel');
const pythonPathInput = document.getElementById('python-path-input');
const btnViewLog = document.getElementById('btn-view-log');
const configError = document.getElementById('config-error');
const modelNotice = document.getElementById('model-notice');
const pythonRuntimeInfo = document.getElementById('python-runtime-info');
const pythonPathHint = document.getElementById('python-path-hint');

function applyLauncherState(state) {
  if (!state || !Number.isInteger(state.revision) || typeof state.status !== 'string'
    || typeof state.canLaunch !== 'boolean' || typeof state.canCancel !== 'boolean') return false;
  if (launcherState && state.revision <= launcherState.revision) return false;
  launcherState = state;
  if (fieldDefinitions) {
    updateControls();
    updatePythonDescription();
  }
  return true;
}

function updatePythonDescription() {
  if (!fieldDefinitions) return;
  const ui = fieldDefinitions.ui.launcher;
  const manual = pythonPathInput.value.trim();
  const location = manual || (launcherState && launcherState.pythonPath)
    || (runtimeDescription && (runtimeDescription.managedExecutable || runtimeDescription.environmentPath));
  pythonRuntimeInfo.textContent = `${manual ? ui.manual : ui.managed}\n${location || ui.unknownLocation}`;
}

function showError(message, error) {
  configError.textContent = error ? `${message}\n${error.message || String(error)}` : message;
  configError.hidden = false;
}

function clearError() {
  configError.textContent = '';
  configError.hidden = true;
}

function updateControls() {
  if (!fieldDefinitions) return;
  const blocked = formBusy || launchPending || editingProfile || !launcherState || !launcherState.canLaunch;
  profileSelect.disabled = blocked;
  btnNewProfile.disabled = blocked;
  btnSaveProfile.disabled = blocked || !currentProfile;
  btnLaunch.disabled = blocked || !currentProfile;
  pythonPathInput.disabled = blocked;
  for (const input of fieldsContainer.querySelectorAll('[data-field]')) {
    input.disabled = blocked;
  }
  const ui = fieldDefinitions.ui;
  btnSaveProfile.textContent = savePending ? ui.saving : (saveSucceeded ? ui.saved : ui.save);
  btnLaunch.textContent = launchPending ? ui.launchPending : launcherState && !launcherState.canLaunch
    ? (launcherState.status === 'running' ? ui.running : ui.launcher.busy) : ui.launch;
}

async function init() {
  fieldDefinitions = await api.config.getFieldDefinitions();
  modelNotice.textContent = fieldDefinitions.ui.modelNotice;
  pythonPathInput.placeholder = fieldDefinitions.ui.launcher.pythonPlaceholder;
  pythonPathHint.textContent = fieldDefinitions.ui.launcher.pythonHint;
  pythonPathInput.addEventListener('input', updatePythonDescription);
  updatePythonDescription();
  window.dispatchEvent(new Event('launcher-ui-ready'));
  profileSelect.addEventListener('change', loadSelectedProfile);
  btnNewProfile.addEventListener('click', onNewProfile);
  btnSaveProfile.addEventListener('click', onSaveProfile);
  btnLaunch.addEventListener('click', onLaunch);
  btnViewLog.addEventListener('click', showLogPanel);
  pythonPathInput.addEventListener('change', async () => {
    try {
      await api.settings.save({ pythonPath: pythonPathInput.value.trim() });
    } catch (error) {
      showError(fieldDefinitions.ui.settingsFailed, error);
    }
  });

  // 壳设置失败不伪装成配置文件缺失，也不阻止读取启动配置。
  let settingsError = null;
  try {
    const settings = await api.settings.load();
    pythonPathInput.value = settings.pythonPath;
    runtimeDescription = settings.runtime;
    updatePythonDescription();
  } catch (error) {
    settingsError = error;
  }
  try {
    await loadProfiles();
  } catch (error) {
    showError(fieldDefinitions.ui.loadFailed, error);
  } finally {
    updateControls();
  }
  if (settingsError && configError.hidden) {
    showError(fieldDefinitions.ui.settingsFailed, settingsError);
  }
}

async function loadProfiles(preferredKey = null) {
  const profiles = await api.config.listProfiles();
  profileSelect.replaceChildren();
  if (profiles.length === 0) {
    currentProfile = null;
    const option = document.createElement('option');
    option.value = '';
    option.textContent = fieldDefinitions.ui.noProfiles;
    profileSelect.appendChild(option);
    const hint = document.createElement('p');
    hint.className = 'hint';
    hint.textContent = fieldDefinitions.ui.createFirstProfile;
    fieldsContainer.replaceChildren(hint);
    return;
  }
  for (const name of profiles) {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    profileSelect.appendChild(option);
  }
  profileSelect.value = profiles.includes(preferredKey) ? preferredKey : profiles[0];
  await loadSelectedProfile();
}

async function loadSelectedProfile() {
  const key = profileSelect.value;
  const sequence = ++profileLoadSequence;
  currentProfile = null;
  saveSucceeded = false;
  fieldsContainer.replaceChildren();
  clearError();
  if (!key) {
    updateControls();
    return;
  }
  formBusy = true;
  updateControls();
  try {
    const values = await api.config.loadProfile(key);
    if (sequence !== profileLoadSequence) return;
    configFields.assertConfigValues(fieldDefinitions, values);
    currentProfile = key;
    profileValues = values;
    rawValues = Object.fromEntries(fieldDefinitions.fields.map((field) => [
      field.name, field.type === 'bool' ? values[field.name] : String(values[field.name]),
    ]));
    dirtyFields = new Set();
    renderFields();
    refreshValues();
  } catch (error) {
    if (sequence === profileLoadSequence) showError(fieldDefinitions.ui.loadFailed, error);
  } finally {
    if (sequence === profileLoadSequence) {
      formBusy = false;
      updateControls();
    }
  }
}

function onNewProfile() {
  if (formBusy || launchPending || editingProfile) return;
  const profileBar = document.querySelector('.profile-bar');
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'new-profile-input';
  input.placeholder = fieldDefinitions.ui.newProfilePlaceholder;
  input.setAttribute('aria-label', fieldDefinitions.ui.newProfilePlaceholder);
  const confirm = document.createElement('button');
  confirm.className = 'btn btn-small btn-confirm-new';
  confirm.textContent = fieldDefinitions.ui.confirm;
  const cancel = document.createElement('button');
  cancel.className = 'btn btn-small';
  cancel.textContent = fieldDefinitions.ui.cancel;
  profileBar.classList.add('editing');
  profileBar.insertBefore(input, btnNewProfile);
  profileBar.insertBefore(confirm, btnNewProfile);
  profileBar.insertBefore(cancel, btnNewProfile);
  editingProfile = true;
  updateControls();
  input.focus();

  function restore() {
    profileBar.classList.remove('editing');
    input.remove();
    confirm.remove();
    cancel.remove();
    editingProfile = false;
    updateControls();
  }

  async function create() {
    if (formBusy) return;
    const name = input.value.trim();
    if (!name) {
      input.focus();
      return;
    }
    formBusy = true;
    input.disabled = true;
    confirm.disabled = true;
    cancel.disabled = true;
    clearError();
    updateControls();
    try {
      await api.config.createProfile(name);
    } catch (error) {
      formBusy = false;
      input.disabled = false;
      confirm.disabled = false;
      cancel.disabled = false;
      updateControls();
      showError(fieldDefinitions.ui.createFailed, error);
      input.focus();
      return;
    }
    restore();
    try {
      await loadProfiles(name);
    } catch (error) {
      currentProfile = null;
      fieldsContainer.replaceChildren();
      showError(fieldDefinitions.ui.loadFailed, error);
    } finally {
      formBusy = false;
      updateControls();
    }
  }

  confirm.addEventListener('click', create);
  cancel.addEventListener('click', restore);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      create();
    } else if (event.key === 'Escape' && !formBusy) {
      restore();
    }
  });
}

function renderFields() {
  fieldsContainer.replaceChildren();
  for (const group of fieldDefinitions.groups) {
    const section = document.createElement('section');
    section.className = 'field-group';
    const title = document.createElement('h2');
    title.className = 'field-group-title';
    title.textContent = group.label;
    section.appendChild(title);
    for (const field of fieldDefinitions.fields) {
      if (field.group === group.id) section.appendChild(createFieldRow(field));
    }
    fieldsContainer.appendChild(section);
  }
}

function createFieldRow(field) {
  const row = document.createElement('div');
  row.className = 'field-row';
  const label = document.createElement('label');
  label.htmlFor = `config-${field.name}`;
  const title = document.createElement('span');
  title.textContent = field.label;
  const name = document.createElement('code');
  name.textContent = field.name;
  label.append(title, name);
  row.appendChild(label);

  const input = document.createElement('input');
  input.id = label.htmlFor;
  input.className = field.type === 'bool' ? 'field-input bool' : 'field-input';
  input.type = field.type === 'bool' ? 'checkbox' : 'text';
  if (field.type === 'bool') input.checked = rawValues[field.name];
  else input.value = rawValues[field.name];
  if (field.type === 'int') input.inputMode = 'numeric';
  input.dataset.field = field.name;
  input.autocomplete = 'off';
  input.setAttribute('aria-describedby', `description-${field.name} error-${field.name}`);
  input.addEventListener('input', () => onFieldInput(field, input));
  input.addEventListener('change', () => onFieldInput(field, input));
  row.appendChild(input);

  const description = document.createElement('p');
  description.id = `description-${field.name}`;
  description.className = 'field-description';
  description.textContent = field.description;
  const error = document.createElement('div');
  error.id = `error-${field.name}`;
  error.className = 'field-error';
  error.setAttribute('aria-live', 'polite');
  row.append(description, error);
  return row;
}

function onFieldInput(field, input) {
  rawValues[field.name] = field.type === 'bool' ? input.checked : input.value;
  saveSucceeded = false;
  clearError();
  refreshValues();
  updateControls();
}

function refreshValues(focusFirst = false) {
  const values = {};
  const errors = {};
  dirtyFields = new Set();
  for (const field of fieldDefinitions.fields) {
    const result = configFields.parseFieldInput(field, rawValues[field.name]);
    if (result.valid) values[field.name] = result.value;
    else errors[field.name] = result;
    if (!result.valid || result.value !== profileValues[field.name]) dirtyFields.add(field.name);
    const input = document.getElementById(`config-${field.name}`);
    input.setAttribute('aria-invalid', String(!result.valid));
    document.getElementById(`error-${field.name}`).textContent = result.valid
      ? '' : configFields.formatFieldError(fieldDefinitions, field.name, result);
  }
  workingValues = values;
  const firstError = Object.keys(errors)[0];
  if (firstError && focusFirst) {
    showError(fieldDefinitions.ui.invalidFields);
    const input = document.getElementById(`config-${firstError}`);
    input.scrollIntoView({ block: 'center' });
    input.focus();
  }
  return !firstError;
}

async function onSaveProfile() {
  if (!currentProfile || formBusy || launchPending || editingProfile) return;
  clearError();
  if (!refreshValues(true)) return;
  const values = { ...workingValues };
  formBusy = true;
  savePending = true;
  saveSucceeded = false;
  updateControls();
  try {
    await api.config.saveProfile(currentProfile, values);
    profileValues = values;
    dirtyFields = new Set();
    saveSucceeded = true;
  } catch (error) {
    showError(fieldDefinitions.ui.saveFailed, error);
  } finally {
    savePending = false;
    formBusy = false;
    updateControls();
  }
}

function showLogPanel() {
  configPanel.classList.remove('active');
  logPanel.classList.add('active');
}

async function onLaunch() {
  if (formBusy || launchPending || editingProfile) return;
  if (!launcherState || !launcherState.canLaunch) {
    showLogPanel();
    return;
  }
  if (!currentProfile) {
    showError(fieldDefinitions.ui.selectProfile);
    return;
  }
  clearError();
  if (!refreshValues(true)) return;
  const overrides = Object.fromEntries([...dirtyFields].map((name) => [name, workingValues[name]]));
  const profile = currentProfile;
  const requestedPython = pythonPathInput.value.trim();
  launchPending = true;
  btnViewLog.style.display = '';
  showLogPanel();
  updateControls();
  try {
    await api.backend.launch(profile, overrides, requestedPython);
    // 接受应答不代表运行成功；包括已经到达的失败状态在内，都以主进程快照为准。
  } catch (error) {
    configPanel.classList.add('active');
    logPanel.classList.remove('active');
    showError(fieldDefinitions.ui.launchRejected, error);
  } finally {
    launchPending = false;
    updateControls();
  }
}

init().catch((error) => {
  showError('Configuration initialization failed.', error);
});
