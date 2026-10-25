export const DEFAULTS = Object.freeze({
  attack: 'auto', ult_slot: 7, blast_interval: 0.4, scroll_interval: 1,
  stop_enabled: false, stop_at_seconds: 60, movement: 'circle', relock: true, hide_chat: true, auto_gravity: true, gravity: 100, sprint: true, blast_jump: true, ult_jump: false, auto_buy: false, replace_slot: false, restore_slot: true, ceiling_aim: true, ki_control_spend: false, ki_control_target: 300, theme: 'dark', accent: '#b4bbc8',
  nav_style: 'keycap', dial_sounds: false, reduced_motion: false, notifications: true, sound: false, after_run: 'none', always_on_top: false,
});

export function validateSettings(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw) || Object.keys(raw).some(key => !Object.hasOwn(DEFAULTS, key))) {
    throw new Error('Settings contain unsupported fields');
  }
  const value = { ...DEFAULTS, ...raw };
  // Cosmetic preferences from older or edited files recover without blocking the macro.
  if (!['keycap', 'dial'].includes(value.nav_style)) value.nav_style = DEFAULTS.nav_style;
  if (typeof value.dial_sounds !== 'boolean') value.dial_sounds = DEFAULTS.dial_sounds;
  for (const [key, choices] of Object.entries({ attack: ['auto', 'blasts', 'ult'], ult_slot: [7, 8],
    movement: ['off', 'w', 'wa', 'wd', 'circle'],
    theme: ['dark', 'aero', 'light', 'system'], after_run: ['none', 'close_app', 'shutdown'] })) {
    if (!choices.includes(value[key])) throw new Error(`Invalid ${key}`);
  }
  for (const key of ['stop_enabled', 'relock', 'hide_chat', 'auto_gravity', 'sprint', 'blast_jump', 'ult_jump', 'auto_buy', 'replace_slot', 'restore_slot', 'ceiling_aim', 'ki_control_spend', 'reduced_motion', 'notifications', 'sound', 'always_on_top']) {
    if (typeof value[key] !== 'boolean') throw new Error(`${key} must be true or false`);
  }
  for (const key of ['blast_interval', 'scroll_interval']) {
    if (typeof value[key] !== 'number' || !Number.isFinite(value[key]) || value[key] < 0.05 || value[key] > 60) {
      throw new Error('Intervals must be between 0.05 and 60 seconds');
    }
  }
  if (!Number.isInteger(value.gravity) || value.gravity < 0 || value.gravity > 100 || value.gravity % 10) {
    throw new Error('Gravity must be 0, 10, 20 ... 100');
  }
  if (!Number.isInteger(value.ki_control_target)) throw new Error('Ki Control target must be a whole number');
  value.ki_control_target = Math.max(1, Math.min(5000, value.ki_control_target));
  if (!Number.isSafeInteger(value.stop_at_seconds) || value.stop_at_seconds < 0 || value.stop_at_seconds > 604800) {
    throw new Error('Stop time must be a whole number from 0 to 604800');
  }
  if (typeof value.accent !== 'string' || !/^#[0-9a-f]{6}$/i.test(value.accent)) throw new Error('Choose a six-digit accent colour');
  return value;
}

export function resolveTheme(theme, systemLight) {
  return theme === 'system' ? (systemLight ? 'light' : 'dark') : theme;
}
