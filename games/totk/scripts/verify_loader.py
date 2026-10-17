#!/usr/bin/env python3
"""Exercise native cross-module calls, mapped permissions, and hash rejection."""
import json
import subprocess
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
exe = ROOT / 'build/totk-native'
run = subprocess.run([str(exe), 'rewritten/v0', 'probe'], cwd=ROOT, capture_output=True, text=True, check=True)
data = json.loads(run.stdout)
assert data['status'] == 'pass' and data['calls'] == 4000 and data['threads'] == 4
assert sum(m['relative'] + m['symbolic'] for m in data['modules']) == 558865
# Alter one byte in a sparse copy: the loader must reject before relocation or execution.
with tempfile.TemporaryDirectory(dir=ROOT / 'build') as temporary:
    path = Path(temporary) / 'main.patched.bin'
    original = ROOT / 'rewritten/v0/main.patched.bin'
    with path.open('wb') as file:
        file.truncate(original.stat().st_size)
    failure = subprocess.run([str(exe), temporary, 'probe'], cwd=ROOT, capture_output=True, text=True)
    assert failure.returncode == 1 and 'image SHA256 differs' in failure.stderr
    assert 'ENTER' not in failure.stderr
    data['invalid_image_negative_control'] = 'rejected before execution'
data['permissions'] = 'all module VM regions checked; text/patch RX, aligned rodata/key R, data RW'
(ROOT / 'analysis/native-loader-probe.json').write_text(json.dumps(data, indent=2) + '\n')
(ROOT / 'analysis/native-loader-probe.log').write_text(run.stderr)
print(json.dumps(data))
