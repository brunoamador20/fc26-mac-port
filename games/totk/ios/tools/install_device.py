#!/usr/bin/env python3
"""Sign the unsigned TOTK IPA with your own Xcode team and install it on a connected iPhone / iPad.

A free (Personal Team) Apple ID signs for 7 days, a paid membership for a year: run this again to renew. Reinstalling
with the same team and bundle identifier keeps the saves and the shader cache (they are in the app's Documents).

  python3 games/totk/ios/tools/install_device.py "Tears of the Kingdom.ipa" --device "Jack iPhone"

Xcode needs your Apple ID (Xcode > Settings > Accounts). The provisioning profile comes from a throwaway Xcode project
built with the same bundle identifier and entitlements (-allowProvisioningUpdates registers the device and the App ID).
"""
import argparse, hashlib, json, os, plistlib, re, shutil, subprocess, sys, tempfile, zipfile
from datetime import timezone
from pathlib import Path

ENTITLEMENT = 'com.apple.developer.kernel.increased-memory-limit'
CACHE = Path.home()/'Library/Caches/MacNativeGames/ios-signing'

def run(cmd, **kw): return subprocess.run([str(x) for x in cmd], check=True, **kw)
def out(cmd): return subprocess.run([str(x) for x in cmd], check=True, capture_output=True, text=True).stdout

