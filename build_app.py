#!/usr/bin/env python3
"""MacNativeGames: turn your own game card image into a native Mac app.

    python3 build_app.py <game.xci> -k <prod.keys> [-o "<output>.app"] [--work <folder>]

Supported: The Legend of Zelda: Tears of the Kingdom, base game version 1.0.0 (title 0100F2C0115B6000), as a game card
image (XCI). Nothing from the game is in this repository; everything is made from your files on your Mac, and key
values are never printed.

Steps (each one checked against games/totk/assets/expected-v1.0.0.json, so a damaged dump or another version stops the
build at the first wrong file):
  1. code: ExeFS out of the card image, the three code modules rewritten for Apple silicon (games/totk/third_party/d2r)
  2. data: RomFS (17 GB), the system shared fonts (from the card's own system update partition), the RomFS overlays
  3. shaders: the game's shader table (shader-map.tsv); the shader translator (vendor/ryujinx + patches, .NET) and
     SPIRV-Cross, both used by the game at run time to translate each shader once and cache it
  4. the game binary, the launcher, and the app bundle (the 17 GB RomFS is an APFS clone when on the same volume)

Every intermediate file is in the work folder (default: "<card image folder>/TOTK_build"); a second run reuses
what is already done and correct. The finished app keeps no writable state: saves, the shader cache and logs go to
~/Library/Application Support/MacNativeGames/TOTK and ~/Library/Logs/MacNativeGames.

Needs: macOS 26 or later on Apple silicon, the Xcode command line tools, Homebrew with
    brew install opus libvpx cmake python@3.14 && brew install --cask dotnet-sdk
"""
import argparse, hashlib, json, os, platform, shutil, subprocess, sys, threading, time
from pathlib import Path

REPO = Path(__file__).resolve().parent
GAME = REPO / 'games/totk'
EXPECTED = json.loads((GAME / 'assets/expected-v1.0.0.json').read_text())
APP_NAME = 'Tears of the Kingdom'
BUNDLE_ID = 'org.macnativegames.totk'
# Pinned upstream sources fetched at build time (repository, commit)
SHADER_LIBRARY = ('https://github.com/KillzXGaming/ShaderLibrary.git', '790dd2e501926e536a9193907d1256d446104162')
SPIRV_CROSS = ('https://github.com/KhronosGroup/SPIRV-Cross.git', 'aa217aeb6c9f0ace7a0ab233b28807edf45eb165')
TOOL_PATHS = ['/opt/homebrew/bin', '/usr/local/bin', '/usr/local/share/dotnet', os.path.expanduser('~/.dotnet')]


class BuildError(Exception):
    pass


