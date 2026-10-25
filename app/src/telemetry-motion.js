export const SNAPSHOT_INTERVAL_MS = 500;
const COUNT_DURATION_MS = 220;
const integer = value => value === null ? '--' : Math.round(value).toLocaleString('en-GB');
const known = value => typeof value === 'number' && Number.isFinite(value);

export function sessionReset(previous, snapshot) {
  if (!previous) return true;
  return (!previous.running && snapshot.running)
    || (known(snapshot.stats?.elapsed) && known(previous.stats?.elapsed) && snapshot.stats.elapsed < previous.stats.elapsed)
    || (known(snapshot.stats?.start_level) && known(previous.stats?.start_level) && snapshot.stats.start_level !== previous.stats.start_level);
}

export function createTelemetryMotion(root) {
  const media = matchMedia('(prefers-reduced-motion: reduce)');
  const reduced = () => media.matches || root.classList.contains('reduced-motion');
  const bars = new Map();
  const numbers = new WeakMap();
  const active = new Map();
  let frame = 0;
  let previous;
  let reset = true;
  let levelChanged = false;

  function write(element, entry, value) {
    entry.current = value;
    const text = entry.format(value);
    if (element.textContent !== text) element.textContent = text;
  }
  function tick(now) {
    frame = 0;
    for (const [element, entry] of active) {
      const progress = Math.min(1, (now - entry.started) / COUNT_DURATION_MS);
      write(element, entry, entry.from + (entry.target - entry.from) * (1 - (1 - progress) ** 3));
      if (progress === 1 || !element.isConnected) active.delete(element);
    }
    if (active.size) frame = requestAnimationFrame(tick);
  }
  function snapBar(element, entry) {
    cancelAnimationFrame(entry.frame);
    element.style.transition = 'none';
    element.style.transform = `scaleX(${entry.target})`;
    // Commit the reset for one paint before restoring the transform transition.
    entry.frame = requestAnimationFrame(() => {
      entry.frame = requestAnimationFrame(() => { element.style.transition = ''; entry.frame = 0; });
    });
  }
  function syncMotion() {
    if (!reduced() && !document.hidden) return;
    cancelAnimationFrame(frame);
    frame = 0;
    for (const [element, entry] of active) write(element, entry, entry.target);
    active.clear();
    for (const [element, entry] of bars) snapBar(element, entry);
  }
  media.addEventListener('change', syncMotion);
  document.addEventListener('visibilitychange', syncMotion);

  return {
    syncMotion,
    begin(snapshot) {
      reset = sessionReset(previous, snapshot);
      levelChanged = known(previous?.stats?.level) && known(snapshot.stats?.level) && previous.stats.level !== snapshot.stats.level;
      previous = { running: snapshot.running, stats: { ...snapshot.stats } };
    },
    progress(element, value, { wrap = false, scale = '' } = {}) {
      const target = known(value) ? Math.max(0, Math.min(1, value)) : 0;
      const entry = bars.get(element);
      const jump = !entry || reset || entry.known !== known(value) || entry.scale !== scale
        || (wrap ? levelChanged || target < entry.target : target > entry.target);
      if (entry && entry.target === target && !jump) return;
      const next = { target, known: known(value), scale, frame: 0 };
      cancelAnimationFrame(entry?.frame);
      bars.set(element, next);
      element.dataset.progress = String(target);
      element.style.setProperty('--progress', String(target));
      if (jump || reduced() || document.hidden) snapBar(element, next);
      else {
        element.style.transition = '';
        element.style.transform = `scaleX(${target})`;
      }
    },
    number(element, value, format = integer) {
      const target = known(value) ? value : null;
      let entry = numbers.get(element);
      const hidden = document.hidden || Boolean(element.closest('[hidden]'));
      if (!entry) {
        entry = { target, current: target, format };
        numbers.set(element, entry);
        write(element, entry, target);
        return;
      }
      entry.format = format;
      if (entry.target === target && !reset) {
        if (!active.has(element)) write(element, entry, target);
        return;
      }
      active.delete(element);
      const from = entry.current;
      entry.target = target;
      if (reset || reduced() || hidden || target === null || from === null || target <= from) {
        write(element, entry, target);
        return;
      }
      Object.assign(entry, { from, started: performance.now() });
      active.set(element, entry);
      if (!frame) frame = requestAnimationFrame(tick);
    },
  };
}
