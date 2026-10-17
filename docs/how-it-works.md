# How it works

The game is not emulated. Its own machine code runs on the Apple chip; this project supplies what the Switch would:
a loader, the operating system's services, and a graphics driver.

## The code (games/totk/third_party/d2r, games/totk/runtime/loader.c)

The Switch and Apple silicon are both ARM64, so almost every instruction of the game runs as it is. A few things
macOS does not allow are rewritten ahead of time (`patch_nso.py`): the platform register x18, the thread pointer
register, system calls (`svc`), and the counter registers. Each one becomes a short jump into a stub that does the same
thing for macOS. The rewrites of versions 1.0.0 and 1.1.2 were verified site by site (every rewritten site executed with random
inputs against the original in an emulator, with negative controls); the build checks that your rewrite is byte for
byte the selected version (`games/totk/assets/expected-v1.0.0.json` / `expected-v1.1.2.json`).

The loader maps the three rewritten modules (main, sdk, subsdk0) at their original layout, resolves their imports
against each other, and starts the game's own `nn::init::Start`.

## The operating system (games/totk/runtime)

The game talks to Horizon (the Switch OS) through system calls and IPC. The host answers what the game uses: threads
and synchronization, memory, the file system (the RomFS straight from the extracted image; saves in your profile
folder), time, settings, the account, input (keyboard and game controllers, with rumble and motion), audio (the
audio renderer with its effects, mixed and played through Core Audio), the software keyboard (the Mac keyboard), and
the movie decoder (VP9 through libvpx). A small number of fixed patches change the game itself, each checked against
the original instructions first: frame timing by real time, the 60 FPS present interval, the output resolution.

## The graphics (games/totk/third_party/d2r_gfx/gfx/nvn)

