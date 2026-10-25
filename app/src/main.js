import { DEFAULTS, resolveTheme, validateSettings } from './settings.js';
import { formatSeconds } from './format.js';
import { mapState, ringState, statTiles, clockTime } from './run-state.js';
import { setupControls, syncControls } from './controls.js';
import { createMotion } from './motion.js';
import { createNavigation } from './navigation.js';
import { sessionMetrics, chamberBar } from './promo-state.js';
import { createTelemetryMotion, SNAPSHOT_INTERVAL_MS } from './telemetry-motion.js';
import { setupWindowControls } from './window-controls.js';

// A browser preview never installs or overrides the desktop bridge.
const preview = !window.__TAURI__?.core?.invoke && new URLSearchParams(location.search).has('mock')
  ? await import('./mock.js').then(module => module.createMock()) : null;

const $ = id => document.getElementById(id);
const invoke = window.__TAURI__?.core?.invoke || preview?.invoke;
const motion = createMotion($('app'));
const telemetry = createTelemetryMotion($('app'));
const windowControls = setupWindowControls($('app'), action => wc(action), error => toast(error, true));
setupControls();
const navigation = createNavigation($('app'));
const systemTheme = matchMedia('(prefers-color-scheme: light)');
let settings = { ...DEFAULTS };
let state = null;
let initialized = false;
let busy = false;
let saving = false;
let dirty = false;
let compact = false;
let online = false;
let lastRun = 0;
let rendered = false;
let toastTimer;
let logEvents = [];
let webhookSaves = Promise.resolve();
let webhookPending = 0;
let pendingSetting = null;

function toast(message, error = false) {
  clearTimeout(toastTimer);
  $('toast').textContent = String(message);
  $('toast').classList.toggle('error', error);
  $('toast').classList.remove('toast-exit');
  $('toast').hidden = false;
  toastTimer = setTimeout(() => { $('toast').classList.add('toast-exit'); setTimeout(() => { if ($('toast').classList.contains('toast-exit')) $('toast').hidden = true; }, 240); }, 6000);
}

async function api(action, payload = {}) {
  if (!invoke) throw new Error('Open the XynLevel app to connect.');
  const result = await invoke('api', { action, payload });
  if (result.ok === false) throw new Error(result.error || 'The operation failed');
  return result;
}

async function wc(action, enabled) {
  if (!invoke) throw new Error('Window controls are available in the desktop app.');
  return invoke('window_control', { action, enabled: enabled ?? null });
}

function appearance() {
  navigation.configure(settings);
  $('app').dataset.theme = resolveTheme(settings.theme, systemTheme.matches);
  $('app').dataset.ui = settings.theme === 'aero' ? 'aero' : 'classic';
  // These are accent presets, so the persisted theme contract stays unchanged.
  $('app').dataset.palette = ['dark', 'aero'].includes(settings.theme)
    ? ({ '#22d3ee': 'cyber', '#fbbf24': 'solar' }[settings.accent.toLowerCase()] || '') : '';
  $('app').classList.toggle('reduced-motion', settings.reduced_motion);
  telemetry.syncMotion();
  $('app').style.setProperty('--accent', settings.accent);
  $('app').dataset.gold = String(settings.accent.toLowerCase() === '#f5c04a');
  $('pin-indicator').hidden = !settings.always_on_top;
  $('pin-toggle').setAttribute('aria-pressed', String(settings.always_on_top));
  if (settings.reduced_motion) motion.clearEffects();
  // Keep text on arbitrary custom accent colours readable.
  const rgb = settings.accent.slice(1).match(/../g).map(x => parseInt(x, 16) / 255).map(x => x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4);
  const luminance = rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
  $('app').style.setProperty('--accent-ink', luminance > 0.179 ? '#0b0b11' : '#ffffff');
  $('app').style.setProperty('--accent-readable', luminance < 0.15 ? 'color-mix(in srgb,var(--accent) 35%,var(--text))' : 'var(--accent)');
}

function fillSettings(value) {
  settings = validateSettings(value);
  for (const input of document.querySelectorAll('[data-setting]')) {
    if (input.type === 'checkbox') input.checked = settings[input.id];
    else input.value = settings[input.id];
  }
  $('stop-pretty').textContent = `(${formatSeconds(settings.stop_at_seconds)})`;
  syncControls();
  appearance();
}

