import { DEFAULTS } from './settings.js';

// Explicit browser-only fixture. No persistence, network calls, game input or OS actions.
export function createMock() {
  const params = new URLSearchParams(location.search);
  const name = params.get('state') || 'idle';
  let snapshot = {
    ok: true, version: '1.0.1', running: !['idle', 'stopped', 'complete', 'countdown'].includes(name), stopping: false,
    status: 'Ready. Stand in the Gravity Chamber, then start.', time_left: null, time_formatted: null, stats: null, webhook: { configured: true, enabled: true, progress_minutes: 15, status: 'Last report delivered' },
    settings: { ...DEFAULTS, nav_style: params.get('nav') || DEFAULTS.nav_style, dial_sounds: params.get('dial_sounds') !== 'off', theme: params.get('theme') || DEFAULTS.theme, accent: params.get('accent') || DEFAULTS.accent },
    settings_warning: null, input_logging: false, hotkey_available: true,
    window: { found: true, size: [1920, 1080], correct: true }, last_run: null,
    after_run: { action: null, status: 'idle', seconds: 0 },
  };
  if (snapshot.running || ['stopped', 'complete', 'countdown'].includes(name)) {
    snapshot.settings = { ...snapshot.settings, stop_after_minutes: 60, stop_at_level: 1300, after_run: 'close_app' };
    Object.assign(snapshot, { stats: { elapsed: 1062, start_level: 1240, level: 1247, levels: 7, start_xp_percent: 20, xp_percent: 69,
      deaths: 0, senzus: 4, refills: 4, pulls: 1010, paused: 12, gravity: 500, exp_mult: 212.13, drain: 519,
      points_left: 182, senzu_left: 483 }, status: 'Training: Health' });
  }
  if (name === 'promo') {
    snapshot.stats = { ...snapshot.stats, elapsed: 2495, level: 1256, levels: 16, senzus: 9, refills: 9, deaths: 0, pulls: 2370, points_left: 140, senzu_left: 478 };
    snapshot.settings.after_run = 'none';
  }
  if (name === 'gravity') snapshot.status = 'Setting gravity to 500G';
  if (name === 'preparing') snapshot.status = 'Getting ready';
  if (name === 'eating') snapshot.status = 'Eating a Senzu';
  if (name === 'refilling') snapshot.status = 'Getting a Senzu from the inventory';
  if (name === 'paused') snapshot.status = "Paused: Roblox isn't the active window";
  if (name === 'stopping') snapshot.stopping = true;
  if (['dead', 'respawning'].includes(name)) snapshot.status = 'Respawning';
  if (name === 'partial') snapshot.stats = {};
  if (name === 'stopped') snapshot.status = 'Stopped: manual stop';
  if (name === 'complete') {
    snapshot.status = 'Stopped: ran for 60 min';
    snapshot.last_run = { id: 1, reason: snapshot.status, completed: true };
    snapshot.stats.elapsed = 3600;
  }
  if (name === 'countdown') {
    snapshot.running = false;
    snapshot.status = 'Stopped: ran for 60 min';
    snapshot.after_run = { action: 'shutdown', status: 'countdown', seconds: 24 };
    snapshot.last_run = { id: 1, reason: snapshot.status, completed: true };
    snapshot.stats.elapsed = 3600;
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
    { time: '14:20:04', message: 'Getting ready' },
    { time: '14:20:06', message: 'Setting gravity to 500G' },
    { time: '14:20:10', message: 'Training: Health' },
    { time: '14:20:24', message: 'Eating a Senzu' },
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
      snapshot.status = 'Getting ready';
      snapshot.stats = { elapsed: 0, deaths: 0, senzus: 0, refills: 0, pulls: 0, paused: 0 };
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
