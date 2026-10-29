import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DEFAULTS } from './settings.js';

const read = name => readFileSync(new URL(name, import.meta.url), 'utf8');
const html = read('./index.html');
const tags = [...html.matchAll(/<[^!][^>]*>/g)].map(match => match[0]);
const REMOVED = new Set(['run-dot', 'run-state', 'run-window', 'run-set-window', 'summary-attack', 'summary-stop', 'run-chips',
  'footer-state', 'footer-time', 'connection-dot', 'connection', 'hotkey-status', 'input-log', 'notification-access',
  'check-found', 'check-found-icon', 'check-size', 'check-size-icon', 'section-attack', 'section-movement', 'section-chamber',
  'gravity-value', 'stop-pretty', 'ki_control_spend-hint', 'time-left', 'stats-empty', 'respawn-learning-template',
  ...['attack', 'ult_slot', 'blast_interval', 'scroll_interval', 'stop_enabled', 'stop_at_seconds', 'movement', 'relock',
    'hide_chat', 'auto_gravity', 'sprint', 'blast_jump', 'ult_jump', 'auto_buy', 'replace_slot', 'restore_slot', 'ceiling_aim',
    'ki_control_spend', 'ki_control_target'].flatMap(key => [key, `${key}-label`])]);
const attribute = (tag, name) => tag.match(new RegExp(`\\b${name}="([^"]*)"`))?.[1];

test('every persisted setting has exactly one field; every literal controller target exists', () => {
  const fields = tags.filter(tag => /\bdata-setting(?:[\s=>])/.test(tag)).map(tag => attribute(tag, 'id'));
  assert.deepEqual(fields.sort(), Object.keys(DEFAULTS).sort());
  const ids = tags.map(tag => attribute(tag, 'id')).filter(Boolean);
  assert.equal(new Set(ids).size, ids.length, 'duplicate element IDs');
  for (const [, id] of read('./main.js').matchAll(/\$\('([^']+)'\)/g)) {
    assert.ok(ids.includes(id), `missing controller target: ${id}`);
  }
});

test('Discord secrets use an empty password input outside persisted settings', () => {
  const password = tags.find(tag => attribute(tag, 'id') === 'webhook-url');
  assert.equal(attribute(password, 'type'), 'password');
  assert.equal(attribute(password, 'value'), undefined);
  assert.ok(!password.includes('data-setting'));
  for (const id of ['webhook-save', 'webhook-enabled', 'webhook-progress', 'webhook-status', 'webhook-test', 'webhook-clear']) {
    assert.ok(tags.some(tag => attribute(tag, 'id') === id), `missing ${id}`);
  }
});

test('theme choices match validation and the backend field contract stays intact', () => {
  const themes = tags.filter(tag => tag.includes('data-theme-choice')).map(tag => attribute(tag, 'data-theme-choice'));
  assert.deepEqual(themes.sort(), ['dark', 'aero', 'light', 'system'].sort());
  const backend = read('../python/settings.py').split('CORE_KEYS')[0];
  const backendFields = [...backend.matchAll(/"([a-z_]+)"\s*:/g)].map(match => match[1]);
  assert.deepEqual(backendFields.sort(), Object.keys(DEFAULTS).sort());
});

