# MacNativeGames

> **请使用你的 AI 助理帮你完成 Mac App 的构建。推荐 Claude Code、Codex，或其他你喜欢的 AI 助理。**
>
> **Use your AI assistant to help you build the Mac app. We recommend Claude Code, Codex, or any other AI assistant you prefer.**

[中文说明](#中文说明)

Play your own copy of **The Legend of Zelda: Tears of the Kingdom** natively on an Apple silicon Mac. Bring your game file (XCI or NSP) and your `prod.keys`; one script turns them into a Mac app. This project currently supports **Mac only**.

**iPhone and iPad support is coming soon. iPhone 16 or newer models are recommended for the upcoming iPhone version.**

It is not an emulator: the game's own ARM64 code runs directly on the Apple chip (rewritten only where macOS requires it), the Switch system services are answered by a small host, and the game's NVN graphics are rebuilt on Metal 4. Nothing from the game is in this repository, and the project is not affiliated with Nintendo.

## What you need

- A Mac with Apple silicon and **macOS 26** or later (the graphics use Metal 4). 16 GB of memory or more is recommended.
- About **25 GB** of free disk space for the work folder, in addition to your game file. Keep the output app on the **same APFS volume** to share the large data files through cloning. If cloning is unavailable or the app is on another volume, allow roughly **17 GB more** for the app copy.
- Your Tears of the Kingdom **base game version 1.0.0** (`0100F2C0115B6000`) as an **XCI or NSP**, and your `prod.keys`. All updates, including **1.2.1 and 1.4.3**, DLC and combined base/update packages are unsupported by this checkout. NSP support does not add support for newer game versions.
- For NSP: its common ticket must be included unless the NCAs are rights-free. NSPs do not contain system shared fonts: supply an unpacked firmware NCA directory with `--firmware`, or previously extracted fonts with `--shared-fonts`. The six fonts must match this project’s verified hashes; valid fonts already in the work folder are reused.

## Build the app

**1. Tools** (once): the Xcode command line tools and [Homebrew](https://brew.sh). An internet connection is needed to install the build dependencies and fetch the pinned SPIRV-Cross source:

```
xcode-select --install
brew install opus libvpx python@3.14
```

**2. Download or clone this repository**, then open Terminal in its `MacNativeGames` folder and run the script with your game file and keys:

```
python3.14 build_app.py ~/Games/totk.xci -k ~/keys/prod.keys
```

For an NSP, supply the shared fonts too:

```sh
python3.14 build_app.py ~/Games/totk.nsp -k ~/keys/prod.keys --firmware ~/Games/firmware
# Or reuse the six .bfttf files from a previous build:
python3.14 build_app.py ~/Games/totk.nsp -k ~/keys/prod.keys --shared-fonts /path/to/TOTK_build/totk/extracted/firmware/shared-fonts
```

`--firmware` accepts a directory of `.nca` files (unpack a firmware archive first), or an installed firmware `registered` directory. `--shared-fonts` accepts the extracted directory containing `0-standard.bfttf` through `5-nintendo-extension.bfttf`. No fonts or keys are downloaded. For an XCI, fonts are read from its system update partition by default; if that partition is missing, use one of these font options too. Both input formats produce a macOS `.app`.

The app appears next to the game file (`Tears of the Kingdom.app`; `-o` chooses another place). A local clean build took about 6 minutes on an M4 Mac mini (hardware, disk and network conditions affect the time): about a minute each to rewrite the main code module and to decrypt the 17 GB of game data, and two to three minutes for macOS to check the finished app once. Building needs no .NET and no cmake, and the finished game needs no Python: its shader translator is a native program that comes with this repository (`games/totk/prebuilt`). Every intermediate file is in a work folder next to the game file (`TOTK_build`, or `--work`); running the script again reuses what is already done.

The extracted code modules, rewritten modules, RomFS and shared fonts are checked against `games/totk/assets/expected-v1.0.0.json`; the prebuilt shader translator has its own SHA-256 check. A mismatch stops the build. Key values are never printed.

**3. Play:** open the app from Finder. The build starts the launcher in `--check` mode, which checks that the game executable exists and allows macOS to perform its first-launch checks; it does not run a gameplay test. You can keep the app where it was built or move it to `/Applications`. Copying it to a different volume can use additional disk space and trigger another macOS check, during which no window may appear. The first game launch verifies the game data (about 20 seconds in local testing). Newly encountered shaders can cause stutters; cached shaders reduce this work on later visits.

## Controls

Controllers recognized by macOS (such as DualSense and Xbox controllers) are mapped to a Switch Pro Controller. Rumble and motion require the corresponding features to be exposed by the controller and macOS; not every controller has a gyroscope. Keyboard mappings use physical key positions corresponding to a US layout:

| Key | Switch | | Key | Switch |
|---|---|---|---|---|
| W A S D | left stick | | arrow keys | right stick |
| J | A | | K, Space | B |
| I | X (jump) | | U | Y (attack) |
| Q / E | L / R | | Option / Shift | ZL / ZR |
| F T H G | d-pad left / up / right / down | | Z / C | left / right stick press |
| Return | + (menu) | | Tab, Esc | − (map) |

Extra keys: **1** MetalFX upscaling on / off (MetalFX is used only for 2K: when the picture on screen is bigger than 1080p), **2** frame interpolation (off → 30+30 → half the refresh rate → unlimited), **3** the game's own 2560×1440 output ↔ 1080p output upscaled by MetalFX. Text entry (naming a horse) uses the Mac keyboard.

## Where things are

- Saves: `~/Library/Application Support/MacNativeGames/TOTK/profile`
- Shader cache: `~/Library/Application Support/MacNativeGames/TOTK/shader-cache` (delete it to translate everything again)
- Log: `~/Library/Logs/MacNativeGames/totk.log` (the run before: `totk.previous.log`)

## Known issues

- Only base game 1.0.0 in XCI or NSP format. No updates, DLC, combined packages, compressed NSZ/XCZ, or personalized tickets. Mac only.
- No online features, no amiibo.
- New shaders can cause compilation stutters. Cache reuse reduces these, but does not guarantee stutter-free gameplay.
- NSP validation currently covers 11 automated container tests and a complete Mac build from a local XCI-derived NSP fixture with a generated common ticket. An independent retail base NSP and gameplay from that input have not yet been tested.

## How it works

See [docs/how-it-works.md](docs/how-it-works.md).

## Acknowledgements

- **[d2r-mobile](https://github.com/jhaizhou-ops/d2r-mobile)** (MIT) developed this way of running Switch games natively (for Diablo II: Resurrected): the NSO rewriter, the Horizon host and the NVN-on-Metal layer here started as its generic parts.
- **[nxnative](https://github.com/seedds/nxnative)**: the one-script packaging and NSP common-ticket import follow its approach; this project builds only Mac apps.
- **Ryujinx** (MIT): its shader translator (`vendor/ryujinx`) turns the game's Maxwell shaders into SPIR-V, and its system-service code is a reference. With this project's patches and service it is compiled ahead of time (.NET NativeAOT) into `games/totk/prebuilt/macos-arm64/totk_xlate`; `games/totk/tools/totk_xlate/publish_native.sh` rebuilds it (needs the .NET 10 SDK, only for developers).
- **[SPIRV-Cross](https://github.com/KhronosGroup/SPIRV-Cross)** (Apache-2.0) turns SPIR-V into Metal Shading Language; it is fetched at a pinned commit and compiled with clang during the build.
- **deko3d** (zlib): texture layout sizes. **bcdec**: BC texture decoding. **libopus** and **libvpx** (BSD) from Homebrew: audio and the pre-rendered movies.

## License

MIT (see [LICENSE](LICENSE)). Third-party code keeps its own license: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

---

# 中文说明

在 Apple 芯片的 Mac 上原生运行你自己的《塞尔达传说 王国之泪》。准备好游戏文件（XCI 或 NSP）和你的 `prod.keys`，一个脚本就把它们做成一个 Mac App。项目目前**只支持 Mac**。

**即将支持 iPhone 和 iPad。未来的 iPhone 版本推荐使用 iPhone 16 及更新机型。**

这不是模拟器：游戏自己的 ARM64 代码直接跑在苹果芯片上（只改写 macOS 不允许的地方），Switch 的系统服务由一个小宿主应答，游戏的 NVN 图形在 Metal 4 上重建。本仓库不含任何游戏内容，项目与任天堂无关。

## 需要准备

- Apple 芯片的 Mac，**macOS 26** 或更高（图形用 Metal 4）。建议使用 16 GB 或更多内存。
- 除游戏文件外，为工作目录预留约 **25 GB** 空闲空间。成品 App 与工作目录放在**同一个 APFS 卷**上时，大型数据文件可通过克隆共享磁盘空间；无法克隆或输出到其他卷时，还需为 App 副本另留约 **17 GB**。
- 你的《王国之泪》**本体 1.0.0 版**（`0100F2C0115B6000`），格式为 **XCI 或 NSP**，以及你的 `prod.keys`。当前仓库不支持任何更新版（包括 **1.2.1 和 1.4.3**）、DLC 或本体与更新合并的包。支持 NSP 格式不代表已适配新版游戏。
- 使用 NSP 时：除不依赖票据的 NCA 外，包内必须包含通用票据。NSP 不含系统共享字体，需要通过 `--firmware` 指定已解包的固件 NCA 目录，或通过 `--shared-fonts` 提供以前提取的字体。六个字体必须符合本项目已验证的哈希；工作目录中已有且校验通过的字体会自动复用。

## 打包 App

**1. 工具**（只需一次）：Xcode 命令行工具和 [Homebrew](https://brew.sh)。安装构建依赖和获取固定版本的 SPIRV-Cross 源码需要联网：

```
xcode-select --install
brew install opus libvpx python@3.14
```

**2. 下载或克隆本仓库**，在终端中进入 `MacNativeGames` 目录，再运行脚本，给出游戏文件和密钥：

```
python3.14 build_app.py ~/Games/totk.xci -k ~/keys/prod.keys
```

使用 NSP 时，还要提供共享字体：

```sh
python3.14 build_app.py ~/Games/totk.nsp -k ~/keys/prod.keys --firmware ~/Games/firmware
# 或复用以前构建时提取的六个 .bfttf 文件：
python3.14 build_app.py ~/Games/totk.nsp -k ~/keys/prod.keys --shared-fonts /path/to/TOTK_build/totk/extracted/firmware/shared-fonts
```

`--firmware` 接受包含 `.nca` 文件的目录（固件压缩包需先解压），也接受已安装固件的 `registered` 目录。`--shared-fonts` 接受包含 `0-standard.bfttf` 至 `5-nintendo-extension.bfttf` 的提取目录。工具不会下载字体或密钥。XCI 默认从其系统更新分区提取字体；如果该分区缺失，也可以使用上述字体选项。两种输入格式最终都生成 macOS `.app`。

App 出现在游戏文件旁边（`Tears of the Kingdom.app`；`-o` 指定别处）。本地一次全新构建在 M4 Mac mini 上约 6 分钟（耗时受硬件、磁盘和网络影响）：改写主代码模块、解密 17 GB 的游戏数据各约 1 分钟，macOS 把做好的 App 检查一遍要 2–3 分钟。打包不需要 .NET 和 cmake，做好的游戏运行时也不需要 Python：着色器翻译器是本仓库自带的原生程序（`games/totk/prebuilt`）。所有中间文件都在游戏文件旁边的工作目录里（`TOTK_build`，或用 `--work` 指定），再运行一次会复用已经做好的部分。

提取的程序模块、改写后的模块、RomFS 和共享字体会与 `games/totk/assets/expected-v1.0.0.json` 中的哈希核对；预编译着色器翻译器另有 SHA-256 校验。不匹配时停止构建。密钥的值不会被打印。

**3. 游玩：** 在访达里打开 App。构建结束时会以 `--check` 模式启动启动器，检查游戏可执行文件是否存在，并让 macOS 执行首次启动检查；这一步不进行游戏游玩测试。App 可以留在原位置，也可以移到“应用程序”。拷贝到另一个卷可能额外占用磁盘空间，并触发 macOS 再次检查，期间可能没有窗口。第一次进入游戏会校验游戏数据（本地测试约 20 秒）。首次遇到的着色器可能造成编译卡顿，缓存可减少后续访问时的重复工作。

## 操作

macOS 能识别的手柄（如 DualSense、Xbox 手柄）会映射为 Switch Pro 手柄。震动和体感需要手柄及 macOS 提供对应能力，并非所有手柄都有陀螺仪。键盘映射按美式布局对应的物理键位：

| 按键 | Switch | | 按键 | Switch |
|---|---|---|---|---|
| W A S D | 左摇杆 | | 方向键 | 右摇杆 |
| J | A | | K、空格 | B |
| I | X（跳） | | U | Y（攻击） |
| Q / E | L / R | | Option / Shift | ZL / ZR |
| F T H G | 十字键 左 / 上 / 右 / 下 | | Z / C | 左 / 右摇杆按下 |
| Return | +（菜单） | | Tab、Esc | −（地图） |

额外按键：**1** 开关 MetalFX 放大（MetalFX 只在 2K 用：画面在屏幕上大于 1080p 时），**2** 补帧（关 → 30+30 → 刷新率一半 → 不限帧），**3** 游戏自己输出 2560×1440 ↔ 输出 1080p 再由 MetalFX 放大。文字输入（给马取名）直接用 Mac 键盘。

## 文件位置

- 存档：`~/Library/Application Support/MacNativeGames/TOTK/profile`
- 着色器缓存：`~/Library/Application Support/MacNativeGames/TOTK/shader-cache`（删掉会全部重新翻译）
- 日志：`~/Library/Logs/MacNativeGames/totk.log`（上一次运行：`totk.previous.log`）

## 已知问题

- 只支持本体 1.0.0 的 XCI 或 NSP。暂不支持更新、DLC、合并包、NSZ/XCZ 压缩格式和个性化票据。平台仅限 Mac。
- 没有联网功能，没有 amiibo。
- 首次遇到新着色器可能出现编译卡顿，缓存能减少重复编译，但不保证完全没有卡顿。
- NSP 当前验证范围：11 项容器自动测试，以及使用本地 XCI 构造、附带生成通用票据的 NSP 测试副本完成完整 Mac 打包。尚未验证独立的零售本体 NSP，也未测试从该类输入构建后的实际游玩。

## 工作原理

见 [docs/how-it-works.md](docs/how-it-works.md)。

## 致谢

- **[d2r-mobile](https://github.com/jhaizhou-ops/d2r-mobile)**（MIT）为《暗黑破坏神 II：狱火重生》开发了这套原生运行 Switch 游戏的方法：这里的 NSO 改写器、Horizon 宿主和 Metal 上的 NVN 层都从它的通用部分起步。
- **[nxnative](https://github.com/seedds/nxnative)**：“用户自己的游戏文件 + 一个脚本出包”和 NSP 通用票据读取的做法借鉴自它；本项目只构建 Mac App。
- **Ryujinx**（MIT）：它的着色器翻译器（`vendor/ryujinx`）把游戏的 Maxwell 着色器转成 SPIR-V，它的系统服务代码也是参考。加上本项目的补丁和着色器服务，用 .NET NativeAOT 预先编成原生程序 `games/totk/prebuilt/macos-arm64/totk_xlate`；改了翻译器用 `games/totk/tools/totk_xlate/publish_native.sh` 重编（要 .NET 10 SDK，只有开发者需要）。
- **[SPIRV-Cross](https://github.com/KhronosGroup/SPIRV-Cross)**（Apache-2.0）把 SPIR-V 转成 Metal 着色语言；打包时按固定提交取得，用 clang 编。
- **deko3d**（zlib）：贴图布局尺寸。**bcdec**：BC 贴图解码。**libopus**、**libvpx**（BSD，来自 Homebrew）：音频和预渲染影片。

## 许可证

MIT（见 [LICENSE](LICENSE)）。第三方代码保留各自的许可证：[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
