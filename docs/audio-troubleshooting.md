# Streamed audio: diagnosis, fix and validation

## Missing dialogue and intermittent background music

The observed failure affected long audio streams: subtitles appeared without
speech, and background music could play a short fragment and then fall silent.
Short effects could still work. These symptoms alone are not sufficient to
identify the cause; device routing and other runtime faults can also cause
audio problems.

In the reproduced case, the game constructed requests such as:

```text
content://Sound/Resource/Stream/Dm_OP_0001.bwav
```

The old RomFS parser removed exactly one separator after the mount name. Its
relative-path validator then rejected the remaining leading slash, returning
file-not-found even though the resource was present. Prefetched audio could
play while the remaining stream buffers contained zeros.

The fix in `games/totk/runtime/romfs_path.h` skips repeated separators immediately
after the mount prefix before validating the relative resource path. Mount
names still have to match. Empty resources, `.` and `..` components,
backslashes, and empty interior components remain rejected. Resource bytes,
shader code and save formats are unchanged.

## Rebuild and verify

1. Rebuild with the normal `build_app.py` command and your own original inputs.
   The same work directory can be reused. A rebuild to the same app path replaces
   the runtime; the profile and shader cache are stored outside the app.
2. Run the game-data-free parser regression:

   ```sh
   python3 -m unittest discover -s tests -p test_romfs_paths.py -v
   ```

3. With Python 3.14 and the build requirements installed, run the existing
   container/update tests together with the parser regression:

   ```sh
   python3.14 -m unittest discover -s tests -v
   ```

4. For local integration testing, the rebuilt runtime supports `probe-fs` and
   `probe-audio`. Run from its resource directory, for example:

   ```sh
   cd "/path/to/Tears of the Kingdom.app/Contents/Resources/totk"
   ./build/totk-native rewritten/v0 probe-fs
   ./build/totk-native rewritten/v0 probe-audio
   ```

   `probe-fs` checks that normal, double-slash and triple-slash paths read the
   same opening-audio bytes and still reject traversal. `probe-audio` checks
   constructed mixer/decoder state without opening an audio device; it does not
   prove that in-game streaming or the selected speaker/headphones are audible.
   For a 1.1.2 app, use `rewritten/v112` instead. The added resource integration
   checks have been exercised locally on 1.0.0, not on 1.1.2.

5. Play the opening scene and confirm both dialogue and background music through
   the intended output device. This listening check confirmed the 1.0.0 fix on
   an Apple M5 Mac running macOS 26.5.2.

## If sound is still missing

- Check the current macOS output device and volume. Test a known system sound;
  if that also fails, inspect the device connection first.
- Check `~/Library/Logs/MacNativeGames/totk.log` for CoreAudio setup failures,
  decode errors and output-level reports. A nonzero mixed level does not by
  itself prove the selected physical output is audible.
- For local file-open diagnostics, quit the game normally and launch with:

  ```sh
  open --env TOTK_FS_LOG=1 "/path/to/Tears of the Kingdom.app"
  ```

  A logged request is not proof of a successful open. Compare it with the
  parser regression and the rebuilt runtime's `probe-fs` results.
- First-use shader compilation can interrupt playback under load. That is a
  separate issue from repeated root separators and is not fixed by this patch.

Do not upload game packages, extracted resources, keys, saves, generated runtime
tables or complete logs when sharing a report. Describe the game version, the
scene, the output device, and relevant redacted error messages instead.

## 中文说明

这次确认的问题是：游戏将音频资源拼成了 `content://Sound/...`，旧版
RomFS 解析器只去掉一个根目录斜杠，随后又将剩余斜杠判为非法路径，导致
已有的配乐和对白资源打开失败。短音效或预读片段可能仍能播放，因此表现为
“有音效、对白缺失、背景音乐断续”。

修复仅规范化挂载根目录后的重复斜杠，并保留挂载名称、路径穿越、反斜杠和
非法内部路径的校验。使用原始游戏输入重新构建即可，存档和着色器缓存无需
删除。已有游戏资源本身不会因这项修复而被改写。

验证分三层：27 个无需游戏数据的解析器用例；`probe-fs` 对真实开场音频进行
单/双/三斜杠路径读取比对；最后实际播放开场，确认对白和配乐。音频混音自检
单独通过并不代表真实游戏流式播放正常。已实测 1.0.0 开场，不将结果外推为
所有场景、1.1.2 或其他游戏均已验证。

如果仍然无声，先确认 macOS 输出设备与系统提示音，再检查日志中的
CoreAudio/解码错误及音频电平。着色器首次编译造成的卡顿属于另一类问题。
