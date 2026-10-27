"""The English text for people (README.md, AGENTS.md, CONTRIBUTING.md, games/fc26/README.md, build.sh messages) passes
tools/ste_check.py: the measurable rules of ASD-STE100 Simplified Technical English."""
import subprocess
import sys
import unittest
from pathlib import Path

FC26 = Path(__file__).resolve().parents[1]
REPO = FC26.parents[1]
FILES = [REPO / 'README.md', REPO / 'AGENTS.md', REPO / 'CONTRIBUTING.md', FC26 / 'README.md', FC26 / 'build.sh']


class Ste(unittest.TestCase):
    def test_english_text_passes_the_ste_checker(self):
        r = subprocess.run([sys.executable, str(FC26 / 'tools/ste_check.py'), *map(str, FILES)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)


if __name__ == '__main__':
    unittest.main()
