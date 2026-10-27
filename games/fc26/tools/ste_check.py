#!/usr/bin/env python3
"""Check English text against the measurable rules of ASD-STE100 (Simplified Technical English), issue 9.

usage: ste_check.py <file.md|file.sh> ...   (exit 1 if a rule fails)

It checks only what a program can check without the STE dictionary:
  - sentence length: 20 words for an instruction, 25 words for a description (rules 5.1, 6.1);
  - paragraph length: 6 sentences (rule 6.6);
  - passive voice: a form of "be" before a past participle (rule 3.2);
  - "-ing" words that are not technical names (rule 3.6);
  - contractions and common words that STE does not approve (rule 1.1), with the approved word.
Code (``` blocks, `inline`), headings, links and commands are not checked; each table cell is checked as a unit. In .md files only the English part is
checked: text from a heading "English" (or the file start, when there is no Portuguese part) to a heading "Português".
In .sh files only the English strings of the bilingual messages (the second argument of `step`, `die`, `say`) are checked.
The vocabulary list here is short. A full vocabulary check needs the ASD-STE100 dictionary.
"""
import re
import sys
from pathlib import Path

# Common words that STE does not approve, with the approved alternative (ASD-STE100 dictionary).
UNAPPROVED = {
    'ensure': 'make sure', 'utilize': 'use', 'utilise': 'use', 'require': 'necessary / must', 'requires': 'necessary / must',
    'required': 'necessary', 'provide': 'give', 'provides': 'give', 'obtain': 'get', 'perform': 'do', 'performs': 'do',
    'allow': 'let', 'allows': 'let', 'via': 'through', 'e.g.': 'for example', 'i.e.': 'that is', 'etc.': '(remove)',
    'please': '(remove)', 'simply': '(remove)', 'just': '(remove)', 'easily': '(remove)', 'basically': '(remove)',
    'should': 'must / can', 'might': 'can', 'may': 'can', 'could': 'can', 'would': 'will', 'once': 'after / when',
    'whether': 'if', 'prior': 'before', 'additional': 'more', 'approximately': 'about', 'commence': 'start',
    'terminate': 'stop', 'locate': 'find', 'modify': 'change', 'verify': 'make sure / check', 'attempt': 'try',
    'assist': 'help', 'select': 'choose', 'sufficient': 'enough', 'numerous': 'many', 'however': 'but',
}
BE = r'\b(is|are|was|were|be|been|being|am)\b'
PARTICIPLE = r'\b(\w+ed|built|made|done|given|taken|kept|found|shown|written|run|read|set|put|sent|left|held|known|seen|cut|lost|split|stored|spent)\b'
ING_OK = {'string', 'thing', 'nothing', 'something', 'anything', 'everything', 'during', 'bring', 'ring', 'spring', 'king',
          'swing', 'sing', 'wing', 'ping', 'ceiling', 'evening', 'morning', 'warning', 'warnings', 'setting', 'settings',
          'building', 'floating'}
IMPERATIVE = re.compile(r'^(?:\d+\.\s*)?(?:Do|Use|Run|Open|Put|Give|Keep|Make|Set|Type|Wait|Get|Install|Close|Click|Choose|'
                        r'Read|Write|Stop|Start|Add|Remove|Delete|Copy|Move|Check|Look|Tell|Ask|Find|Go|Let|Never|Always|'
                        r'Push|Pull|Download|Clone|Build|Quit|Show|Send|Change|Try|Follow|See|Plug|Connect|Select|Press)\b')


