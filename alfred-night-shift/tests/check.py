#!/usr/bin/env python3
"""Run read-only checks; pass --live to exercise settings and restore them."""
import json
import pathlib
import subprocess
import sys
import time
import zipfile
import plistlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN = ROOT / 'workflow/night-shift'

def run(*args):
    return subprocess.run([str(BIN), *args], text=True, capture_output=True, check=True).stdout

def status():
    return json.loads(run('status'))

def apply(arg):
    run('apply', arg)
    time.sleep(.3)

before = status()
for query in ['', 'toggle', 'on', 'off', '0', '50', '100', ' 75 ']:
    result = json.loads(run('filter', query))
    assert result['items'][0]['valid'], query
for query in ['-1', '101', '50.5', 'nan', '1e2', '50; touch /tmp/no', '999999999999']:
    assert not json.loads(run('filter', query))['items'][0]['valid'], query
    assert subprocess.run([str(BIN), 'apply', query], capture_output=True).returncode != 0
assert status() == before, 'Preview or invalid input changed settings'
with zipfile.ZipFile(ROOT / 'dist/Night Shift.alfredworkflow') as z:
    info = plistlib.loads(z.read('info.plist'))
    assert info['objects'][0]['config']['keyword'] == 'night'
    assert (z.getinfo('night-shift').external_attr >> 16) & 0o111
print('PASS: previews, input validation, no preview side effects, workflow package')
if '--live' in sys.argv:
    assert abs(before['strength'] * 100 - before['warmth']) < .0001, 'Live check needs an integer starting warmth to restore exactly'
    try:
        apply('toggle')
        assert status()['enabled'] != before['enabled']
        apply('toggle')
        assert status()['enabled'] == before['enabled']
        for value in ['0', '75', '100']:
            apply(value)
            s = status()
            assert s['enabled'] and s['warmth'] == int(value), s
        apply('off')
        assert not status()['enabled']
        apply('on')
        assert status()['enabled']
    finally:
        apply(str(before['warmth']))
        apply('on' if before['enabled'] else 'off')
    assert status() == before, (status(), before)
    print('PASS: live toggle, on/off, warmth 0/75/100; original settings restored')
