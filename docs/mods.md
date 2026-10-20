# Player mods

[English](#english) | [中文](#chinese)

<a id="english"></a>
## English

A mod reaches the game in one of two ways:

- **RomFS content** is loaded while the game runs. Whether a mod is used is decided by one file:
  `manifest.tsv`. The app does not scan folders for mods.
- **Code patches for the main module** (`exefs/main.pchtxt`, `exefs/*.ips`, `exefs/*.ips32`) are merged into
  the app **at build time** with `--mod`. See [Code patches](#code) below.

Nothing under `exefs/` is loaded while the game runs: the app runs the three code modules it was built from,
rewritten for Apple silicon and bound to their SHA-256. The build is the only place code can change.

The launcher points `TOTK_ROMFS_MODS` at

```text
~/Library/Application Support/MacNativeGames/TOTK/mods/<version>
```

where `<version>` is the game version the app was built from: `v0` (1.0.0), `v112` (1.1.2), `v121`
(1.2.1) or `v143` (1.4.3).

### What `manifest.tsv` is

Only the files listed in `manifest.tsv` are served. Each line has four tab-separated fields:

```text
<RomFS path>	<size>	<SHA-256 of the mod file>	<SHA-256 of the original, or ->
```

At startup the loader checks each listed file's size and SHA-256, and checks the original's SHA-256
against the game image. `-` in the last field adds a file the game's RomFS does not have (used by mods
that add assets). Paths are case-sensitive and keep the RomFS spelling.

A folder without `manifest.tsv` means "no mod". Files copied into the folder but not listed are not
used. In detail:

- A **new path** that is not listed is treated as absent: the game cannot see the file.
- A **replacement whose size or hash changed** without regenerating the manifest stops the start with
  `RomFS overlay file missing or wrong size` or `RomFS overlay integrity mismatch`.
- A path that exists in the game but is not listed is read from the game, so the copied file has no
  effect.

### Install a mod

1. Quit the game completely.
2. Copy the mod's RomFS paths **directly** into the version folder. If the mod ships a `romfs/` folder,
   copy its contents, not the folder itself:

   ```bash
   MODDIR="$HOME/Library/Application Support/MacNativeGames/TOTK/mods/v121"
   rsync -a --exclude='.DS_Store' --exclude='manifest.tsv' "/path/to/mod/romfs/" "$MODDIR/"
   ```

3. Generate the manifest with the app you built. Run this from the repository root:

   ```bash
   python3 games/totk/scripts/make_mod_manifest.py "$MODDIR" \
     --app "/path/to/Tears of the Kingdom.app" --version v121
   ```

   The script reads `Contents/Resources/totk/extracted/<version>/romfs` from the app, hashes each file
   and its original, leaves out files that are identical to the original, and writes `manifest.tsv`.
   It prints a line such as `...: 12 files (10 replaced, 2 added)`.

4. Start the game and check the log:

   ```bash
   grep "mods/v121 checked" "$HOME/Library/Logs/MacNativeGames/totk.log" | tail -1
   ```

   It should say `.../mods/v121 checked, N files`; additions also print `M files added to the RomFS`.

### Switching versions

The game reads the installed folder as it is; it does not follow the folder you downloaded or unpacked.
If the new version removes files, set the old version folder aside (or delete it after a backup) before
copying, or the removed files stay active. Generate the manifest again after every change.

<a id="code"></a>
### Code patches (build time)

A mod that changes the game's code ships `exefs/` files: an IPS or IPS32 patch, or the newer text form
(`.pchtxt`). Those can be merged into the app while it is built:

```bash
python3 build_app.py "/path/to/Tears of the Kingdom.xci" -k "/path/to/prod.keys" --mod "/path/to/Mod"
```

Why the build and not the game: the app has no module loader. At start it maps the three code modules it
was built from - main, sdk and subsdk0 - rewritten for Apple silicon and bound by SHA-256, and nothing in
it reads a mod's `exefs/` the way Ryujinx or a Switch does (that is the extra-module support of v2, see
below). So the code side goes in one step earlier: `--mod` merges the mod's main-module patches into the
verified retail module before it is rewritten, and the app ships code that still matches its hash. RomFS
(data) mods are not affected - they are still loaded at start, as described above.

