export function createMotion(root) {
  const media = matchMedia('(prefers-reduced-motion: reduce)');
  const reduced = () => media.matches || root.classList.contains('reduced-motion');
  let previous = null;
  let completedId = 0;
  const effects = new Set();
  const animations = new Set();
  let pageAnimation;
  function track(animation, done = () => {}) {
    animations.add(animation);
    const finish = () => { animations.delete(animation); done(); };
    animation.finished.then(finish, finish);
    return animation;
  }
  function revealPage(page) {
    pageAnimation?.cancel();
    if (reduced() || document.hidden) return;
    pageAnimation = track(page.animate([
      { opacity: .5, transform: 'translateY(6px)' },
      { opacity: 1, transform: 'translateY(0)' },
    ], { duration: 200, easing: 'cubic-bezier(.2,.9,.3,1.1)' }));
  }
  function flash(element, name, duration) {
    if (!element || document.hidden) return;
    element.classList.remove(name);
    void element.offsetWidth;
    element.classList.add(name);
    setTimeout(() => element.classList.remove(name), duration);
  }
  function clearEffects() {
    for (const animation of animations) animation.cancel();
    animations.clear();
    for (const element of effects) element.remove();
    effects.clear();
  }
  function particles(level) {
    if (reduced() || document.hidden) return;
    const layer = document.createElement('div');
    layer.className = level ? 'level-particles' : 'confetti-layer';
    layer.setAttribute('aria-hidden', 'true');
    for (let i = 0; i < (level ? 18 : 30); i++) {
      const bit = document.createElement('i');
      if (level) bit.textContent = '+1';
      bit.style.left = `${Math.random() * 100}%`;
      bit.style.setProperty('--delay', `${Math.random() * .45}s`);
      bit.style.setProperty('--drift', `${(Math.random() - .5) * 130}px`);
      bit.style.setProperty('--spin', `${Math.random() * 600 - 300}deg`);
      bit.style.color = i % 2 ? 'var(--power)' : 'var(--accent)';
      layer.append(bit);
    }
    (level ? document.getElementById('run') : root).append(layer);
    effects.add(layer);
    setTimeout(() => { layer.remove(); effects.delete(layer); }, 2800);
  }
  function update(snapshot, word) {
    if (previous && !document.hidden) {
      if (previous.word !== word) {
        flash(document.getElementById('status'), 'state-enter', 260);
      }
      if (!previous.running && snapshot.running) flash(document.getElementById('run'), 'run-start', 700);
      if (snapshot.stats?.deaths > previous.stats?.deaths) flash(document.querySelector('[data-stat=deaths]'), 'death-pop', 400);
      if (snapshot.stats?.levels > previous.stats?.levels) {
        flash(document.getElementById('level-up'), 'level-visible', reduced() ? 1500 : 2400);
        particles(true);
      }
      if (snapshot.last_run?.completed && snapshot.last_run.id > completedId) {
        completedId = snapshot.last_run.id;
        flash(document.getElementById('run'), 'run-complete', 2700);
        particles(false);
      }
    }
    // Initial/reconnected snapshots describe history, not new events.
    completedId = Math.max(completedId, snapshot.last_run?.id || 0);
    previous = { word, running: snapshot.running, stats: { ...snapshot.stats } };
  }
  document.addEventListener('visibilitychange', () => { if (document.hidden) clearEffects(); });
  media.addEventListener('change', () => { if (reduced()) clearEffects(); });
  return { update, clearEffects, revealPage };
}
