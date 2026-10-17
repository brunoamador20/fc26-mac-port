# How it works

The game is not emulated. Its own machine code runs on the Apple chip; this project supplies what the Switch would:
a loader, the operating system's services, and a graphics driver.

## The code (games/totk/third_party/d2r, games/totk/runtime/loader.c)

The Switch and Apple silicon are both ARM64, so almost every instruction of the game runs as it is. A few things
macOS does not allow are rewritten ahead of time (`patch_nso.py`): the platform register x18, the thread pointer
register, system calls (`svc`), and the counter registers. Each one becomes a short jump into a stub that does the same
thing for macOS. The rewrite of version 1.0.0 was verified site by site (every rewritten site executed with random
inputs against the original in an emulator, with negative controls); the build checks that your rewrite is byte for
byte that one (`games/totk/assets/expected-v1.0.0.json`).

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
Updates, DLC, combined packages, personalized tickets, and NSZ/XCZ inputs are outside the supported input set.
Changing an input path, size, or modification time invalidates the extraction manifest, including its NCA offsets;
verified version-specific output can still be reused after the new input's code passes the hash checks.

Container tests use generated encrypted fixtures with no game data or real keys:

```sh
/path/to/TOTK_build/venv/bin/python -m unittest discover -s tests -v
```
