#!/usr/bin/env python3
"""Build the native helper and an importable Alfred workflow using macOS tools."""
import pathlib
import plistlib
import subprocess
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent
workflow = ROOT / 'workflow'
workflow.mkdir(exist_ok=True)
subprocess.run(['xcrun', 'clang', '-arch', 'arm64', '-arch', 'x86_64',
                '-mmacosx-version-min=11.0', '-fobjc-arc', '-Wall', '-Wextra', '-Werror',
                '-O2', '-framework', 'Foundation', str(ROOT / 'src/night-shift.m'),
                '-o', str(workflow / 'night-shift')], check=True)
subprocess.run(['codesign', '--force', '--sign', '-', str(workflow / 'night-shift')], check=True)

def obj(uid, kind, version, config):
    return dict(uid=uid, type='alfred.workflow.' + kind, version=version, config=config)

info = dict(
    name='Night Shift', bundleid='local.harshal.night-shift', version='1.0.0',
    createdby='Harshal Ranjhani', description='Toggle Night Shift and control display warmth.',
    disabled=False, webaddress='https://harshalranjhani.in',
    readme='Type night and press Return to toggle Night Shift. Use night on, night off, or night 0–100 to set warmth and turn it on. 0 is least warm, not off. Existing macOS schedules still apply. Requires Alfred Powerpack. Uses the private macOS CoreBrightness API.',
    objects=[
        obj('NIGHT-INPUT', 'input.scriptfilter', 3, dict(
            keyword='night', title='Night Shift', subtext='Toggle or set warmth: night on / off / 0–100',
            argumenttype=1, withspace=True, argumenttrimmode=0, argumenttreatemptyqueryasnil=False,
            alfredfiltersresults=False, alfredfiltersresultsmatchmode=0,
            script='./night-shift filter "$1"', scriptargtype=1, scriptfile='', type=0,
            escaping=0, queuemode=1, queuedelaymode=0, queuedelaycustom=0,
            queuedelayimmediatelyinitially=True, runningsubtext='Reading Night Shift…')),
        obj('NIGHT-ACTION', 'action.script', 2, dict(
            script='./night-shift apply "$1"', scriptargtype=1, scriptfile='',
            type=0, escaping=0, concurrently=False)),
        obj('NIGHT-NOTIFY', 'output.notification', 1, dict(
            title='Night Shift', text='{query}', onlyshowifquerypopulated=True,
            removeextension=False, lastpathcomponent=False)),
    ],
    connections={
        'NIGHT-INPUT': [dict(destinationuid='NIGHT-ACTION', modifiers=0, modifiersubtext='', vitoclose=False)],
        'NIGHT-ACTION': [dict(destinationuid='NIGHT-NOTIFY', modifiers=0, modifiersubtext='', vitoclose=False)],
    },
    uidata={uid: dict(xpos=100 + i*300, ypos=100) for i, uid in enumerate(['NIGHT-INPUT','NIGHT-ACTION','NIGHT-NOTIFY'])},
)
with (workflow / 'info.plist').open('wb') as f:
    plistlib.dump(info, f)
dist = ROOT / 'dist'
dist.mkdir(exist_ok=True)
archive = dist / 'Night Shift.alfredworkflow'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
    for name in ['info.plist', 'night-shift']:
        z.write(workflow / name, name)
print(archive)
