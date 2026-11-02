/** Launcher snapshots and installation/backend logs; waiting never obscures the controls. */
'use strict';

// api, fieldDefinitions and applyLauncherState are shared with config.js.
const MAX_LINES = 2000;
const logOutput = document.getElementById('log-output');
const statusBadge = document.getElementById('status-badge');
const btnBackToConfig = document.getElementById('btn-back-to-config');
const btnCancelLaunch = document.getElementById('btn-cancel-launch');
const preparationPanel = document.getElementById('preparation-panel');
const preparationText = document.getElementById('preparation-text');
const preparationSpinner = document.getElementById('preparation-spinner');
const launchError = document.getElementById('launch-error');
let cancelRequestPending = false;
let stateReadError = null;
let cancelError = null;

function appendLogLine(log) {
  const line = document.createElement('div');
  line.className = `log-line ${log.stream === 'stderr' ? 'stderr' : 'stdout'}`;
  const ts = new Date(log.ts).toLocaleTimeString('zh-CN', { hour12: false });
  line.textContent = `[${ts}] ${log.line}`;
  logOutput.appendChild(line);
  while (logOutput.children.length > MAX_LINES) logOutput.firstChild.remove();
  logOutput.scrollTop = logOutput.scrollHeight;
}

function renderLauncherState() {
  if (!fieldDefinitions) return;
  const ui = fieldDefinitions.ui.launcher;
  btnCancelLaunch.textContent = ui.cancelLaunch;
  if (!launcherState) {
    btnCancelLaunch.disabled = true;
    if (stateReadError) {
      launchError.hidden = false;
      launchError.textContent = `${ui.stateFailed}\n${stateReadError.message || stateReadError}`;
    }
    return;
  }
  const state = launcherState;
  statusBadge.textContent = ui.status[state.status] || state.status;
  statusBadge.className = `status-badge status-${state.status}`;
  const waiting = ['preparing', 'starting', 'cancelling', 'evolving'].includes(state.status);
  const failed = ['setup_failed', 'crashed', 'timeout'].includes(state.status);
  preparationPanel.hidden = !waiting && !failed && state.status !== 'cancelled';
  preparationSpinner.hidden = !waiting;
  preparationText.textContent = ui.phase[state.phase] || ui.status[state.status] || state.status;
  btnCancelLaunch.hidden = !waiting;
  btnCancelLaunch.disabled = cancelRequestPending || !state.canCancel;
  const messages = [];
  if (state.errorCode) messages.push(ui.errors[state.errorCode] || state.errorCode);
  if (state.detail) messages.push(state.detail);
  if (failed && !state.canLaunch) messages.push(ui.cleanupBlocked);
  if (cancelError) messages.push(ui.cancelFailed, cancelError.message || String(cancelError));
  launchError.textContent = messages.join('\n');
  launchError.hidden = messages.length === 0;
}

function receiveState(state) {
  if (!applyLauncherState(state)) return;
  stateReadError = null;
  cancelError = null;
  renderLauncherState();
}

api.backend.onLog(appendLogLine);
api.backend.onStatus(receiveState);
// 注册监听后再读取快照；revision可拒绝比事件更晚到达的旧读取结果。
api.backend.getState().then(receiveState).catch((error) => {
  stateReadError = error;
  appendLogLine({ stream: 'stderr', line: error.message || String(error), ts: Date.now() });
  renderLauncherState();
});
window.addEventListener('launcher-ui-ready', renderLauncherState);
renderLauncherState();

btnBackToConfig.addEventListener('click', () => {
  configPanel.classList.add('active');
  logPanel.classList.remove('active');
});

btnCancelLaunch.addEventListener('click', async () => {
  if (cancelRequestPending || !launcherState || !launcherState.canCancel) return;
  cancelRequestPending = true;
  cancelError = null;
  renderLauncherState();
  try {
    await api.backend.cancel();
  } catch (error) {
    cancelError = error;
    appendLogLine({ stream: 'stderr', line: error.message || String(error), ts: Date.now() });
  } finally {
    cancelRequestPending = false;
    renderLauncherState();
  }
});
