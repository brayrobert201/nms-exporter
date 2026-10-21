# pyMHF + NMS.py under Proton: trial notes (2026-10-21)

Question: how far does pyMHF / NMS.py get on this Linux host, inside the NMS
Proton prefix, without starting or injecting into the game?

Answer in one line: **everything up to the injection works.** Windows Python
3.12.10 installs and runs in the game prefix under Proton Experimental's own
wine, `pip install nmspy` pulls every dependency as a prebuilt win_amd64 wheel
(no compiler needed), all imports succeed, `pymhf --help` runs, and NMS.py
181442.1 targets exactly the installed NMS.exe (FileVersion 181442). The live
injection is untested by design; a launcher (`scripts/nms-hook`) is ready.

## Environment

| | |
|---|---|
| Game | No Man's Sky, Steam app 275850, Steam buildid 25800958 (appmanifest) |
| NMS.exe | 88,593,480 bytes, mtime 2026-10-08, sha256 `21cdfd6f...ba55052`, PE FileVersion/ProductVersion **181442** |
| Prefix | `~/.local/share/Steam/steamapps/compatdata/275850/pfx`, `version` = 11.0-100, created by Proton - Experimental (config_info) |
| Proton | `steamapps/common/Proton - Experimental`, version file `experimental-11.0-20261014-x86_64` |
| Wine reports | Windows 10.0.19045, "using server-side synchronization" (ntsync) |
| Game running? | No, throughout. Nothing was injected. Saves not touched. |

## Sources stored (research/sources/web/)

- `2026-10-21-pymhf-readme.md`, `2026-10-21-nmspy-readme.md` (already stored earlier today; reused)
- `2026-10-21-pymhf-pypi-json.md`, `2026-10-21-nmspy-pypi-json.md` - versions, deps
- `2026-10-21-pymhf-main-py.md` - launch/attach logic (source of the config analysis below)
- `2026-10-21-nmspy-pymhf-toml.md` - NMS.py's default pyMHF config
- `2026-10-21-pymhf-docs-settings.md` - pyMHF config key reference
- `2026-10-21-pymhf-changelog.md` - 0.2.5 changelog (the stored text is the docs site chrome plus changelog; the sdist's `docs/docs/change_log.rst` was read too)
- `2026-10-21-nmspy-gh-releases.md` (empty: the repo has no GitHub releases), `2026-10-21-nmspy-gh-commits.md`
- `2026-10-21-pymhf-issues-linux.md` (0 hits), `2026-10-21-nmspy-issues-linux.md` (1 hit, #45)
- `2026-10-21-python-3-12-10-release.md` - first stored as gzip bytes (research-fetch did not decompress); fixed in research-fetch and re-stored as text the same day.
  did not decompress python.org's gzip response. Tool bug worth fixing (check
  `Content-Encoding` and gunzip). The page was re-read with `curl --compressed`.

## Step 1 - what the docs and source say

Versions on PyPI today: **nmspy 181442.1** (uploaded 2026-10-21 00:25), depends on
`pymhf[gui,http_api]==0.2.5` (uploaded 2026-10-21 00:11). pymhf deps: cyminhook>=0.1.4,
psutil~=5.9.5, pymem[speed]~=1.14.0, keyboard, pywin32, questionary, pywinctl,
packaging, tomlkit, pefile, iced_x86, typing_extensions, pyrun-injected==0.2.1;
extras dearpygui (gui), uvicorn+fastapi (http_api). requires-python >=3.10,<4.

Version-support: nmspy's version number is the **NMS.exe build number**
(Hello Games' SVN revision, stored in the exe's PE FileVersion and next to an
`svn.hellogames.dev` string). Release history: 170671.6 (Sep 8), 178994.x
(Sep 12-14), 179105.0, 180132.0, 180383.0, 181442.0 (Oct 9), 181442.1 (Oct 21).
The installed NMS.exe has FileVersion **181442** (exe mtime Oct 8, nmspy 181442.0
followed a day later). So the current NMS.py is built for exactly this binary.
No GitHub releases or release notes exist; the commit log for 181442.1 is
"Final set of updated for 181442.1" plus new function patterns.

Offline cross-check (no game run): `/tmp/pymhf-trial/scripts/scan_patterns.py`
pulls every byte signature from nmspy's `nmspy/data/types.py` (parsed with
`ast`, never executed) and `tools/data.json`, and searches NMS.exe's `.text`:

