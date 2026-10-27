# Guide for AI assistants: install FC 26 for the user

This guide is for AI assistants that write code, for example Claude Code and Codex. It tells you how to build `FC 26.app` on the
user's Mac. The build uses one command: `games/fc26/build.sh`. The user gives the game files and the keys. You run the
build, monitor it and correct the problems.

The text follows ASD-STE100 Simplified Technical English.

## 1. Hard rules

Obey these rules at all times. If the user asks you to break a rule, refuse and tell the user why.

1. Do not download games, keys or firmware. Do not tell the user where to get them.
2. Do not ask the user for files from other persons. The files must come from the user's own console.
3. Do not print, read, copy or show the contents of `prod.keys`. Give the build only its path.
4. Do not put `prod.keys`, an NSP or a key value in an output, a log, a message or a commit.
5. Do not edit `games/fc26/assets/expected-*.json` to make a check pass.
6. Do not edit the scripts, the `Makefile` or `build.sh` to make a check pass.
7. Do not run `scripts/prepare_runtime.py --record`. It writes new values into `expected-*.json`.
8. Do not commit game data, keys, the work folder, `FC 26.app` or other build output.
9. Use only the file paths that the user gives you. Do not search other disks or folders for game files or keys.
10. Do not delete a file or a folder that the build did not make. Ask the user first.

A failed check almost always means that an input file is incorrect. Tell the user which file and which check.

## 2. What the user must give

Ask the user for these five items before you start:

| Item | Option | Notes |
|---|---|---|
| The EA SPORTS FC 26 1.0.0 base game, as an NSP | `--base` | Title ID `01004FF021942000`. A full base game NSP, dumped from the user's console. |
| The 1.89.6e65 update (v1638400), as an NSP | `--update` | A separate update NSP, dumped from the user's console. The build accepts no other version. |
| The console keys file, `prod.keys` | `--keys` | From the user's own Switch. |
| A work folder | `--work` | About 75 GB free. Outside the repository. No spaces in the path. It can be a new folder. |
| The path of the app | `--app` | It must end in `.app`. For example `~/Applications/"FC 26.app"`. |

The user does not need DLC. The two NSP files can be on a different disk from the work folder.

## 3. Checks before the build

Do these checks before you start the build. `build.sh` does them again, but early checks save time.

| Check | Command | Necessary result |
|---|---|---|
| Apple silicon | `uname -m` | `arm64` |
| No Rosetta | `sysctl -n sysctl.proc_translated` | `0` or no value |
| macOS version | `sw_vers -productVersion` | 26 or higher |
| Memory | `sysctl -n hw.memsize` | 8 GB is sufficient. Below 16 GB, the build shows a warning. |
| Disk space | `df -h <parent folder of the work folder>` | About 75 GB free |
| Command Line Tools | `xcode-select -p` | A path, not an error |
| opus and libvpx | `ls /opt/homebrew/opt/opus/lib/libopus.a /opt/homebrew/opt/libvpx/lib/libvpx.a` | Both files exist |
| Python | `python3 -V` | 3.10 or higher |
| Input files | `test -s <path> && echo ok` for each file | `ok`. Do not open or print the files. |

If the Mac does not have a tool, tell the user the install command. Ask the user before you install software:

