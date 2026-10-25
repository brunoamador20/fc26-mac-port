"""Explicit windowless LaunchServices probe. Run from the repo root under /tmp/fc26-boot.lock.
Builds only harmless stand-ins in work/build-modojogo. No real runtime is opened.
"""
from pathlib import Path
import json, os, re, subprocess, time
root = Path(__file__).resolve().parents[3]
out = root / 'work/build-modojogo'
work = out / 'mock-work'
home = out / 'mock-home'
(work / 'build-update').mkdir(parents=True, exist_ok=True)
flags = ['-std=gnu11','-O2','-Wall','-Wextra','-Werror','-fobjc-arc']
for src, exe, extra in [('app_mock_runtime.m',work/'build-update/fc26-native',[]),('launcher_open_test.m',out/'open-test',['-Wno-unused-function','-DFC26_RUNTIME_DIR="build-update"','-DFC26_VERSION_DIR="v1638400"','-DFC26_SHADER_CACHE="build-update/shader-cache/rt-update"'])]:
    subprocess.run(['xcrun','clang',*flags,*extra,str(root/'games/fc26/tests'/src),'-framework','Cocoa','-o',str(exe)],check=True)
logs = root / 'work/logs'
logs.mkdir(parents=True, exist_ok=True)
for stale in (work/'mock-report.json', work/'mock-expected.json'):
    stale.unlink(missing_ok=True)
# Only an explicit harmless environment is passed. No credentials go into the probe's report.
env = {'HOME':os.environ['HOME'],'PATH':'/usr/bin:/bin','TMPDIR':os.environ.get('TMPDIR','/tmp'), 'KEEP':'sentinel','FC26_AUDIO':'0','TOTK_HEADLESS':'1','TOTK_AUDIO_OFF':'1'}
with (logs/'modojogo_gamepolicy.log').open('w') as stream:
    logger = subprocess.Popen(['/usr/bin/log','stream','--info','--debug','--style','compact','--predicate','process == "gamepolicyd" OR process == "GamePolicyAgent"'],stdout=stream,stderr=subprocess.STDOUT)
    try:
        time.sleep(1)
        assert logger.poll() is None, 'log stream did not stay running'
        old_log=home/'Library/Logs/MacNativeGames/fc26.log'
        old_log.parent.mkdir(parents=True,exist_ok=True)
        old_log.write_text('previous sentinel')
        stale_input=home/'Library/Application Support/MacNativeGames/FC26/input.txt'
        stale_input.parent.mkdir(parents=True,exist_ok=True)
        stale_input.write_text('stale command')
        subprocess.run([str(out/'open-test'),str(work),str(home)],env=env,check=True)
        report = work/'mock-report.json'
        for _ in range(100):
            if report.exists(): break
            time.sleep(.1)
        data = json.loads(report.read_text())
        pid = data['pid']
        identity = subprocess.run(['/usr/bin/lsappinfo','info',str(pid)],capture_output=True,text=True)
        (logs/'modojogo_lsappinfo.txt').write_text(identity.stdout + identity.stderr)
        assert 'org.macnativegames.fc26.game' in identity.stdout, identity.stdout
        assert str(work/'launcher-apps/FC 26.app') in identity.stdout
        recorded_version = re.search(r'pV:(\d+)', identity.stdout)
        assert recorded_version and int(recorded_version[1]) == data['pidversion'], 'audit pidversion differs'
        assert data['cwd']==str(work)
        assert data['args']==['rewritten/v1638400','boot'], data['args']
        actual = data['environment']
        assert actual == json.loads((work/'mock-expected.json').read_text()), 'full environment differs'
        assert actual['KEEP']=='sentinel' and actual['DM_PRESENT_HZ']=='60'
        assert not any(k in actual for k in ('FC26_AUDIO','TOTK_HEADLESS','TOTK_AUDIO_OFF','FC26_APP_BOOTSTRAP'))
        input_file=home/'Library/Application Support/MacNativeGames/FC26/input.txt'
        assert input_file.read_bytes()==b''
        log=home/'Library/Logs/MacNativeGames/fc26.log'
        assert (log.parent/'fc26.previous.log').read_text()=='previous sentinel'
        assert 'mock stdout' in log.read_text() and 'mock stderr' in log.read_text()
        (logs/'modojogo_mock_report.json').write_text(json.dumps(data,indent=2))
        time.sleep(9)
    finally:
        logger.terminate() # Only our logger PID.
        logger.wait(timeout=10)
text=(logs/'modojogo_gamepolicy.log').read_text()
assert not any('mismatched pidversion' in line and str(pid) in line for line in text.splitlines())
print('MOCK PASS pid='+str(pid)+'; correct bundle, cwd, arguments, environment, empty input, both log streams; exited itself.')
print('No mismatched pidversion for mock PID in captured interval. Full-screen Game Mode NOT tested.')
