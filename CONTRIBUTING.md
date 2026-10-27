# Contributing

This page tells you how the project works. It also gives the rules for a pull request.

## Legal rules

- Do not commit game content. This includes game code, RomFS files, art, text, audio, translated shaders, keys and saves.
- Do not commit build output. The work folder of `build.sh` and `FC 26.app` stay on your Mac.
- Write your own code. The repository uses the MIT license.
- Do not copy GPL code or code from game mods. You can read them for ideas.
- Third-party code keeps its license. Put its source and its license in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- Do not help a person get keys or game files.

## How the port works

- The game's ARM64 code runs natively on Apple silicon. The build rewrites it one time, before the game starts.
- The runtime loads and relocates the rewritten code. A small host (HLE) answers the Switch system services.
- The NVN layer rebuilds the game's NVN graphics on Metal.
- [AGENTS.md](AGENTS.md) and [games/fc26/README.md](games/fc26/README.md) give the build steps.

## Rules for the code

- Do not add CPU emulation. This includes interpreters, JIT, dynamic binary translation and CPU emulators.
- Do not copy Horizon services, IPC or schedulers from an emulator.
- You can use an emulator outside the port as a reference. For example, compare a picture.
- Repair the platform, not the symptom. Repair a platform bug in the platform layer, not with a patch in game code.
- A game patch must check the original instruction at its address first. If the instruction is different, the patch must stop with an error.
- The build starts from the original game files only. Do not patch a rewritten binary. Do not edit bytes by hand.
- The build checks the input and output hashes in `games/fc26/assets/expected-*.json` and `games/fc26/runtime/game_version.h`.
- When you add a build step, record its inputs and outputs in these checks. Do not add a different mechanism.
- Change the game logic as little as possible. Do not change the state of the player or the world to make a test pass.
- Make each gameplay change a separate option. The user must be able to turn it off.

## Repository layout

- `games/fc26/` holds all the code of the port: runtime, graphics layer, rewriter, scripts, launcher and tests.
- The NVN layer maps NVN functions one by one. It does not contain camera, scene or gameplay decisions.
- Keep game-specific code apart from the NVN layer. Put it behind a switch and write why it is necessary.

## Picture quality and performance

- The picture must be correct before it is fast.
- Missing objects, black blocks, incorrect geometry or changed gameplay are not an acceptable cost for more frames.
- A performance change must not change the picture. Small floating-point differences are acceptable.
- Measure before you optimize. Use Instruments, the Xcode GPU frame capture and the Metal HUD (`MTL_HUD_ENABLED=1`).
- Write your own timer only when these tools cannot show the value. Tell what the timer measures.
- Report the local saving, the added cost and the change of the full frame as three separate values.
- Keep incomplete or faulty experiments off by default.

## Pull requests

- Make one pull request for one topic. Do not add unrelated features, debug code or new formatting.
- Do not change keys, defaults or `expected-*.json` unless this is the topic of the pull request.
- Build the app after your change. If you cannot build it, tell this in the pull request.
- Run the synthetic tests in `games/fc26`: `make test PY=python3`. GitHub Actions runs them too (`.github/workflows/fc26.yml`).
- Tell how you tested your change: build only, or a game played on a Mac. Give the game version and the game mode.
- Tests do not replace a played game.
- Keep diagnostics off by default. Turn them on with an environment variable or an input-file command.
- Write commit messages as `<type>: <description>`. Use one of these types: feat, fix, refactor, docs, test, chore, perf, ci.
