import { DEFAULTS } from './settings.js';

// Explicit browser-only fixture. No persistence, network calls, game input or OS actions.
export function createMock() {
  const params = new URLSearchParams(location.search);
  const name = params.get('state') || 'idle';
  let snapshot = {
    ok: true, version: '1.0.0', running: !['idle', 'stopped', 'complete'].includes(name), stopping: false,
    status: 'Ready. Stand in the bot room, then start.', time_left: null, time_formatted: null, stats: null, webhook: { configured: true, enabled: true, progress_minutes: 15, status: 'Last report delivered' },
    settings: { ...DEFAULTS, nav_style: params.get('nav') || DEFAULTS.nav_style, dial_sounds: params.get('dial_sounds') !== 'off', theme: params.get('theme') || DEFAULTS.theme, accent: params.get('accent') || DEFAULTS.accent },
    settings_warning: null, input_logging: false, hotkey_available: true,
    window: { found: true, size: [1920, 1080], correct: true }, last_run: null,
    after_run: { action: null, status: 'idle', seconds: 0 },
  };
  if (snapshot.running || name === 'stopped' || name === 'complete') {
    snapshot.settings = { ...snapshot.settings, movement: 'wa', stop_enabled: true, after_run: 'close_app' };
    Object.assign(snapshot, { time_left: 6130, time_formatted: '1h 42m 10s', stats: { elapsed: 1062, ults: 38, deaths: 2, blasts: 264 }, status: 'Charging Ki, 4x Kamehameha in slot 7' });
  }
  if (name === 'blasts') snapshot.status = 'Ki blasts';
  if (name === 'promo') {
    Object.assign(snapshot, {
      status: 'Charging Ki, 4x Kamehameha in slot 7', time_left: 42, time_formatted: '42s',
      stats: { elapsed: 2495, start_level: 203, level: 204, levels: 1, xp_percent: 69, ults: 405, deaths: 9, blasts: 8227 },
    });
    snapshot.settings = { ...snapshot.settings, stop_enabled: true, stop_at_seconds: 15, after_run: 'none' };
  }
  if (name === 'gravity') snapshot.status = 'Setting gravity to 100G';
  if (name === 'shopping') snapshot.status = 'Checking the shop for 4x Kamehameha';
  if (name === 'locking') snapshot.status = 'Retaking lock-on';
  if (name === 'stopping') snapshot.stopping = true;
  if (name === 'firing') snapshot.status = 'Firing slot 7';
  if (name === 'dead') Object.assign(snapshot, { status: 'Dead: clicking Respawn', time_left: 582, time_formatted: '9m 42s' });
  if (name === 'stopped') snapshot.status = 'Stopped: manual stop';
  if (name === 'complete') {
    snapshot.status = 'Stopped: 60s (1m 0s) left';
    snapshot.last_run = { id: 1, reason: snapshot.status, completed: true };
    snapshot.time_left = 60;
    snapshot.time_formatted = '1m 0s';
  }
  if (name === 'countdown') {
    snapshot.running = false;
    snapshot.status = 'Stopped: 60s (1m 0s) left';
    snapshot.after_run = { action: 'shutdown', status: 'countdown', seconds: 24 };
    snapshot.last_run = { id: 1, reason: snapshot.status, completed: true };
    snapshot.time_left = 60;
    snapshot.time_formatted = '1m 0s';
    snapshot.settings.after_run = 'shutdown';
  }
  if (params.has('reduced')) snapshot.settings.reduced_motion = true;
  if (params.get('page')) location.hash = params.get('page');
  const calls = [];
  let failSettings = false;
  let offline = false;
  const logs = [
    { time: '14:20:00', message: 'Bridge connected. F6 global toggle ready.' },
    { time: '14:20:02', message: 'Game area checked: 1920 x 1080.' },
    { time: '14:20:04', message: 'Run started. Auto attack, ult slot 7.' },
    { time: '14:20:06', message: 'Setting gravity to 100G' },
    { time: '14:20:10', message: 'Charging Ki' },
    { time: '14:20:24', message: 'Firing slot 7' },
  ];
  // This test surface exists only after explicitly opting into mock mode.
  window.xynMock = {
    calls,
    set(patch) { snapshot = { ...snapshot, ...patch }; },
    get() { return structuredClone(snapshot); },
    failSettings(value) { failSettings = value; },
    offline(value) { offline = value; },
  };
  async function invoke(command, args = {}) {
    calls.push({ command, ...args });
    if (command === 'notification_access') return 'granted (mock)';
    if (command === 'window_control') return { ok: true };
    const { action, payload } = args;
    if (offline) throw new Error('Mock bridge unavailable');
    if (action === 'state') return structuredClone(snapshot);
    if (action === 'settings') {
      if (failSettings) throw new Error('Mock save failed');
      snapshot.settings = { ...payload };
    }
    if (action === 'reset_settings') snapshot.settings = { ...DEFAULTS };
    if (action === 'start') {
      snapshot.running = true;
      snapshot.stopping = false;
      snapshot.status = 'Charging';
      snapshot.stats = { elapsed: 0, ults: 0, deaths: 0, blasts: 0 };
      snapshot.last_run = null;
    }
    if (action === 'stop') { snapshot.running = false; snapshot.status = 'Stopped: manual stop'; }
    if (action === 'cancel_after_run') snapshot.after_run = { action: null, status: 'cancelled', seconds: 0 };
    if (action === 'log_start' || action === 'log_stop') snapshot.input_logging = action === 'log_start';
    if (action === 'logs') return { ok: true, events: logs };
    if (action === 'webhook_save') {
      snapshot.webhook = { configured: true, enabled: payload.enabled, progress_minutes: payload.progress_minutes, status: 'Saved (preview)' };
      return { ok: true, webhook: structuredClone(snapshot.webhook) };
    }
    if (action === 'webhook_test') {
      snapshot.webhook.status = 'Test delivered (preview)';
      return { ok: true, webhook: structuredClone(snapshot.webhook) };
    }
    if (action === 'webhook_clear') {
      snapshot.webhook = { configured: false, enabled: false, progress_minutes: 0, status: 'Not set up' };
      return { ok: true, webhook: structuredClone(snapshot.webhook) };
    }
    if (action === 'updater') return { ok: true, message: 'Automatic updates are disabled. Signing and release endpoints are not configured.' };
    if (action === 'report_preview') return { ok: true, report: { product: 'XynLevel', settings: snapshot.settings, window: snapshot.window, events: logs } };
    if (action === 'report_save' || action === 'export_logs') return { ok: true, filename: 'mock-report.zip' };
    return { ok: true };
  }
  return { invoke, compact: params.has('compact') };
}