```
patterns: 452  unique: 427  multiple: 5  not found: 20
```

14 of the 20 misses are already listed in upstream's own `broken_patterns.txt`
(renderer/geometry internals: cEgRenderer::DrawMeshes, cEgModelNode::Animate,
nvgArc, ...). The others: cGcPlayerState::CanRepairTechnology,
cGcPlayerWeapon::Update, cGcBaseBuildingManager::AddObjectMarker,
cTkGraphicsAPI::createVertexBuffer, cEgRendererBase::CreateVertexBuffer,
cEgRenderer::ExecutePipelineCommand. pyMHF resolves patterns only for
functions a mod actually hooks, so unused misses are harmless. 94% unique
match is strong evidence the definitions fit this exe. **Verdict: supported.**

How pymhf finds the target (pymhf/main.py `run_module`, `get_process_when_ready`):

- Config = nmspy's `pymhf.toml` (`exe = "NMS.exe"`, `steam_gameid = 275850`,
  `start_paused = true`, logs and mod saves in `{EXE_DIR}`), updated key-by-key by
  `%APPDATA%\pymhf\nmspy\pymhf.local.toml` `[pymhf.local_config]`.
- `start_exe` (default true): first tries `pymem.Pymem("NMS.exe")`; if running,
  **attaches**. Otherwise with steam_gameid it looks for `steam.exe` in the
  (Wine) process list, raises "Steam not running!" if absent, else
  `webbrowser.open("steam://rungameid/275850")` and polls for NMS.exe. Under Proton
  that would go through winebrowser/xdg-open to native Steam: unpredictable, so avoided.
- `start_exe = false`: attach only, `pymem.Pymem(exe)`; raises ProcessNotFound if absent.
  On normal exit in attach mode pymhf kills only its log window, not the game.
  But the `close_callback` (injected side finished or raised) does
  `os.kill(game_pid, SIGTERM)` regardless of mode: an injected-side crash ends the game.
- `pid` key also supported (attach to a pid) when `exe` unset.
- First run without a local config pops a tkinter folder chooser for the mod
  folder; a `.config_in_progress` file re-triggers it. Pre-writing the local
  config skips this.
- Log window: `cmd.exe /c "start "NMS.py" python log_terminal.py <log_dir>"` -
  needs `python` on the Wine PATH (we installed with PrependPath=0, so the
  launcher sets `WINEPATH`).
- Injection: pyrun-injected `dllinject.pyRunner(pymem handle)` (remote-thread
  LoadLibrary of python312.dll into NMS.exe), injected REPL talks back over TCP
  127.0.0.1:6770; hooks via cyminhook (MinHook).
- `pymhf cmd check nmspy` is registered in nmspy's pyproject but points at a
  module `check` that does not exist in the package: not usable.

Linux/Wine/Proton: no pyMHF issues mention it (search 0 hits). NMS.py #45 (open,
2026-09-05) asks to swap pymem for PyMemoryEditor in `tools/extract.py` so the
extraction tool can run against NMS under Proton/Steam Deck natively - i.e. nobody
reports the Wine-prefix route either way. Package classifiers say
"Environment :: Win32 (MS Windows)"; README says use python.org Python, 3.14
unsupported (though the 0.2.5 changelog claims 3.14 now works via pyrun-injected 0.2.1).

## Step 2 - running Windows programs in the prefix

Proton's wine works directly from the host, no `proton run` wrapper needed:

```
WINEPREFIX=~/.local/share/Steam/steamapps/compatdata/275850/pfx WINEDEBUG=-all \
WINEDLLOVERRIDES=winemenubuilder.exe=d \
"~/.local/share/Steam/steamapps/common/Proton - Experimental/files/bin/wine" cmd /c ver
-> wineserver: using server-side synchronization.
-> Microsoft Windows 10.0.19045        (1.3 s, rc 0)
```

(`wineserver -k` was run afterwards only while the game was not running. The
launcher never does this.)

## Step 3 - Windows Python

- Downloaded `https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe`
  to `/tmp/pymhf-trial/dl-python/` - 26,964,224 bytes, sha256
  `67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb`, md5
  `5eddb0b6f12c852725de071ae681dde4`. 3.12.10 is the last 3.12 with a Windows
  installer (later 3.12.x are source-only security releases). python.org no
  longer prints MD5s on the page (sigstore only); size matches the listed 25.7 MB.
  Signature not verified (no sigstore client here).
