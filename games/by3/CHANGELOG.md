# Bayonetta 3 port: work log

A record of how this port is being made, for anyone who continues it or tries the same with another game. Each entry
says what was found, what was done and why, what went wrong on the way, and how it was checked. Newest entries go at
the bottom of [Log](#log); [Status](#status) is kept current.

Conventions: dates are absolute; "verified" means a check with a recorded result, never "it looked right"; commits are
named by hash and subject. Game data, keys and saves are never committed (see the Bayonetta block in `.gitignore`).

## Status

| Stage | Goal | State |
|---|---|---|
| 0 | Feasibility: does the game fit the TotK architecture? | done 2026-10-19 |
| 1 | Code and data out of the dump; code rewritten for Apple silicon | done 2026-10-19 |
| 2 | A runtime target with the TotK-only parts compiled out, booting to `nnMain` | done 2026-10-19 |
| 3 | Follow every unknown service / command / NVN call until the first `nvnQueuePresentTexture` | done 2026-10-19 |
| 4 | A picture, audio (Wwise), input, saves; the 1.2.0 patches (60 fps, 900p) applied to the native code | done 2026-10-19 (playable) |
| 5 | Performance, shaders, packaging as an app | in progress: app and presets done |

## Log

### 2026-10-19: stage 0, feasibility

Inputs: base `01004A4010FEA000` v65536 (13.3 GB NSP), update 1.2.0 `01004A4010FEA800` v131072 (2.2 GB NSP),
`prod.keys` from the same Switch. Community 1.2.0 patches (`.pchtxt`: 60 fps, 900p, LOD, film grain) in `mods/`.

Findings, each read from the dump:

- **The base Program NCA is sparse.** Its sections end past the stored NCA (14.8 GB virtual, 13.3 GB stored); the
  FS headers carry a sparse table (`BKTR`, generation 1). The ExeFS table has 0 entries: the base holds no code at all,
  which is why the base is v65536 rather than v0. All code comes from the update.
- **The update has two Program NCAs**: program 0 (`…A000`, the game, 1.8 GB) and program 1 (`…A001`, 0.4 GB, its own
  main). Only program 0 matters so far; what program 1 is has not been looked into.
- **Same module layout as TotK**: `main`, `sdk`, `subsdk0`, `rtld`, `main.npdm`. SDK 13.3.2 (nnSdk, NVN, movie).
  `main` also links Nintendo's online SDK (NPLN, gRPC, OpenSSL) and Wwise 2021.1 for audio.
- **Graphics are NVN**, not Vulkan or GL. Of the 533 NVN names main loads, 419 are implemented in
  `games/totk/third_party/d2r_gfx/gfx/nvn` and 5 are deliberate no-ops; 109 are not (mostly getters; the ones a renderer
  may really call: indirect draw/dispatch, downsample, fence sync, report value, integer clears). 12 names are not in
  TotK's table at all (`*Deferred` binds, subtile size, ZCull). An unimplemented call aborts with its name, so stage 3
  will list exactly the ones the game uses.
- **The npdm allows 47 services.** The TotK host answers most system calls by replacing SDK functions by mangled name
  (loader relocations → `runtime_override`); real IPC is only `sm:` + `audren:u`. Nothing answers `nifm`, sockets,
  `ssl`, `friends`, `bcat`; anything unknown aborts. The host fails loudly by design, which makes iteration tractable.
- **The patches match this binary**: main's build ID `B47CC79B88B7091EA514B2B725C50AE01C6F00DF` is the one in every
  1.2.0 `.pchtxt`. Since the code runs natively, they can later be applied to it directly.

Where TotK is hard-coded (survey of `games/totk`, file:line evidence in the session): title ID (`services.c`,
`fs_host.c`, `extract_exefs.py`, Makefile), guest code addresses (`game_version.h` `GAME_ADDR` maps, `game_patches*.c`,
`world_survey.c`, a crash workaround in `loader.c`), the application pool `0xcd500000` and heap cap (`services.c`),
RomFS overlays and the shader seed (`build_app.py`, `prepare_shader_seed.py`), pinned per-version hashes everywhere.
The mechanisms underneath (rewriter, loader, IPC framing, threads/memory SVCs, NVN on Metal) are generic.

### 2026-10-19: stage 1, code and data

**Rewrite.** `patch_nso.py` (a generic scan, not a site table) rewrote `sdk` and `subsdk0` unchanged. `main` stopped at
one site: `mov sp, x18` at `0x12874f4`, a variable-length stack array where the compiler used x18 as a scratch
register. The plain x18 block restores its scratch pair from sp, which that instruction has just moved. New block kind
`site_spset`: save the pair below the old sp, keep the old sp in the second scratch register, run the instruction with
x18 replaced, restore the pair from the copy. `structck.py` got the matching narrow rule. TotK has no such site, so its
pinned rewrite hashes are unchanged.

Verified: `structck.py` OK for all three modules (0 violations); `equiv.py` 36,627 sites, 0 divergent, 600 of 600
mutation controls caught, the new site 3 of 3 effective trials; a copy with a corrupted restore offset fails structck;
two rewrites give identical bytes.

**Data.** `scripts/merge_romfs.py` rebuilds the RomFS because the pinned hactool has no sparse layer. Layers, bottom up:

1. base sparse indirect table, encrypted with AES-CTR whose upper IV carries `generation << 16`;
2. base data: stored blocks are the original ciphertext, decrypted at their original (virtual) offsets; regions the
   update replaces read as zeros;
3. update AES-CTR-Ex table (plain AES-CTR), which covers everything before it, the indirect table included;
4. update indirect table: each range comes from the base section or from the update data.

The update's IVFC header covers the merged image, so any wrong layer fails a block hash.

Verified: all six IVFC levels, 918,430 of 918,430 data blocks; 552 files (72 `.pkz` archives, 478 `.webm` movies,
2 `.avi`), 15.0 GB, SHA-256 `4d8de0ab…`; 13.26 GB come from the base, 1.82 GB from the update; flipping one byte of
update data fails its block. `scripts/extract_code.py` takes the ExeFS from the update with every block verified; its
output matches an independent extraction byte for byte. `assets/expected-v1.2.0.json` pins all of it.

Pitfalls, so nobody repeats them:

- `patch_nso.py` defaults to `DM_PRIVATE_GATES=1`; the TotK build runs it with `DM_RULESET=native DM_PRIVATE_GATES=0`.
  A first rewrite without those variables had to be redone. Always use the build's variables.
- `structck.py` needs LLVM at `/opt/homebrew/opt/llvm@23/bin` (or `LLVM_BIN`): `brew install llvm`.
- Two assumptions about the IV were checked against the dump before writing the extractor: of nine candidate IVs for the
  sparse table only `generation << 16` decodes a valid root node (index 0, one entry set, end = section size). The
  counter offset (`physical_offset + bucket offset` vs. section start + bucket offset) cannot be told apart here because
  the two are equal; the script refuses a layout where they differ instead of guessing.
- The indirect table first decoded with the plain IV only because its range's generation equals the header's. It is
  now read through the AES-CTR-Ex layer, as the table extents show it must be.
- Scripts named like TotK's (`extract_exefs.py`, `extract_romfs.py`) shadow the modules they import; the Bayonetta
  scripts have distinct names.
- `python -I` drops the script's folder from `sys.path`; repo scripts run without it, as the build does.

Commits:

- `29034df` feat: the rewriter handles instructions that set sp from x18 (site_spset)
- `558bce8` feat(by3): extract the code and merge the sparse RomFS of Bayonetta 3 1.2.0
- docs(by3): README and this work log

Open questions carried forward: what program 1 (`…A001`) is; whether the WebM movies are VP9 (the TotK movie host
decodes VP9 with libvpx); the audio renderer revision Wwise requests under SDK 13.3.2; whether NVN struct layouts differ
between SDK 13.3.2 and the version `nvn.h` assumes.

### 2026-10-19: stage 2, the game reaches `nnMain`

**Layout.** `games/by3/runtime` is a fork of `games/totk/runtime` (commit `52edc0a` is the unchanged copy, so the next
commit's diff is the whole fork). A fork rather than `#ifdef`s in the shared files: TotK addresses, patches and
diagnostics sit in several files and nothing here can test TotK. The NVN-on-Metal layer
(`games/totk/third_party/d2r_gfx`) is compiled unchanged by `games/by3/Makefile`. Generated headers and the binary live
in `BY3_build/build`; the runtime reads `extracted/` and `rewritten/` relative to its working directory, so it runs from
`BY3_build`.

**What changed in the fork:**

- `game_version.h` defines no game address on purpose: any leftover TotK `GAME_ADDR` is a compile error. That found
  every use: the loader's TotK fault workaround (removed), the frame-controller diagnostic (returns 0), the startup
  checkpoint's caller check (now prints the caller's offset instead), the software keyboard probe (refuses to run).
- `game_patches.c`: no patches; the host hooks the shared graphics layer and input call (`runtime_output_*`,
  `runtime_frame_step_*`, `runtime_aspect_*`) answer "off". `aspect_patch.h` and `game_patches_v143.c` are gone.
- `world_survey.c` (TotK actors and scenes): stubs.
- Title ID `01004A4010FEA000` (save ownership in `fs_host.c`, `svcGetInfo` 18 in `services.c`), window and menu titles.
- `shared_font.c`: the NSPs have no system fonts, and the game imports `nn::pl::GetSharedFont`. Without fonts the rows
  are empty and the runtime stops with instructions when the game first asks for one.
- Includes of the graphics layer point at `../../totk/third_party/d2r_gfx`.

`scripts/prepare_runtime.py` merges TotK's three generators (runtime tables, RomFS index, fonts config) and checks every
input against `assets/expected-v1.2.0.json`. TotK pins the compiler's exact DT_INIT instruction pair; here the first
`adrp` + `ldr w` on the same register in DT_INIT is decoded and printed. All three Bayonetta modules have TotK 1.0.0's
shape (x20, +0x10 / +0x18).

Verified:

- `by3-native rewritten/v120 probe`: pass. Three modules mapped, 236,495 relocations, identity checked, 4,000 calls
  main PLT → sdk → host timer on 4 threads. The first Bayonetta code to run on the Mac.
- `TOTK_HEADLESS=1 TOTK_VERIFY_STARTUP=1 by3-native rewritten/v120 boot`: pass (phase 4). The original
  `nn::init::Start` ran the SDK startup; the RomFS (15.0 GB) was verified; every constructor finished with state 2 (main
  265, subsdk0 45, sdk 112 init_array entries); the original `nnMain` ran up to its focus-handling setup, called from
  `main+0xce39c8`.

The graphics layer reports its own NVN table (TotK's 523 names, 413 implemented); Bayonetta's 12 extra names get the
unimplemented stub too.

Commits: `52edc0a` chore(by3): copy games/totk/runtime as the starting point; then feat(by3): a runtime that boots
Bayonetta 3 to nnMain.

### 2026-10-19: stage 3 (in progress), from `nnMain` into the game's own init

Method: boot (headless until the game needs a window, then with one), read where the host stops, fix that, repeat.
`scripts/symbolize.py` names sdk frames of a host failure (the SDK exports its functions; main mostly does not). When
the game itself gives up, its init is a chain of `cbz w0, fail` calls: an lldb breakpoint on the failure label and the
value of `lr` name the call that returned 0; repeat one level down. The game's own code is read with capstone.

Answered so far (in order of appearance):

- `set` (nn::settings) over IPC: language codes, region (`runtime/system_services.c`). `services.c`'s language choice is
  now `runtime_desired_language()`, shared with it.
- `bsd:u` offline: the client registers and its monitor starts; every socket fails with ENETDOWN.
- **CMIF domains** in `ipc.c` (TotK never needed them): ConvertCurrentObjectToDomain, CopyFromCurrentDomain, domain
  requests and closes, objects returned as ids instead of handles, clones sharing the domain (reference counted).
  `threads.c` gained `runtime_handle_take_session` for that.
- SDK functions answered by name: `nn::hid` single-state reads, touch screen (no touches), handheld activation, the
  one-argument ShowControllerSupport (`input.c`); SDK 13's one-argument `MountRom` (`romfs.c`); `EnsureSaveData`,
  `CommitSaveData` (`fs_host.c`); offline `nifm`, `ssl`, network-service-account, `friends` presence, network clock,
  recording controls, `nsd` environment, `prepo` init (`system_services.c`, `runtime_by3_override`).
  `nn::oe::ExecuteProgram` stops with a message: the game can start its program index 1 (`…A001`), not supported yet.
- RomFS directory listing (`romfs.c` `runtime_romfs_list`, snapshot handles in `fs_host.c`): the game lists
  `Contents:/` to find its 72 `.pkz` archives. The mount root is the empty path, which the strict file-path check
  rejects; folders are trimmed and the root handled before it.
- Shared graphics layer (`games/totk/third_party/d2r_gfx`, TOTK behaviour unchanged):
  - `DM_POOL_BUFFER_MAX_MIB` (default 1024, the TotK guard against IOGPUFamily panics): Bayonetta 3 makes one 1348 MiB
    NVN memory pool at start; its runtime sets 2048.
  - Texture views can sample the stencil plane (`nvnTextureViewSetDepthStencilMode`): a spare bit of the packed 16-byte
    view, and an `X32_Stencil8` Metal view of `Depth32Float_Stencil8`. Not verified yet: that the translated shader
    declares that texture as unsigned integer, which Metal expects.

Where it stands: Metal device, VI window and the NVN window (3-image swapchain, 1600x900) are up; 18 threads run; all
`.pkz` archives are open and `shader2.dat` loads. The game's init (`main+0x6705c0`) now fails while creating its first
shader programs by name (`hwfillcolor` at `main+0x69c7d8` → `main+0xcb5944` → … → `main+0xcff458`), and the game then
crashes in its own shutdown path finalizing a subsystem that never started (`main+0xb8462c`). Not yet seen: audio
(Wwise uses `AudioOut`, `audout:u`, which the host lacks), system fonts.

Pitfalls: `TOTK_HEADLESS` is tested for presence, so an empty value still means headless. A game-side null
dereference in a shutdown path is a symptom; the cause is the init step that failed before it.

### 2026-10-19: stage 3 done, the first frame is presented

Upstream `main` was merged first (sampler border colour emulation, #49, reaches Bayonetta through the shared graphics
layer; the TotK runtime fixes stay in `games/totk`). The merged `hle_nvn.c` reads `runtime_survey_sync`, which the
fork's survey stub now defines.

The game's init failed while creating its shader programs. Following the `cbz w0` chain down: `main+0xd0d998` checks a
shader binary's header (`VSO\0`, GPU code major/minor at bytes 6/7) against the range `nvnDeviceGetInteger` reports.
The graphics layer's table was measured on an older driver (Super Mario Odyssey) and stops at 1.14; Bayonetta 3's
binaries are 1.15, 1.16 and maybe newer. `DM_NVN_GPU_CODE_MAX_MINOR` (the Bayonetta runtime sets 31) opens that; the
layer reads only three control-section fields (code length, stage, compute group size), each checked, so a layout
change would show at once. Then, one at a time, NVN calls TotK never makes: `nvnTexturePoolRegisterImage` (images share
the texture registration), `nvnQueueWaitSync` (replay is in submission order on one Metal queue),
`nvnCommandBufferClearBuffer` (an inline buffer write of the repeated value), colour reduction (no-op).

The host keeps GPU submission off unless `TOTK_GPU_ALLOW_SUBMIT=1` (the TotK launcher sets it); with it the game
reports **"first presented frame" at 0.64 s**. That is stage 3's goal.

Past it, so far:

- `audout:u` (`runtime/audio_out.c`): Wwise's AudioOut. Buffers are consumed at real time (a playback thread holds each
  one for its duration, releases it and signals the buffer event) but not heard yet; Core Audio output is stage 4.
  Wwise also opens `audren:u`, which the host already has.
- `nn::account::PopOpenUsers` / `PushOpenUsers`: users kept across a program jump; a fresh start has none.
- Runtime shader translation: `make shader-tools` puts the repository's prebuilt `totk_xlate` (SHA-256 checked) and
  SPIRV-Cross (pinned commit, built like `build_app.py` does) where the graphics layer looks for them.

State: the game runs about 6 s (137 frames), draws, translates its first pixel shader, then stops at
`nvnCommandBufferDispatchComputeIndirect`. Frames 2 and 137 are black (`TOTK_INPUT_FILE` "shot" captures). Seen in
the log, not handled yet: a draw with no program bound, and logic op 3 / alpha test 5 (Metal has neither; drawn
without). Still unseen: system fonts.

Commits: `1ce8e8b` (first frame), and this entry's commit (AudioOut, open users, shader tools).

### 2026-10-19: stage 4, playable; stage 5, the app

**Picture.** After the first frame, NVN features TotK never uses, one at a time:

- `DispatchComputeIndirect`: Metal's indirect dispatch (both encoder APIs); the record is `OP_DISPATCH` with
  `x == DISPATCH_INDIRECT` and the argument address in its spare field, so no op switch changes.
- `CommandBufferFenceSync`: a fence that stands for the next submission (approximation; it cannot hang).
- `DrawArrays/ElementsIndirect`, `MultiDraw*IndirectCount`: draw records with a tail (`p_draw_indirect`); the replay
  writes the arguments it reads from memory into the record before drawing, because several passes keep pointers to
  draw records. Arguments a GPU pass of the same submission writes are seen as in memory (usually last frame's).
- Shader control sections are copied at `nvnProgramSetShaders` (content-interned, kept for the process): the game frees
  that memory and the replay, which reads it later, found text there ("invalid shader code length 807416121").
- **Per-stage program binding**: Bayonetta binds a vertex-only and a fragment-only program (NVN's stage mask). The
  replay combines the bound stages into a host program per combination; a graphics bind covering every bound stage and
  every compute-only bind keep the old behaviour (TotK's case). This is what made the title screen appear.

The game then runs: logo, title, main menu, Naive Angel Mode screen, the story's opening (captures in the work
folder). The game uses its own fonts; the system fonts were never asked for.

**Input.** The Mac keyboard drives the controller (the player navigated the menus and started the story); game
controllers go through the TotK host's GameController support, unchanged.

**Sound.** Wwise mixes through `audout:u`; `runtime/audio_out.c` plays it with one Core Audio AudioQueue per output
(5.1 mixed down to stereo), and the device's callbacks release the buffers, so the output paces the game.

**Saves** are written (`GameData.dat`, `SlotData_0.dat` under the profile's `save/<account>`).

**Pacing.** The TotK host presents on the display's rate (120 Hz on ProMotion) and uncapped, relying on TotK's
real-time patch. Bayonetta has no such patch, so the fork sets a Switch 60 Hz base (`DM_PRESENT_HZ=60`,
`TOTK_UNCAPPED=0`): about 25-30 fps on the title as shipped, 59 fps with the 60 fps patch (1,774 frames in 30 s).
At a 120 Hz base the game ran above 100 fps; whether its logic then runs fast is not established, so the launcher
labels 120 as experimental.

**Mods.**
- exefs `.pchtxt` (60 fps, 900p, LOD, film grain): `scripts/prepare_patches.py` checks the build ID and that no patch
  touches bytes the Apple-silicon rewrite changed, and writes `patches/<slug>.tsv`; offsets are main image offsets
  (the files' `offset_shift 0x100` is for the IPS container; every site decodes to a sensible change only that way).
  `runtime/game_patches.c` applies what `BY3_PATCHES` names, checking original bytes at each site.
- RomFS mods (the PS5-prompt UI `ui_000.pkz`): the TotK host's overlay manifest (`make mods`), loaded from
  `TOTK_ROMFS_MODS`; replacement and original are both hashed at start.

**The app** (`make app`, `app/launcher.m`): a settings window, then the game. Presets (Original 30 fps, Recommended
60 fps, Performance 60 fps + fixed 900p, Quality: 900p, better LOD, no grain, full screen; Custom), frame rate,
internal resolution, window or full screen (`BY3_FULLSCREEN`), window size, extras, interface mod and the HUD
(`BY3_HUD_RENDER=1`: "FPS 60  1600x900 > 2560x1440"). The bundle is small: Info.plist's `BY3WorkFolder` names the work
folder the game runs from. The icon comes from the game's own control data. Saves:
`~/Library/Application Support/MacNativeGames/BY3/profile`; log: `~/Library/Logs/MacNativeGames/by3.log`.

Pitfalls: `TOTK_GPU_ALLOW_SUBMIT=1` is needed for any picture; the TotK launcher also sets `TOTK_GPU_WIDEN`,
`BLOCKRT`, `MIDCLEAR` (now the Bayonetta launcher does too). A shot's brightness says more than its file size when
watching dozens of captures.

Open:
- 120 fps: does the game's logic follow real time? (compare a timed event at 60 and 120 Hz bases)
- Menus show bands of "noise text": probably logic op 3 / alpha test 5, which Metal lacks and the layer skips.
- Depth-bounds test (unavailable on Metal) is skipped; indirect-draw and fence approximations as above.
- Shader stutter: no shared shader list or startup seed for Bayonetta yet (TotK's build prepares one).
- `nn::oe::ExecuteProgram` (program 1, `…A001`) still stops with a message: not met in play so far.
- Controllers: supported by the host; not yet tried with this game.

Commits: `e0c96a0` (graphics: title screen), `2706d98` (sound, patches, pacing, full screen), `ae8c86a` (app, HUD).
