import test from 'node:test';
import assert from 'node:assert/strict';
import { formatSeconds } from './format.js';

test('uses the core time format, including zero components', () => {
  for (const [input, expected] of [[3725, '1h 2m 5s'], [3600, '1h 0m 0s'], [90, '1m 30s'], [60, '1m 0s'], [45, '45s'], [0, '0s']]) {
    assert.equal(formatSeconds(input), expected);
  }
});
test('unknown times stay unknown; negative and fractional times are bounded', () => {
  for (const value of [null, undefined, NaN, Infinity, '60']) assert.equal(formatSeconds(value), '--');
  assert.equal(formatSeconds(-12), '0s');
  assert.equal(formatSeconds(90.9), '1m 30s');
});
