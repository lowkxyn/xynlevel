import test from 'node:test';
import assert from 'node:assert/strict';
import { DEFAULTS, loadSettings, resolveTheme, validateSettings } from './settings.js';

test('defaults match the training contract and survive persistence', () => {
  const value = validateSettings({});
  assert.deepEqual(value, {
    gravity_mode: 'max', gravity: 500, auto_senzu: true, senzu_at: 35,
    stop_after_minutes: 0, stop_at_level: 0, theme: 'dark', accent: '#b4bbc8',
    nav_style: 'keycap', dial_sounds: false, reduced_motion: false, notifications: true,
    sound: false, after_run: 'none', always_on_top: false,
  });
  assert.deepEqual(validateSettings(JSON.parse(JSON.stringify(value))), value);
});

test('training integer boundaries and custom values survive persistence', () => {
  for (const [key, min, max] of [['gravity', 1, 500], ['senzu_at', 10, 90], ['stop_after_minutes', 0, 10080], ['stop_at_level', 0, 100000]]) {
    for (const number of [min, max]) {
      const raw = { ...DEFAULTS, gravity_mode: 'custom', [key]: number };
      assert.deepEqual(validateSettings(JSON.parse(JSON.stringify(raw))), raw);
    }
  }
  assert.equal(validateSettings({ gravity: 123 }).gravity, 123);
});

test('legacy settings load silently without retaining bot-room keys or gravity', () => {
  const legacy = { attack: 'ult', ult_slot: 8, auto_gravity: false, gravity: 0, movement: 'off',
    stop_enabled: true, stop_at_seconds: 60, ki_control_spend: true, extra_legacy: 'ignored',
    theme: 'light', accent: '#22d3ee', sound: true, notifications: false, after_run: 'close_app',
    reduced_motion: true, always_on_top: true, nav_style: 'dial', dial_sounds: true };
  const loaded = loadSettings(JSON.parse(JSON.stringify(legacy)));
  assert.deepEqual(loaded, { ...DEFAULTS, theme: 'light', accent: '#22d3ee', sound: true, notifications: false,
    after_run: 'close_app', reduced_motion: true, always_on_top: true, nav_style: 'dial', dial_sounds: true });
  assert.equal(legacy.gravity, 0);
  assert.throws(() => validateSettings(legacy));
  assert.equal(loadSettings({ ...legacy, gravity_mode: 'custom', gravity: 175 }).gravity, 175);
});

test('explicit false and zero values survive loading missing new fields', () => {
  const value = loadSettings({ auto_senzu: false, stop_after_minutes: 0, stop_at_level: 0, sound: false });
  assert.equal(value.auto_senzu, false);
  assert.equal(value.senzu_at, 35);
  assert.equal(value.stop_after_minutes, 0);
  assert.equal(value.stop_at_level, 0);
  assert.equal(value.sound, false);
});

test('new writes reject malformed shapes, removed keys and nonboolean switches', () => {
  for (const raw of [null, [], 'settings', { attack: 'auto' }, { toString: 'invalid' }, { extra: 1 }]) {
    assert.throws(() => validateSettings(raw));
  }
  for (const key of ['auto_senzu', 'notifications', 'sound', 'reduced_motion', 'always_on_top', 'dial_sounds']) {
    assert.equal(validateSettings({ [key]: false })[key], false);
    for (const bad of [null, 0, 1, 'false', [], {}]) assert.throws(() => validateSettings({ [key]: bad }));
  }
});

test('training integers reject fractions, nonnumbers, nonfinite and out-of-range values', () => {
  for (const [key, min, max] of [['gravity', 1, 500], ['senzu_at', 10, 90], ['stop_after_minutes', 0, 10080], ['stop_at_level', 0, 100000]]) {
    for (const bad of [min - 1, max + 1, 1.5, null, true, false, '35', '', [], {}, NaN, Infinity, -Infinity]) {
      assert.throws(() => validateSettings({ [key]: bad }), `${key}: ${bad}`);
      assert.throws(() => loadSettings({ [key]: bad }), `${key}: ${bad}`);
    }
  }
});

test('enum and colour input stays allowlisted; system theme follows the OS', () => {
  for (const raw of [{ gravity_mode: 'off' }, { nav_style: 'other' }, { theme: 'other' },
    { accent: 'red' }, { accent: '#123456; color:red' }, { after_run: 'shell' }]) {
    assert.throws(() => validateSettings(raw));
  }
  assert.equal(resolveTheme('system', true), 'light');
  assert.equal(resolveTheme('system', false), 'dark');
  assert.equal(resolveTheme('aero', true), 'aero');
});

test('loading recovers cosmetic preferences while writes stay strict', () => {
  for (const bad of [null, 0, 1, 'other', [], {}]) {
    assert.equal(loadSettings({ nav_style: bad }).nav_style, 'keycap');
    assert.equal(loadSettings({ dial_sounds: bad }).dial_sounds, false);
    assert.throws(() => validateSettings({ nav_style: bad }));
    assert.throws(() => validateSettings({ dial_sounds: bad }));
  }
  for (const bad of [null, [], 'settings']) assert.throws(() => loadSettings(bad));
  const dial = { ...DEFAULTS, nav_style: 'dial', dial_sounds: true };
  assert.deepEqual(loadSettings(JSON.parse(JSON.stringify(dial))), dial);
});