- Installed:
  ```
  wine python-3.12.10-amd64.exe /quiet InstallAllUsers=0 TargetDir='C:\pymhf\python' \
    PrependPath=0 Include_launcher=0 InstallLauncherAllUsers=0 Include_test=0 \
    Shortcuts=0 AssociateFiles=0 Include_doc=0 /log 'C:\pymhf\python-install.log'
  -> 12.9 s, rc 0, log "Exit code: 0x0, restarting: No"
  ```
- `wine 'C:\pymhf\python\python.exe' --version` -> `Python 3.12.10`;
  `sys.version` 3.12.10 MSC v.1943 AMD64, platform Windows-10-10.0.19045-SP0,
  ssl OpenSSL 3.0.16, tkinter imports.

## Step 4 - pip install nmspy

```
wine python.exe -m pip install --no-cache-dir --disable-pip-version-check \
  --no-warn-script-location --only-binary=:all: nmspy==181442.1
-> 22 s, rc 0. Every package a wheel (cp312-win_amd64 or abi3/py3-none-any).
```

Installed: nmspy 181442.1, pymhf 0.2.5, cyminhook 0.1.6, pyrun-injected 0.2.1,
pymem 1.14.0 (+regex 2024.9.11), pywin32 312, psutil 5.9.8, keyboard 0.13.5,
pywinctl 0.4.1 (pymonctl 0.92, pywinbox 0.7), questionary 2.1.1 (prompt_toolkit 3.0.53),
dearpygui 2.3.1, iced_x86 1.21.0, pefile 2024.8.26, tomlkit 0.15.2, packaging 26.3,
fastapi 0.156.8, uvicorn 0.54.0, starlette 1.9.0, pydantic 2.14.1 / core 2.50.1,
plus small pure-python deps. `pip check` -> "No broken requirements found."

Import check, **first attempt failed** with stdout piped:

```
python -c "import pymhf, ..."
-> prompt_toolkit.output.win32.NoConsoleScreenBufferError: Found xterm-256color,
   while expecting a Windows console.
```

Cause: `pymhf/__init__.py` builds questionary prompts at import time, and
prompt_toolkit needs a console screen buffer; with stdout a pipe Wine has none.
**Fix: run under a tty** (`script -qec ...`). Then:

```
import pymhf, nmspy, pymem, cyminhook, pyrun_injected, win32api, keyboard,
       pywinctl, dearpygui, iced_x86, psutil, pymhf.main
-> imports ok nmspy 181442.1 pymhf 0.2.5 cyminhook 0.1.6
python -m pymhf --help     -> usage: pymhf [-h] [--version] {run,config,init,cmd} ...
python -m pymhf --version  -> 0.2.5
```

Consequence: the launcher must be run from a real terminal (it refuses otherwise).

Config written (so nothing prompts and nothing auto-launches the game):
`C:\users\steamuser\AppData\Roaming\pymhf\nmspy\pymhf.local.toml`

```toml
[pymhf.local_config]
mod_dir = "C:\\pymhf\\mods"
mod_save_dir = "C:\\pymhf\\mod_saves"
start_exe = false
start_paused = false
[pymhf.local_config.logging]
log_level = "info"
window_name_override = "NMS.py"
log_dir = "C:\\pymhf\\logs"
shown = true
```

