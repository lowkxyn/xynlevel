import test from 'node:test';
import assert from 'node:assert/strict';
import { mapState, clockTime, ringState, statTiles, runChips } from './run-state.js';
import { DEFAULTS } from './settings.js';

const values = stats => Object.fromEntries(statTiles(stats).map(tile => [tile.key, tile.value]));

test('training statuses map to short words and tones', () => {
  for (const [status, word, tone] of [
    ['Getting ready', 'Preparing', 'text'], ['Setting gravity to 500G', 'Setting gravity', 'text'],
    ['Training: Health', 'Training', 'accent'], ['Eating a Senzu', 'Eating', 'good'],
    ['Getting a Senzu from the inventory', 'Refilling', 'text'], ['Respawning', 'Respawning', 'warn'],
    ["Paused: Roblox isn't the active window", 'Paused', 'warn'], ['New status from bot', 'Running', 'accent'],
  ]) assert.deepEqual(mapState({ running: true, status }), { word, tone });
  assert.equal(mapState({ running: true, stopping: true }).word, 'Stopping');
  assert.equal(mapState({ running: false, status: 'Stopped: manual stop' }).word, 'Stopped');
  assert.equal(mapState({ running: false, status: 'Stopped' }).word, 'Stopped');
  assert.equal(mapState({ running: false, last_run: { completed: true } }).word, 'Complete');
  assert.equal(mapState({ running: false }).word, 'Ready');
});

test('run clock uses elapsed time and progress uses the optional duration limit', () => {
  const base = { running: true, settings: { ...DEFAULTS, stop_after_minutes: 60 } };
  assert.equal(ringState({ ...base, stats: { elapsed: 1800 }, time_left: null }).fraction, 0.5);
  assert.equal(ringState({ ...base, stats: { elapsed: 7200 } }).fraction, 1);
  assert.equal(ringState({ ...base, stats: { elapsed: 3600 } }).tone, 'power');
  for (const elapsed of [null, undefined, NaN, Infinity, '60', -1]) {
    const ring = ringState({ ...base, stats: { elapsed } });
    assert.equal(ring.empty, true);
    assert.equal(ring.time, '--');
  }
  const unlimited = ringState({ settings: DEFAULTS, stats: { elapsed: 6130 } });
  assert.equal(unlimited.empty, true);
  assert.equal(unlimited.time, '01:42:10');
  assert.equal(unlimited.description, 'Run time: 01:42:10');
  assert.equal(ringState({ ...base, running: false, stats: { elapsed: 582 } }).time, '00:09:42');
  assert.equal(clockTime(7200), '02:00:00');
  assert.equal(clockTime(-1), '00:00:00');
  assert.equal(clockTime(61.9), '00:01:01');
  assert.equal(clockTime('60'), '--:--');
});

test('run tiles show missing readings as placeholders and render zeroes', () => {
  for (const stats of [null, {}, { elapsed: null, level: '42', senzus: NaN, deaths: -1, points_left: Infinity }]) {
    assert.deepEqual(values(stats), { elapsed: '--', level: '--', senzus: '--', deaths: '--', points_left: '--', gravity: '--' });
  }
  assert.deepEqual(values({ elapsed: 1062, level: 231, senzus: 1234, deaths: 0, points_left: 0, gravity: 500, exp_mult: 212.13 }),
    { elapsed: '00:17:42', level: '231', senzus: '1,234', deaths: '0', points_left: '0', gravity: '500G  x212' });
  assert.equal(values({ gravity: 175 }).gravity, '175G  --');
  assert.ok(!statTiles({ ults: 1, blasts: 2 }).some(tile => ['ults', 'blasts'].includes(tile.key)));
});

test('chips describe Health training and only enabled limits', () => {
  assert.deepEqual(runChips(DEFAULTS), ['Health', 'Max gravity', 'Senzu at 35% HP']);
  assert.deepEqual(runChips({ ...DEFAULTS, gravity_mode: 'custom', gravity: 175, auto_senzu: false, stop_after_minutes: 30, stop_at_level: 500 }),
    ['Health', '175G', 'Stop after 30 min', 'Stop at level 500']);
});
