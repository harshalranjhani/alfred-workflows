# Meetings for Alfred

See your upcoming meetings, join a call with one key, and get a reminder card before each meeting starts.

## Install

1. Download and open [Meetings.alfredworkflow](dist/Meetings.alfredworkflow?raw=true) and choose **Import** in Alfred.
2. Open Alfred and type `mt`. macOS asks to give **Meetings** access to your calendars; click **Allow**.

Requires Alfred 5 with Powerpack and macOS 14 or later. Meetings come from the macOS Calendar app, so every account added there (iCloud, Google, Exchange/Outlook) is included. No API keys, Homebrew, or runtime downloads are needed.

## Commands

| Alfred input | Shows | Return | ⌘ Return | ⌥ Return |
| --- | --- | --- | --- | --- |
| `mt` | Meetings for the next 7 days, soonest first | Join the call, or open the event if it has no link | Open the event in Calendar | Copy the meeting link |
| `mt design` | Meetings whose title, calendar, location or provider match | Same as above | | |
| `mt remind` | Lead-time presets (5, 10, 15, 30, 60 min), off, preview, remove agent | Apply the choice | | |
| `mt remind 45` | Custom lead time from 1 to 240 minutes | Save it | | |

Meetings in progress show a red **Now** badge. All-day, cancelled and declined events are hidden. Zoom, Google Meet, Microsoft Teams and Webex links are detected in the event URL, location and notes; any other web link in the URL or location is used as a fallback.

## Reminders

A small background agent (`~/Library/LaunchAgents/local.harshal.meetings.plist`) checks your calendar every 20 seconds and when it changes. When a meeting is within your lead time (30 minutes by default), a card appears in the top-right corner of the menu-bar display with a sound. Click **Join** or the card to join, or hover and click ✕ to dismiss it. It hides after 60 seconds unless you are hovering over it.

The card is drawn by the workflow rather than macOS Notification Center, because clickable system notifications require an app signed with a paid Apple Developer ID. As a result:

- Reminders still appear when Focus / Do Not Disturb is on.
- Cards are excluded from screen sharing and recordings.
- Missed reminders are not kept in Notification Center; `mt` always lists what's next.

If your Mac wakes from sleep inside the lead time, the reminder shows right away. Turn reminders off with `mt remind` → **Turn reminders off**; the meetings list keeps working. Before deleting the workflow, choose `mt remind` → **Remove background agent**. If you skip that, the agent removes itself when it notices the workflow is gone.

## Privacy

Calendar data stays on your Mac. The agent writes the next 7 days of meetings to `~/Library/Caches/local.harshal.meetings/events.json` so Alfred can list them instantly without calendar access of its own. Removing the background agent deletes this cache.

## Build and check

Apple Command Line Tools and Python 3 are needed only to rebuild:

```sh
python3 build.py
python3 tests/check.py
```

`src/meetings.m` is the helper: Alfred's list and action commands, plus the LaunchAgent that reads EventKit, writes the cache and shows reminder cards. `src/icons.swift` renders every icon from SF Symbols at build time. `build.py` compiles a universal `Meetings.app`, ad-hoc signs it, and packages the workflow. `workflow/` is the unpacked workflow; `dist/` contains the importable package. The checks use a fake event cache and never touch your calendar.

Each rebuild or workflow update produces a new ad-hoc signature, so macOS asks for calendar access again once afterwards. The running agent restarts itself on the new build.

Verified locally on macOS 26.5.1: calendar permission flow, real events listed with Google Meet detection, open-in-Calendar for recurring events, reminder card position and appearance in light and dark mode, and agent restart after a rebuild. Not exercised: Alfred's UI after import, a full reminder firing on schedule, multiple stacked cards, and Intel execution.

Created by [Harshal Ranjhani](https://harshalranjhani.in).
