/**
 * config.js — 配置面板交互逻辑
 *
 * 职责：
 *   - 加载 profile 列表并填充下拉选择器
 *   - 按分组渲染 27 个字段编辑控件
 *   - 实时校验字段值
 *   - 保存到 profile / 临时覆盖
 *   - 收集覆盖差异 → 调用 backend.launch
 */

'use strict';

const api = window.electronAPI;
const { FIELD_GROUPS, FIELD_TYPES, FIELD_DEFAULTS, FIELD_VALIDATORS } = api.fieldDefs;

// ── 状态 ──────────────────────────────────────────────────

let currentProfile = null;       // 当前选中的 profile key
let profileValues = {};          // 当前 profile 存储的字段值
let workingValues = {};          // 用户在 UI 中编辑后的字段值
let dirtyFields = new Set();    // 被用户修改过的字段名
let backendLaunched = false;     // 后端是否已启动（防止重复启动）

// ── DOM 引用 ───────────────────────────────────────────────

const profileSelect = document.getElementById('profile-select');
const btnNewProfile = document.getElementById('btn-new-profile');
const btnSaveProfile = document.getElementById('btn-save-profile');
const btnLaunch = document.getElementById('btn-launch');
const fieldsContainer = document.getElementById('fields-container');
const configPanel = document.getElementById('config-panel');
const logPanel = document.getElementById('log-panel');
const pythonPathInput = document.getElementById('python-path-input');
const btnViewLog = document.getElementById('btn-view-log');

// ── 初始化 ──────────────────────────────────────────────────

async function init() {
  // 加载壳设置（Python 路径）— 失败不阻塞 profile 加载
  try {
    const settings = await api.settings.load();
    pythonPathInput.value = settings.pythonPath || '';
    // 显示自动探测到的路径作为 placeholder
    if (settings.detectedPythonPath && settings.detectedPythonPath !== 'python') {
      pythonPathInput.placeholder = settings.detectedPythonPath + '（自动探测）';
    }
  } catch (err) {
    console.error('[config] settings.load failed:', err);
  }

  // Python 路径变更时自动保存
  pythonPathInput.addEventListener('change', async () => {
    try {
      await api.settings.save({ pythonPath: pythonPathInput.value.trim() });
    } catch (err) {
      console.error('[config] settings.save failed:', err);
    }
  });

  await loadProfiles();
  profileSelect.addEventListener('change', onProfileChange);
  btnNewProfile.addEventListener('click', onNewProfile);
  btnSaveProfile.addEventListener('click', onSaveProfile);
  btnLaunch.addEventListener('click', onLaunch);
  btnViewLog.addEventListener('click', () => {
    configPanel.classList.remove('active');
    logPanel.classList.add('active');
  });
}

// ── Profile 列表 ──────────────────────────────────────────

async function loadProfiles() {
  const profiles = await api.config.listProfiles();
  profileSelect.innerHTML = '';

  if (profiles.length === 0) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = '（无配置，请新建）';
    profileSelect.appendChild(opt);
    fieldsContainer.innerHTML = '<p class="hint">点击"新建"创建第一个配置方案</p>';
    return;
  }

  for (const name of profiles) {
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name;
    profileSelect.appendChild(opt);
  }

  // 默认选第一个
  profileSelect.value = profiles[0];
  await onProfileChange();
}

// ── Profile 切换 ──────────────────────────────────────────

async function onProfileChange() {
  currentProfile = profileSelect.value;
  if (!currentProfile) return;

  profileValues = await api.config.loadProfile(currentProfile);
  workingValues = { ...profileValues };
  dirtyFields = new Set();
  renderFields();
}

// ── 新建 Profile ──────────────────────────────────────────

async function onNewProfile() {
  // Electron 不支持 window.prompt()，使用内联输入替代
  const profileBar = document.querySelector('.profile-bar');
  if (profileBar.classList.contains('editing')) return;

  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'new-profile-input';
  input.placeholder = '输入配置方案名称...';

  const btnConfirm = document.createElement('button');
  btnConfirm.className = 'btn btn-small btn-confirm-new';
  btnConfirm.textContent = '确认';

  const btnCancel = document.createElement('button');
  btnCancel.className = 'btn btn-small';
  btnCancel.textContent = '取消';

  profileBar.classList.add('editing');
  profileBar.insertBefore(input, btnNewProfile);
  profileBar.insertBefore(btnConfirm, btnNewProfile);
  profileBar.insertBefore(btnCancel, btnNewProfile);
  input.focus();

  function restore() {
    profileBar.classList.remove('editing');
    input.remove();
    btnConfirm.remove();
    btnCancel.remove();
  }

  async function doCreate() {
    const name = input.value.trim();
    if (!name) { restore(); return; }

    const profiles = await api.config.listProfiles();
    if (profiles.includes(name)) {
      alert(`配置方案 "${name}" 已存在`);
      input.focus();
      input.select();
      return;
    }

    await api.config.createProfile(name);
    restore();
    await loadProfiles();
    profileSelect.value = name;
    await onProfileChange();
  }

  btnConfirm.addEventListener('click', doCreate);
  btnCancel.addEventListener('click', restore);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); doCreate(); }
    else if (e.key === 'Escape') { e.preventDefault(); restore(); }
  });
}

