import test from 'node:test';
import assert from 'node:assert/strict';
import { sessionMetrics, chamberBar } from './promo-state.js';
import { ringState } from './run-state.js';

const values = stats => Object.fromEntries(sessionMetrics(stats).cards.map(card => [card.key, card.value]));

test('session stats use reported level readings and include the current life', () => {
  const stats = { start_level: 203, level: 204, xp_percent: 69, elapsed: 2495, levels: 1, ults: 405, deaths: 9 };
  assert.equal(sessionMetrics(stats).level, '204');
  assert.equal(sessionMetrics(stats).xp, 69);
  // Run time, ults and deaths are on the Run page, so Stats only shows what's derived from them.
  assert.deepEqual(values(stats), { 'level-range': '203 to 204', levels: '+1', 'level-hour': '1', 'next-level': '12:53', 'ults-per-life': '40.5', 'avg-life': '04:10', paused: '--:--' });
  // XP at both ends counts part-levels: 203 at 50% -> 204 at 69% in 10 min is 1.19 levels.
  const precise = values({ start_level: 203, start_xp_percent: 50, level: 204, xp_percent: 69, elapsed: 600, levels: 1, paused: 75 });
  assert.equal(precise['level-hour'], '7');
  assert.equal(precise['next-level'], '02:36');
  assert.equal(precise.paused, '01:15');
  assert.equal(values({ ults: 12, deaths: 0 })['ults-per-life'], '12');
  assert.equal(values({ start_level: 205, level: 204, elapsed: 60 }).levels, '-1');
});

test('missing, invalid, and zero-duration stats never fabricate readings or ratios', () => {
  for (const stats of [null, {}, { start_level: null, level: '204', xp_percent: NaN, elapsed: Infinity, ults: -1, deaths: null }]) {
    assert.equal(sessionMetrics(stats).level, '--');
    assert.equal(sessionMetrics(stats).xp, null);
    assert.equal(values(stats)['ults-per-life'], '--');
    assert.equal(values(stats)['level-hour'], '--');
  }
  assert.equal(values({ elapsed: 0, levels: 0 })['level-hour'], '--');
  assert.equal(values({ elapsed: 60, levels: 0 })['level-hour'], '0');
  assert.equal(sessionMetrics({ xp_percent: 110 }).xp, 100);
  assert.equal(sessionMetrics({ xp_percent: -1 }).xp, null);
});

test('final-minute bar follows real seconds and leaves the existing ring unchanged', () => {
  const snapshot = { running: true, time_left: 42 };
  const ring = ringState(snapshot);
  assert.equal(chamberBar(snapshot, ring).fraction, 0.7);
  assert.equal(chamberBar(snapshot, ring).description, 'Final minute: 42 seconds left');
  assert.equal(ring.fraction, 42 / 7200);
  for (const time_left of [null, undefined, NaN, Infinity, '42', -1, 0, 61, 7200]) {
    const state = { running: true, time_left };
    const bar = chamberBar(state, ringState(state));
    assert.ok(Number.isFinite(bar.fraction) && bar.fraction >= 0 && bar.fraction <= 1);
  }
  assert.equal(chamberBar({ time_left: 42 }, ringState({ time_left: 42 })).fraction, 0);
});
