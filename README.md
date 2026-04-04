# Meeting Auto-Recorder

Automatically detects meeting invitations from your email, schedules recordings, and captures mic + speaker + screen — all running silently in the background.

## Features

- **Email scanning** — Monitors Gmail (or any IMAP) for calendar invites with Zoom, Google Meet, Teams, Webex, GoToMeeting links
- **Auto-recording** — Starts recording mic, system audio, and screen at meeting time
- **GUI Dashboard** — Tkinter-based dashboard with meeting list, manual scheduling, device selector, and recording history
- **System tray** — Runs hidden with tray icon; green = idle, red = recording
- **Global hotkeys** — `Ctrl+Shift+M` to toggle dashboard, `Ctrl+Shift+S` to stop recording
- **Auto-start on boot** — Windows (registry) and macOS (launchd) support
- **Device hot-swap** — Automatically detects when you switch between headphones and speakers
- **Manual device override** — Pick mic/speaker from the GUI if auto-detect fails
- **Multiple email accounts** — Monitor personal + work email simultaneously
- **Cross-platform** — Windows and macOS (macOS requires BlackHole for speaker capture)

## Quick Start

### 1. Install

```bash
git clone https://github.com/sachincse/meeting-auto-recorder.git
cd meeting-auto-recorder
pip install -r requirements.txt
```

### 2. Configure

Edit `data/config.yaml`:

```yaml
email_accounts:
  - name: "My Gmail"
    imap_host: "imap.gmail.com"
    imap_port: 993
    imap_user: "you@gmail.com"
    imap_pass: "xxxx xxxx xxxx xxxx"  # Gmail App Password
    imap_folder: "INBOX"
    enabled: true

recording:
  output_dir: "C:/Users/you/Documents/MeetingRecordings"
  record_mic: true
  record_speaker: true
  record_screen: true
```

For Gmail, generate an App Password at: https://myaccount.google.com/apppasswords

### 3. Run

```bash
python main.py --tray
```

This starts the app **hidden in the system tray** (small green icon in the taskbar). It will:
- Scan your configured email accounts every 15 minutes
- Detect meeting invitations (ICS calendar invites with Zoom/Meet/Teams links)
- Automatically start recording mic + speaker + screen 1 minute before each meeting
- Open the meeting URL in your default browser so you can join normally

Press **Ctrl+Shift+M** to open the GUI dashboard at any time.

### 4. Other Commands

| Command | What it does |
|---------|-------------|
| `python main.py --tray` | **Recommended.** Runs silently in system tray. Scans emails on schedule, auto-records meetings. Access the GUI dashboard with Ctrl+Shift+M or by clicking the tray icon. |
| `python main.py --install` | Registers the app to **auto-start on boot** (Windows: adds to registry startup, macOS: creates launchd plist). After this, the recorder runs every time you turn on your computer — no manual launch needed. |
| `python main.py --uninstall` | Removes auto-start. The app will no longer launch on boot. |
| `python main.py --scan` | **One-shot mode.** Scans your emails once, finds upcoming meetings, schedules recordings, then waits. Useful for testing — you can see exactly which meetings were detected. Exits after all scheduled recordings are done. |
| `python main.py --schedule` | Like `--scan` but **keeps running in the foreground** and re-scans every 15 minutes. Same as `--tray` but without the system tray icon (shows output in terminal). |
| `python main.py --record URL` | **Record a meeting right now.** Opens the URL in your browser and immediately starts recording mic + speaker + screen. Add `--duration 3600` to stop after 1 hour (in seconds), or omit for indefinite recording (stop via Ctrl+C or Ctrl+Shift+S). |
| `python main.py --status` | Prints a summary: auto-start status, email accounts configured, meeting stats (total/scheduled/recorded/failed), upcoming meetings, and hotkey bindings. Quick way to check everything is working. |

## Windows Setup (Speaker Capture)

Speaker/system audio capture uses WASAPI loopback via `pyaudiowpatch`. This works automatically on most Windows systems.

If speaker capture fails, enable **Stereo Mix**:
1. Right-click speaker icon in taskbar > **Sound settings**
2. Scroll to **More sound settings** > **Recording** tab
3. Right-click blank area > **Show Disabled Devices**
4. Right-click **Stereo Mix** > **Enable**

