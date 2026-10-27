# Third-party code

Code in this repository that comes from other projects keeps its license. The license file is next to the code.

| Code | From | License | File |
|---|---|---|---|
| The native approach of `games/fc26` (rewriter, Horizon host, NVN on Metal, launcher) | [MacNativeGames](https://github.com/ly05010419/MacNativeGames), adapted for FC 26 | MIT | `LICENSE` |
| `games/fc26/third_party/d2r` (NSO rewriter, verification tools) | [d2r-mobile](https://github.com/jhaizhou-ops/d2r-mobile), adapted | MIT | `games/fc26/third_party/d2r/LICENSE` |
| `games/fc26/third_party/d2r_gfx` (NVN on Metal, texture tools, host headers) | d2r-mobile, extended | MIT | `games/fc26/third_party/d2r_gfx/LICENSE` |
| Texture layout sizes in `games/fc26/third_party/d2r_gfx/gfx/nvn/nvn_tex.c` | deko3d | zlib | `games/fc26/third_party/d2r_gfx/LICENSE.deko3d` |
| `games/fc26/third_party/d2r_gfx/third_party/bcdec` | [bcdec](https://github.com/iOrange/bcdec) 0.985 | MIT or public domain | `games/fc26/third_party/d2r_gfx/third_party/bcdec/LICENSE` |
| Variable shader constants and the GPU timestamp profiler in `games/fc26/third_party/d2r_gfx/gfx/nvn` | [nxnative](https://github.com/seedds/nxnative), `7a3b95873bf1836bf7f70e2e2e3245e1cabb1620`, adapted | MIT | `games/fc26/third_party/d2r_gfx/LICENSE.nxnative` |
| Thread synchronization fixes and the yield back-off in `games/fc26/runtime/threads.c` | nxnative, rewritten for this runtime | MIT | `games/fc26/third_party/d2r_gfx/LICENSE.nxnative` |
| Audio effects and the mixer in `games/fc26/runtime/audio_reverb.c`, `audio_effects.c` and `audio_mixer.c` | Ryujinx.Audio, ported | MIT | `games/fc26/third_party/licenses/Ryujinx-Audio.txt` |
| `games/fc26/prebuilt/macos-arm64/totk_xlate` (the shader translator, a native program) | Ryujinx.Graphics.Shader with the totk_xlate front end of d2r-mobile, built with .NET NativeAOT in MacNativeGames. It contains .NET runtime libraries. The source is in this repository: `games/fc26/vendor/ryujinx` (Ryujinx) and `games/fc26/tools/totk_xlate` (front end, patches, `publish_native.sh`). | MIT (Ryujinx, d2r-mobile, .NET) | `games/fc26/third_party/licenses/Ryujinx-Audio.txt` (Ryujinx), `games/fc26/third_party/d2r/LICENSE` (d2r-mobile) |

Downloaded or linked during the build (not in this repository):

| Code | Use | License |
|---|---|---|
| [SPIRV-Cross](https://github.com/KhronosGroup/SPIRV-Cross) at `aa217ae` | SPIR-V to Metal Shading Language | Apache-2.0 |
| libopus (Homebrew), linked statically | Opus audio | BSD-3-Clause |
| libvpx (Homebrew), linked statically | VP9 movies | BSD-3-Clause |
