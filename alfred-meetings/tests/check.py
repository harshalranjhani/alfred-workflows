#!/usr/bin/env python3
"""Check list output, reminder menu, link detection and the package against a fake event cache."""
import json
import os
import pathlib
import plistlib
import subprocess
import tempfile
import time
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / 'workflow'
BIN = WORKFLOW / 'Meetings.app/Contents/MacOS/meetings'
cache = pathlib.Path(tempfile.mkdtemp())
env = dict(os.environ, MEETINGS_CACHE_DIR=str(cache))

def run(*args):
    return subprocess.run([str(BIN), *args], text=True, capture_output=True, env=env)

def items(query=''):
    result = json.loads(run('list', query).stdout)
    for item in result['items']:
        assert (WORKFLOW / item['icon']['path']).exists(), item
    return result

def write(status, events=()):
    (cache / 'events.json').write_text(json.dumps({'status': status, 'events': list(events)}))

now = time.time()
def event(title, start, minutes, **extra):
    return dict(title=title, start=now + start * 60, end=now + (start + minutes) * 60, calendar='Work',
                location='', ical='ical://ekevent/x/y?method=show', key=title, **extra)

# Link detection
for text, provider in [('Join https://us02web.zoom.us/j/8812345678?pwd=abc).', 'Zoom'),
                       ('meet: https://meet.google.com/abc-defg-hij', 'Google Meet'),
                       ('<https://teams.microsoft.com/l/meetup-join/19%3ameeting_x/0?context=y>', 'Microsoft Teams'),
                       ('https://acme.webex.com/meet/jane', 'Webex'),
                       ('https://www.example.com/room', 'example.com')]:
    found = json.loads(run('link', text).stdout)
    assert found['provider'] == provider and found['link'].startswith('https://') and not found['link'][-1] in '.)>', found
assert json.loads(run('link', 'no links, javascript:alert(1) file:///etc').stdout) == {}

# Setup and permission states
write('pending')
assert items()['rerun'] and not items()['items'][0]['valid']
write('denied')
assert items()['items'][0]['arg'].startswith('x-apple.systempreferences:')

# Meetings list
zoom = dict(link='https://zoom.us/j/1', provider='Zoom', icon='zoom')
write('granted', [event('Ended', -60, 30), event('Standup', -5, 15, **zoom), event('Design review', 12, 45),
                  event('Planning', 26 * 60, 30, link='https://meet.google.com/abc-defg-hij', provider='Google Meet', icon='meet')])
listed = items()
titles = [i['title'] for i in listed['items']]
assert titles[:3] == ['Standup', 'Design review', 'Planning'] and 'Ended' not in titles, titles
standup, review, planning, footer = listed['items']
assert standup['arg'] == 'https://zoom.us/j/1' and standup['icon']['path'] == 'icons/now.png' and 'Now' in standup['subtitle']
assert review['arg'].startswith('ical://') and 'In 12 min' in review['subtitle'] and not review['mods']['alt']['valid']
assert planning['icon']['path'] == 'icons/meet.png' and planning['mods']['alt']['arg'] == planning['arg']
assert footer['autocomplete'] == 'remind ' and not footer['valid'] and listed['skipknowledge']
assert [i['title'] for i in items('design')['items']] == ['Design review']
assert items('zzz')['items'][0]['title'] == 'No matching meetings'
write('granted')
assert items()['items'][0]['title'] == 'No meetings in the next 7 days'

# Reminder menu and actions
menu = items('remind')['items']
assert {'remind:5', 'remind:30', 'remind:60', 'preview', 'uninstall'} <= {i['arg'] for i in menu}
assert items('remind 45')['items'][0]['arg'] == 'remind:45'
for bad in ['0', '241', '-5', '1e2', '15; rm -rf ~', 'abc']:
    assert not items('remind ' + bad)['items'][0]['valid'], bad
for bad in ['remind:241', 'remind:abc', 'file:///Applications/Calculator.app', 'javascript:alert(1)', 'not a url']:
    assert run('act', bad).returncode != 0, bad

with zipfile.ZipFile(ROOT / 'dist/Meetings.alfredworkflow') as z:
    info = plistlib.loads(z.read('info.plist'))
    assert info['objects'][0]['config']['keyword'] == 'mt'
    assert (z.getinfo('Meetings.app/Contents/MacOS/meetings').external_attr >> 16) & 0o111
    assert 'icon.png' in z.namelist()
subprocess.run(['codesign', '--verify', '--strict', str(WORKFLOW / 'Meetings.app')], check=True)
print('PASS: link detection, setup states, list and filtering, reminder menu, input validation, workflow package')
