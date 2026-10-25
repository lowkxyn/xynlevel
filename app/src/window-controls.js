const interactive = 'button, input, select, textarea, a, [role="button"], [contenteditable]:not([contenteditable="false"]), [data-no-drag]';

// Use the app command, as the default capability doesn't grant startDragging.
export function setupWindowControls(root, send, reportError, windowApi = window.__TAURI__?.window) {
  const allowed = event => event.button === 0 && !event.target.closest(interactive);
  root.addEventListener('mousedown', event => {
    if (!allowed(event) || event.detail > 1 || !event.target.closest('[data-tauri-drag-region]')) return;
    // Don't also dispatch Tauri's attribute-based drag command from this event.
    event.stopPropagation();
    send('drag').catch(reportError);
  });
  root.addEventListener('dblclick', event => {
    if (allowed(event) && event.target.closest('.titlebar')) {
      send('maximize').then(syncMaximized).catch(reportError);
    }
  });

  let currentWindow;
  try { currentWindow = windowApi?.getCurrentWindow(); } catch { /* Optional global API. */ }
  let query = 0;
  async function syncMaximized() {
    if (!currentWindow?.isMaximized) return;
    const request = ++query;
    try {
      const maximized = await currentWindow.isMaximized();
      if (request !== query || typeof maximized !== 'boolean') return;
      const button = root.querySelector('#maximize');
      button.dataset.maximized = String(maximized);
      button.title = button.ariaLabel = maximized ? 'Restore down' : 'Maximize';
      root.classList.toggle('maximized', maximized);
    } catch { /* Never infer native state from a click or the viewport size. */ }
  }
  // Browser resize also covers native snap/restore when the optional API exists.
  window.addEventListener('resize', syncMaximized);
  syncMaximized();
  return { syncMaximized };
}
