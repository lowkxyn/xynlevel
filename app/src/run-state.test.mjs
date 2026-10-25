import test from 'node:test';
import assert from 'node:assert/strict';
import { mapState, clockTime, ringState, statTiles, runChips } from './run-state.js';
import { DEFAULTS } from './settings.js';

test('bot statuses map to state words without hiding the original detail', () => {
  for (const [status, word, tone] of [
    ['Charging', 'Charging', 'accent'], ['Firing slot 7', 'Firing', 'power'], ['Ki blasts', 'Blasts', 'accent'],
    ['Dead: clicking Respawn', 'Respawning', 'warn'], ['Waiting (respawning / loading)', 'Respawning', 'warn'],
    ['Setting gravity to 100G', 'Setting gravity', 'text'], ['Checking the shop for 4x Kamehameha', 'Shopping', 'text'],
    ['Retaking lock-on', 'Locking', 'text'], ['New status from bot', 'Running', 'accent'],
  ]) assert.deepEqual(mapState({ running: true, status }), { word, tone });
  assert.equal(mapState({ running: true, stopping: true, status: 'Charging' }).word, 'Stopping');
  assert.equal(mapState({ running: false, status: 'Stopped: manual stop' }).word, 'Stopped');
  assert.equal(mapState({ running: false, last_run: { completed: true } }).word, 'Complete');
  assert.equal(mapState({ running: false }).word, 'Ready');
});
test('ring clamps to two hours and changes colour at the actual boundaries', () => {
  const base = { running: true, settings: { ...DEFAULTS, stop_enabled: true } };
  assert.equal(ringState({ ...base, time_left: 8000 }).fraction, 1);
  assert.equal(ringState({ ...base, time_left: -1 }).fraction, 0);
  assert.equal(ringState({ ...base, time_left: 600 }).tone, 'accent');
  assert.equal(ringState({ ...base, time_left: 599 }).tone, 'warn');
  assert.equal(ringState({ ...base, time_left: 60 }).tone, 'power');
  assert.equal(ringState({ ...base, time_left: 61 }).tone, 'warn');
  for (const time_left of [null, undefined, NaN, Infinity, '60']) assert.equal(ringState({ ...base, time_left }).empty, true);
  assert.equal(ringState({ ...base, running: false, time_left: 60 }).empty, true);
  assert.equal(ringState({ ...base, running: false, time_left: 60, last_run: { completed: true } }).empty, false);
  assert.equal(ringState({ ...base, time_left: 60, time_formatted: '1m 0s' }).description, '1m 0s');
  assert.equal(ringState({ ...base, time_left: 6130 }).time, '1:42:10');
  assert.equal(ringState({ ...base, time_left: 582 }).time, '09:42');
});
test('only reported stat fields mount, null stays unavailable, elapsed uses a clock', () => {
  assert.deepEqual(statTiles(null), []);
  assert.deepEqual(statTiles({}), []);
  assert.deepEqual(statTiles({ elapsed: 1062, deaths: 0, levels: null }).map(x => [x.key, x.value, x.hint]),
    [['elapsed', '00:17:42', ''], ['deaths', '0', ''], ['levels', '--', 'not tracked']]);
  assert.deepEqual(statTiles({ ults: 1234, blasts: -1, unused: 8 }).map(x => x.value), ['1,234', '--']);
  assert.equal(statTiles({ levels: 1 })[0].value, '+1');
  assert.equal(clockTime(7200), '02:00:00');
  assert.equal(clockTime(-1), '00:00:00');
  assert.equal(clockTime(61.9), '00:01:01');
  assert.equal(clockTime('60'), '--:--');
});
test('chips use the snapshot run configuration and skip inactive settings', () => {
  assert.deepEqual(runChips(DEFAULTS), ['Auto', '100G', 'Circle']);
  assert.deepEqual(runChips({ ...DEFAULTS, attack: 'ult', ult_slot: 8, auto_gravity: false, movement: 'wa', stop_enabled: true }), ['Ult · 8', 'W+A', 'Stop · 1m 0s']);
});