def teams():
    pems = out(['security','find-certificate','-a','-c','Apple Development','-p'])
    found = set()
    for pem in re.findall(r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', pems, re.S):
        subject = subprocess.run(['openssl','x509','-noout','-subject'], input=pem, capture_output=True, text=True).stdout
        if m := re.search(r'OU\s*=\s*([A-Z0-9]{10})', subject): found.add(m.group(1))
    return sorted(found)

def devices():
    with tempfile.NamedTemporaryFile(suffix='.json') as f:
        run(['xcrun','devicectl','list','devices','--json-output',f.name], capture_output=True)
        return [d for d in json.load(open(f.name))['result']['devices']
                if d.get('hardwareProperties',{}).get('platform') == 'iOS']

def pick_device(name):
    devs = devices()
    match = [d for d in devs if name in (d['deviceProperties'].get('name'), d['identifier'], d['hardwareProperties'].get('udid'))] if name else devs
    if len(match) != 1:
        listed = '\n'.join(f"  {d['deviceProperties'].get('name')} ({d['hardwareProperties'].get('marketingName')})" for d in devs)
        sys.exit(f"choose the device with --device <name>:\n{listed}" if devs else 'no paired iPhone / iPad found: connect it with a cable and trust this Mac')
    return match[0]

def profile(team, bundle_id, udid):
    """Build an empty app with the game's bundle identifier and entitlements; Xcode makes the profile for it."""
    proj = CACHE/bundle_id; proj.mkdir(parents=True, exist_ok=True)
    (proj/'main.m').write_text('int main(void) { return 0; }\n')
    (proj/'TOTK.entitlements').write_bytes(plistlib.dumps({ENTITLEMENT: True}))
    (proj/'project.yml').write_text(f'''name: TOTKSigning
options: {{deploymentTarget: {{iOS: "26.0"}}}}
targets:
  TOTK:
    type: application
    platform: iOS
    sources: [main.m]
    settings:
      GENERATE_INFOPLIST_FILE: YES
      PRODUCT_BUNDLE_IDENTIFIER: {bundle_id}
      DEVELOPMENT_TEAM: {team}
      CODE_SIGN_STYLE: Automatic
      CODE_SIGN_ENTITLEMENTS: TOTK.entitlements
''')
    run(['xcodegen','generate','--quiet'], cwd=proj)
    derived = proj/'derived'
    log = proj/'xcodebuild.log'
    with log.open('w') as f:
        r = subprocess.run(['xcodebuild','-project','TOTKSigning.xcodeproj','-scheme','TOTK','-configuration','Debug',
                            '-destination',f'id={udid}','-derivedDataPath',str(derived),
                            '-allowProvisioningUpdates','-allowProvisioningDeviceRegistration','build'],
                           cwd=proj, stdout=f, stderr=subprocess.STDOUT)
    if r.returncode:
        errors = [l for l in log.read_text(errors='replace').splitlines() if 'error:' in l]
        sys.exit('Xcode could not make a provisioning profile:\n' + '\n'.join(errors[-8:]) + f'\nfull log: {log}')
    app = derived/'Build/Products/Debug-iphoneos/TOTK.app'
    return app/'embedded.mobileprovision', app

def identity_of(signed_app):
    """The SHA-1 of the certificate Xcode signed the empty app with: the same identity signs the game."""
    with tempfile.TemporaryDirectory() as d:
        run(['codesign','-d','--extract-certificates='+d+'/cert','-v',signed_app], capture_output=True)
        der = Path(d+'/cert0').read_bytes()
    return hashlib.sha1(der).hexdigest().upper()

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('ipa', type=Path, help='the unsigned IPA from build_app.py --platform ios')
    ap.add_argument('--device', help='device name (as in Finder) or identifier; needed when several are paired')
    ap.add_argument('--team', help='Apple team ID (default: the only team with an Apple Development certificate)')
    ap.add_argument('--bundle-id', help='default: org.macnativegames.totk.<team>, so it is free to register on your team')
    a = ap.parse_args()
    team = a.team or (lambda t: t[0] if len(t) == 1 else sys.exit(
        f'choose the team with --team: {", ".join(t)}' if t else 'no Apple Development certificate: add your Apple ID in Xcode > Settings > Accounts'))(teams())
    bundle_id = a.bundle_id or f'org.macnativegames.totk.{team.lower()}'
    dev = pick_device(a.device)
    udid = dev['hardwareProperties']['udid']
    print(f"team {team}, bundle {bundle_id}, device {dev['deviceProperties'].get('name')} ({udid})")

    print('provisioning profile: asking Xcode')
    prov, signed = profile(team, bundle_id, udid)
    info = plistlib.loads(out(['security','cms','-D','-i',prov]).encode())
    ents = info['Entitlements']
    if not ents.get(ENTITLEMENT):
        print(f'warning: your team cannot grant {ENTITLEMENT}; iOS may close the game when it runs out of memory')
    expires = info['ExpirationDate'].replace(tzinfo=timezone.utc).astimezone()  # plistlib returns naive UTC
    print(f"provisioning profile valid until {expires:%Y-%m-%d %H:%M} local time (run this again before then)")

    # Unpack once per IPA; later runs only re-sign. 16 GiB of game data is signed in place.
    work = a.ipa.with_suffix('.signed'); stamp = work/'.ipa-mtime'
    app = work/'Payload/TOTK.app'
    if not stamp.is_file() or stamp.read_text() != str(a.ipa.stat().st_mtime_ns):
        print(f'unpacking {a.ipa.name}')
        shutil.rmtree(work, ignore_errors=True); work.mkdir()
        run(['ditto','-x','-k',a.ipa,work])
        stamp.write_text(str(a.ipa.stat().st_mtime_ns))
    plist = app/'Info.plist'
    infoplist = plistlib.loads(plist.read_bytes()); infoplist['CFBundleIdentifier'] = bundle_id
    plist.write_bytes(plistlib.dumps(infoplist, fmt=plistlib.FMT_BINARY))
    shutil.copy2(prov, app/'embedded.mobileprovision')
    entfile = work/'entitlements.plist'
    entfile.write_bytes(plistlib.dumps({k: ents[k] for k in ('application-identifier','com.apple.developer.team-identifier',
                                                                'get-task-allow', ENTITLEMENT) if k in ents}))
    print('signing (a few minutes: every game file is hashed)')
    run(['codesign','--force','--sign',identity_of(signed),'--entitlements',entfile,'--generate-entitlement-der',app])
    print('installing (a few minutes over the cable)')
    run(['xcrun','devicectl','device','install','app','--device',dev['identifier'],app])
    print('installed. First time on this device: Settings > General > VPN & Device Management > trust your Apple ID.')

if __name__ == '__main__': main()