function collectSettings() {
  const value = {};
  for (const input of document.querySelectorAll('[data-setting]')) {
    if (input.type === 'checkbox') value[input.id] = input.checked;
    else if (['ult_slot', 'gravity', 'blast_interval', 'scroll_interval', 'stop_at_seconds', 'ki_control_target'].includes(input.id)) {
      input.classList.remove('invalid');
      input.removeAttribute('aria-invalid');
      const outsideRange = input.id !== 'ki_control_target' && (input.validity.rangeUnderflow || input.validity.rangeOverflow);
      const invalidInteger = (input.id === 'stop_at_seconds' && !Number.isSafeInteger(Number(input.value)))
        || (input.id === 'ki_control_target' && !Number.isInteger(Number(input.value)));
      if (input.value.trim() === '' || input.validity.badInput || outsideRange || invalidInteger) {
        input.classList.add('invalid');
        input.setAttribute('aria-invalid', 'true');
        throw new Error('Enter a valid number before saving');
      }
      value[input.id] = Number(input.value);
    } else value[input.id] = input.value;
  }
  return validateSettings(value);
}

async function saveSettings() {
  if (saving) return;
  saving = true;
  try {
    while (dirty) {
      const draft = collectSettings();
      dirty = false;
      $('save-status').textContent = 'Saving';
      $('save-status').dataset.status = 'saving';
      await api('settings', draft);
      settings = draft;
      if (!dirty) $('ki_control_target').value = settings.ki_control_target;
      appearance();
      await wc('pin', settings.always_on_top);
      $('save-status').textContent = 'Saved';
      $('save-status').dataset.status = 'saved';
      for (const input of document.querySelectorAll('[data-setting]:focus')) {
        input.classList.add('save-flash');
        setTimeout(() => input.classList.remove('save-flash'), 450);
      }
    }
  } catch (error) {
    dirty = true;
    $('save-status').dataset.status = 'error';
    $('save-status').textContent = `Not saved: ${String(error.message || error)}`;
    toast(error.message || error, true);
  } finally {
    saving = false;
    if (state) render(state);
  }
}

for (const input of document.querySelectorAll('[data-setting]')) {
  input.addEventListener('input', () => {
    dirty = true;
    syncControls();
    $('save-status').textContent = 'Unsaved changes';
    $('save-status').dataset.status = 'saving';
    // Appearance previews immediately; invalid drafts never reach the bridge.
    try { settings = collectSettings(); appearance(); } catch { /* Keep the last valid appearance. */ }
    if (input.id === 'stop_at_seconds') {
      const value = Number(input.value);
      $('stop-pretty').textContent = input.value.trim() && Number.isSafeInteger(value) && value >= 0 && value <= 604800 ? `(${formatSeconds(value)})` : '(invalid number)';
    }
  });
  input.addEventListener('change', saveSettings);
}