The game records NVN commands (Nintendo's graphics API) into command buffers. The NVN layer implements the API on the
host and replays each submitted command buffer on Metal 4: textures and buffers in the game's memory pools become
Metal resources (with dirty-page tracking for what the CPU changes), render targets become render passes, and draws
become Metal draws. Shaders are Maxwell machine code: the first time one is used it is translated by the Ryujinx shader
translator (to SPIR-V), SPIRV-Cross (to Metal Shading Language) and Metal, and the result is cached
(`~/Library/Application Support/MacNativeGames/TOTK/shader-cache`). The translator runs as one native program,
`totk_xlate --service` (`games/totk/tools/totk_xlate`: the Ryujinx translator with this project's patches and the
service that turns each request into the MSL and its reflection file), compiled ahead of time with .NET NativeAOT; it
ships ready-made in `games/totk/prebuilt/macos-arm64`, so neither building nor playing needs .NET, and playing needs no Python. Building still requires Python 3.14. MetalFX upscales the game's 1600x900 scene into its
1080p or 1440p canvas and can generate in-between frames.

## The build (build_app.py)

1. Detect XCI (HFS0 secure partition) or NSP (PFS0) by its header. Read the base Program NCA in place, extract ExeFS,
   then rewrite and check the three modules against the verified 1.0.0 hashes. NSP common tickets supply encrypted
   title keys in memory; `prod.keys` supplies the matching titlekek. Rights-free NCAs use their key area, as before.
   The importer follows nxnative's container/common-ticket approach without its iOS packaging or .NET dependency.
2. The RomFS (17 GB) decrypted and verified through all six IVFC levels. The shared fonts come from the XCI's
   system update partition, `--firmware` (an unpacked firmware NCA directory), or `--shared-fonts` (six extracted
   BFTTF files). Actual font bytes and the complete manifest are verified before reuse. Then the
   RomFS overlays (small data patches: quick-menu capture timing at high frame rates, the game-over retry, the heap
   sizes the 1440p output needs) are made from your own files.
3. SPIRV-Cross compiled with clang; the prebuilt shader translator checked against its SHA-256.
4. The game binary built against your extracted files (it checks their hashes at every start) and everything put into
   an app bundle; the app's launcher points the game at your profile, cache and log folders.

The output is macOS-only: Apple silicon, macOS 26 or later, and an AppKit launcher. There is no iPhone/iOS build option.
The separate cumulative 1.1.2 update is accepted with `--update`. Other updates, DLC, combined packages, personalized tickets and NSZ/XCZ remain unsupported.
Changing an input path, size, or modification time invalidates the extraction manifest, including its NCA offsets;
verified version-specific output can still be reused after the new input's code passes the hash checks.

Container tests use generated encrypted fixtures with no game data or real keys:

```sh
/path/to/TOTK_build/venv/bin/python -m unittest discover -s tests -v
```

## Cumulative update path

`--update` first validates the base code, then extracts and validates the update ExeFS and its rewritten modules against the fixed 1.1.2 manifest. An update's Program NCA can have the base title ID; the BKTR section marker identifies the input type, while exact ExeFS and merged RomFS hashes identify the supported version. A renamed 1.1.0/1.2.1 file cannot pass as 1.1.2.

The pinned hactool commit `1d64a83450e025622f3468c28fc4164dad2c5ef6` merges the base and update Program NCAs. The build adds a small explicit title-key-file hook (`MNG_TITLE_KEYS`): temporary common tickets for both inputs stay in a 0600 file under a private temporary directory, and are removed on success or failure. It does not edit the player's key store or pass keys in process arguments. All six IVFC levels must verify, then the final image must match the 1.1.2 SHA-256. The hactool output uses `--sectionN`, because `--romfs` does not export this BKTR section.

Runtime addresses, resource overlays, generated headers and modules are selected together. The app contains one executable and one selected data set; its launcher is compiled for that same version and `--check` verifies the bundle's version metadata. The normal window title reports the version. Saves keep their existing location, with an atomic full pre-upgrade backup before the first 1.1.2 launch.

The exact 1.1.2 visibility-counter vertex shader needs a targeted lowering: each passing vertex atomically adds one instead of using a subgroup ballot/reduction. The original atomic side effect is retained, and the code SHA-256 limits this transformation to the analysed shader. This is not a general subgroup fallback. The native prebuilt translator is rebuilt from the checked-in source and has an updated SHA-256.

<a id="112-validation"></a>
## 1.1.2 validation

The development runtime passed 55,018 rewrite-site checks and 600 negative controls, native loader/boot/resource probes, 96 real GPU vertex-counter cases with an intentionally wrong-count negative control, and basic Mac gameplay. These are scoped checks, not full-game or performance acceptance.

The package importer also fixes the ticket signature-type byte order: real Switch ticket headers encode `0x10004` as `04 00 01 00`. The old synthetic fixtures mirrored an incorrect big-endian reader; they did not establish retail-ticket compatibility. Tests now use the real header order and reject the reversed header.

Automated container/update tests cover update selection, unsupported version hashes, private ticket handoff and cleanup, and a bundle containing only the selected version. The synthetic merge helper verifies plumbing only; real BKTR cryptography is checked by the local full build.

Local packaging run (2026-10-17, M4 Mac): base XCI + the actual 1.1.2 NSP completed BKTR integrity verification and produced 304,471 indexed files. Merged SHA-256: `d98fde0833a57378f3436275f641a920a29e95500d5667e1ac2ee9ba32f30c43`. The output bundle contains only v112 code/data, and its game executable matches the compiled v112 binary. Temporary NCAs and ticket files were removed. The prebuilt translator's SPIR-V/MSL bytes and reflection JSON match the development shader used by the 96-case GPU probe. The 16 automated tests passed; both launcher versions passed `--check`, and deliberately wrong bundle version metadata was rejected.

Build evidence remains local at `<work>/logs/v112-*`; game images, keys, saves and generated game bytes are not committed. This packaging run does not claim a fresh full gameplay test of the packaged App or an independent retail base-NSP test.

The complete update build and actual packaged launcher `--check` passed (`ok: game version 1.1.2`), taking about 11 minutes with base data cached; 153 seconds were the macOS first-launch scan. Both versions passed 4-thread / 4,000-call native loader probes and rejected altered images. The new native RomFS probe matched independent reads of 65 files, verified three overlays and rejected a corrupted index. No additional GPU/gameplay run was made for this packaging check.