test('assets are local and the logo has no animated sheen', () => {
  for (const tag of tags.filter(tag => /^<(script|link|img)\b/.test(tag))) {
    const url = attribute(tag, 'src') || attribute(tag, 'href') || '';
    assert.ok(!/^https?:|^\/\//.test(url), 'remote asset');
  }
  assert.ok(!read('./assets/fonts.css').includes('https://'));
  assert.match(read('./styles.css'), /\.brand-mark,\.sidebar-brand:hover \.brand-mark\{animation:none;transition:none;transform:none\}/);
});


test('top navigation keeps five real routes and both live skin controls', () => {
  assert.ok(!html.includes('<aside'));
  assert.match(html, /<header class="navigation-header">/);
  const links = tags.filter(tag => tag.includes('class="dock-key"'));
  assert.deepEqual(links.map(tag => attribute(tag, 'href')), ['#run', '#settings', '#window', '#tools', '#stats']);
  assert.deepEqual(links.map(tag => attribute(tag, 'aria-label')), ['Run', 'Settings', 'Window', 'Tools', 'Stats']);
  assert.deepEqual(tags.filter(tag => tag.includes('data-nav-choice')).map(tag => attribute(tag, 'data-nav-choice')), ['keycap', 'dial']);
  assert.match(html, /data-depends="nav_style" data-depends-value="dial"/);
});

test('Run actions and unrelated content retain their controller IDs', () => {
  assert.match(html, /id="run-button"><span id="run-button-label">Start run<\/span><span aria-hidden="true" class="kbd run-kbd">F6<\/span>/);
  assert.match(html, /aria-label="Stop" class="btn-stop" disabled="" id="stop-button"/);
  assert.match(html, /class="stop-dot"/);
  assert.match(html, /class="run-panel"/);
  const original = read('../_backup_nav2/src/index.html');
  const originalIds = [...original.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
  const currentIds = tags.map(tag => attribute(tag, 'id')).filter(Boolean);
  for (const id of originalIds.filter(id => !REMOVED.has(id))) assert.ok(currentIds.includes(id), `original ID retained: ${id}`);
  for (const title of ['Troubleshooting', 'Run stats']) assert.ok(html.includes(title));
  assert.match(read('./steel.css'), /\.xyn-app\[data-theme=dark\]\[data-ui=classic\]/);
});

test('training controls have the required bounds, labels and dependencies', () => {
  assert.match(html, /for="gravity_mode" id="gravity_mode-label">Gravity/);
  assert.ok(html.includes('Max unlocked'));
  assert.ok(html.includes('Higher gravity gives much more EXP but drains HP. Senzu beans keep you alive.'));
  assert.match(html, /data-depends="gravity_mode" data-depends-value="custom" data-hide-disabled="" hidden=""/);
  assert.match(html, /data-depends="auto_senzu"/);
  assert.match(html, /data-range-for="senzu_at"/);
  for (const [id, min, max] of [['gravity', '1', '500'], ['senzu_at', '10', '90'], ['stop_after_minutes', '0', '10080'], ['stop_at_level', '0', '100000']]) {
    const target = tags.find(tag => attribute(tag, 'id') === id);
    for (const [key, value] of Object.entries({ type: 'number', min, max, step: '1' })) {
      assert.equal(attribute(target, key), value, `${id}: ${key}`);
    }
  }
  for (const id of ['attack', 'movement', 'auto_buy', 'stop_enabled', 'stop_at_seconds', 'ki_control_spend']) {
    assert.ok(!tags.some(tag => attribute(tag, 'id') === id), `removed setting: ${id}`);
  }
});

test('promo Run has the Level card and preserves diagnostics and extra window controls', () => {
  const run = html.slice(html.indexOf('id="run"'), html.indexOf('id="settings"'));
  const window = html.slice(html.indexOf('id="window"'), html.indexOf('id="tools"'));
  assert.ok(run.includes('id="run-level"'));
  assert.ok(run.includes('id="level-gauge"'));
  assert.ok(run.includes('id="run-time-state"'));
  assert.ok(run.includes('data-open-setting="gravity_mode"'));
  assert.ok(run.includes('id="run-points"'));
  assert.ok(!/GC time left|Ults fired|Ki blasts/.test(run));
  assert.ok(!run.includes('Setup checklist'));
  assert.ok(run.includes('id="status"'), 'Run shows the latest status line');
  for (const id of ['set-window', 'game-size', 'window-hint']) assert.ok(window.includes(`id="${id}"`), `Window retains ${id}`);
  const titlebar = html.slice(html.indexOf('class="titlebar-controls"'), html.indexOf('class="app-shell"'));
  for (const id of ['compact', 'pin-toggle']) assert.ok(titlebar.includes(`id="${id}"`), `title bar has ${id}`);
  assert.match(read('./main.js'), /'run', 'settings', 'window', 'tools', 'stats'/);
  assert.ok(html.includes('id="session-stats"'));
  assert.ok(html.includes('data-open-setting="stop_after_minutes"'));
  assert.ok(html.includes('data-open-setting="stop_at_level"'));
  const before = read('../_backup_promo_ui/src/index.html');
  for (const [, id] of [...before.matchAll(/\bid="([^"]+)"/g)].filter(([, id]) => !REMOVED.has(id))) assert.ok(tags.some(tag => attribute(tag, 'id') === id), `pre-promo ID retained: ${id}`);
});

test('every element the runtime scripts look up by id or class exists', () => {
  const ids = new Set(tags.map(tag => attribute(tag, 'id')).filter(Boolean));
  const classes = new Set(tags.flatMap(tag => (attribute(tag, 'class') || '').split(/\s+/)).filter(Boolean));
  for (const file of ['main.js', 'motion.js', 'navigation.js', 'controls.js', 'telemetry-motion.js', 'window-controls.js']) {
    const code = read(`./${file}`);
    for (const [, id] of code.matchAll(/getElementById\('([^']+)'\)/g)) assert.ok(ids.has(id), `${file}: missing #${id}`);
    for (const [, name] of code.matchAll(/document\.querySelector\('\.([\w-]+)'\)/g)) assert.ok(classes.has(name), `${file}: missing .${name}`);
  }
});