function navigate() {
  const target = ['run', 'settings', 'window', 'tools', 'stats'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'run';
  const previous = document.querySelector('.page:not([hidden])');
  for (const section of document.querySelectorAll('.page')) section.hidden = section.id !== target;
  navigation.select(target);
  if (previous && previous.id !== target) motion.revealPage($(target));
  requestAnimationFrame(() => {
    document.querySelector('.xyn-main').scrollTop = 0;
    if (target === 'settings' && pendingSetting) {
      const input = $(pendingSetting);
      pendingSetting = null;
      const section = input.closest('.settings-section');
      section.scrollIntoView({ block: 'start' });
      (input.disabled ? section : input).focus({ preventScroll: true });
    }
  });
}
for (const link of document.querySelectorAll('[data-open-setting]')) link.addEventListener('click', event => {
  event.preventDefault();
  pendingSetting = link.dataset.openSetting;
  if (location.hash === '#settings') navigate();
  else location.hash = '#settings';
});
window.addEventListener('hashchange', navigate);
systemTheme.addEventListener('change', appearance);
navigate();

function renderStats(stats) {
  const tiles = statTiles(stats);
  $('run-time').textContent = tiles.find(tile => tile.key === 'elapsed')?.value || '--:--';
  const counters = tiles.filter(tile => ['ults', 'deaths', 'blasts'].includes(tile.key));
  const container = $('run-stats');
  container.hidden = !counters.length;
  $('stats-empty').hidden = Boolean(counters.length);
  for (const hint of $('stats-empty').querySelectorAll('.telem-sub')) hint.textContent = stats ? 'not reported' : 'no run yet';
  container.style.setProperty('--stat-count', Math.min(counters.length, 4));
  for (const child of [...container.children]) {
    if (!counters.some(tile => tile.key === child.dataset.key)) child.remove();
  }
  for (const tile of counters) {
    let card = container.querySelector(`[data-key="${tile.key}"]`);
    if (!card) {
      card = document.createElement('div');
      card.className = 'stat-tile telem-card';
      card.dataset.key = tile.key;
      const label = document.createElement('div');
      label.className = 'telem-label';
      label.textContent = tile.label;
      const value = document.createElement('output');
      value.className = 'telem-value';
      value.dataset.stat = tile.key;
      const hint = document.createElement('span');
      hint.className = 'stat-hint telem-sub';
      card.append(label, value, hint);
      container.append(card);
    }
    const raw = stats[tile.key];
    telemetry.number(card.querySelector('output'), typeof raw === 'number' && raw >= 0 ? Math.floor(raw) : null);
    card.querySelector('.stat-hint').textContent = tile.hint;
  }
  const miniTiles = [['deaths', 'd'], ['ults', 'u']].filter(([key]) => tiles.some(tile => tile.key === key));
  for (const child of [...$('mini-counters').children]) {
    if (!miniTiles.some(([key]) => key === child.dataset.key)) child.remove();
  }
  for (const [key, label] of miniTiles) {
    let counter = $('mini-counters').querySelector(`[data-key="${key}"]`);
    if (!counter) {
      counter = document.createElement('span');
      counter.className = 'mini-counter';
      counter.dataset.key = key;
      counter.append(`${label} `, document.createElement('output'));
      $('mini-counters').append(counter);
    }
    telemetry.number(counter.querySelector('output'), typeof stats[key] === 'number' && stats[key] >= 0 ? Math.floor(stats[key]) : null);
  }
  for (const element of document.querySelectorAll('.hud-counters')) element.hidden = !miniTiles.length;
  const metrics = sessionMetrics(stats);
  telemetry.number($('run-level'), typeof stats?.level === 'number' && stats.level >= 0 ? stats.level : null);
  $('run-level-percent').textContent = metrics.xp !== null ? `${metrics.xp}% to next` : stats ? 'XP not read yet' : 'Reads during the run';
  telemetry.progress($('level-progress'), metrics.xp === null ? null : metrics.xp / 100, { wrap: true });
  $('level-gauge').classList.toggle('empty', metrics.xp === null);
  $('level-gauge').setAttribute('aria-label', metrics.xp === null ? 'Level progress unavailable' : `${metrics.xp}% to next level`);
  for (const metric of metrics.cards) {
    let card = $('session-stats').querySelector(`[data-session-stat="${metric.key}"]`);
    if (!card) {
      card = document.createElement('div');
      card.className = `telem-card${metric.key === 'level-range' ? ' session-level' : ''}`;
      card.dataset.sessionStat = metric.key;
      const label = document.createElement('div');
      label.className = 'telem-label';
      label.textContent = metric.label;
      const value = document.createElement('output');
      value.className = 'telem-value';
      const hint = document.createElement('div');
      hint.className = 'telem-sub';
      card.append(label, value, hint);
      if (metric.key === 'avg-life') card.append($('respawn-learning-template').content.cloneNode(true));
      $('session-stats').append(card);
    }
    const output = card.querySelector('output');
    if (metric.key === 'levels') {
      const value = typeof stats?.levels === 'number' ? stats.levels
        : typeof stats?.level === 'number' && typeof stats?.start_level === 'number' ? stats.level - stats.start_level : null;
      telemetry.number(output, value, number => number === null ? '--' : `${number > 0 ? '+' : ''}${Math.round(number).toLocaleString('en-GB')}`);
    } else if (metric.key === 'level-range') {
      const start = Number.isFinite(stats?.start_level) && stats.start_level >= 0 ? stats.start_level.toLocaleString('en-GB') : '--';
      telemetry.number(output, stats?.level >= 0 ? stats.level : null, number => `${start} to ${number === null ? '--' : Math.round(number).toLocaleString('en-GB')}`);
    } else output.textContent = metric.value;
    card.querySelector('.telem-sub').textContent = metric.hint;
  }
}

function render(snapshot) {
  telemetry.begin(snapshot);
  renderWebhook(snapshot.webhook);
  const running = snapshot.running;
  const after = snapshot.after_run || {};
  const mapped = mapState(snapshot);
  const ring = ringState(snapshot);
  const bar = chamberBar(snapshot, ring);
  $('app').dataset.running = String(running);
  $('run-button-label').textContent = snapshot.stopping ? 'Stopping...' : running ? 'Running' : 'Start run';
  $('run-button').title = snapshot.status;
  $('run-time-state').textContent = snapshot.stopping ? 'stopping' : running ? 'running' : snapshot.stats ? 'last run' : 'press Start run';
  const stopClock = clockTime(snapshot.settings.stop_at_seconds);
  $('session-stop-at').textContent = snapshot.settings.stop_enabled ? (snapshot.settings.stop_at_seconds < 3600 ? stopClock.slice(3) : stopClock) : 'Off';
  $('session-note').textContent = !snapshot.stats ? 'Start a run to collect statistics. Level readings appear when available.' : running ? 'Current session. Rates use elapsed run time; level readings appear when available.' : `Latest run. ${snapshot.last_run?.reason || snapshot.status}`;
  $('mini-run').textContent = snapshot.stopping ? 'Stopping...' : running ? 'Stop' : 'Start';
  for (const id of ['run-button', 'mini-run']) {
    $(id).disabled = busy || snapshot.stopping || (!running && (!online || saving || dirty || Boolean(snapshot.settings_warning) || Boolean(after.action) || ['requesting', 'requested', 'unknown'].includes(after.status)));
    $(id).classList.toggle('xyn-danger', running);
    $(id).classList.toggle('xyn-primary', !running);
  }
  // Separate v2 Start/Stop controls share the existing command/saving guards.
  $('stop-button').disabled = !running || busy || snapshot.stopping;
  $('run-button').disabled ||= running;
  $('status').textContent = snapshot.status;
  $('status').title = snapshot.status;
  $('mini-status').textContent = mapped.word;
  $('mini-status').title = snapshot.status;
  $('time-left').textContent = ring.time;
  $('time-left').classList.toggle('short-time', ring.time.length <= 5);
  telemetry.progress($('time-progress'), ring.empty ? null : bar.fraction, { scale: snapshot.time_left <= 60 ? 'minute' : 'chamber' });
  $('mini-time').textContent = ring.time;
  $('mini-time').title = ring.description;
  $('gauge').classList.toggle('empty', ring.empty);
  $('gauge').dataset.tone = ring.tone;
  $('gauge').setAttribute('aria-label', bar.description);
  telemetry.progress($('mini-progress'), ring.empty ? null : ring.fraction);
  renderStats(snapshot.stats);
  $('run-gravity').textContent = snapshot.settings.auto_gravity ? `${snapshot.settings.gravity}G` : 'Off';
  $('run-gravity-hint').textContent = snapshot.settings.auto_gravity ? 'set at start' : 'not changed';
  $('mini-dot').classList.toggle('active', running);
  $('mini-dot').style.background = after.action ? 'var(--power)' : mapped.tone === 'warn' ? 'var(--warn)' : running ? 'var(--good)' : 'var(--text3)';
  $('set-window').disabled = running || busy || !online;
  $('reset-settings').disabled = running || busy || saving || !online;
  $('game-size').textContent = snapshot.window.size ? `${snapshot.window.size[0]} \u00d7 ${snapshot.window.size[1]}` : 'Roblox not found';
  $('game-size').dataset.tone = snapshot.window.correct ? 'good' : 'warn';
  $('window-hint').textContent = snapshot.window.correct ? 'Game area is ready.' : snapshot.window.found ? 'Not 1920 × 1080 yet. Starting a run fixes it, or click Set window.' : 'Open Roblox first.';
  $('settings-warning').hidden = !snapshot.settings_warning;
  $('settings-warning').textContent = snapshot.settings_warning || '';
  $('version').textContent = snapshot.version || '1.0.0';
  const action = after.action;
  $('after-banner').hidden = !action;
  $('mini-cancel').hidden = !action;
  $('mini-time').hidden = Boolean(action);
  $('after-message').textContent = `${action === 'shutdown' ? 'PC shutdown' : 'Close XynLevel'} in ${after.seconds}s`;
  if (action) {
    $('mini-status').textContent = $('after-message').textContent;
    $('mini-status').title = $('after-message').textContent;
    $('mini-cancel').textContent = 'Cancel';
  }
  $('bridge-status').textContent = action ? 'Countdown' : running ? 'Running' : snapshot.hotkey_available ? 'Ready · F6' : 'Ready';
  $('bridge-dot').style.background = action ? 'var(--power)' : running ? 'var(--good)' : 'var(--text3)';
  motion.update(snapshot, mapped.word);
  const run = snapshot.last_run;
  if (run && run.id > lastRun) {
    // Reopening the app shouldn't toast an old completed session.
    if (rendered && !after.action) toast(run.reason);
    lastRun = run.id;
  }
  rendered = true;
}

async function command(action, payload = {}) {
  if (busy) return;
  busy = true;
  if (state) render(state);
  try {
    const result = await api(action, payload);
    if (result.filename) toast(`Saved ${result.filename}. Use Open app data to find it in reports.`);
    return result;
  } catch (error) {
    toast(error.message || error, true);
  } finally {
    busy = false;
    if (state) render(state);
  }
}

for (const id of ['run-button', 'stop-button', 'mini-run']) $(id).addEventListener('click', async () => {
  // Saving errors must not start with a stale configuration.
  if (!state?.running && dirty) await saveSettings();
  if (!state || (!state.running && (dirty || saving))) return;
  await command(state.running ? 'stop' : 'start');
});
$('set-window').addEventListener('click', () => command('set_window'));
$('pin-toggle').addEventListener('click', () => $('always_on_top').click());
for (const id of ['cancel-after', 'mini-cancel']) $(id).addEventListener('click', () => command('cancel_after_run'));
$('open-data').addEventListener('click', () => command('open_data'));
$('export-logs').addEventListener('click', () => command('export_logs'));
$('reset-settings').addEventListener('click', async () => {
  const result = await command('reset_settings');
  if (result?.ok) {
    const snapshot = await api('state');
    dirty = false;
    fillSettings(snapshot.settings);
    await wc('pin', settings.always_on_top);
    $('save-status').textContent = 'Defaults restored. Previous settings backed up.';
  }
});
// Turning notifications on is when Windows should ask, not a separate button.
$('notifications').addEventListener('change', async () => {
  if (!$('notifications').checked || !invoke) return;
  try {
    const permission = await invoke('notification_access');
    if (permission !== 'granted') toast(`Windows notifications are ${permission}. Allow XynLevel in Windows Settings > Notifications.`, true);
  } catch (error) { toast(error.message || error, true); }
});

// Discord webhook: kept out of settings.json and never echoed back into the page.
function renderWebhook(hook) {
  if (!hook) return;
  $('webhook-status').textContent = hook.status;
  $('webhook-url-hint').textContent = hook.configured
    ? 'A webhook is saved and encrypted. Paste a new one to replace it.'
    : "Paste a Discord webhook. It's encrypted for your Windows account and never shown again.";
  for (const id of ['webhook-enabled', 'webhook-progress', 'webhook-test', 'webhook-clear']) $(id).disabled = !hook.configured;
  if (!webhookPending && document.activeElement !== $('webhook-enabled')) $('webhook-enabled').checked = hook.enabled;
  if (!webhookPending && document.activeElement !== $('webhook-progress')) $('webhook-progress').value = String(hook.progress_minutes);
}

async function saveWebhook(extra = {}) {
  const payload = { enabled: $('webhook-enabled').checked, progress_minutes: Number($('webhook-progress').value), ...extra };
  // Preserve fast consecutive edits instead of dropping the second while busy.
  webhookPending++;
  const save = webhookSaves.then(async () => {
    try { return await api('webhook_save', payload); }
    catch (error) { toast(error.message || error, true); }
    finally { webhookPending--; }
  });
  webhookSaves = save;
  const result = await save;
  if (result?.webhook) renderWebhook(result.webhook);
  return result;
}

$('webhook-save').addEventListener('click', async () => {
  const url = $('webhook-url').value.trim();
  if (!url) { toast('Paste a webhook URL first', true); return; }
  // Turning reports on with a fresh webhook is what people expect from Save.
  const result = await saveWebhook({ url, enabled: true });
  if (result?.ok) { $('webhook-url').value = ''; toast('Webhook saved'); }
});
$('webhook-enabled').addEventListener('change', () => saveWebhook());
$('webhook-progress').addEventListener('change', () => saveWebhook());
$('webhook-test').addEventListener('click', async () => {
  const result = await command('webhook_test');
  if (result?.webhook) { renderWebhook(result.webhook); toast('Test message sent to Discord'); }
});
$('webhook-clear').addEventListener('click', async () => {
  const result = await command('webhook_clear');
  if (result?.webhook) { renderWebhook(result.webhook); toast('Webhook removed'); }
});

$('report-preview').addEventListener('click', async () => {
  const result = await command('report_preview');
  if (!result) return;
  $('report-content').textContent = JSON.stringify(result.report, null, 2);
  $('report-save').disabled = false;
  $('report-dialog').showModal();
});
$('report-close').addEventListener('click', () => $('report-dialog').close());
$('report-save').addEventListener('click', async () => {
  $('report-save').disabled = true;
  const result = await command('report_save');
  if (result?.ok) $('report-dialog').close();
  else $('report-save').disabled = false;
});

function renderLogs() {
  const filter = $('log-filter').value.toLowerCase();
  const events = logEvents.filter(event => event.message.toLowerCase().includes(filter));
  const lines = events.map(event => {
    const line = document.createElement('div');
    line.className = 'log-line';
    line.textContent = `${event.time}  ${event.message}`;
    return line;
  });
  $('logs').replaceChildren(...lines);
  if (!lines.length) $('logs').textContent = 'No matching events.';
  if ($('log-follow').checked) $('logs').scrollTop = $('logs').scrollHeight;
}
$('log-filter').addEventListener('input', renderLogs);
$('log-follow').addEventListener('change', renderLogs);

for (const action of ['minimize', 'maximize', 'close']) $(action).addEventListener('click', () => wc(action).then(() => {
  if (action === 'maximize') windowControls.syncMaximized();
}).catch(error => toast(error, true)));
async function toggleCompact() {
  if ($('app').classList.contains('compact-transition')) return;
  try {
    $('app').classList.add('compact-transition');
    if (!settings.reduced_motion && !matchMedia('(prefers-reduced-motion: reduce)').matches) await new Promise(resolve => setTimeout(resolve, 110));
    await wc('compact', !compact);
    compact = !compact;
    $('app').classList.toggle('compact', compact);
    $('mini').hidden = !compact;
    $('compact').ariaLabel = compact ? 'Expand' : 'Roll up';
    $('compact').title = compact ? 'Expand' : 'Roll up into a small bar';
  } catch (error) { toast(error, true); }
  finally { $('app').classList.remove('compact-transition'); }
}
$('compact').addEventListener('click', toggleCompact);
$('mini-expand').addEventListener('click', toggleCompact);
$('mini-close').addEventListener('click', () => wc('close').catch(error => toast(error, true)));

async function poll() {
  try {
    const snapshot = await api('state');
    online = true;
    state = snapshot;
    if (!initialized) {
      fillSettings(snapshot.settings);
      initialized = true;
      $('save-status').textContent = snapshot.settings_warning ? 'Settings need recovery' : 'Saved';
      await wc('pin', settings.always_on_top);
    } else if (!dirty && !saving) fillSettings(snapshot.settings);
    render(snapshot);
    if (!$('tools').hidden) {
      const logs = await api('logs');
      logEvents = logs.events;
      renderLogs();
    }
  } catch (error) {
    online = false;
    const message = String(error.message || error);
    $('bridge-status').textContent = 'Offline';
    $('bridge-dot').style.background = 'var(--danger)';
    $('mini-dot').classList.remove('active');
    $('mini-dot').style.background = 'var(--danger)';
    $('status').textContent = message;
    $('run-button').title = message;
    $('run-time-state').textContent = 'not connected';
    $('mini-status').textContent = message;
    // Keep Stop clickable when the last known state was running, so a transient loss can recover.
    $('run-button').disabled = true;
    for (const id of ['stop-button', 'mini-run']) $(id).disabled = !state?.running || busy;
    $('set-window').disabled = true;
  } finally {
    // One poll at a time, including slow startup or timeout responses.
    setTimeout(poll, SNAPSHOT_INTERVAL_MS);
  }
}
fillSettings(DEFAULTS);
if (preview?.compact) { compact = true; $('app').classList.add('compact'); $('mini').hidden = false; }
poll();
