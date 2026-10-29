export const DEFAULTS = Object.freeze({
  gravity_mode: 'max', gravity: 500, auto_senzu: true, senzu_at: 35,
  stop_after_minutes: 0, stop_at_level: 0, theme: 'dark', accent: '#b4bbc8',
  nav_style: 'keycap', dial_sounds: false, reduced_motion: false, notifications: true, sound: false, after_run: 'none', always_on_top: false,
});

export function validateSettings(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw) || Object.keys(raw).some(key => !Object.hasOwn(DEFAULTS, key))) {
    throw new Error('Settings contain unsupported fields');
  }
  const value = { ...DEFAULTS, ...raw };
  for (const [key, choices] of Object.entries({ gravity_mode: ['max', 'custom'], nav_style: ['keycap', 'dial'],
    theme: ['dark', 'aero', 'light', 'system'], after_run: ['none', 'close_app', 'shutdown'] })) {
    if (!choices.includes(value[key])) throw new Error(`Invalid ${key}`);
  }
  for (const key of ['auto_senzu', 'dial_sounds', 'reduced_motion', 'notifications', 'sound', 'always_on_top']) {
    if (typeof value[key] !== 'boolean') throw new Error(`${key} must be true or false`);
  }
  for (const [key, min, max] of [['gravity', 1, 500], ['senzu_at', 10, 90], ['stop_after_minutes', 0, 10080], ['stop_at_level', 0, 100000]]) {
    if (!Number.isInteger(value[key]) || value[key] < min || value[key] > max) {
      throw new Error(`${key} must be a whole number from ${min} to ${max}`);
    }
  }
  if (typeof value.accent !== 'string' || !/^#[0-9a-f]{6}$/i.test(value.accent)) throw new Error('Choose a six-digit accent colour');
  return value;
}

export function loadSettings(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('Settings must be an object');
  const supported = Object.fromEntries(Object.entries(raw).filter(([key]) => Object.hasOwn(DEFAULTS, key)));
  if (!Object.hasOwn(raw, 'gravity_mode') && Object.hasOwn(raw, 'auto_gravity')) delete supported.gravity;
  if (Object.hasOwn(supported, 'nav_style') && !['keycap', 'dial'].includes(supported.nav_style)) supported.nav_style = DEFAULTS.nav_style;
  if (Object.hasOwn(supported, 'dial_sounds') && typeof supported.dial_sounds !== 'boolean') supported.dial_sounds = DEFAULTS.dial_sounds;
  return validateSettings(supported);
}

export function resolveTheme(theme, systemLight) {
  return theme === 'system' ? (systemLight ? 'light' : 'dark') : theme;
}
