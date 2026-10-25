<p align="center">
  <img src="app/src-tauri/icons/128x128@2x.png" width="96" alt="XynLevel logo">
</p>

<h1 align="center">XynLevel</h1>

<p align="center">
  Levels your <b>Dragon Generations</b> (DG, formerly Dragon Ball Online Generations / DBOG) character in the Gravity Chamber bot room while you're away.<br>
  Free, open source, Windows 10/11.
</p>

<p align="center">
  <a href="https://github.com/lowkxyn/xynlevel/releases/latest"><b>Download the latest release</b></a>
</p>

https://github.com/user-attachments/assets/cd2ed2d1-334d-4f0c-bed8-a4577b30f484

---

## What it does

You stand in the Gravity Chamber bot room, press **F6**, and XynLevel plays the room for you until the
chamber timer reaches the time you chose.

- **Charges and fires your ult.** It holds Shift to charge 4x Kamehameha, waits until the hotbar slot
  lights up, fires, and repeats. It reads the Ki bar on screen, so it keeps up with any race or Ki
  Control level instead of guessing timings.
- **Ki blasts before you have an ult.** It locks on, fires Ki blasts and switches targets with the scroll
  wheel. Auto mode uses the ult when there is one and blasts otherwise.
- **Respawns on its own.** When you die it clicks Respawn and carries on. It also waits out loading
  screens.
- **Sets gravity** at the start of each run (100G by default).
- **Can buy and equip 4x Kamehameha** while you're dead, once you're level 135 with 5,000 Zeni. It checks
  your hotbar and owned moves first and only goes to the shop if you don't have it.
- **Can spend skill points on Ki Control** while dead, up to a target you set.
- **Stops on your timer,** then can close itself or shut down the PC (with a 30-second countdown you can
  cancel).
- **Sets the Roblox window up for you:** fullscreen on a 1080p screen, a centred 1920 x 1080 window on a
  bigger one.
- **Shows live stats:** time left, run time, level and XP, ults, deaths, levels per hour, time to the next
  level and more.
- **Optional Discord reports** through your own webhook.

<p align="center">
  <img src="docs/app-run.png" width="49%" alt="Run page">
  <img src="docs/app-stats.png" width="49%" alt="Stats page">
</p>

## Install

