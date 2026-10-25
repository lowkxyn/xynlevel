// Both skins share the real hash links and a single eased dial position.
export function createNavigation(app) {
  const dock = document.getElementById('navigation-dock');
  const links = [...dock.querySelectorAll('a')];
  const pip = dock.querySelector('.dock-pip');
  const rail = dock.querySelector('.dial-rail');
  const motionPreference = matchMedia('(prefers-reduced-motion: reduce)');
  let style = 'keycap';
  let sounds = true;
  let reduced = false;
  let selected = -1;
  let position = 0;
  let frame = 0;
  let lastFrame = 0;
  let lastWheel = -Infinity;
  let lastWheelInput = -Infinity;
  let wheelDelta = 0;
  let settleSound = false;
  let detent = 0;
  let audio;
  let lastTick = -Infinity;
  let spacing = 112;
  const voices = new Set();

  const quiet = () => reduced || motionPreference.matches;
  const clamp = value => Math.max(0, Math.min(links.length - 1, value));

  function stopSounds() {
    for (const source of voices) source.stop();
    voices.clear();
    settleSound = false;
  }

  function unlockSound() {
    if (style !== 'dial' || !sounds) return;
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (!Audio) return;
    try {
      audio ||= new Audio();
      if (audio.state === 'suspended') audio.resume().catch(() => {});
    } catch { /* Navigation still works when an audio device is unavailable. */ }
  }

  // One damped sine "ping" per voice: a high, short one is the crisp metal tick of a watch crown,
  // a lower one gives it body. Noise bursts sounded harsh, so no noise.
  function ping(at, frequency, peak, decay) {
    const osc = audio.createOscillator();
    const gain = audio.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(frequency * (0.97 + Math.random() * 0.06), at);
    gain.gain.setValueAtTime(0.0001, at);
    gain.gain.exponentialRampToValueAtTime(peak, at + 0.0015);
    gain.gain.exponentialRampToValueAtTime(0.0001, at + decay);
    osc.connect(gain).connect(audio.destination);
    voices.add(osc);
    osc.onended = () => { voices.delete(osc); osc.disconnect(); gain.disconnect(); };
    osc.start(at);
    osc.stop(at + decay + 0.01);
  }

  function tick(settled = false) {
    if (style !== 'dial' || !sounds || !audio || audio.state !== 'running' || document.hidden) return;
    const now = audio.currentTime;
    // Drop excess ticks instead of queuing them during rapid wheel input.
    if ((!settled && now - lastTick < 0.045) || voices.size >= 6) return;
    lastTick = now;
    if (settled) {
      // Landing: a softer, lower "tock" with a faint second click, like a bezel seating.
      ping(now, 1900, 0.07, 0.05);
      ping(now, 620, 0.05, 0.07);
      ping(now + 0.035, 2600, 0.025, 0.03);
    } else {
      ping(now, 4200, 0.05, 0.018);
      ping(now, 1350, 0.03, 0.025);
    }
  }

  function paint() {
    if (style === 'keycap') {
      const key = links[Math.max(0, selected)];
      pip.style.left = '0px';
      pip.style.transform = `translateX(${key.offsetLeft + key.offsetWidth / 2 - pip.offsetWidth / 2}px)`;
      return;
    }
    links.forEach((link, i) => {
      const distance = i - position;
      const depth = Math.abs(distance);
      link.style.setProperty('--dial-position', `translate(${distance * spacing}px,${depth * depth * 4}px) scale(${Math.max(0.55, 1 - depth * 0.2)})`);
      link.style.transform = 'var(--dial-position)';
      link.style.opacity = Math.max(0.22, 1 - depth * 0.3);
      link.style.zIndex = String(10 - Math.round(depth));
    });
    rail.style.transform = `translateX(${-position * spacing}px)`;
    pip.style.left = 'calc(50% - 11px)';
    pip.style.transform = `translateX(${(selected - position) * spacing}px)`;
  }

  function animate(now) {
    const elapsed = lastFrame ? Math.min(64, now - lastFrame) : 16;
    lastFrame = now;
    position += (selected - position) * (1 - Math.exp(-elapsed / 32));
    const nextDetent = Math.round(position * 4);
    if (nextDetent !== detent) {
      detent = nextDetent;
      if (settleSound) tick();
    }
    if (Math.abs(selected - position) < 0.002) {
      position = selected;
      frame = 0;
      lastFrame = 0;
      paint();
      if (settleSound) tick(true);
      settleSound = false;
      return;
    }
    paint();
    frame = requestAnimationFrame(animate);
  }

  function snap() {
    cancelAnimationFrame(frame);
    frame = 0;
    lastFrame = 0;
    position = Math.max(0, selected);
    detent = position * 4;
    paint();
    if (settleSound) tick(true);
    settleSound = false;
  }

  function select(page) {
    const index = links.findIndex(link => link.hash === `#${page}`);
    if (index < 0 || index === selected) return;
    const initial = selected < 0;
    selected = index;
    links.forEach((link, i) => {
      if (i === selected) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
      link.tabIndex = i === selected ? 0 : -1;
    });
    if (initial) {
      pip.style.transition = 'none';
      snap();
      requestAnimationFrame(() => requestAnimationFrame(() => { pip.style.transition = ''; }));
    } else if (style !== 'dial' || quiet()) snap();
    else if (!frame) frame = requestAnimationFrame(animate);
  }

  function go(index, focus = false) {
    index = clamp(index);
    if (index !== selected) {
      unlockSound();
      settleSound = style === 'dial' && sounds;
      if (settleSound) tick();
      location.hash = links[index].hash;
      // Update now so rapid inputs build on the latest selection, before hashchange.
      select(links[index].hash.slice(1));
    }
    if (focus) links[index].focus({ preventScroll: true });
  }

  links.forEach((link, i) => {
    link.title = link.getAttribute('aria-label');
    link.addEventListener('click', event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
      event.preventDefault();
      go(i, true);
    });
  });
  dock.addEventListener('keydown', event => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    if (step || event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      go(event.key === 'Home' ? 0 : event.key === 'End' ? links.length - 1 : selected + step, true);
    }
  });
  dock.addEventListener('wheel', event => {
    if (event.ctrlKey) return;
    event.preventDefault();
    const delta = Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? event.deltaY : event.deltaX;
    if (!delta) return;
    const now = performance.now();
    if (now - lastWheelInput > 200 || Math.sign(delta) !== Math.sign(wheelDelta)) wheelDelta = 0;
    lastWheelInput = now;
    wheelDelta += delta * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? dock.clientWidth : 1);
    if (Math.abs(wheelDelta) < 24 || now - lastWheel < 100) return;
    lastWheel = now;
    go(selected + Math.sign(wheelDelta));
    wheelDelta = 0;
  }, { passive: false });
  motionPreference.addEventListener('change', () => { if (quiet()) snap(); });
  new ResizeObserver(() => {
    spacing = Math.min(112, dock.clientWidth / 4.4);
    paint();
  }).observe(dock);
  // Browsers only start audio from a click or key press (a wheel turn doesn't count), so unlock
  // it on the first one anywhere; otherwise scrolling the dial first would stay silent.
  for (const type of ['pointerdown', 'keydown']) document.addEventListener(type, unlockSound, { capture: true });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { stopSounds(); snap(); }
  });

  return {
    select,
    configure(settings) {
      const changed = style !== settings.nav_style;
      style = settings.nav_style;
      sounds = false; // dial ticks muted for now (2026-10-25): they sounded off
      reduced = settings.reduced_motion;
      app.dataset.navStyle = style;
      if (!sounds || style !== 'dial') stopSounds();
      if (changed) {
        for (const link of links) {
          link.style.transform = ''; link.style.opacity = ''; link.style.zIndex = '';
        }
      }
      if (changed || (quiet() && frame)) snap();
    },
  };
}
