import test from 'node:test';
import assert from 'node:assert/strict';
import { DEFAULTS, resolveTheme, validateSettings } from './settings.js';

test('defaults match the GC core contract', () => {
  const value = validateSettings({});
  assert.equal(value.attack, 'auto');
  assert.equal(value.ult_slot, 7);
  assert.equal(value.blast_interval, 0.4);
  assert.equal(value.scroll_interval, 1);
  assert.equal(value.stop_enabled, false);
  assert.equal(value.movement, 'circle');
  assert.equal(value.sprint, true);
  assert.equal(value.blast_jump, true);
  assert.equal(value.ki_control_spend, false);
  assert.equal(value.ki_control_target, 300);
  assert.equal(value.after_run, 'none');
  assert.equal(value.theme, 'dark');
  assert.equal(value.accent, '#b4bbc8');
  assert.deepEqual(validateSettings(JSON.parse(JSON.stringify(value))), value);
});
test('valid extremes and slot 8 survive persistence', () => {
  const raw = { ...DEFAULTS, attack: 'ult', ult_slot: 8, stop_at_seconds: 604800, blast_interval: 0.05, scroll_interval: 60 };
  assert.deepEqual(validateSettings(raw), raw);
  assert.equal(validateSettings({ stop_at_seconds: 0 }).stop_at_seconds, 0);
});
test('old saved settings gain new booleans and explicit false survives', () => {
  const old = { ...DEFAULTS, attack: 'blasts' };
  delete old.restore_slot;
  delete old.ceiling_aim;
  const value = validateSettings(JSON.parse(JSON.stringify(old)));
  assert.equal(value.restore_slot, true);
  assert.equal(value.ceiling_aim, true);
  assert.equal(value.attack, 'blasts');
  for (const key of ['restore_slot', 'ceiling_aim', 'blast_jump', 'ki_control_spend']) {
    assert.equal(validateSettings({ [key]: false })[key], false);
    for (const bad of [null, 0, 1, 'false', [], {}]) {
      assert.throws(() => validateSettings({ [key]: bad }));
    }
  }
});
test('old movement and sprint choices survive new bot defaults', () => {
  const old = { ...DEFAULTS, movement: 'off', sprint: false };
  for (const key of ['blast_jump', 'ki_control_spend', 'ki_control_target']) delete old[key];
  const value = validateSettings(JSON.parse(JSON.stringify(old)));
  assert.equal(value.movement, 'off');
  assert.equal(value.sprint, false);
  assert.equal(value.blast_jump, true);
  assert.equal(value.ki_control_spend, false);
  assert.equal(value.ki_control_target, 300);
});
test('Ki Control target clamps whole numbers and persists', () => {
  for (const [target, expected] of [[-10, 1], [0, 1], [1, 1], [300, 300], [5000, 5000], [5001, 5000]]) {
    const value = validateSettings({ ki_control_target: target });
    assert.equal(value.ki_control_target, expected);
    assert.deepEqual(validateSettings(JSON.parse(JSON.stringify(value))), value);
  }
});
test('Ki Control target rejects non-numbers and fractional numbers', () => {
  for (const target of [null, true, false, '300', '', [], {}, NaN, Infinity, -Infinity, 1.5]) {
    assert.throws(() => validateSettings({ ki_control_target: target }));
  }
});
test('rejects malformed shapes, unsupported fields and string booleans', () => {
  for (const value of [null, [], 'settings', { extra: 1 }, { toString: 'invalid' }, { stop_enabled: 'false' }, { ult_slot: '7' }, { ult_slot: true }, { notifications: 1 }]) {
    assert.throws(() => validateSettings(value));
  }
});
test('rejects nonfinite, unsafe and out-of-range timing values', () => {
  for (const raw of [{ blast_interval: NaN }, { scroll_interval: Infinity }, { blast_interval: 0 },
    { scroll_interval: '1' }, { stop_at_seconds: 1.5 }, { stop_at_seconds: -1 }, { stop_at_seconds: 604801 }]) {
    assert.throws(() => validateSettings(raw));
  }
});
test('theme input is allowlisted and system theme follows the OS', () => {
  for (const raw of [{ theme: 'other' }, { accent: 'red' }, { accent: '#123456; color:red' }, { after_run: 'shell' }]) {
    assert.throws(() => validateSettings(raw));
  }
  assert.equal(resolveTheme('system', true), 'light');
  assert.equal(resolveTheme('system', false), 'dark');
  assert.equal(resolveTheme('aero', true), 'aero');
});


test('navigation defaults migrate old files and malformed cosmetic values recover', () => {
  const old = { ...DEFAULTS, attack: 'blasts' };
  delete old.nav_style;
  delete old.dial_sounds;
  const value = validateSettings(old);
  assert.equal(value.nav_style, 'keycap');
  assert.equal(value.dial_sounds, false);
  assert.equal(value.attack, 'blasts');
  for (const bad of [null, 0, 1, 'other', [], {}]) {
    assert.equal(validateSettings({ nav_style: bad }).nav_style, 'keycap');
    assert.equal(validateSettings({ dial_sounds: bad }).dial_sounds, false);
  }
  const dial = { ...DEFAULTS, nav_style: 'dial', dial_sounds: true };
  assert.deepEqual(validateSettings(JSON.parse(JSON.stringify(dial))), dial);
});