## macOS Setup (Speaker Capture)

macOS does not support system audio loopback natively. Install [BlackHole](https://existential.audio/blackhole/):

1. Download and install BlackHole 2ch
2. Open **Audio MIDI Setup** (Spotlight > "Audio MIDI Setup")
3. Click **+** > **Create Multi-Output Device**
4. Check your speakers + BlackHole 2ch
5. Set this Multi-Output Device as your system output
6. In `data/config.yaml`, set the speaker device to BlackHole's index (find it in Settings tab)

## GUI Dashboard

Press **Ctrl+Shift+M** (or click "Show Dashboard" in the tray menu) to open:

| Tab | Description |
|-----|-------------|
| **Upcoming Meetings** | Detected meetings with status, scan button, stats |
| **Record / Schedule** | Manual recording: enter URL, date/time, duration |
| **Settings** | Audio device selector, recording output path |
| **History** | All past meetings with recording paths (double-click to open) |

## Configuration

All settings live in `data/config.yaml`. GUI-changed settings (device overrides, output path) are stored separately in `data/user_prefs.yaml` so your config comments are preserved.

### Key Config Options

| Section | Key | Description |
|---------|-----|-------------|
| `email_accounts` | `imap_user/pass` | Email credentials (supports multiple accounts) |
| `recording` | `output_dir` | Where recordings are saved |
| `recording` | `record_mic/speaker/screen` | Toggle each capture source |
| `scheduler` | `scan_cron` | How often to check email (default: every 15 min) |
| `scheduler` | `max_emails_to_scan` | How many recent emails to scan per account |
| `devices` | `mic_index/speaker_index` | Override auto-detected audio devices |
| `tray` | `hotkey_toggle_dashboard` | Hotkey to show/hide dashboard |

## Architecture

```
meeting-auto-recorder/
├── main.py                  # Entry point (--tray, --scan, --record, --install)
├── src/
│   ├── config.py            # YAML config + user prefs loader
│   ├── email_reader.py      # IMAP scanning, ICS parsing, multi-account
│   ├── meeting_scheduler.py # APScheduler job management, DB tracking
│   ├── meeting_recorder.py  # Wrapper around recordmymeeting library
│   ├── gui_dashboard.py     # Tkinter GUI (4 tabs, threaded)
│   ├── tray_app.py          # System tray (pystray + pynput hotkeys)
│   ├── autostart.py         # Windows registry / macOS launchd
│   ├── notifier.py          # Cross-platform desktop notifications
│   └── db.py                # SQLite schema and helpers
├── data/
│   ├── config.yaml          # Main configuration
│   ├── user_prefs.yaml      # GUI-writable overrides (auto-generated)
│   └── meetings.db          # SQLite database (auto-created)
└── requirements.txt
```

## How It Works

1. **Email scan** — Connects via IMAP, finds ICS calendar attachments and meeting URLs in email bodies
2. **Meeting detection** — Parses ICS for VEVENT entries, extracts start/end times and meeting URLs (Zoom, Meet, Teams, Webex)
3. **Scheduling** — APScheduler creates a job 1 minute before each meeting start time
4. **Recording** — At scheduled time, opens meeting URL in browser and starts `recordmymeeting` (mic via PyAudio, speaker via WASAPI loopback, screen via mss+OpenCV)
5. **Device monitoring** — Every 2 seconds, checks if audio devices changed and switches automatically
6. **Persistence** — All meetings tracked in SQLite to avoid duplicates

## CLI Reference

| Command | Description |
|---------|-------------|
| `python main.py --tray` | Run hidden in system tray (recommended for daily use) |
| `python main.py --scan` | One-shot: scan emails, schedule recordings, wait, then exit |
| `python main.py --schedule` | Continuous foreground mode (like --tray but with terminal output) |
| `python main.py --record URL` | Record a specific meeting immediately |
| `python main.py --record URL --duration 3600` | Record for exactly 1 hour (seconds) |
| `python main.py --install` | Enable auto-start on system boot |
| `python main.py --uninstall` | Disable auto-start |
| `python main.py --status` | Print status summary and exit |

## License

MIT
