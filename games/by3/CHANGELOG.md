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
| 2 | A runtime target with the TotK-only parts compiled out, booting to `nnMain` | next |
| 3 | Follow every unknown service / command / NVN call until the first `nvnQueuePresentTexture` | open |
| 4 | Audio (Wwise), input, saves; the 1.2.0 patches (60 fps, 900p) applied to the native code | open |
| 5 | Performance, shaders, packaging as an app | open |

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
