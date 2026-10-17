# MacNativeGames

[中文说明](#中文说明)

Play your own copy of **The Legend of Zelda: Tears of the Kingdom** natively on an Apple silicon Mac. Bring your game card image (XCI) and your `prod.keys`; one script turns them into a Mac app.

It is not an emulator: the game's own ARM64 code runs directly on the Apple chip (rewritten only where macOS requires it), the Switch system services are answered by a small host, and the game's NVN graphics are rebuilt on Metal 4. Nothing from the game is in this repository, and the project is not affiliated with Nintendo.

## What you need

- A Mac with Apple silicon and **macOS 26** or later (the graphics use Metal 4). 16 GB of memory is enough.
- About **25 GB** of free disk space for the build (the finished app is an APFS clone of it when both are on the same volume).
- Your game card image of Tears of the Kingdom, **base game version 1.0.0** (`0100F2C0115B6000`, about 17.5 GB), and your `prod.keys`. Updates (1.1.x, 1.2.x) are not supported yet.

## Build the app

**1. Tools** (once): the Xcode command line tools and [Homebrew](https://brew.sh):

```
xcode-select --install
brew install opus libvpx cmake python@3.14
brew install --cask dotnet-sdk
```

**2. Run the script** with your card image and keys:

```
git clone <this repository> MacNativeGames && cd MacNativeGames
python3 build_app.py ~/Games/totk.xci -k ~/keys/prod.keys
```

The app appears next to the card image (`Tears of the Kingdom.app`; `-o` chooses another place). The first build takes about 10 minutes on an M4 Mac mini (slower Macs and disks take longer): rewriting the main code module, decrypting the 17 GB of game data, and letting macOS check the finished app once take most of it. Every intermediate file is in a work folder next to the card image (`TOTK_build`, or `--work`); running the script again reuses what is already done.

Each step is checked against the hashes in `games/totk/assets/expected-v1.0.0.json`: another version or a damaged dump stops the build at the first file that differs. Key values are never printed.

**3. Play:** open the app from Finder. You can move it to `/Applications` on the same disk: macOS already checked the new app during the build, and a move within one disk keeps that check (a copy on another disk is checked again when it first starts: a few minutes with nothing on screen). The first start verifies the game data once (about 20 seconds); new shaders are translated the first time a scene shows them (short stutters that do not come back).

## Controls

A game controller (DualSense, Xbox, …) works as a Switch Pro Controller, with rumble and motion. The keyboard:

| Key | Switch | | Key | Switch |
|---|---|---|---|---|
| W A S D | left stick | | arrow keys | right stick |
| J | A | | K, Space | B |
| I | X (jump) | | U | Y (attack) |
| Q / E | L / R | | Option / Shift | ZL / ZR |
| F T H G | d-pad left / up / right / down | | Z / C | left / right stick press |
| Return | + (menu) | | Tab, Esc | − (map) |

Extra keys: **1** MetalFX upscaling on / off, **2** frame interpolation (off → 30+30 → half the refresh rate → unlimited), **3** the game's own 2560×1440 output ↔ 1080p output upscaled by MetalFX. Text entry (naming a horse) uses the Mac keyboard.

## Where things are

- Saves: `~/Library/Application Support/MacNativeGames/TOTK/profile`
- Shader cache: `~/Library/Application Support/MacNativeGames/TOTK/shader-cache` (delete it to translate everything again)
- Log: `~/Library/Logs/MacNativeGames/totk.log` (the run before: `totk.previous.log`)

## Known issues

- Only the base game 1.0.0 as a card image (XCI); NSP and updates are not supported yet.
- No online features, no amiibo.
- The first time a scene appears, its shaders are translated (stutter); later visits are smooth.

## How it works

See [docs/how-it-works.md](docs/how-it-works.md).

## Acknowledgements

- **[d2r-mobile](https://github.com/jhaizhou-ops/d2r-mobile)** (MIT) developed this way of running Switch games natively (for Diablo II: Resurrected): the NSO rewriter, the Horizon host and the NVN-on-Metal layer here started as its generic parts.
- **[nxnative](https://github.com/seedds/nxnative)**: the one-script packaging from the user's own game files follows its approach.
- **Ryujinx** (MIT): its shader translator (`vendor/ryujinx`) turns the game's Maxwell shaders into SPIR-V, and its system-service code is a reference.
- **[ShaderLibrary](https://github.com/KillzXGaming/ShaderLibrary)** (MIT) reads the game's shader archives; **[SPIRV-Cross](https://github.com/KhronosGroup/SPIRV-Cross)** (Apache-2.0) turns SPIR-V into Metal Shading Language. Both are fetched at a pinned commit during the build.
- **deko3d** (zlib): texture layout sizes. **bcdec**: BC texture decoding. **libopus** and **libvpx** (BSD) from Homebrew: audio and the pre-rendered movies.

## License

MIT (see [LICENSE](LICENSE)). Third-party code keeps its own license: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

---

# 中文说明

在 Apple 芯片的 Mac 上原生运行你自己的《塞尔达传说 王国之泪》。准备好游戏卡带镜像（XCI）和你的 `prod.keys`，一个脚本就把它们做成一个 Mac App。

这不是模拟器：游戏自己的 ARM64 代码直接跑在苹果芯片上（只改写 macOS 不允许的地方），Switch 的系统服务由一个小宿主应答，游戏的 NVN 图形在 Metal 4 上重建。本仓库不含任何游戏内容，项目与任天堂无关。

## 需要准备

- Apple 芯片的 Mac，**macOS 26** 或更高（图形用 Metal 4）。16 GB 内存够用。
- 约 **25 GB** 空闲磁盘给打包用（成品 App 和工作目录在同一个卷上时是 APFS 克隆，不另占空间）。
- 你的《王国之泪》卡带镜像，**本体 1.0.0 版**（`0100F2C0115B6000`，约 17.5 GB），以及你的 `prod.keys`。更新版（1.1.x、1.2.x）暂不支持。

## 打包 App

**1. 工具**（只需一次）：Xcode 命令行工具和 [Homebrew](https://brew.sh)：

```
xcode-select --install
brew install opus libvpx cmake python@3.14
brew install --cask dotnet-sdk
```

**2. 运行脚本**，给出卡带镜像和密钥：

```
git clone <本仓库> MacNativeGames && cd MacNativeGames
python3 build_app.py ~/Games/totk.xci -k ~/keys/prod.keys
```

App 出现在卡带镜像旁边（`Tears of the Kingdom.app`；`-o` 指定别处）。第一次打包在 M4 Mac mini 上约 10 分钟（更慢的 Mac 和磁盘会更久），大头是改写主代码模块、解密 17 GB 的游戏数据，以及让 macOS 把做好的 App 检查一遍。所有中间文件都在卡带镜像旁边的工作目录里（`TOTK_build`，或用 `--work` 指定），再运行一次会复用已经做好的部分。

每一步都和 `games/totk/assets/expected-v1.0.0.json` 里的哈希核对：版本不对或镜像损坏，会在第一个对不上的文件处停下。密钥的值不会被打印。

**3. 游玩：** 在访达里打开 App。可以先拖进同一块磁盘上的“应用程序”：打包时 macOS 已经把新 App 检查过一遍，同一块磁盘里移动不用重新检查（拷到另一块磁盘上，第一次启动会再检查一遍：几分钟，屏幕上什么都没有）。第一次启动会把游戏数据校验一遍（约 20 秒）；新的着色器在场景第一次出现时翻译（短暂卡顿，之后不会再有）。

## 操作

游戏手柄（DualSense、Xbox 等）当作 Switch Pro 手柄用，带震动和体感。键盘：

| 按键 | Switch | | 按键 | Switch |
|---|---|---|---|---|
| W A S D | 左摇杆 | | 方向键 | 右摇杆 |
| J | A | | K、空格 | B |
| I | X（跳） | | U | Y（攻击） |
| Q / E | L / R | | Option / Shift | ZL / ZR |
| F T H G | 十字键 左 / 上 / 右 / 下 | | Z / C | 左 / 右摇杆按下 |
| Return | +（菜单） | | Tab、Esc | −（地图） |

额外按键：**1** 开关 MetalFX 放大，**2** 补帧（关 → 30+30 → 刷新率一半 → 不限帧），**3** 游戏自己输出 2560×1440 ↔ 输出 1080p 再由 MetalFX 放大。文字输入（给马取名）直接用 Mac 键盘。

## 文件位置

- 存档：`~/Library/Application Support/MacNativeGames/TOTK/profile`
- 着色器缓存：`~/Library/Application Support/MacNativeGames/TOTK/shader-cache`（删掉会全部重新翻译）
- 日志：`~/Library/Logs/MacNativeGames/totk.log`（上一次运行：`totk.previous.log`）

## 已知问题

- 只支持本体 1.0.0 的卡带镜像（XCI）；NSP 和更新版暂不支持。
- 没有联网功能，没有 amiibo。
- 场景第一次出现时要翻译它的着色器（会卡一下），以后再来就流畅了。

## 工作原理

见 [docs/how-it-works.md](docs/how-it-works.md)。

## 致谢

- **[d2r-mobile](https://github.com/jhaizhou-ops/d2r-mobile)**（MIT）为《暗黑破坏神 II：狱火重生》开发了这套原生运行 Switch 游戏的方法：这里的 NSO 改写器、Horizon 宿主和 Metal 上的 NVN 层都从它的通用部分起步。
- **[nxnative](https://github.com/seedds/nxnative)**：“用户自己的游戏文件 + 一个脚本出包”的做法借鉴自它。
- **Ryujinx**（MIT）：它的着色器翻译器（`vendor/ryujinx`）把游戏的 Maxwell 着色器转成 SPIR-V，它的系统服务代码也是参考。
- **[ShaderLibrary](https://github.com/KillzXGaming/ShaderLibrary)**（MIT）读游戏的着色器档案；**[SPIRV-Cross](https://github.com/KhronosGroup/SPIRV-Cross)**（Apache-2.0）把 SPIR-V 转成 Metal 着色语言。两者都在打包时按固定提交取得。
- **deko3d**（zlib）：贴图布局尺寸。**bcdec**：BC 贴图解码。**libopus**、**libvpx**（BSD，来自 Homebrew）：音频和预渲染影片。

## 许可证

MIT（见 [LICENSE](LICENSE)）。第三方代码保留各自的许可证：[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