def english_blocks(path):
    text = path.read_text()
    if path.suffix == '.sh':
        text = re.sub(r'\\\n\s*', ' ', text)   # join continued lines: a message often goes on the next line
        for m in re.finditer(r'(?:^\s*|[;&|{]\s*|\b(?:then|else|do)\s+)(?:step|die|say|warn|info|skip)\s[^\n]*', text, re.M):
            parts = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(0))
            if len(parts) >= 2:
                yield text.count('\n', 0, m.start()) + 1, parts[1]   # pt-BR first, English second
        return
    lines, out, english = text.splitlines(), [], not re.search(r'^#+\s*portugu', text, re.I | re.M)
    in_code = False
    for n, line in enumerate(lines, 1):
        if line.startswith('```'):
            in_code = not in_code; out.append((n, '')); continue
        h = re.match(r'^#+\s*(.*)', line)
        if h:
            name = h.group(1).strip().lower()
            if name.startswith('english'):
                english = True
            elif name.startswith('portugu'):
                english = False
            out.append((n, '')); continue
        if english and not in_code and line.lstrip().startswith('|') and not re.match(r'^\s*\|[\s:|-]+\|?\s*$', line):
            for cell in line.strip().strip('|').split('|'):   # each table cell is its own unit
                if re.search(r'[A-Za-z]{3}', re.sub(r'`[^`]*`', '', cell)):
                    yield n, cell.strip()
            out.append((n, '')); continue
        if in_code or not english or line.lstrip().startswith(('|', '<', '>', '[!')):
            out.append((n, '')); continue
        out.append((n, line))
    para, start = [], None
    for n, line in out + [(len(lines) + 1, '')]:
        if re.match(r'^\s*(?:[-*]|\d+\.)\s', line):   # a list item is its own unit
            if para:
                yield start, ' '.join(para); para, start = [], None
            yield n, line.strip(); continue
        if line.strip():
            start = start or n; para.append(line.strip())
        elif para:
            yield start, ' '.join(para); para, start = [], None


def clean(s):
    s = re.sub(r'`[^`]*`', 'CODE', s)
    s = re.sub(r'"[^"]*"', 'QUOTE', s)   # quoted UI labels and program messages are not our sentences
    s = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', s)
    s = re.sub(r'https?://\S+', 'URL', s)
    return re.sub(r'[*_]', '', s)


def check(path):
    problems = []
    for line, para in english_blocks(path):
        text = clean(para)
        items = re.split(r'^\s*(?:[-*]|\d+\.)\s+', text) if re.match(r'^\s*(?:[-*]|\d+\.)\s', text) else [text]
        sentences = [s.strip() for item in items for s in re.split(r'(?<=[.!?:;])\s+(?=[A-Z"(])', item) if s.strip()]
        if len(sentences) > 6:
            problems.append((line, 'paragraph', f'{len(sentences)} sentences (max 6)'))
        for s in sentences:
            words = re.findall(r"[A-Za-z0-9][\w'./-]*", s)
            limit = 20 if IMPERATIVE.match(s) else 25
            if len(words) > limit:
                problems.append((line, 'length', f'{len(words)} words (max {limit}): {s[:90]}…'))
            if re.search(BE + r'(\s+(?:not|\w+ly))?\s+' + PARTICIPLE, s, re.I):
                problems.append((line, 'passive', s[:110]))
            for w in re.findall(r"\b[a-z]+ing\b", s):
                if w not in ING_OK:
                    problems.append((line, '-ing', f'"{w}": {s[:90]}'))
            if re.search(r"\b\w+'(t|s|re|ll|ve|d)\b", s) and re.search(r"\b(n't|it's|that's|there's|you're|we're|they're|you'll|it'll|you've|i'm)\b", s, re.I):
                problems.append((line, 'contraction', s[:110]))
            for w in re.findall(r"(?<![\w-])[A-Za-z][\w.]*(?![\w-])", s):   # not parts of command names (xcode-select)
                key = w.lower().rstrip('.') if w.lower() not in UNAPPROVED else w.lower()
                if key in UNAPPROVED:
                    problems.append((line, 'word', f'"{w}" -> {UNAPPROVED[key]}: {s[:80]}'))
    return problems


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    total = 0
    for name in sys.argv[1:]:
        for line, rule, detail in check(Path(name)):
            print(f'{name}:{line}: [{rule}] {detail}')
            total += 1
    print(f'{total} problem(s)')
    sys.exit(1 if total else 0)


if __name__ == '__main__':
    main()
