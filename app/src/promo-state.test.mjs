import test from 'node:test';
import assert from 'node:assert/strict';
import { sessionMetrics } from './promo-state.js';

const values = stats => Object.fromEntries(sessionMetrics(stats).cards.map(card => [card.key, card.value]));

test('session stats show training counters and measured level progress', () => {
  const stats = { start_level: 203, level: 204, xp_percent: 69, elapsed: 2495, levels: 1, senzus: 405, senzu_left: 0, deaths: 9 };
  assert.equal(sessionMetrics(stats).level, '204');
  assert.equal(sessionMetrics(stats).xp, 69);
  assert.deepEqual(values(stats), { levels: '+1', 'level-hour': '1', 'next-level': '12:53', senzus: '405', 'senzu-left': '0', deaths: '9', paused: '--' });
  const precise = values({ start_level: 203, start_xp_percent: 50, level: 204, xp_percent: 69, elapsed: 600, levels: 1, paused: 75 });
  assert.equal(precise['level-hour'], '7');
  assert.equal(precise['next-level'], '02:36');
  assert.equal(precise.paused, '01:15');
  assert.equal(values({ start_level: 205, level: 204, elapsed: 60 }).levels, '-1');
});

test('missing and invalid stats never fabricate readings or rates', () => {
  for (const stats of [null, {}, { start_level: null, level: '204', xp_percent: NaN, elapsed: Infinity, senzus: -1, senzu_left: null, deaths: null }]) {
    assert.equal(sessionMetrics(stats).level, '--');
    assert.equal(sessionMetrics(stats).xp, null);
    assert.ok(Object.values(values(stats)).every(value => value === '--'));
  }
  assert.equal(values({ elapsed: 0, levels: 0 })['level-hour'], '--');
  assert.equal(values({ elapsed: 60, levels: 0 })['level-hour'], '0');
  assert.equal(values({ elapsed: 60, levels: 0 })['next-level'], '--');
  assert.equal(sessionMetrics({ xp_percent: 110 }).xp, 100);
  assert.equal(sessionMetrics({ xp_percent: -1 }).xp, null);
});