1. Download **`XynLevel_1.0.0_setup.exe`** from the
   [latest release](https://github.com/lowkxyn/xynlevel/releases/latest).
2. Run it and click **Install**. It installs for your Windows account only (to
   `%LOCALAPPDATA%\XynLevel`), so it doesn't need admin rights.

**"Windows protected your PC"?** XynLevel isn't code-signed (signing certificates cost money each year),
so Windows SmartScreen doesn't recognise it yet. Click **More info**, then **Run anyway**. The full source
is in this repo, and every release is built from it. If your antivirus flags it, that's usually because
the bot is a packaged Python program that sends key presses. You can build it yourself from source
(see below) if you'd rather.

## Quick start

1. Open Roblox, join DG and go into the **Gravity Chamber bot room**. Alive or dead is fine.
2. Open XynLevel and look through **Settings**. The defaults work for most people.
3. Click into Roblox so it's the active window, then press **F6**. Press **F6** again to stop.

Keep Roblox as the active window while it runs. If you click away, the run pauses and carries on when
you come back. F6 only starts a run while Roblox is the active window, so pressing it in another app
won't start anything. It stops a run from anywhere.

## Requirements

| | |
| --- | --- |
| Windows | 10 or 11 (64-bit) |
| Display | 1920 x 1080 or larger |
| Roblox | The normal Roblox desktop app |
| Language pack | The English Windows OCR pack, for level and XP readings. Without it the run still works, the level tiles just stay empty. |

The bot reads the screen at exactly 1920 x 1080. You don't have to set that up yourself: every run puts
Roblox in fullscreen on a 1080p display, or in a centred 1920 x 1080 window on a bigger one. The
**Window** page shows the current size and has a **Set window** button if you want to do it before a run.

## Settings

Everything saves as you change it and applies to your next run.

<p align="center"><img src="docs/app-settings.png" width="70%" alt="Settings page"></p>

### Attack

| Setting | Default | What it does |
| --- | --- | --- |
| Attack mode | Auto | **Auto** uses your ult when the slot has one, otherwise Ki blasts. **Blasts** only uses Ki blasts. **Ult** only uses the ult. |
| Ult slot | 7 | Which hotbar slot holds your ult (7 or 8). Use a move that hits the whole room, like 4x Kamehameha. |
| Blast interval | 0.4 s | Time between Ki blasts. |
| Scroll interval | 1.0 s | Time between target switches while blasting. |
| Jump when firing ults | Off | Runs, hops and fires in the air, then lands and charges again. |
| Aim ults at the ceiling | On | Each life, zooms out and tilts the camera up before charging, so the ult hits more bots. |

### Movement (Ki blasts only)

| Setting | Default | What it does |
| --- | --- | --- |
| Movement | Circle | Off, W, W+A, W+D or Circle while blasting. Charging 4x Kamehameha always stands still. |
| Sprint | On | Holds Shift while moving. |
| Jump while blasting | On | Double hops every 1.2 to 2 s while firing. |
| Re-lock now and then | On | Takes lock-on again every 8 to 15 s if switching targets stalls. |

### Chamber

| Setting | Default | What it does |
| --- | --- | --- |
| Auto gravity | On | Sets gravity once at the start of each run. |
| Gravity | 100G | The gravity it sets. |
| Hide chat | On | Keeps chat from covering the HP and Ki bars. |
| Auto-buy 4x Kamehameha | Off | While dead, buys and equips it. Needs level 135 and 5,000 Zeni. Checks your hotbar and owned moves first. |
| Replace slot move | Off | Lets it put 4x Kamehameha over another move in your ult slot. |
| Put the old move back at the end | On | Re-equips the replaced move when the run ends. |
| Spend skill points on Ki Control | Off | While dead, spends points on Ki Control until it reaches the target. **Spent points are permanent.** |
| Ki Control output target | 300 | The Ki Control value to stop at. |

### Stopping

| Setting | Default | What it does |
| --- | --- | --- |
| Stop at time left | Off | Ends the run when the chamber timer reaches your threshold. |
| Threshold | 60 s | The time left to stop at. |
| After reaching the threshold | Do nothing | Or **Close XynLevel**, or **Shut down PC**. There's a 30-second countdown you can cancel, and stopping by hand or an error skips it. Windows shutdown is never forced. |

### Appearance and notifications

Themes (Steel, Glass, Daylight, Follow Windows), accent colours, keycap or dial navigation, reduce
motion, and a pin button in the title bar to keep XynLevel on top. **Desktop notifications** shows a
Windows pop-up when a run ends, and **Sound when the run ends** plays a sound at the stop time.

## Discord reports (optional)

In **Settings > Notifications**, paste a Discord webhook URL and click **Save**. XynLevel can then post:

- when a run finishes, is stopped, or needs attention (for example Roblox disconnected)
- progress updates every 5 to 60 minutes while it runs, if you turn them on

Reports only contain run counters: run time, level, deaths, ults, Ki blasts and time left. The webhook
is encrypted for your Windows account, never shown again, and only ever sent to `discord.com`. **Send
test** checks it works, and **Remove** deletes it.

## Stats

The **Run** page shows the chamber time left, run time, level and XP, ults fired, deaths and Ki blasts.
The **Stats** page adds levels gained, levels per hour, time to the next level, ults per life, average
life length and time paused.

## Privacy and safety

- **Everything stays on your PC.** XynLevel has no account, no telemetry and no update server. The only
  thing it ever sends anywhere is a Discord webhook report, if you set one up.
- **It works like a person at the keyboard.** It reads the screen and presses keys and clicks. It doesn't
  read or change Roblox's memory or files, and it doesn't inject anything into the game.
- **Bug reports are redacted.** Tools > Bug report shows you exactly what will be saved before it saves
  a ZIP: settings, the game-area size, the run result and events with paths, emails, IPs and links
  removed. No screenshots.
- **The app's local connection is locked down.** The window talks to the bot over a localhost port that
  needs a fresh random token each launch and rejects web pages.
- **Use it at your own risk.** Automation can be against a game's rules. You're responsible for how you
  use it.

Settings, logs and saved bug reports live in `%LOCALAPPDATA%\com.xynlevel.app` (**Tools > Open app
data** opens it).

## Troubleshooting

| Problem | Fix |
| --- | --- |
| F6 does nothing | Click into Roblox first. F6 only starts a run while Roblox is the active window. |
| "Roblox not found" | Open the Roblox desktop app and join the game before starting. |
| Window size is wrong | Click **Set window** on the Window page, or just start a run. On a display smaller than 1920 x 1080 it can't work. |
| It pauses | Roblox lost focus. Click back into Roblox and it carries on. |
| No ults fire | Check the ult slot (7 or 8) in Settings and that the move is on that slot. Auto falls back to Ki blasts. |
| Level shows "--" | Install the English Windows OCR language pack (Settings > Time & language > Language). The run works without it. |
| Keys seem stuck after a crash | Tap Shift, W, A and D. XynLevel releases them when it closes, even if the bot stops responding. |

## Reporting a bug

Open an [issue](https://github.com/lowkxyn/xynlevel/issues) and attach a bug report from **Tools > Bug
report**. Say what you expected, what happened, your race and level, and your display size.

## Uninstall

Windows Settings > Apps > Installed apps > **XynLevel** > Uninstall. To remove your settings and logs
too, delete `%LOCALAPPDATA%\com.xynlevel.app`.

## Build from source

Needs Python 3.11+, [Bun](https://bun.sh), Rust (MSVC) and 7-Zip.

```powershell
py -m pip install -r app/python/requirements.txt
cd app
bun install
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_release.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_custom_installer.ps1
```

The setup file lands in `app/dist/`. The release script also scans everything it ships, including inside
the installer, and refuses the build if it finds your Windows username, computer name, or anything you
list in the `XYNLEVEL_PRIVATE_WORDS` environment variable (comma-separated).

Tests: `py -m pytest tests app/tests` and `cd app && bun test src/`. Most bot tests replay real game
screenshots, which aren't published, so those test files are skipped on a fresh clone.

### Layout

| Path | What's there |
| --- | --- |
| `gc_*.py`, `window.py` | The bot: screen reading, charging, menus, aim, window setup |
| `assets/` | Digit and menu templates the bot matches against |
| `app/src/` | The app's UI (plain JavaScript) |
| `app/python/` | The local bridge between the UI and the bot |
| `app/src-tauri/` | The Tauri (Rust) app window |
| `app/installer/` | The themed installer |
| `tests/`, `app/tests/` | Tests |

## Licence

[MIT](LICENSE). Made by Xyn.
