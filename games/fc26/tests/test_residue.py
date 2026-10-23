"""Nothing of another game in FC 26's own code: no Bayonetta 3 or Tears of the Kingdom title ID, no Bayonetta version
(1.2.0 / v120), no by3 name, outside the places that only record where the code came from.
ALLOWED names those places and why; docs/ESTORIA2_NUVEM.md lists every residue left there."""
from pathlib import Path
import re
import subprocess
import unittest

HERE = Path(__file__).resolve().parents[1]
PATTERN = re.compile(r'by3|bayonetta|0100F2C0115B6|01004A4010FEA|v120|1\.2\.0', re.I)
ALLOWED = {
    'docs/': 'the briefing, the story notes and the work log say which port this one is modelled on',
    'CHANGELOG.md': 'the work log names the model (games/by3)',
    'README.md': 'says where the folder was forked from',
    'third_party/d2r/': 'the rewriter, copied in story 1 and not touched here (patch_nso.py is another front\'s)',
    'third_party/d2r_gfx/': 'historical comments of the NVN-on-Metal layer (which game first needed each feature); '
                            'kept so fixes can be brought over from games/by3; nothing there is read at run time',
    'tests/test_residue.py': 'this test',
}


def source_files():
    """What git tracks here, plus new files it does not ignore: never the work folder, the RomFS or anything ignored."""
    run = subprocess.run(['git', '-C', str(HERE), 'ls-files', '--cached', '--others', '--exclude-standard', '-z', '--', '.'],
                         capture_output=True, text=True)
    if run.returncode:
        raise unittest.SkipTest('git is needed to list the source files')
    return sorted(HERE / name for name in run.stdout.split('\0') if name)


class Residue(unittest.TestCase):
    def test_no_other_game_outside_the_allowed_places(self):
        found = []
        for path in source_files():
            rel = path.relative_to(HERE).as_posix()
            if not path.is_file() or any(rel == a or rel.startswith(a) for a in ALLOWED):
                continue
            try:
                text = path.read_text()
            except UnicodeDecodeError:
                continue   # binaries (prebuilt/): the translator is the kit's, not a game's
            for n, line in enumerate(text.splitlines(), 1):
                if PATTERN.search(line):
                    found.append(f'{rel}:{n}: {line.strip()[:160]}')
        self.assertEqual(found, [], 'other-game residue:\n' + '\n'.join(found))


if __name__ == '__main__':
    unittest.main()
