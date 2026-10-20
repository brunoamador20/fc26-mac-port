#!/usr/bin/env python3
"""Replace a player's RomFS mod folder for one game version with a mod's romfs/, and write its manifest.

The app loads a RomFS mod while it plays, from
~/Library/Application Support/MacNativeGames/TOTK/mods/<version> (runtime/romfs.c through TOTK_ROMFS_MODS). A build with
--mod merges the mod's code patches; this module puts the data half there, and only when the build was asked to:
build_app.py --install-mod-romfs says that folder may be replaced. Nothing here runs for a build that leaves the flag out.

The folder is emptied first, then the mod's romfs/ is copied into it, so afterwards it holds exactly this mod's RomFS -
files another mod or the player left there are gone, and the build says so before it starts. scripts/make_mod_manifest.py
then writes manifest.tsv against the app the build just made, so the paths the app replaces itself are left out (the heap
table included: the 2K overlay carries the mod's heap sizes) and a misspelt path stops the build.

Nothing outside the folder is touched: the deletion never follows a symlink out of it, and the folder is the version's
own (one game version, one mod set). make_mod_manifest.py --check runs first, on the mod folder itself, so a folder that
would stop the game at start is reported while the player's folder has not been touched yet.
"""
from collections import namedtuple
from pathlib import Path
import shutil
import subprocess


def mods_folder(version):
    """<data>/mods/<version>: where the launcher points the game for a player's RomFS mods (runtime/romfs.c,
    TOTK_ROMFS_MODS)."""
    return Path.home() / 'Library/Application Support/MacNativeGames' / 'TOTK' / 'mods' / version


class InstallError(RuntimeError):
    """The mod folder would stop the game at start, or could not be written. `output` holds what the tool said, so the
    build can write it to its log."""

    def __init__(self, message, output=''):
        super().__init__(message)
        self.output = output


Installed = namedtuple('Installed', 'folder copied removed manifest')
Installed.__doc__ = """What one install did.

    folder     the player's mod folder that was replaced
    copied     how many files were copied out of the mod's romfs/
    removed    how many entries the folder held before and no longer does
    manifest   the manifest tool's output lines"""


def files_below(folder):
    """Every file under `folder` (symlinks to files included, symlinks to folders not followed)."""
    return sorted(p for p in folder.rglob('*') if p.is_file())


def empty(folder):
    """Delete everything inside `folder` and keep the folder itself; nothing outside it is followed or removed.
    Returns how many entries went."""
    removed = 0
    for child in sorted(folder.iterdir()):
        if child.is_symlink() or not child.is_dir():
            child.unlink()            # a symlink goes itself, not what it points at
        else:
            shutil.rmtree(child)
        removed += 1
    return removed


def copy_tree(source, dest):
    """Copy every file under `source` into `dest`, keeping modification times; returns the count."""
    copied = 0
    for file in files_below(source):
        target = dest / file.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, target)
        copied += 1
    return copied


def _manifest(py, tree, folder, app, version, check):
    """Run scripts/make_mod_manifest.py on `folder` against the app; returns the lines it printed.

    check=True is --check: it says what the manifest would hold and writes nothing, so a folder that would stop the game
    at start is found before the player's folder is emptied."""
    command = [str(py), str(tree/'scripts/make_mod_manifest.py'), str(folder), '--app', str(app), '--version', version]
    if check:
        command.append('--check')
    result = subprocess.run(command, cwd=tree, capture_output=True, text=True)
    output = (result.stdout + result.stderr).strip()
    lines = [line for line in output.splitlines() if line.strip()]
    if result.returncode:
        raise InstallError(lines[-1] if lines else f'make_mod_manifest.py failed ({result.returncode})', output)
    return lines


def install(mod, version, app, py, tree, *, say=print):
    """Replace the player's mod folder for `version` with `mod`'s romfs/ and write its manifest against `app`.

    Returns Installed; None when the mod has no romfs/ or an empty one, in which case nothing is touched."""
    source = mod/'romfs'
    folder = mods_folder(version)
    if not source.is_dir():
        say(f'{mod.name} has no romfs/, so {folder} is left as it is')
        return None
    if not files_below(source):
        say(f'{mod.name}/romfs holds no files, so {folder} is left as it is')
        return None
    _manifest(py, tree, source, app, version, check=True)      # the mod folder itself: nothing is written there
    if folder.is_symlink():
        raise InstallError(f'{folder} is a symlink; replace it with a real folder before --install-mod-romfs writes there')
    folder.mkdir(parents=True, exist_ok=True)
    say(f'{folder}: emptied, then filled with {mod.name}/romfs and its manifest.tsv (--install-mod-romfs)')
    removed = empty(folder)
    copied = copy_tree(source, folder)
    manifest = _manifest(py, tree, folder, app, version, check=False)
    return Installed(folder, copied, removed, manifest)