Verified by reproducing `load_module`'s merge in the prefix Python: result has
`exe: NMS.exe, start_exe: False, start_paused: False, mod_dir: C:\pymhf\mods,
logging.log_dir: C:\pymhf\logs`, gui shown. (Logs/mod saves would otherwise go in
the game's Binaries folder.)

Not done: a dry `pymhf run nmspy` with the game absent (expected
ProcessNotFound). The permission classifier refused running the downloaded
package's entry point, so the "game not running" path is only checked by the
launcher's own pre-flight.

## Step 5 - launcher

`scripts/nms-hook` (bash, not committed). Pre-flight, in order: Proton wine exists;
prefix exists; `C:\pymhf\python\python.exe`, nmspy and pymhf present; local config
exists and has `start_exe = false`; an `NMS.exe` process (by `/proc/*/comm`) with
`WINEPREFIX` = this prefix; warns if the game's env never mentions our Proton dir
or if the game is in a different pid namespace; copies the game's
`WINE*SYNC*` / `PROTON_NO_*SYNC` vars; requires a tty; then runs prefix Python
(process listing only) to confirm **our wine client can see NMS.exe** - i.e. it
joined the game's wineserver - and aborts if not. Then asks "Have you saved?",
and `exec`s `wine C:\pymhf\python\python.exe -m pymhf run nmspy` with
`WINEPATH=C:\pymhf\python;C:\pymhf\python\Scripts`. `--check` stops before
injecting; `--yes` skips the question.

Tested: `--check` with the game not running -> "No Man's Sky is not running ...", rc 1;
with a fake STEAM_ROOT -> "Windows Python not installed in the prefix ...", rc 1;
unknown flag -> rc 2.

## Open risks for the live test

1. **Wineserver sharing.** The game runs under the Steam Linux Runtime (sniper)
   container. Our host-side wine finds the server by `/tmp/.wine-$UID/server-<dev>-<ino>`
   of the prefix; pressure-vessel shares /tmp and the home dir, so it should join.
   If the container has its own pid namespace, wineserver signals to our threads
   could misfire. `nms-hook --check` detects both (NMS.exe visibility and ns
   comparison). Fallback: launch the game with Steam launch option
   `STEAM_COMPAT_LAUNCHER_SERVICE=proton %command%` and run the same command inside
   the container via `steam-runtime-launch-client --alongside-steam --appid 275850 -- ...`
   (not tried).
2. Proton update between now and the test: wineserver protocol must match. The
   game and nms-hook both use "Proton - Experimental", so fine unless the game
   is switched to another Proton (then set `NMS_HOOK_PROTON`).
3. Injection itself under Wine: remote LoadLibrary + MinHook is ordinary Win32
   and generally works in Wine, but untested here. DearPyGui needs D3D11 (wined3d
   or DXVK in the prefix) for the GUI window.
4. An injected-side exception makes pymhf terminate NMS.exe. Save first.
5. NMS anti-tamper: none known for single-player; never use online.

## Exact next step (first live test)

1. Start No Man's Sky from Steam; load a save; save in-game (and copy
   `pfx/drive_c/users/steamuser/AppData/Roaming/HelloGames/NMS` somewhere).
2. In a terminal: `~/Projects/nms-exporter/scripts/nms-hook --check`.
   Expect `wine side: pymhf 0.2.5 nmspy 181442.1 NMS.exe windows pid <n>`.
3. If that passes: `~/Projects/nms-exporter/scripts/nms-hook`, answer `y`.
   Success = "Python injected", "Found PID", an "Exe hash is" line, the NMS.py log
   window and DearPyGui window appear, and the game keeps running. Logs land in
   `pfx/drive_c/pymhf/logs`. Ctrl+C detaches.
4. If `--check` says NOT VISIBLE: try the launcher-service fallback in risk 1.

## What the trial added (for removal)

All inside `~/.local/share/Steam/steamapps/compatdata/275850/pfx`:

- `drive_c/pymhf/` (94 MB): `python/` (Python 3.12.10 + site-packages), `logs/`,
  `mods/`, `mod_saves/` (empty), `python-install*.log`
- `drive_c/users/steamuser/AppData/Roaming/pymhf/` (contains `nmspy/pymhf.local.toml`)
- Installer bookkeeping: `drive_c/users/steamuser/AppData/Local/Package Cache/`
  (7 dirs, all created by this install, including the cached
  `{b6ce88eb-2ce3-4d91-8efc-425ae1f48caf}/python-3.12.10-amd64.exe`),
  MSI files under `drive_c/windows/Installer/`, and registry keys in `user.reg`:
  `HKCU\Software\Python\PythonCore\3.12` plus "Python 3.12.10 ..." uninstall/product entries.

Clean removal (game not running):

```
P=~/.local/share/Steam/steamapps/compatdata/275850/pfx
W="$HOME/.local/share/Steam/steamapps/common/Proton - Experimental/files/bin/wine"
WINEPREFIX=$P "$W" "$P/drive_c/users/steamuser/AppData/Local/Package Cache/{b6ce88eb-2ce3-4d91-8efc-425ae1f48caf}/python-3.12.10-amd64.exe" /quiet /uninstall
rm -rf "$P/drive_c/pymhf" "$P/drive_c/users/steamuser/AppData/Roaming/pymhf"
```

Outside the prefix: `/tmp/pymhf-trial/` (downloads, unpacked sdists, scan script,
pip log) and `scripts/nms-hook` in this repo.
