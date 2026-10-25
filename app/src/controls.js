// Native fields remain the settings contract; buttons are accessible views of them.
export function setupControls() {
  for (const select of document.querySelectorAll('select[data-segmented]')) {
    const group = document.createElement('div');
    group.className = 'segmented';
    group.setAttribute('role', 'group');
    group.setAttribute('aria-labelledby', `${select.id}-label`);
    group.dataset.for = select.id;
    group.style.setProperty('--seg-count', select.options.length);
    for (const option of select.options) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = option.textContent;
      button.dataset.value = option.value;
      button.addEventListener('click', () => setValue(select, option.value));
      group.append(button);
    }
    select.hidden = true;
    select.after(group);
  }
  for (const slider of document.querySelectorAll('[data-range-for]')) {
    const input = document.getElementById(slider.dataset.rangeFor);
    // Gravity is itself the native settings field; interval sliders proxy numbers.
    if (input === slider) {
      slider.addEventListener('input', syncControls);
      continue;
    }
    slider.addEventListener('input', () => {
      input.value = slider.value;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      syncControls();
    });
    slider.addEventListener('change', () => input.dispatchEvent(new Event('change', { bubbles: true })));
  }
  for (const button of document.querySelectorAll('[data-theme-choice], [data-accent-choice], [data-nav-choice]')) {
    button.addEventListener('click', () => {
      const key = button.dataset.navChoice ? 'nav_style' : button.dataset.themeChoice ? 'theme' : 'accent';
      setValue(document.getElementById(key), button.dataset.navChoice || button.dataset.themeChoice || button.dataset.accentChoice);
    });
  }
  for (const button of document.querySelectorAll('[data-section]')) {
    button.addEventListener('click', () => {
      const section = document.getElementById(`section-${button.dataset.section}`);
      const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches || document.getElementById('reduced_motion').checked;
      section.scrollIntoView({ behavior: reduced ? 'instant' : 'smooth', block: 'start' });
      section.focus({ preventScroll: true });
    });
  }
}

function setValue(input, value) {
  input.value = value;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
  syncControls();
}

export function syncControls() {
  for (const group of document.querySelectorAll('.segmented')) {
    const input = document.getElementById(group.dataset.for);
    const buttons = [...group.children];
    group.style.setProperty('--seg-index', Math.max(0, buttons.findIndex(button => button.dataset.value === input.value)));
    for (const button of buttons) button.setAttribute('aria-pressed', String(button.dataset.value === input.value));
  }
  for (const slider of document.querySelectorAll('[data-range-for]')) {
    slider.value = document.getElementById(slider.dataset.rangeFor).value;
    slider.style.setProperty('--pct', `${(Number(slider.value) - Number(slider.min)) / (Number(slider.max) - Number(slider.min)) * 100}%`);
  }
  document.getElementById('gravity-value').textContent = `${document.getElementById('gravity').value}G`;
  for (const row of document.querySelectorAll('[data-depends]')) {
    const parent = document.getElementById(row.dataset.depends);
    // Nested rows: a parent switched off by its own parent counts as off.
    const enabled = !parent.disabled && (row.dataset.dependsValue ? parent.value === row.dataset.dependsValue : parent.type === 'checkbox' ? parent.checked : parent.value !== 'off');
    row.classList.toggle('is-disabled', !enabled);
    for (const control of row.querySelectorAll('input,select,button')) control.disabled = !enabled;
  }
  document.getElementById('after-row').classList.toggle('shutdown-warning', document.getElementById('after_run').value === 'shutdown');
  for (const button of document.querySelectorAll('[data-theme-choice]')) button.setAttribute('aria-pressed', String(button.dataset.themeChoice === document.getElementById('theme').value));
  for (const button of document.querySelectorAll('[data-accent-choice]')) button.setAttribute('aria-pressed', String(button.dataset.accentChoice === document.getElementById('accent').value.toLowerCase()));
  for (const button of document.querySelectorAll('[data-nav-choice]')) button.setAttribute('aria-pressed', String(button.dataset.navChoice === document.getElementById('nav_style').value));
  document.getElementById('accent-value').textContent = document.getElementById('accent').value.toUpperCase();
}