// ── 保存到 Profile ────────────────────────────────────────

async function onSaveProfile() {
  if (!currentProfile) return;

  // 收集所有 workingValues（不仅 dirty）
  const toSave = {};
  for (const [field, value] of Object.entries(workingValues)) {
    toSave[field] = value;
  }
  await api.config.saveProfile(currentProfile, toSave);

  // 保存后重置 dirty
  profileValues = { ...workingValues };
  dirtyFields = new Set();
  btnSaveProfile.textContent = '已保存';
  setTimeout(() => { btnSaveProfile.textContent = '保存到 Profile'; }, 1500);
}

// ── 字段渲染 ──────────────────────────────────────────────

function renderFields() {
  fieldsContainer.innerHTML = '';

  for (const [groupTitle, fieldNames] of Object.entries(FIELD_GROUPS)) {
    const groupDiv = document.createElement('div');
    groupDiv.className = 'field-group';

    const titleDiv = document.createElement('div');
    titleDiv.className = 'field-group-title';
    titleDiv.textContent = groupTitle;
    groupDiv.appendChild(titleDiv);

    for (const fieldName of fieldNames) {
      const type = FIELD_TYPES[fieldName] || 'str';
      const value = workingValues[fieldName] ?? FIELD_DEFAULTS[fieldName];
      groupDiv.appendChild(createFieldRow(fieldName, type, value));
    }

    fieldsContainer.appendChild(groupDiv);
  }
}

function createFieldRow(fieldName, type, value) {
  const row = document.createElement('div');

  // label
  const label = document.createElement('label');
  label.textContent = fieldName;
  row.appendChild(label);

  // input
  let input;
  if (type === 'bool') {
    input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = !!value;
    input.className = 'field-input bool';
  } else {
    input = document.createElement('input');
    input.type = 'text';
    input.value = String(value ?? '');
    input.className = 'field-input';
  }
  input.dataset.field = fieldName;
  input.dataset.type = type;
  input.addEventListener('input', () => onFieldInput(input));
  input.addEventListener('change', () => onFieldInput(input));
  row.appendChild(input);

  // error 提示
  const errorDiv = document.createElement('div');
  errorDiv.className = 'field-error';
  errorDiv.id = `error-${fieldName}`;
  row.appendChild(errorDiv);

  return row;
}

function onFieldInput(input) {
  const fieldName = input.dataset.field;
  const type = input.dataset.type;
  let rawValue;

  if (type === 'bool') {
    rawValue = input.checked;
  } else {
    rawValue = input.value;
  }

  // 校验
  const validator = FIELD_VALIDATORS[fieldName];
  if (validator && type !== 'bool') {
    const result = validator(rawValue);
    const errorEl = document.getElementById(`error-${fieldName}`);
    if (!result.valid) {
      errorEl.textContent = result.error;
      input.style.borderColor = 'var(--error)';
    } else {
      errorEl.textContent = '';
      input.style.borderColor = '';
    }
  }

  // 类型转换并存储
  let storeValue = rawValue;
  if (type === 'int') storeValue = parseInt(rawValue, 10);
  else if (type === 'float') storeValue = parseFloat(rawValue);
  else if (type === 'bool') storeValue = rawValue;
  else storeValue = rawValue;

  workingValues[fieldName] = storeValue;

  // 标记 dirty（与 profile 原始值比较）
  if (JSON.stringify(storeValue) !== JSON.stringify(profileValues[fieldName])) {
    dirtyFields.add(fieldName);
  } else {
    dirtyFields.delete(fieldName);
  }
}

// ── 启动 ──────────────────────────────────────────────────

function onLaunch() {
  if (!currentProfile) {
    alert('请先选择或创建一个配置方案');
    return;
  }
  if (backendLaunched) {
    // 已启动 → 直接切到日志面板
    configPanel.classList.remove('active');
    logPanel.classList.add('active');
    return;
  }

  // 收集临时覆盖（仅 dirty 字段）
  const overrides = {};
  for (const field of dirtyFields) {
    overrides[field] = workingValues[field];
  }

  // Python 路径（从壳设置中读取）
  const pythonPath = pythonPathInput.value.trim() || 'python';

  // 标记已启动 + 禁用启动按钮
  backendLaunched = true;
  btnLaunch.disabled = true;
  btnLaunch.textContent = '运行中';
  btnViewLog.style.display = '';

  // 切换到日志面板
  configPanel.classList.remove('active');
  logPanel.classList.add('active');

  // 发送启动命令
  api.backend.launch(currentProfile, overrides, pythonPath);
}

// ── 启动 ──────────────────────────────────────────────────

init();