- Command Line Tools: `xcode-select --install`. This opens a dialog box. The user must accept it.
- Homebrew: the user installs it from [brew.sh](https://brew.sh).
- opus, libvpx and Python: `brew install opus libvpx python`.

The build needs internet access for the Python packages and for SPIRV-Cross. It downloads nothing from the game.

## 4. The build command

Run this command from the repository root. Replace the paths with the paths from the user:

```sh
games/fc26/build.sh \
  --base   "<base game 1.0.0>.nsp" \
  --update "<update 1.89.6e65>.nsp" \
  --keys   "<path>/prod.keys" \
  --work   "<work folder>" \
  --app    "<folder>/FC 26.app"
```

- Use `--python <path to python3>` if the default `python3` is older than 3.10.
- `games/fc26/build.sh --help` shows all the options.
- The build can take 2 to 5 hours. Run it as a background task if your tool has a time limit for commands.
- Write the output to a file, then read the file to monitor the build.
- Each step also writes its own log: `<work>/logs/build/<step>.log`.
- Tell the user that the build takes a long time. Tell the user to keep the Mac connected to power.
- Tell the user to keep the Mac awake. For example, run the build with `caffeinate -i`.

## 5. The steps

The times are approximate values for an M1 Mac with an internal SSD.

| Step | Log | What it does | Time | Space in the work folder |
|---|---|---|---|---|
| 1. Checks | — | Examines the Mac, macOS, the tools, the disk space and the memory. | Seconds | — |
| 2. Python environment | `venv.log`, `pip.log` | Makes `<work>/venv` and installs `games/fc26/requirements.txt`. | 1 to 3 min | ~0.3 GB |
| 3. Update code | `exefs.log` | `extract_exefs.py --update` extracts the ExeFS of the update. | Less than 1 min | Less than 1 GB |
| 4. Game data | `romfs.log` | `merge_update_romfs.py` merges the base RomFS and the update RomFS. It checks each block. | 30 min to 1.5 h | ~38 GB |
| 5. Rewrite | `rewrite.log` | `make rewrite` rewrites the game code (main, sdk) for Apple silicon. It uses 4 to 5 GB of RAM. | 1 to 3 h | A few GB |
| 6. Video module | `nro.log` | `make nro` extracts and rewrites `Engine.Render.Core2.PlatformNvn.nro`. | 5 to 20 min | Less than 1 GB |
| 7a. Checks and tables | `prepare.log` | `make prepare` compares all files with `expected-*.json` and makes the runtime tables. | Minutes | Small |
| 7b. Runtime | `runtime.log` | `make runtime` compiles the runtime. | 10 to 30 min | A few GB |
| 8. App | `app.log` | `make app` builds the launcher, SPIRV-Cross and `FC 26.app`. | 3 to 10 min the first time | Small |

Do not stop the build. If the build stops, it starts the incomplete step again from its start. A restart of step 4 or
step 5 can cost more than one hour.

## 6. How to continue after a stop

The build can stop because of an error, a full disk, a shutdown or Ctrl-C. Do these steps:

1. Read the last lines of the output. Read the end of the step log in `<work>/logs/build/`.
2. Find the error in section 7. Correct the cause.
3. Run the same command again, with the same `--work`.

The build skips the steps that are complete. Do not delete the work folder to start again. Do not use a new work folder.
The build cannot use the complete steps of a different folder.

## 7. Errors and corrections

`build.sh` shows each error in Portuguese (`ERRO:`) and in English (`ERROR:`). The Python scripts stop with a
traceback. The last line of the traceback has the message.

### Errors of the input options

| Message | Correction |
|---|---|
| `--base: file not found: <path>` (also `--update`, `--keys`) | Ask the user for the correct path. Put quotes around a path that has spaces. |
| `--base: the file is empty: <path>` | The file is damaged. The user must dump it again. |
| `--base and --update are the same file.` | Ask the user for the two different files. |
| `--work must not contain spaces, because the Makefile cannot use them` | Use a path with no spaces, for example `~/FC26-work`. |
| `--work: its parent folder does not exist` | Make the parent folder, or use a different path. |
| `--work must be outside the repository, because it will contain game data` | Use a folder outside the repository. |
| `--app must end in .app` | Add `.app` to the end of the path. |
| `--app must be outside the repository` | Use a path outside the repository, for example `~/Applications/"FC 26.app"`. |
| `<app> exists and this build did not make it. Use a different path, or delete it yourself.` | Use a different `--app` path. Do not delete the existing app. The user must decide. |

### Errors of the Mac and the tools

| Message | Correction |
|---|---|
| `you must use an Apple silicon Mac (M1 or newer).` | The build cannot operate on this Mac. Stop and tell the user. |
| `the Terminal runs under Rosetta (Intel). Open the Terminal without Rosetta.` | Tell the user to clear "Open using Rosetta" in the Get Info window of Terminal. |
| `you must have macOS 26 or newer. This Mac has macOS <version>.` | The user must update macOS. Stop the installation. |
| `the Xcode Command Line Tools are not installed.` | Ask the user to run `xcode-select --install` and accept the dialog box. |
| `the '<tool>' command is not installed.` | The same correction: `xcode-select --install`. |
| `/opt/homebrew/opt/<library> not found.` | Install Homebrew, then run `brew install opus libvpx`. |
| `Python 3 not found` or `you must have Python 3.10 or newer with venv.` | Run `brew install python`, or give `--python <path to python3>`. |
| `the Python packages do not load. Read <work>/logs/build/pip.log` | Read `pip.log`. Make sure that the Mac has internet access. Delete `<work>/venv`, then run the build again. |
| `not sufficient disk space: <n> GB free at <path>. The build needs ~<n> GB.` | Ask the user to make disk space free, or use a work folder on a different disk. |
| `No space left on device` in a step log | The same correction. Then run the same command again. |

### Errors of the game files (steps 3 and 4)

| Message (last line of the traceback) | Cause and correction |
|---|---|
| `Expected NCA3 (check prod.keys and the game file)` | The keys do not decrypt the file. The keys can be old or from a different console. The user must dump `prod.keys` again from the same console. |
| `Missing header_key in prod.keys` or `Missing <key name> in prod.keys` | The keys file is old or incomplete. The user must dump `prod.keys` again after a firmware update of the console. |
| `Missing common ticket for rights-managed NCA in the NSP` | The NSP has no ticket. The user must dump the NSP again with its ticket. |
| `Personalized NSP tickets are unsupported; a common ticket is required` | The user must dump the NSP again with a common ticket. |
| `Update belongs to another game` | The `--update` file is not an FC 26 update. Ask for the correct file. |
| `Expected a BKTR update, not a base game` | The `--update` file is a base game. Make sure that `--base` and `--update` are not interchanged. |
| `Expected one update Program NCA; combined packages are unsupported` | The `--update` file contains more than one title. The user must dump the update alone. |
| `Expected FC 26 base game 1.0.0; updates, DLC and other games are unsupported` | The `--base` file is not the FC 26 1.0.0 base game. Ask for the correct file. |
| `Expected one base Program NCA; updates, DLC and other games are unsupported` | The same cause and correction. |
| `Base RomFS is sparse: this script expects a full base game NSP` | The base game NSP is not complete. The user must dump the full base game. |
| `FS header hash mismatch`, `ExeFS hash-table mismatch` or another hash error | The file is damaged. The user must dump it again. |
| `the RomFS step stopped, but index.json does not have status pass.` | Read `romfs.log`. Run the same command again. If the error occurs again, the user must dump the two NSP files again. |

### Errors of make prepare (step 7a)

`make prepare` compares the files with `games/fc26/assets/expected-v1.89.6e65.json`. Each message starts with
`prepare_runtime:`.

| Message | Cause and correction |
|---|---|
| `the ExeFS came from a <n>-byte file, pinned NSP is <n> bytes` | The update is not version 1.89.6e65. Ask the user for the correct update. |
| `ExeFS <name>: <hash> differs from the pinned <hash>` | A different update version or a damaged dump. The user must dump the update again. |
| `main build ID: ... differs from the pinned ...` | The same cause and correction. |
| `RomFS size <n>, pinned <n>` or `RomFS has <n> files, pinned <n>` | The base game or the update is a different version. Ask for the correct files. |
| `RomFS SHA-256 ... does not start with ...` or `RomFS SHA-256: ... differs from the pinned ...` | A different version or a damaged dump. The user must dump the two NSP files again. |
| `rewrite <module>: ... differs from the pinned ...` | The rewrite output is not correct. Delete `<work>/rewritten`, then run the same command again. If the error occurs again, report it to the project. |

Do not edit `expected-*.json` for these errors. Do not run `--record`. The values in the file are correct for the
supported version.

### Other errors

| Message or symptom | Correction |
|---|---|
| `step '<name>' failed (exit <n>). Read the end of <log>.` | Read the end of the log. Find the cause in this section. Then run the same command again. |
| Step 5 stops and `rewrite.log` shows `Killed`, or the Mac becomes very slow | Not sufficient memory. Ask the user to close other apps. Then run the same command again. |
| Step 8 stops at `git clone` of SPIRV-Cross | No internet access. Connect the Mac, then run the same command again. |
| Step 8 stops at the `shasum` test of `totk_xlate` | The file `games/fc26/prebuilt/macos-arm64/totk_xlate` changed. Run `git checkout -- games/fc26/prebuilt`. Do not edit `totk_xlate.sha256`. |
| `scripts/game_config.py gave no values with PY=...` | This occurs only when you run `make` yourself. Give `PY` a full path. In zsh, use `$HOME`, not `~`, after `=`. |
| The app opens and closes immediately | Read the end of `~/Library/Logs/MacNativeGames/fc26.log`. The work folder must be at the same path as during the build. |
| Small stops in the first matches | The game translates new shaders. This is normal. It stops when the shader cache is full. |

If you cannot find the error here, read `games/fc26/build.sh`, `games/fc26/Makefile` and the script that failed. Each
script shows its options with `--help`.

## 8. Where the files are

| What | Where |
|---|---|
| The app | The `--app` path. It is only the launcher. |
| Extracted game data and the runtime | The work folder: `extracted/`, `rewritten/`, `build-update/` |
| Build logs | `<work>/logs/build/<step>.log` |
| Profile and saves | `~/Library/Application Support/MacNativeGames/FC26/profile` |
| Game log | `~/Library/Logs/MacNativeGames/fc26.log` |
| Shader cache | `<work>/build-update/shader-cache/rt-update` |
| App options | The defaults domain `org.macnativegames.fc26` |

`"<app>/Contents/MacOS/FC 26" --dry-run` shows the paths and the options of the app. It does not start the game.

## 9. After the build

Tell the user these items:

1. The path of the app. Double-click the app to start it. An options window opens first.
2. The first start checks the ~38 GB of game data. It takes more time than the next starts.
3. Do not delete or move the work folder. The app reads the game from it.
4. If the user moves the work folder, the user must run the build again with the new `--work`.
5. The app and the work folder contain the game. The user must not share them.
6. The port operates offline only. It does not connect to EA servers and has no online modes.
