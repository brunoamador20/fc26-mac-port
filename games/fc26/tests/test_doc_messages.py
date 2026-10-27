"""Every error message that README.md and AGENTS.md quote in their problem tables is a message the build really prints:
when build.sh or a script changes a message, the documentation must change with it."""
import re
import unittest
from pathlib import Path

FC26 = Path(__file__).resolve().parents[1]
REPO = FC26.parents[1]
SOURCES = [FC26 / 'build.sh', FC26 / 'Makefile', *sorted((FC26 / 'scripts').glob('*.py')),
           *sorted((FC26 / 'third_party/d2r').glob('*.py'))]
NOT_OURS = {'No space left on device', 'rewrite.log'}   # macOS messages and file names


def quoted_messages(doc):
    for n, line in enumerate(doc.read_text().split('\n'), 1):
        if not line.startswith('|'):
            continue
        for a, b in re.findall(r'`([^`]{8,})`|"([^"]{8,})"', line.strip('|').split('|')[0]):
            pieces = [p.strip() for p in re.split(r'\.\.\.|…|<[^>]*>|--[a-z]+|\d+', a or b) if len(p.strip()) >= 8]   # option names and numbers are values the build fills in
            if pieces:
                yield n, max(pieces, key=len)


class DocMessages(unittest.TestCase):
    def test_quoted_messages_exist(self):
        text = '\n'.join(p.read_text() for p in SOURCES)
        missing = [f'{doc.name}:{n}: {m}' for doc in (REPO / 'README.md', REPO / 'AGENTS.md')
                   for n, m in quoted_messages(doc)
                   if m not in NOT_OURS and m not in text and re.sub(r'[^/\s]+$', '', m) not in text]   # a filled-in last value
        self.assertEqual(missing, [], 'messages quoted in the docs that the build does not print:\n' + '\n'.join(missing))


if __name__ == '__main__':
    unittest.main()
