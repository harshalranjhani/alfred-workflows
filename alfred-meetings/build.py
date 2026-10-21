#!/usr/bin/env python3
"""Build the Meetings helper app, icons and an importable Alfred workflow using macOS tools."""
import pathlib
import plistlib
import shutil
import subprocess
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent
workflow = ROOT / 'workflow'
app = workflow / 'Meetings.app/Contents'
shutil.rmtree(workflow, ignore_errors=True)
(app / 'MacOS').mkdir(parents=True)
(app / 'Resources').mkdir()

with tempfile.TemporaryDirectory() as tmp:
    iconset = pathlib.Path(tmp) / 'AppIcon.iconset'
    subprocess.run(['xcrun', 'swift', str(ROOT / 'src/icons.swift'), str(workflow), str(iconset)], check=True)
    subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(app / 'Resources/AppIcon.icns')], check=True)
subprocess.run(['xcrun', 'clang', '-arch', 'arm64', '-arch', 'x86_64',
                '-mmacosx-version-min=14.0', '-fobjc-arc', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                '-O2', '-framework', 'AppKit', '-framework', 'EventKit', str(ROOT / 'src/meetings.m'),
                '-o', str(app / 'MacOS/meetings')], check=True)
with (app / 'Info.plist').open('wb') as f:
    plistlib.dump(dict(
        CFBundleIdentifier='local.harshal.meetings', CFBundleExecutable='meetings', CFBundleName='Meetings',
        CFBundleDisplayName='Meetings', CFBundlePackageType='APPL', CFBundleIconFile='AppIcon',
        CFBundleShortVersionString='1.0.0', CFBundleVersion='1', LSMinimumSystemVersion='14.0', LSUIElement=True,
        NSCalendarsFullAccessUsageDescription='Meetings reads your calendars to list upcoming meetings in Alfred and remind you before they start.',
    ), f)
subprocess.run(['codesign', '--force', '--sign', '-', str(workflow / 'Meetings.app')], check=True)

def obj(uid, kind, version, config):
    return dict(uid=uid, type='alfred.workflow.' + kind, version=version, config=config)

def link(destination, modifiers=0):
    return dict(destinationuid=destination, modifiers=modifiers, modifiersubtext='', vitoclose=False)

CMD, ALT = 1 << 20, 1 << 19
helper = './Meetings.app/Contents/MacOS/meetings'
info = dict(
    name='Meetings', bundleid='local.harshal.meetings.workflow', version='1.0.0',
    createdby='Harshal Ranjhani', description='See upcoming meetings, join with one key, and get reminded before they start.',
    disabled=False, webaddress='https://harshalranjhani.in',
    readme='Type mt to see meetings for the next 7 days from the macOS Calendar app. Return joins the call (Zoom, Google Meet, Teams, Webex), ⌘↩ opens the event in Calendar, ⌥↩ copies the meeting link. Type mt remind to change when reminders appear (default 30 minutes before), turn them off, or preview one. On first use, allow “Meetings” to access your calendars. Before deleting the workflow, run mt remind → Remove background agent.',
    objects=[
        obj('MT-INPUT', 'input.scriptfilter', 3, dict(
            keyword='mt', title='Meetings', subtext='Upcoming meetings · mt remind to set reminders',
            argumenttype=1, withspace=True, argumenttrimmode=0, argumenttreatemptyqueryasnil=False,
            alfredfiltersresults=False, alfredfiltersresultsmatchmode=0,
            script=f'{helper} list "$1"', scriptargtype=1, scriptfile='', type=0,
            escaping=0, queuemode=1, queuedelaymode=0, queuedelaycustom=0,
            queuedelayimmediatelyinitially=True, runningsubtext='Loading meetings…')),
        obj('MT-ACTION', 'action.script', 2, dict(
            script=f'{helper} act "$1"', scriptargtype=1, scriptfile='',
            type=0, escaping=0, concurrently=False)),
        obj('MT-NOTIFY', 'output.notification', 1, dict(
            title='Meetings', text='{query}', onlyshowifquerypopulated=True,
            removeextension=False, lastpathcomponent=False)),
        obj('MT-COPY', 'output.clipboard', 3, dict(
            clipboardtext='{query}', autopaste=False, transient=False, ignoredynamicplaceholders=False)),
    ],
    connections={
        'MT-INPUT': [link('MT-ACTION'), link('MT-ACTION', CMD), link('MT-COPY', ALT)],
        'MT-ACTION': [link('MT-NOTIFY')],
    },
    uidata={uid: dict(xpos=100 + i % 3 * 300, ypos=100 + i // 3 * 160)
            for i, uid in enumerate(['MT-INPUT', 'MT-ACTION', 'MT-NOTIFY', 'MT-COPY'])},
)
with (workflow / 'info.plist').open('wb') as f:
    plistlib.dump(info, f)
dist = ROOT / 'dist'
dist.mkdir(exist_ok=True)
archive = dist / 'Meetings.alfredworkflow'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
    for path in sorted(workflow.rglob('*')):
        z.write(path, path.relative_to(workflow))
print(archive)
