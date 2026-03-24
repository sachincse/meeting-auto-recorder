# Meeting Auto-Recorder

Automatically detects meeting invitations from your email and records mic, speaker audio, and screen in the background — completely hidden and hands-free.

## How It Works

```
Emails arrive with calendar invites (.ics)
        |
Scans all configured IMAP accounts every 15 min
        |
Parses ICS data -> extracts meeting URL + time
        |
Stores in SQLite (deduped by URL + start time)
        |
APScheduler triggers 1 min before meeting
        |
Opens meeting URL in your default browser
        |
recordmymeeting captures mic + speaker + screen
        |
Auto-stops after meeting duration
        |
Saves recordings to your configured output path
```

## Features

- **Fully Hidden** — Runs in system tray with no visible window. Zero distraction.
- **Auto-Start on Boot** — Survives restarts. One command to enable.
- **Multiple Email Accounts** — Monitor personal + work inboxes simultaneously.
- **Audio Device Hot-Swap** — Switch between headphones and speakers mid-meeting; recording adapts automatically.
- **Global Hotkeys** — Toggle dashboard or emergency-stop a recording without touching the tray.
- **Configurable** — All settings in one `config.yaml`: output path, email accounts, hotkeys, scan frequency.
- **No LLM Required** — Meeting detection uses ICS calendar parsing + regex. Fast and free.

## Quick Start

### 1. Install

```bash
git clone https://github.com/sachincse/meeting-auto-recorder.git
cd meeting-auto-recorder
pip install -r requirements.txt
```

### 2. Configure

```bash
cp data/config.example.yaml data/config.yaml
```

Edit `data/config.yaml`:
- Add your email account(s) with IMAP credentials
- Set `recording.output_dir` to where you want recordings saved
- For Gmail, use [App Passwords](https://myaccount.google.com/apppasswords)

### 3. Enable Auto-Start (Recommended)

```bash
python main.py --install
```

This registers the app to start hidden on every Windows boot. That's it — you're done.

### 4. Start Now (Without Reboot)

```bash
python main.py --tray
```

Or for foreground mode:

```bash
python main.py --schedule
```

## Usage

| Command | Description |
|---------|-------------|
| `python main.py --tray` | Run hidden in system tray (background) |
| `python main.py --schedule` | Run continuously in foreground |
| `python main.py --scan` | One-shot: scan emails, record, exit |
| `python main.py --record URL` | Record a specific meeting right now |
| `python main.py --record URL --duration 3600` | Record for 1 hour |
| `python main.py --install` | Enable auto-start on Windows boot |
| `python main.py --uninstall` | Disable auto-start |
| `python main.py --status` | Show status, stats, upcoming meetings |

## System Tray

When running in `--tray` mode:

- **Green icon** = idle, monitoring emails
- **Red icon** = actively recording a meeting
- **Right-click menu**:
  - Status Dashboard
  - Stop Current Recording
  - Open Recordings Folder
  - Edit Config
  - Reload Config
  - Quit

## Hotkeys

| Hotkey | Action |
|--------|--------|
| `Ctrl+Shift+M` | Toggle status dashboard |
| `Ctrl+Shift+S` | Emergency stop current recording |

Hotkeys are configurable in `config.yaml` under `tray:`.

## Configuration

All settings live in `data/config.yaml`:

```yaml
# Monitor multiple email accounts
email_accounts:
  - name: "Personal Gmail"
    imap_host: "imap.gmail.com"
    imap_port: 993
    imap_user: "you@gmail.com"
    imap_pass: "xxxx xxxx xxxx xxxx"
    enabled: true

  - name: "Work Outlook"
    imap_host: "outlook.office365.com"
    imap_port: 993
    imap_user: "you@company.com"
    imap_pass: "your-password"
    enabled: true

# Where to save recordings
recording:
  output_dir: "C:/Users/You/Documents/MeetingRecordings"
  record_mic: true
  record_speaker: true
  record_screen: true
  video_fps: 10
  auto_open_meeting: true

# Scan frequency and timing
scheduler:
  timezone: "Asia/Kolkata"
  scan_cron: "*/15 * * * *"
  pre_meeting_buffer_min: 1

# Hotkeys
tray:
  hotkey_toggle_dashboard: "ctrl+shift+m"
  hotkey_stop_recording: "ctrl+shift+s"
  show_notifications: true
```

## What Gets Recorded

Each meeting creates a folder in your output directory:

```
MeetingRecordings/
  20260326_160000_Technical_Discussion/
    microphone.wav     # Your voice
    speaker.wav        # Other participants (system audio)
    merged.wav         # Both combined
    screen.mp4         # Screen capture
```

## Audio Device Hot-Swap

`recordmymeeting` monitors audio devices every 2 seconds. If you:
- Plug in headphones mid-meeting
- Switch from speakers to Bluetooth
- Disconnect and reconnect a USB mic

The recorder automatically detects the change and switches to the new device. No action needed.

## Supported Meeting Platforms

Meeting URLs are auto-detected from calendar invites:
- Google Meet
- Zoom
- Microsoft Teams
- Webex
- GoToMeeting

## Stopping & Managing

- **Stop recording**: `Ctrl+Shift+S` or tray menu > Stop Current Recording
- **Stop the app**: Tray menu > Quit
- **Disable auto-start**: `python main.py --uninstall`
- **Update config**: Edit `data/config.yaml`, then tray menu > Reload Config (or it picks up changes on next scan)
- **View logs**: `data/recorder.log`

## Requirements

- Windows 10/11
- Python 3.11+

## License

MIT
