import test from 'node:test';
import assert from 'node:assert/strict';
import { createTelemetryMotion, sessionReset, SNAPSHOT_INTERVAL_MS } from './telemetry-motion.js';

const snapshot = (elapsed, patch = {}) => ({ running: true, stats: { elapsed, start_level: 203, level: 204, ...patch } });

function clock(run) {
  const saved = Object.fromEntries(['document', 'matchMedia', 'requestAnimationFrame', 'cancelAnimationFrame', 'performance'].map(key => [key, globalThis[key]]));
  let now = 0;
  let id = 0;
  const frames = new Map();
  const media = { matches: false, addEventListener(_name, callback) { this.changed = callback; } };
  const root = { reduced: false, classList: { contains: () => root.reduced } };
  globalThis.document = { hidden: false, addEventListener() {} };
  globalThis.matchMedia = () => media;
  globalThis.performance = { now: () => now };
  globalThis.requestAnimationFrame = callback => { frames.set(++id, callback); return id; };
  globalThis.cancelAnimationFrame = key => frames.delete(key);
  const advance = ms => {
    now += ms;
    const callbacks = [...frames.values()];
    frames.clear();
    for (const callback of callbacks) callback(now);
  };
  const element = () => ({ textContent: '', dataset: {}, style: { setProperty(key, value) { this[key] = value; } }, hidden: false, isConnected: true, closest() { return this.hidden ? {} : null; } });
  try { run({ motion: createTelemetryMotion(root), root, media, element, advance, frames }); }
  finally { Object.assign(globalThis, saved); }
}

test('session resets include restart, elapsed rollback and changed starting level', () => {
  assert.equal(sessionReset(null, snapshot(0)), true);
  assert.equal(sessionReset({ ...snapshot(10), running: false }, snapshot(0)), true);
  assert.equal(sessionReset(snapshot(100), snapshot(0)), true);
  assert.equal(sessionReset(snapshot(100), snapshot(101, { start_level: 300 })), true);
  assert.equal(sessionReset(snapshot(100), snapshot(101)), false);
  assert.equal(SNAPSHOT_INTERVAL_MS, 500);
});

test('counter updates interpolate, coalesce repeated targets and reach the exact value', () => clock(({ motion, element, advance, frames }) => {
  const counter = element();
  motion.begin(snapshot(100)); motion.number(counter, 100);
  motion.begin(snapshot(101)); motion.number(counter, 200);
  advance(60);
  assert.ok(Number(counter.textContent) > 100 && Number(counter.textContent) < 200);
  const pending = frames.size;
  motion.number(counter, 200);
  assert.equal(frames.size, pending);
  advance(160);
  assert.equal(counter.textContent, '200');
  assert.equal(frames.size, 0);
}));

test('a counter can retarget mid-flight without dropping to the previous snapshot', () => clock(({ motion, element, advance }) => {
  const counter = element();
  motion.begin(snapshot(100)); motion.number(counter, 10);
  motion.begin(snapshot(101)); motion.number(counter, 50);
  advance(80);
  const intermediate = Number(counter.textContent);
  motion.begin(snapshot(102)); motion.number(counter, 80);
  assert.equal(Number(counter.textContent), intermediate);
  advance(220);
  assert.equal(counter.textContent, '80');
}));

test('counter corrections, new runs, unknowns and hidden pages snap immediately', () => clock(({ motion, element, advance }) => {
  const counter = element();
  motion.begin(snapshot(100)); motion.number(counter, 500);
  motion.begin(snapshot(101)); motion.number(counter, 490);
  assert.equal(counter.textContent, '490');
  motion.begin(snapshot(0)); motion.number(counter, 0);
  assert.equal(counter.textContent, '0');
  motion.begin(snapshot(1)); motion.number(counter, null);
  assert.equal(counter.textContent, '--');
  counter.hidden = true;
  motion.number(counter, 1000);
  advance(250);
  assert.equal(counter.textContent, '1,000');
}));

test('app and OS reduced motion cancel an active counter and use instant targets', () => clock(({ motion, root, media, element, advance }) => {
  const counter = element();
  motion.begin(snapshot(100)); motion.number(counter, 10);
  motion.begin(snapshot(101)); motion.number(counter, 40);
  advance(40);
  root.reduced = true;
  motion.syncMotion();
  assert.equal(counter.textContent, '40');
  motion.number(counter, 60);
  assert.equal(counter.textContent, '60');
  root.reduced = false;
  motion.number(counter, 80);
  media.matches = true;
  media.changed();
  assert.equal(counter.textContent, '80');
}));

test('bars use transform, snap XP wraps and reset the GC scale without width writes', () => clock(({ motion, element, advance }) => {
  const bar = element();
  motion.begin(snapshot(100)); motion.progress(bar, .8, { wrap: true });
  advance(16); advance(16);
  assert.equal(bar.style.transition, '');
  motion.begin(snapshot(101)); motion.progress(bar, .9, { wrap: true });
  assert.equal(bar.style.transform, 'scaleX(0.9)');
  assert.equal(bar.style.width, undefined);
  motion.begin(snapshot(102, { level: 205 })); motion.progress(bar, .1, { wrap: true });
  assert.equal(bar.style.transition, 'none');
  assert.equal(bar.style.transform, 'scaleX(0.1)');
  advance(16); advance(16);
  motion.begin(snapshot(103)); motion.progress(bar, .8, { scale: 'minute' });
  assert.equal(bar.style.transition, 'none');
}));

test('bars clamp invalid inputs and reduced motion preserves their final transforms', () => clock(({ motion, root, element, advance }) => {
  const bar = element();
  motion.begin(snapshot(100)); motion.progress(bar, 2);
  assert.equal(bar.style.transform, 'scaleX(1)');
  advance(16); advance(16);
  root.reduced = true;
  motion.begin(snapshot(101)); motion.progress(bar, .3);
  assert.equal(bar.style.transition, 'none');
  assert.equal(bar.style.transform, 'scaleX(0.3)');
  motion.progress(bar, NaN);
  assert.equal(bar.style.transform, 'scaleX(0)');
}));