With several mods, let the mod manager do the combining: TKMM's merged output is one folder with one
`exefs/` and one `romfs/` (a manager may also pack several mods' records into one `.ips`), so `--mod
<that folder>` picks all of them up, and its `romfs/` is installed as usual. Two patch files that change
the same bytes are refused with both names, so a merge that overwrote one mod's change with another's
stops the build instead of shipping silently.

The folder you pass holds the mod's files in the usual layout - `exefs/` for code, `romfs/` for data - and
its `romfs/` half is still installed separately (see above); the build only reads `exefs/`. With
`--update` the patch is merged into the updated module, which is the one the app runs.

What the build does, in order:

1. Extracts and verifies the retail ExeFS, as always. The patch is only ever applied to the verified
   retail module of the version being built, never to an already rewritten one.
2. Applies the mod's patches. Offsets are **main addresses** - the address space the game's code lives
   in, the same numbers the app's own patch tables use:

   - `.pchtxt`: the community format, read exactly as the runtime reads it. The first line must be
     `@nsobid-<build id>`: the 16 bytes the rewriter's tables use (32 hex digits) or the 20 bytes the
     runtime compares (40 hex digits; the runtime's own `TOTK_PCHTXT` experiment takes only that longer
     form). Patch lines `<hex main address> <hex bytes>` follow, and only lines between `@enabled` and
     `@stop` count. That line is what ties the file to this main, so it may be named anything.
   - `.ips` / `.ips32`: applied as emulators apply them, whose offsets count the 0x100-byte NSO header,
     so the build subtracts 0x100. A record below 0x100, a truncated file or a missing `EOF` is an error.
     The file names neither its module nor its build, so it is read as a main patch only when it is named
     `main`, or after main's build id (`exefs/<build id>.ips`, the Atmosphere and mod-manager
     convention). Anything else is left out with a note: a patch for `sdk` or `subsdk9`, or one named
     after another build of main. An `.ips` named `main` has no id to check, so name it after the build
     id, or ship a `.pchtxt`, when you want that check.

3. Checks the result before building on it. The patch is refused, with the address and the reason, when
   it lands outside main's text, rodata or data (the padding after text is reserved), when two patch
   files change the same bytes, when it changes nothing, or when it touches a site the app patches
   itself - the 60 FPS and real-time frame-step sites, render/output resolution, ultrawide, cloth, and
   the rewriter's registered cuts. Leave those features to the app (`TOTK_FPS60`, `TOTK_REALTIME`,
   `TOTK_RENDER_RES`, `TOTK_OUTPUT_RES`, `TOTK_ASPECT`): the runtime re-checks the original instruction
   at each of its sites and stops the game if it changed.
4. Rewrites the patched module for Apple silicon and binds the app to its SHA-256. The report in `--work`
   (`analysis/phase12-validation.json` for 1.0.0, `analysis/<version>-port/phase12-validation.json`
   otherwise, under `mod_exefs`) records the mod folder, every patch file's SHA-256, the addresses it
   changed and the merged module's hash.

The iPhone / iPad build merges the same way: `--mod` with `--platform ios`.

What else a mod's `exefs/` may hold:

| In the mod's `exefs/` | Result |
| --- | --- |
| `*.pchtxt`, `*.ips`, `*.ips32` for main | merged into the build; an `.ips` must be named `main` or after main's build id, while a `.pchtxt` names its build in `@nsobid-` and may be named anything |
| `main.npdm` | ignored with a note: the native loader never reads a module's metadata |
| `subsdk9` and other extra code modules | **not loaded**, with a note in the build output and in the report: the app loads the three modules it was built from (main, sdk, subsdk0), so the module's own code never runs |
| a whole replacement `main` | refused: ship a patch instead, so the build can check it against this version |

An extra module is how a mod built with a hooking framework (exlaunch and the like) changes code while
the game runs: its trampolines never install here. Such a mod - The Second Quest is one - keeps its main
patches and its whole RomFS, but not the part of its code changes that lives in that module. Making one
work means the app growing a module loader (rewriting the module for Apple silicon and answering its
service calls), which this version does not do; open an issue with the module and what it changes if you
need it.

Changing the mod after a build means building again (the mod's bytes are part of the app). A merge that
already happened is reused: the rewrite is skipped while the recorded hash matches.

### Notes

- Do not edit `manifest.tsv` by hand; regenerate it.
- Do not change files while the game runs. The loader records each file's identity at start and stops
  if a file changes mid-session.
- There is one overlay directory for player mods: to use several mods, merge their files into one
  version folder and generate one manifest. Do not nest mod folders. If two mods change the same path,
  choose one file.
- The build replaces a few RomFS files itself: `UI/LayoutArchive/Common.Product.<n>.Nin_NX_NVN.blarc.zs` (quick-menu
  timing; `<n>` is 100, 110 or 140 depending on the version), `Event/EventFlow/DmF_SY_GameOver.bfevfl.zs`, and with the
  2K output `System/HeapSize/Product.Nin_NX_NVN.HeapDef.byml.zs`. A mod replacing one of them cannot be loaded next to
  the app's own version (the start would stop with "two overlays replace the same file"), so the manifest leaves those
  paths to the app and says which file it left out (UI translation mods hit this, #73).
- `make_mod_manifest.py` handles all of them itself: a mod file whose path the app replaces is left out of the manifest
  (with a line saying so), because both overlays cannot be loaded. The heap table is the exception the build can fold in:
  with `--mod` the 2K overlay is built *on top of* the mod's table, so the mod's own heap sizes and the 2K texture heaps
  both hold, and the manifest line says whether the app's table carries them (`already carries these heap sizes`) or
  tells you to build with `--mod`.
- A mod manager (TKMM, or Ryujinx's `mods/contents/<title id>/<name>`) hands you `exefs/` and `romfs/` in one folder:
  pass that folder to `--mod` - its `exefs` patches are merged, and a manager's merged `.ips` may hold several mods'
  records in one file - then copy its `romfs/` into the version's mods folder and generate the manifest (no `--exclude`
  needed: the manager's heap table and the app's 2K overlay are reconciled for you). Generate the manifest again after
  every re-merge in the manager: the game checks every file's hash at start. This is also how several mods with code
  patches are combined: merge them in the manager first, then build with `--mod <the manager's output folder>`; the
  build refuses two patch files that change the same bytes and names both of them.
- A mod with a code patch also needs its `exefs/` patch to match the game version the app is built from.
  The build checks what the file itself says: a `.pchtxt` is refused when its `@nsobid-` names another
  main, and an `.ips` / `.ips32` named after a build id is left out when that id is not this main's.
- This guide covers the Mac app; installing mods into the iPhone/iPad app container is not covered.

### When the start stops

The game closes the window and writes one line to `~/Library/Logs/MacNativeGames/totk.log` instead of starting with data
it cannot trust. The line above it names the file.

- `two overlays replace the same file` - the manifest lists a path the app replaces itself: a manifest written by hand
  or by another tool, since `make_mod_manifest.py` leaves those paths out by itself. Regenerate it with that script.
- `two overlays add the same file` - two overlays (the app's, or two mod folders) add one path the RomFS lacks.
- `RomFS overlay integrity mismatch` - a file in the mods folder differs from the SHA-256 in the manifest: files were
  copied in after the manifest was written. Regenerate it (`make_mod_manifest.py` writes nothing for a mismatching dump).
- `RomFS overlay names a file the RomFS lacks` / `adds a file the RomFS already has` - a replacement's original is wrong
  (a file copied from another game version); regenerate the manifest and rebuild the app for that version.
- `RomFS overlay file changed while the game ran` - the folder was edited during play; restart the game (and regenerate
  the manifest).

The window can also vanish with no line of ours: a mod's data can make Metal abort the process (the log then has a host
call stack, for example `-[MTLTextureDescriptorInternal validateWithDevice:]` "requests 9 mipmap levels, but the
dimensions (1, 1, 1) can only support 1"). A texture with more mip levels than its size holds is something the Switch
never checks and Metal refuses to build; the app caps the chain at what the dimensions allow and logs
`[tex] <w>x<h>x<d> ... 声明 N 级 mip ...`, so check the mod's texture if the picture looks wrong.

<a id="chinese"></a>
## 中文

一个 mod 有两种方式进入游戏：

- **RomFS 内容**在游戏运行时加载，是否生效完全由 `manifest.tsv` 决定，App 不会扫描文件夹找 mod。
- **主模块的代码补丁**（`exefs/main.pchtxt`、`exefs/*.ips`、`exefs/*.ips32`）在**构建时**用 `--mod`
  合并进 App，见下面的「代码补丁（构建时合并）」。

`exefs/` 里的文件在运行时一律不加载：App 跑的是构建时改写好的三个代码模块，按 SHA-256 绑定。代码只能
在构建这一环节改变。

启动器把 `TOTK_ROMFS_MODS` 指向

```text
~/Library/Application Support/MacNativeGames/TOTK/mods/<version>
```

`<version>` 是构建这个 App 时使用的游戏版本：`v0`（1.0.0）、`v112`（1.1.2）、`v121`（1.2.1）、
`v143`（1.4.3）。

### manifest.tsv 是什么

只有列在 `manifest.tsv` 里的文件才会被提供给游戏。每一行是四个用制表符分开的字段：

```text
<RomFS 路径>	<大小>	<mod 文件的 SHA-256>	<原版文件的 SHA-256，或 ->
```

启动时加载器会逐个核对 mod 文件的大小和 SHA-256，并核对原版文件的 SHA-256。最后一个字段是 `-`
表示这是游戏 RomFS 里没有的新文件（用于新增资源）。路径区分大小写，必须和 RomFS 里的写法一致。

没有 `manifest.tsv` 就等于没有 mod。只把文件复制进目录但不写进清单，游戏不会使用：

- 清单里没有的**新路径**会被当成不存在，游戏完全看不到这个文件。
- 覆盖已有文件但大小或哈希变了、又没有重新生成清单，启动会直接报
  `RomFS overlay file missing or wrong size` 或 `RomFS overlay integrity mismatch`。
- 原版有这个路径、但清单里没列，游戏会读取原版文件，复制进去的文件看起来“没有效果”。

### 安装步骤

1. 先完全退出游戏。
2. 把 mod 的 RomFS 路径**直接**放进版本目录。如果 mod 带一层 `romfs/` 文件夹，复制的是它里面的
   内容，不是 `romfs` 这一层：

   ```bash
   MODDIR="$HOME/Library/Application Support/MacNativeGames/TOTK/mods/v121"
   rsync -a --exclude='.DS_Store' --exclude='manifest.tsv' "/path/to/mod/romfs/" "$MODDIR/"
   ```

3. 用你构建好的 App 生成清单。在仓库根目录执行：

   ```bash
   python3 games/totk/scripts/make_mod_manifest.py "$MODDIR" \
     --app "/path/to/Tears of the Kingdom.app" --version v121
   ```

   脚本会读取 App 里的 `Contents/Resources/totk/extracted/<version>/romfs`，计算每个文件和原版
   文件的哈希，跳过与原始完全相同的文件，然后写入 `manifest.tsv`。成功时会打印类似
   `...: 12 files (10 replaced, 2 added)` 的一行。

4. 启动游戏，确认日志：

   ```bash
   grep "mods/v121 checked" "$HOME/Library/Logs/MacNativeGames/totk.log" | tail -1
   ```

   应出现 `.../mods/v121 checked, N files`；有新增文件时还会打印 `M files added to the RomFS`。

### 换版本时

游戏读取的是安装目录本身，不会跟着你下载或解压的那个文件夹走。如果新版本删掉了旧版本的某些
文件，先把旧的版本目录整个移走（或备份后删除）再复制，否则被删掉的文件会继续生效。每次改动后
都要重新生成清单。

### 代码补丁（构建时合并）

改了游戏代码的 mod 会带 `exefs/` 文件：IPS、IPS32 补丁，或者新的文本格式 `.pchtxt`。这些可以在
构建 App 时合并进去：

```bash
python3 build_app.py "/path/to/Tears of the Kingdom.xci" -k "/path/to/prod.keys" --mod "/path/to/Mod"
```

为什么只能在构建时、而不是运行时：App 没有模块加载器。启动时它映射的是构建时的那三个代码模块（main、
sdk、subsdk0），已经改写为 Apple 芯片版本并按 SHA-256 绑定，里面没有任何东西会像 Ryujinx 或 Switch 那样去
加载 mod 的 `exefs/`（那是 v2 的额外模块支持，见下文）。所以代码这一半只能在更早一步进去：`--mod` 在改写
之前把 mod 的主模块补丁合并进核对过的原版模块，App 里跑的仍是与哈希一致的那份代码。RomFS（数据）部分不受
影响，仍按上面的说明在启动时加载。

有多个 mod 时，让模组管理器去做合并这件事：TKMM 的合并输出就是一个文件夹，里面一套 `exefs/`、一套
`romfs/`（管理器也可能把几个 mod 的记录合进同一个 `.ips`），`--mod <那个文件夹>` 会把它们一起收进来，
它的 `romfs/` 照常安装。两个补丁文件改到同一批字节时构建会拒绝并报出两个文件名，所以「合并时被另一个 mod
覆盖」这种情况会停在构建阶段，不会不声不响地打进去。

传入的文件夹按 mod 的常见结构放文件——代码在 `exefs/`、数据在 `romfs/`。构建只读 `exefs/`，
`romfs/` 那一半仍按上面的步骤单独安装。带 `--update` 时补丁合并进更新后的模块，也就是 App 实际运行的
那个。

构建做的事，按顺序：

1. 照常解出并核对原版 ExeFS。补丁只打在当前版本、核对过的原版模块上，绝不会打在已经改写过的模块上。
2. 打补丁。偏移量都是**主地址**（游戏代码所在的地址空间，和 App 自己补丁表用的数字一致）：

   - `.pchtxt`：社区文本格式，读取规则和运行时完全一致。第一行必须是 `@nsobid-<build id>`：改写器
     表里用的 16 字节（32 位十六进制）或运行时比较的 20 字节（40 位十六进制；运行时自己的
     `TOTK_PCHTXT` 实验只认长的这种）。后面是 `<十六进制主地址> <十六进制字节>` 行，只有 `@enabled`
     与 `@stop` 之间的行生效。这一行就是文件和这个 main 的绑定，所以文件名可以随便起。
   - `.ips` / `.ips32`：按模拟器的用法应用，其偏移量包含 0x100 字节的 NSO 头，构建时会减掉 0x100。
     偏移小于 0x100、文件截断、缺少 `EOF` 都算错误。这种文件本身不写模块名和 build id，所以只有名字是
     `main`，或者是 main 的 build id（`exefs/<build id>.ips`，Atmosphere 和模组管理器的约定）时才会
     当作 main 补丁读入；其余情况（给 `sdk`、`subsdk9` 的补丁，或者名字里是另一个 build id 的补丁）
     会留出清单并提示。名字叫 `main` 的 `.ips` 没有 id 可核对，想要这道检查就按 build id 命名，或者
     改成 `.pchtxt`。

3. 打完后先检查再往下走。以下情况会被拒绝，并指出地址和原因：补丁落在 main 的 text、rodata、data
   之外（text 之后的填充区是保留的）；两个补丁文件改同一批字节；补丁什么都没改；补丁改到了 App 自己
   打补丁的位置——60 帧与实时单帧步进的地址、渲染/输出分辨率、超宽屏、布料，以及改写器登记的 cut。
   这些功能请交给 App（`TOTK_FPS60`、`TOTK_REALTIME`、`TOTK_RENDER_RES`、`TOTK_OUTPUT_RES`、
   `TOTK_ASPECT`）：运行时会逐个核对那里原来的指令，被改了就直接停止游戏。
4. 把打过补丁的模块改写为 Apple 芯片版本，App 按它的 SHA-256 绑定。`--work` 里的报告（1.0.0 是
   `analysis/phase12-validation.json`，其他版本是 `analysis/<version>-port/phase12-validation.json`，
   字段 `mod_exefs`）记录 mod 目录、每个补丁文件的 SHA-256、改动的地址和合并后模块的哈希。

iPhone / iPad 构建同样处理：`--mod` 加 `--platform ios`。

mod 的 `exefs/` 里可能还有这些文件，构建这样处理：

| mod 的 `exefs/` 里 | 结果 |
| --- | --- |
| 给 main 的 `*.pchtxt`、`*.ips`、`*.ips32` | 合并进构建；`.ips` 必须叫 `main` 或按 main 的 build id 命名，`.pchtxt` 由 `@nsobid-` 指定版本、文件名任意 |
| `main.npdm` | 忽略并提示：原生加载器不读模块元数据 |
| `subsdk9` 等额外代码模块 | **不加载**：构建输出和报告里都会注明；App 只加载构建时的三个模块（main、sdk、subsdk0），模块自己的代码不会运行 |
| 整个替换的 `main` | 拒绝：请改成补丁，构建才能按版本核对 |

用 exlaunch 这类 hook 框架做的 mod，运行时改代码的部分就在这种额外模块里：它的 trampoline 在本 App
里不会安装。像 The Second Quest 这样的 mod，主模块补丁和整个 RomFS 都会生效，但依赖那个模块的那部分
代码改动不会。要支持它就得让 App 具备模块加载能力（把模块也改写为 Apple 芯片版本，并实现它用到的
服务），本版本没有做；需要的话请带上模块和它改了什么开个 issue。

构建之后再改 mod 就要重新构建（mod 的字节已经是 App 的一部分）。已经合并过的结果会复用：记录的哈希
一致时跳过改写。

### 注意

- 不要手改 `manifest.tsv`，每次重新生成。
- 游戏运行中不要改 mod 文件；加载器会在启动时记录每个文件的身份，运行中变化会停止游戏。
- 玩家 mod 只有一个覆盖目录：多个 mod 就合并到同一个版本目录，最后生成一份清单；不要把 mod
  文件夹嵌套进去。两个 mod 改同一个路径时，只能选一个文件。
- 构建本身也会替换几个 RomFS 文件：`UI/LayoutArchive/Common.Product.<n>.Nin_NX_NVN.blarc.zs`（快捷菜单时机，`<n>`
  按版本是 100、110 或 140）、`Event/EventFlow/DmF_SY_GameOver.bfevfl.zs`，开 2K 输出时还有
  `System/HeapSize/Product.Nin_NX_NVN.HeapDef.byml.zs`。模组如果也替换其中一个，就无法和 App 自己的版本同时加载
  （启动会报“two overlays replace the same file”），所以清单会把这些路径留给 App，并说明排除了哪个文件
  （界面翻译模组会碰到，见 #73）。
- 这些文件由 `make_mod_manifest.py` 自己处理：路径与 App 自身替换项相同的模组文件不会写进清单（并打印一行说明），
  因为两份覆盖无法同时加载。堆表是构建能合并的例外：带 `--mod` 时 2K 覆盖文件是**在模组那份堆表之上**生成的，模组自己的
  堆大小和 2K 贴图堆同时成立；清单那一行会告诉你 App 是否已经带着这些堆大小（`already carries these heap sizes`），
  否则提示你用 `--mod` 重新构建。
- 模组管理器（TKMM，或 Ryujinx 的 `mods/contents/<title id>/<name>`）给出的是同一个文件夹里的 `exefs/` 和 `romfs/`：
  把这个文件夹交给 `--mod`（里面的 `exefs` 补丁会合并，管理器合并出来的 `.ips` 可能一个文件里装着好几个模组的记录），
  再把它 `romfs/` 的内容拷进对应版本的 mods 目录并生成清单（不需要再手动 `--exclude`：管理器的堆表和 App 的 2K 覆盖
  文件会自动协调）。每次在管理器里重新合并后都要重新生成清单：游戏启动时会逐个校验文件哈希。多个带代码补丁的
  mod 也是这样合的：先在管理器里合并，再用 `--mod <管理器的输出文件夹>` 构建；两个补丁文件改到同一批字节时构建
  会拒绝，并同时报出这两个文件。
- 带代码补丁的 mod，其 `exefs/` 补丁也要和构建所用的游戏版本一致。构建按文件自己写的东西核对：`.pchtxt` 的
  `@nsobid-` 不是这个 main 就拒绝；按 build id 命名的 `.ips` / `.ips32`，id 不是这个 main 就留出并提示。
- 本文面向 Mac App；iPhone/iPad 的 App 容器内安装未在此说明。

### 启动停止时

游戏会关掉窗口，并在 `~/Library/Logs/MacNativeGames/totk.log` 写下最后一行原因，它上面一行就是出问题的文件。

- `two overlays replace the same file`：清单里列了 App 自己也会替换的路径——通常是手工写的清单或别的工具写的清单，
  因为 `make_mod_manifest.py` 自己就会把这类路径排除。用那个脚本重新生成即可。
- `two overlays add the same file`：两个覆盖（App 的或两个模组目录）新增了同一个 RomFS 里没有的路径。
- `RomFS overlay integrity mismatch`：模组目录里的文件和清单里的 SHA-256 不一致，也就是生成清单之后又拷了文件进去。
  重新生成清单即可（`make_mod_manifest.py` 遇到对不上的文件不会写清单）。
- `RomFS overlay names a file the RomFS lacks` / `adds a file the RomFS already has`：替换项的“原件”对不上（文件是从
  别的游戏版本拷来的）；按对应版本重新生成清单并重新构建 App。
- `RomFS overlay file changed while the game ran`：游戏运行中改了文件夹；重启游戏并重新生成清单。

窗口也可能直接消失、日志里没有上面这些行：某个模组的数据能让 Metal 直接终止进程（此时日志里有宿主调用栈，例如
`-[MTLTextureDescriptorInternal validateWithDevice:]` 报 “requests 9 mipmap levels, but the dimensions (1, 1, 1) can only
support 1”）。mip 级数超过尺寸允许的贴图在 Switch 上没人检查，Metal 却拒绝创建；App 会把级数裁到尺寸允许的数量并记一行
`[tex] <w>x<h>x<d> ... 声明 N 级 mip ...`，画面不对时应检查该模组的贴图。
