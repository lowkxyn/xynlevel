"""Finding the Roblox window and snapping its game area to 1920x1080."""

import ctypes
import time
import ctypes.wintypes as wt

GAME_WIDTH = 1920
GAME_HEIGHT = 1080
ROBLOX_EXECUTABLES = {"robloxplayerbeta.exe", "windows10universal.exe", "robloxplayer.exe", "roblox.exe"}

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Per-monitor DPI awareness, so every size below is in real screen pixels even
# with Windows display scaling at 125%/150%. Must run before any window exists.
if not user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
    ctypes.windll.shcore.SetProcessDpiAwareness(2)


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]


def _process_exe(hwnd):
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        path = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(len(path))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
            return ""
        return path.value.rsplit("\\", 1)[-1].lower()
    finally:
        kernel32.CloseHandle(handle)


def find_roblox_window():
    """The Roblox game window handle, or None.

    Checks the process name too, so a browser tab titled "Roblox" doesn't match.
    """
    matches = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def check(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, 256)
        if "roblox" in title.value.lower() and _process_exe(hwnd) in ROBLOX_EXECUTABLES:
            matches.append(hwnd)
        return True

    user32.EnumWindows(check, 0)
    # EnumWindows walks Z-order, so the first game-sized match is the Roblox window used last.
    # Small ones are skipped because a Roblox crash or error dialog can sit on top.
    for hwnd in matches:
        width, height = game_area_size(hwnd)
        if width >= 800 and height >= 600:
            return hwnd
    return max(matches, key=lambda h: game_area_size(h)[0] * game_area_size(h)[1], default=None)


def _rects(hwnd):
    window, client = wt.RECT(), wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(window))
    user32.GetClientRect(hwnd, ctypes.byref(client))
    return window, client


def game_area_size(hwnd):
    _, client = _rects(hwnd)
    return client.right, client.bottom


def _monitor(hwnd):
    monitor = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(monitor))
    return monitor.rcMonitor, monitor.rcWork


def _fits_work_area(hwnd):
    _, work = _monitor(hwnd)
    left, top, width, height = game_area_rect(hwnd)
    return left >= work.left and top >= work.top and left + width <= work.right and top + height <= work.bottom


def _press_f11(hwnd):
    import pydirectinput  # sends scan codes, which Roblox reads; plain virtual keys can be missed
    if user32.GetForegroundWindow() != hwnd:
        # Windows only lets a process take the foreground right after a keypress, so tap Alt first.
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)
    pydirectinput.keyDown("f11")
    time.sleep(0.05)
    pydirectinput.keyUp("f11")


def auto_window(hwnd, wait=3.0):
    """Get a 1920x1080 game area the way the display allows. Returns (ok, message).

    A 1080p monitor can't fit a 1920x1080 window plus its title bar, so Roblox goes fullscreen there.
    A bigger monitor gets a centred 1920x1080 window (fullscreen would be the wrong size).
    F11 is Roblox's fullscreen toggle, so it's only pressed when the current mode is measurably wrong.
    """
    screen, _ = _monitor(hwnd)
    screen_size = (screen.right - screen.left, screen.bottom - screen.top)
    target = (GAME_WIDTH, GAME_HEIGHT)

    def toggle(until):
        _press_f11(hwnd)
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            time.sleep(0.15)
            if until():
                return True
        return False

    if screen_size == target:
        if game_area_size(hwnd) == target:
            return True, "Roblox is fullscreen at 1920x1080."
        if user32.IsIconic(hwnd) or user32.IsZoomed(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        if toggle(lambda: game_area_size(hwnd) == target):
            return True, "Roblox switched to fullscreen (1080p display)."
        return False, "Roblox didn't go fullscreen. Press F11 in Roblox, then start again."
    if screen_size[0] < GAME_WIDTH or screen_size[1] < GAME_HEIGHT:
        return False, f"This display is {screen_size[0]}x{screen_size[1]}; XynLevel needs 1920x1080 or bigger."
    # Already the right size and fully on screen: leave it where the player put it.
    if game_area_size(hwnd) == target and _fits_work_area(hwnd):
        return True, "Roblox window is already 1920x1080."
    if game_area_size(hwnd) == screen_size and not toggle(lambda: game_area_size(hwnd) != screen_size):
        return False, "Roblox didn't leave fullscreen. Press F11 in Roblox, then start again."
    return snap_window(hwnd)


def snap_window(hwnd, width=GAME_WIDTH, height=GAME_HEIGHT):
    """Resize the window so its game area is exactly width x height, centred on its monitor.

    Returns (ok, message).
    """
    if user32.IsIconic(hwnd) or user32.IsZoomed(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE

    screen, work = _monitor(hwnd)

    game_w, game_h = game_area_size(hwnd)
    if (game_w, game_h) == (screen.right - screen.left, screen.bottom - screen.top):
        return False, "Roblox is fullscreen. Press F11 in Roblox, then click Set window again."

    # Frame = title bar + borders. Measured, not assumed: it changes with the
    # Windows version and display scale, and a wrong guess shifts every pixel read.
    window, client = _rects(hwnd)
    frame_w = (window.right - window.left) - client.right
    frame_h = (window.bottom - window.top) - client.bottom
    total_w, total_h = width + frame_w, height + frame_h

    work_w, work_h = work.right - work.left, work.bottom - work.top
    if total_w > work_w or total_h > work_h:
        return False, f"Screen too small: needs {total_w}x{total_h}, has {work_w}x{work_h}."

    # Centre in the work area so the taskbar never covers the game.
    x = work.left + (work_w - total_w) // 2
    y = work.top + (work_h - total_h) // 2
    SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
    user32.SetWindowPos(hwnd, 0, x, y, total_w, total_h, SWP_NOZORDER | SWP_NOACTIVATE)

    # Some windows round their size; correct once by whatever is left over.
    got_w, got_h = game_area_size(hwnd)
    if (got_w, got_h) != (width, height):
        total_w += width - got_w
        total_h += height - got_h
        user32.SetWindowPos(hwnd, 0, x, y, total_w, total_h, SWP_NOZORDER | SWP_NOACTIVATE)
        got_w, got_h = game_area_size(hwnd)

    if (got_w, got_h) != (width, height):
        return False, f"Roblox ended up at {got_w}x{got_h} instead of {width}x{height}."
    return True, f"Roblox set to {width}x{height}, centred."


def game_area_rect(hwnd):
    """(left, top, width, height) of the game area on screen, or None if the window is gone."""
    if not user32.IsWindow(hwnd):
        return None
    _, client = _rects(hwnd)
    origin = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    return origin.x, origin.y, client.right, client.bottom