def say(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def run(cmd, log, cwd=None, env=None, quiet=True):
    """Run a step with its whole output in log; on failure show the end of it. quiet: a line a minute instead of the output."""
    cmd = [str(c) for c in cmd]
    log.parent.mkdir(parents=True, exist_ok=True)
    done = threading.Event()

    def beat():
        t0 = time.time()
        while not done.wait(60):
            say(f'   ... still running ({(time.time() - t0) / 60:.0f} min)')
    if quiet:
        threading.Thread(target=beat, daemon=True).start()
    try:
        with open(log, 'w') as f:
            p = subprocess.run(cmd, cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT)
    finally:
        done.set()
    if p.returncode:
        tail = log.read_text(errors='replace').splitlines()[-25:]
        raise BuildError(f'{Path(cmd[1] if Path(cmd[0]).name.startswith("python") else cmd[0]).name} failed (exit {p.returncode}); '
                         f'full output: {log}\n' + '\n'.join(tail))


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(8 << 20):
            h.update(chunk)
    return h.hexdigest()


def check(what, got, want):
    if got != want:
        raise BuildError(f'{what}: SHA-256 {got[:16]}... is not the expected {want[:16]}... '
                         f'(is this Tears of the Kingdom 1.0.0, and the dump complete?)')


# ---- prerequisites ----
def find_dotnet(given):
    for p in ([given] if given else []) + [shutil.which('dotnet', path=os.pathsep.join(TOOL_PATHS + [os.environ.get('PATH', '')]))]:
        if p and Path(p).exists():
            exe = Path(p).resolve()
            r = subprocess.run([exe, '--list-sdks'], capture_output=True, text=True)
            if any(line.startswith('10.') for line in r.stdout.splitlines()):
                return exe
            raise BuildError(f'{exe}: no .NET SDK 10 (brew install --cask dotnet-sdk)')
    raise BuildError('dotnet not found: brew install --cask dotnet-sdk (or pass --dotnet <path to dotnet>)')


def prerequisites(args):
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise BuildError('needs a Mac with Apple silicon')
    major = int(platform.mac_ver()[0].split('.')[0] or 0)
    if major < 26:
        raise BuildError(f'needs macOS 26 or later (Metal 4); this is macOS {platform.mac_ver()[0]}')
    if subprocess.run(['xcrun', '--find', 'clang'], capture_output=True).returncode:
        raise BuildError('the Xcode command line tools are missing: xcode-select --install')
    brew = Path('/opt/homebrew')
    missing = [p for p in ('opus', 'libvpx') if not (brew / 'opt' / p / 'lib').is_dir()]
    if missing:
        raise BuildError(f'Homebrew packages missing: brew install {" ".join(missing)}')
    for tool in ('cmake', 'git'):
        if not shutil.which(tool, path=os.pathsep.join(TOOL_PATHS + ['/usr/bin'])):
            raise BuildError(f'{tool} not found: brew install {tool}')
    py = next((p for p in (shutil.which(n, path=os.pathsep.join(TOOL_PATHS)) for n in ('python3.14', 'python3.15')) if p), None)
    if not py:
        raise BuildError('Python 3.14 not found (the build reads zstd with the standard library): brew install python@3.14')
    return Path(py), find_dotnet(args.dotnet)


# ---- work folder ----
def git_fetch(url, commit, dst, log):
    if (dst / '.git').is_dir() and subprocess.run(['git', '-C', dst, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip() == commit:
        return
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    run(['git', '-C', dst, 'init', '-q'], log)
    run(['git', '-C', dst, 'fetch', '-q', '--depth', '1', url, commit], log)
    run(['git', '-C', dst, 'checkout', '-q', 'FETCH_HEAD'], log)


def link(path, target):
    if path.is_symlink() or path.exists():
        if path.is_symlink() and path.resolve() == Path(target).resolve():
            return
        path.unlink() if path.is_symlink() else shutil.rmtree(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)


def prepare_work(work, py, dotnet, logs):
    """work/totk: the game folder of this repository with the generated files inside it (the build scripts write
    extracted/, rewritten/, build/ and analysis/ next to themselves); its tooling/ points at the fetched sources."""
    tree = work / 'totk'
    tree.mkdir(parents=True, exist_ok=True)
    run(['rsync', '-a', f'{GAME}/', f'{tree}/'], logs / 'sources.log')
    src = work / 'src'
    say('fetching the pinned ShaderLibrary and SPIRV-Cross sources')
    git_fetch(*SHADER_LIBRARY, src / 'ShaderLibrary', logs / 'fetch-shader-library.log')
    git_fetch(*SPIRV_CROSS, src / 'SPIRV-Cross', logs / 'fetch-spirv-cross.log')
    link(tree / 'tooling/shader-library', src / 'ShaderLibrary')
    link(tree / 'tooling/spirv-cross', src / 'SPIRV-Cross')
    link(tree / 'tooling/d2r-mobile/dm/third_party/ryujinx', REPO / 'vendor/ryujinx')
    link(tree / 'tooling/dotnet', dotnet.parent)
    venv = work / 'venv'
    if not (venv / 'bin/python').exists():
        say('Python environment for the build tools')
        run([py, '-m', 'venv', venv], logs / 'venv.log')
    run([venv / 'bin/python', '-m', 'pip', 'install', '-q', '-r', tree / 'requirements.txt'], logs / 'pip.log')
    link(tree / '.venv', venv)
    (tree / 'analysis').mkdir(exist_ok=True)
    (tree / 'build').mkdir(exist_ok=True)
    return tree


# ---- steps ----
def step_code(tree, xci, keys, env, logs):
    py = tree / '.venv/bin/python'
    exefs = tree / 'extracted/v0/exefs'
    want = EXPECTED['exefs_sha256']
    if not all((exefs / n).exists() and sha256(exefs / n) == h for n, h in want.items()):
        say('1/4 code: extracting the ExeFS from the card image')
        if exefs.exists():
            shutil.rmtree(exefs)
        run([py, 'scripts/extract_exefs.py', xci, '--keys', keys, '--output', exefs], logs / 'extract_exefs.log', cwd=tree)
        for n, h in want.items():
            check(f'ExeFS {n}', sha256(exefs / n), h)
    if not (tree / 'extracted/v0/elf/main-inventory.json').exists():
        run([py, 'scripts/prepare_modules.py', exefs, '--output', tree / 'extracted/v0/elf'], logs / 'prepare_modules.log', cwd=tree)
    out = tree / 'rewritten/v0'
    out.mkdir(parents=True, exist_ok=True)
    for name in ('sdk', 'subsdk0', 'main'):
        image, h = out / f'{name}.patched.bin', EXPECTED['rewritten_sha256'][f'{name}.patched.bin']
        if image.exists() and sha256(image) == h:
            continue
        say(f'1/4 code: rewriting {name} for Apple silicon' + (' (the big one: several minutes)' if name == 'main' else ''))
        run([py, 'third_party/d2r/patch_nso.py', exefs / name, out, name], logs / f'rewrite_{name}.log', cwd=tree,
            env=dict(env, DM_RULESET='native', DM_PRIVATE_GATES='0'))
        check(f'rewritten {name}', sha256(image), h)
    # The loader binds itself to these images (scripts/prepare_runtime.py): they are the same bytes as the rewrite that
    # was verified site by site (python3 games/totk/scripts/verify_rewrites.py re-runs that verification, hours).
    report = dict(format=1, status='pass', rom_version='1.0.0', scope='hash match with the verified 1.0.0 rewrite',
                  module_file_sha256={**{f'extracted/v0/exefs/{n}': want[n] for n in ('main', 'sdk', 'subsdk0')},
                                      **{f'rewritten/v0/{n}.patched.bin': EXPECTED['rewritten_sha256'][f'{n}.patched.bin'] for n in ('main', 'sdk', 'subsdk0')}})
    (tree / 'analysis/phase12-validation.json').write_text(json.dumps(report, indent=2) + '\n')


def step_data(tree, xci, keys, logs):
    py = tree / '.venv/bin/python'
    romfs = tree / 'extracted/v0/romfs'
    index = romfs / 'index.json'
    ok = index.exists() and json.loads(index.read_text()).get('romfs_sha256') == EXPECTED['romfs']['sha256'] and \
        (romfs / 'romfs.bin').stat().st_size == EXPECTED['romfs']['size']
    if not ok:
        say('2/4 data: extracting and verifying the RomFS (17 GB, about 10 minutes)')
        if romfs.exists():
            shutil.rmtree(romfs)
        run([py, 'scripts/extract_romfs.py', '--keys', keys], logs / 'extract_romfs.log', cwd=tree)
        r = json.loads(index.read_text())
        check('RomFS', r['romfs_sha256'], EXPECTED['romfs']['sha256'])
    fonts = tree / 'extracted/firmware/shared-fonts'
    manifest = fonts / 'manifest.json'
    if not manifest.exists():
        say('2/4 data: the system shared fonts from the card\'s update partition')
        if fonts.exists():
            shutil.rmtree(fonts)
        run([py, 'scripts/extract_shared_fonts.py', '--keys', keys, '--xci', xci, '--output', fonts], logs / 'shared_fonts.log', cwd=tree)
    for f in json.loads(manifest.read_text())['fonts']:
        check(f'shared font {f["name"]}', f['sha256'], EXPECTED['shared_fonts_sha256'][f['name']])
    if not (tree / 'extracted/v0/romfs-patches/manifest.tsv').exists():
        say('2/4 data: RomFS overlays (quick-menu capture timing, game-over retry)')
        run([py, 'scripts/make_romfs_patches.py'], logs / 'romfs_patches.log', cwd=tree)
    if not (tree / 'extracted/v0/romfs-patches-out/2560x1440/manifest.tsv').exists():
        say('2/4 data: RomFS overlay for the 2560x1440 output (key 3 in the game)')
        run([py, 'scripts/make_output_res_overlay.py', '2560x1440'], logs / 'output_res_overlay.log', cwd=tree)


def step_shaders(tree, env, logs):
    py = tree / '.venv/bin/python'
    if not (tree / 'build/shader-map.tsv').exists():
        say('3/4 shaders: reading the game\'s shader archives (shader-map.tsv)')
        run([py, 'scripts/prepare_graphics_assets.py'], logs / 'graphics_assets.log', cwd=tree)
        run([tree / 'tooling/dotnet/dotnet', 'run', '--project', 'scripts/shader_inventory', '--',
             'extracted/v0/graphics', 'extracted/v0/shaders-v2'], logs / 'shader_inventory.log', cwd=tree, env=env)
        run([py, 'scripts/verify_shader_inventory.py'], logs / 'shader_map.log', cwd=tree)
    if not (tree / 'build/totk_xlate/totk_xlate.dll').exists():
        say('3/4 shaders: building the shader translator (Ryujinx, .NET)')
        run(['make', 'shader-tools', f'RYU_PINNED={REPO / "vendor/ryujinx"}'], logs / 'shader_tools.log', cwd=tree, env=env)
    if not (tree / 'build/spirv-cross/spirv-cross').exists():
        say('3/4 shaders: building SPIRV-Cross')
        run(['cmake', '-S', 'tooling/spirv-cross', '-B', 'build/spirv-cross', '-DCMAKE_BUILD_TYPE=Release',
             '-DSPIRV_CROSS_ENABLE_TESTS=OFF'], logs / 'spirv_cross_configure.log', cwd=tree, env=env)
        run(['cmake', '--build', 'build/spirv-cross', '-j', str(os.cpu_count())], logs / 'spirv_cross_build.log', cwd=tree, env=env)


def step_binary(tree, xci, keys, env, logs):
    say('4/4 app: building the game binary and the launcher')
    run(['make', 'runtime'], logs / 'runtime.log', cwd=tree, env=env)
    run(['xcrun', 'clang', '-fobjc-arc', '-O2', '-Wall', '-Ithird_party/d2r_gfx/gfx/nvn', 'app/launcher.m', '-framework', 'AppKit',
         '-o', 'build/app-launcher'], logs / 'launcher.log', cwd=tree, env=env)
    if not (tree / 'build/AppIcon.icns').exists():   # the game's own icon from its control data; optional
        try:
            run([tree / '.venv/bin/python', 'scripts/extract_app_icon.py', xci, '--keys', keys, '--output', 'build/AppIcon.icns'],
                logs / 'app_icon.log', cwd=tree)
        except BuildError as e:
            say(f'   no app icon, the app gets the default one ({str(e).splitlines()[0]})')


def clone(src, dst):
    """APFS clone when on the same volume (no extra space), else a copy."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if subprocess.run(['cp', '-c', src, dst], capture_output=True).returncode:
        shutil.copy2(src, dst)


def copy_tree(src, dst):
    for p in sorted(src.rglob('*')):
        if p.is_file():
            clone(p, dst / p.relative_to(src))


def dotnet_runtime(tree, dst):
    """Only what runs the translator: the dotnet host, hostfxr and the Microsoft.NETCore.App version it targets."""
    root = (tree / 'tooling/dotnet').resolve()
    cfg = json.loads((tree / 'build/totk_xlate/totk_xlate.runtimeconfig.json').read_text())['runtimeOptions']
    want = cfg.get('framework', cfg.get('frameworks', [{}])[0])['version'].split('.')[0]
    shared = sorted((root / 'shared/Microsoft.NETCore.App').glob(f'{want}.*'), key=lambda p: [int(x) if x.isdigit() else 0 for x in p.name.split('.')])
    fxr = sorted((root / 'host/fxr').glob(f'{want}.*'))
    if not shared or not fxr:
        raise BuildError(f'no .NET {want} runtime under {root}')
    clone(root / 'dotnet', dst / 'dotnet')
    copy_tree(fxr[-1], dst / 'host/fxr' / fxr[-1].name)
    copy_tree(shared[-1], dst / 'shared/Microsoft.NETCore.App' / shared[-1].name)


def step_app(tree, out, logs):
    tmp = out.with_name(out.name + '.partial')
    if tmp.exists():
        shutil.rmtree(tmp)
    res = tmp / 'Contents/Resources/totk'
    for rel in ('build/totk-native', 'build/pso_manifest.tsv', 'build/shader-map.tsv', 'build/spirv-cross/spirv-cross',
                'scripts/shader_service.py', 'rewritten/v0/main.patched.bin', 'rewritten/v0/sdk.patched.bin',
                'rewritten/v0/subsdk0.patched.bin', 'extracted/v0/romfs/romfs.bin', 'extracted/v0/romfs/runtime-index.bin'):
        clone(tree / rel, res / rel)
    for rel in ('build/totk_xlate', 'extracted/v0/romfs-patches', 'extracted/v0/romfs-patches-out', 'extracted/firmware/shared-fonts'):
        copy_tree(tree / rel, res / rel)
    dotnet_runtime(tree, res / 'tooling/dotnet')
    clone(tree / 'build/app-launcher', tmp / 'Contents/MacOS/TOTK')
    info = dict(CFBundleDevelopmentRegion='en', CFBundleExecutable='TOTK', CFBundleIdentifier=BUNDLE_ID, CFBundleName=APP_NAME,
                CFBundleDisplayName=APP_NAME, CFBundlePackageType='APPL', CFBundleShortVersionString=EXPECTED['display_version'],
                CFBundleVersion='1', LSMinimumSystemVersion='26.0', NSHighResolutionCapable=True,
                LSApplicationCategoryType='public.app-category.action-games', LSSupportsGameMode=True,
                GCSupportsControllerUserInteraction=True)
    icon = tree / 'build/AppIcon.icns'
    if icon.exists():
        clone(icon, tmp / 'Contents/Resources/AppIcon.icns')
        info['CFBundleIconFile'] = 'AppIcon'
    import plistlib
    (tmp / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    (tmp / 'Contents/PkgInfo').write_bytes(b'APPL????')
    if out.exists():
        shutil.rmtree(out)
    tmp.rename(out)


def parse_args(argv):
    ap = argparse.ArgumentParser(description='Build a native Mac app from your own Tears of the Kingdom 1.0.0 game card image.',
                                 epilog='example: python3 build_app.py ~/Games/totk.xci -k ~/keys/prod.keys')
    ap.add_argument('xci', type=Path, help='the game card image (.xci), base game 1.0.0')
    ap.add_argument('-k', '--keys', type=Path, required=True, help='your prod.keys')
    ap.add_argument('-o', '--out', type=Path, help=f'the app to write (default: "{APP_NAME}.app" next to the card image)')
    ap.add_argument('--work', type=Path, help='work folder (default: TOTK_build next to the card image)')
    ap.add_argument('--dotnet', help='the dotnet executable to use (default: from PATH or the usual install folders)')
    return ap.parse_args(argv)


def main(argv):
    args = parse_args(argv)
    xci, keys = args.xci.expanduser().resolve(), args.keys.expanduser().resolve()
    if not xci.is_file():
        raise BuildError(f'no such file: {xci}')
    if not keys.is_file():
        raise BuildError(f'no such file: {keys}')
    out = (args.out.expanduser().resolve() if args.out else xci.parent / f'{APP_NAME}.app')
    work = (args.work.expanduser().resolve() if args.work else xci.parent / 'TOTK_build')
    if out.suffix != '.app':
        raise BuildError(f'the output must end in .app: {out}')
    py, dotnet = prerequisites(args)
    free = shutil.disk_usage(work.parent if work.parent.exists() else xci.parent).free / 2**30
    say(f'work folder {work} ({free:.0f} GB free on its volume)')
    if free < 25 and not (work / 'totk/extracted/v0/romfs/romfs.bin').exists():
        raise BuildError('needs about 25 GB free for the work folder (the app itself is an APFS clone of it when on the same volume)')
    logs = work / 'logs'
    env = dict(os.environ, PATH=os.pathsep.join(TOOL_PATHS + [os.environ.get('PATH', '/usr/bin:/bin:/usr/sbin:/sbin')]))
    t0 = time.time()
    tree = prepare_work(work, py, dotnet, logs)
    step_code(tree, xci, keys, env, logs)
    step_data(tree, xci, keys, logs)
    step_shaders(tree, env, logs)
    step_binary(tree, xci, keys, env, logs)
    say(f'4/4 app: assembling {out}')
    step_app(tree, out, logs)
    # macOS scans a new app the first time it runs (minutes for 16 GB, with nothing on screen): run it once here, in its
    # check-only mode, so the player's first start is immediate.
    say('4/4 app: macOS checks the new app once (a few minutes for the 16 GB bundle)')
    t1 = time.time()
    r = subprocess.run([out / 'Contents/MacOS/TOTK', '--check'], capture_output=True, text=True, timeout=1800)
    if r.returncode:
        raise BuildError(f'the app does not start: {(r.stdout + r.stderr).strip()}')
    say(f'   checked in {time.time() - t1:.0f} s')
    say(f'done in {(time.time() - t0) / 60:.0f} min: {out}')
    say('Open it from Finder (or move it to /Applications first: moving within one volume keeps the check). The first '
        'start verifies the 17 GB of game data once and translates shaders as they appear (short stutters the first '
        'time a scene is seen).')


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except BuildError as e:
        print(f'\nERROR: {e}', file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
