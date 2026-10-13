# Night Shift for Alfred

Toggle macOS Night Shift and set the same colour-temperature control shown in System Settings → Displays → Night Shift.

## Install

1. Download and open [Night Shift.alfredworkflow](dist/Night%20Shift.alfredworkflow?raw=true) and choose **Import** in Alfred.
2. Open Alfred, type `night`, and press Return.

Requires Alfred 5 with Powerpack and a Mac/display that supports Night Shift. The package includes a universal Apple Silicon / Intel executable. No Homebrew, runtime downloads, or Accessibility permission is needed.

## Commands

| Alfred input | Action on Return |
| --- | --- |
| `night` | Show current state; Return toggles Night Shift |
| `night toggle` | Toggle Night Shift |
| `night on` | Enable with the saved temperature |
| `night off` | Disable and return to normal display colour |
| `night 50` | Set warmth to 50% and enable Night Shift |
| `night 0` | Enable at the least-warm setting |
| `night 100` | Enable at the warmest setting |

Use any whole number from 0 to 100. The default menu also offers 25%, 50%, 75%, and 100% presets. Typing only previews an action; settings change on Return. This controls Night Shift, not the light/dark appearance of macOS apps. Temperature is expressed as the slider percentage, not Kelvin. Your macOS schedule is preserved and can still change Night Shift later.

## Build and check

Apple Command Line Tools and Python 3 are needed only to rebuild:

```sh
python3 build.py
python3 tests/check.py
# Briefly changes display warmth and state, then restores the original settings:
python3 tests/check.py --live
```

`src/night-shift.m` implements the helper using Foundation and dynamically loaded CoreBrightness. `build.py` compiles, ad-hoc signs, and packages it. `workflow/` is the unpacked workflow; `dist/` contains the importable package. For diagnostics, run `./workflow/night-shift status` or open Alfred's workflow debugger.

Verified locally on macOS 26.5.1: status, two-way toggling, explicit on/off, warmth at 0/75/100, invalid input rejection, preview side effects, and archive permissions. Restored the initial off / 50% settings. The Alfred UI import and Intel execution have not been exercised.

## Compatibility

Apple's CoreBrightness interface is private and may change in future macOS releases. The helper checks required methods and reports read/write failures. Display support and macOS restrictions still apply.

API references: [nightlight's CoreBrightness client](https://github.com/smudge/nightlight/blob/master/src/macos/client.rs), [status layout](https://github.com/smudge/nightlight/blob/master/src/macos/status.rs), and [Alfred's Script Filter documentation](https://www.alfredapp.com/help/workflows/inputs/script-filter/).

Created by [Harshal Ranjhani](https://harshalranjhani.in).
