# Meeting Auto-Recorder

Automatically detects meeting invitations from your email, schedules recordings, and captures mic + speaker + screen — all running silently in the background. No manual intervention needed.

## Current Status

| Component | Status | Notes |
|-----------|--------|-------|
| Email scanning (IMAP/ICS) | Done | Multi-account, Gmail App Passwords |
| Meeting detection (Zoom/Meet/Teams/Webex) | Done | ICS parsing + URL regex |
| Auto-recording (mic + speaker + screen) | Done | WASAPI loopback for speaker on Windows |
| Audio device hot-swap | Done | Auto-detects headphone/speaker changes every 2s |
| GUI Dashboard (Tkinter) | Done | 4 tabs: Upcoming, Record, Settings, History |
| System tray (hidden) | Done | Green=idle, Red=recording |
| Global hotkeys | Done | Ctrl+Shift+M (dashboard), Ctrl+Shift+S (stop) |
| Auto-start on boot | Done | Windows (registry) + macOS (launchd) |
| Cross-platform | Done | Windows fully tested, macOS supported (needs BlackHole for speaker) |
| Desktop notifications | Done | Windows toast + macOS osascript |
| Manual recording scheduler | Done | Enter URL + date/time from GUI |
| Multiple email accounts | Done | Configure in config.yaml |
| SQLite tracking | Done | Dedup, status tracking, recording paths |

## How It Works

```
Your Email Inbox
       │
       ▼
┌──────────────────────────┐
│  IMAP Scanner             │  Runs every 15 min (configurable)
│  Finds ICS calendar       │  Supports: Gmail, Outlook, Yahoo, any IMAP
│  invites with meeting URLs │
└───────────┬──────────────┘
            ▼
┌──────────────────────────┐
│  APScheduler              │  Creates a job 1 min before each meeting
│  Schedules recording at   │
│  meeting start time       │
└───────────┬──────────────┘
            ▼
┌──────────────────────────┐
│  recordmymeeting library  │  At scheduled time, silently records:
│  Captures:                │  - Microphone (PyAudio)
│  - mic (your voice)       │  - Speaker audio (WASAPI loopback)
│  - speaker (their voice)  │  - Screen (mss + OpenCV)
│  - screen                 │
└───────────┬──────────────┘
            ▼
    Session folder with:
    microphone.wav, speaker.wav, merged.wav, screen.mp4
```

The user joins the meeting normally in their own browser/app. The recorder runs invisibly in the background — no browser pop-ups, no distractions.

## Quick Start

### 1. Install

```bash
git clone https://github.com/sachincse/meeting-auto-recorder.git
cd meeting-auto-recorder
pip install -r requirements.txt
```

### 2. Configure

Copy and edit `data/config.yaml`:

```yaml
# Email accounts to monitor
email_accounts:
  - name: "Personal Gmail"
    imap_host: "imap.gmail.com"
    imap_port: 993
    imap_user: "you@gmail.com"
    imap_pass: "xxxx xxxx xxxx xxxx"   # Gmail App Password
    imap_folder: "INBOX"
    enabled: true

  - name: "Work Email"
    imap_host: "imap.gmail.com"
    imap_port: 993
    imap_user: "you@company.com"
    imap_pass: "xxxx xxxx xxxx xxxx"
    imap_folder: "INBOX"
    enabled: true

# Recording settings
recording:
  output_dir: "C:/Users/you/Documents/MeetingRecordings"
  record_mic: true
  record_speaker: true
  record_screen: true
  video_fps: 10
  auto_open_meeting: false   # Don't pop up browser — user joins on their own

# How often to scan emails
scheduler:
  timezone: "Asia/Kolkata"
  scan_cron: "*/15 * * * *"   # Every 15 minutes
  max_emails_to_scan: 500

# Audio device overrides (null = auto-detect)
devices:
  mic_index: null
  speaker_index: null

# Hotkeys
tray:
  hotkey_toggle_dashboard: "<ctrl>+<shift>+m"
  hotkey_stop_recording: "<ctrl>+<shift>+s"
  show_notifications: true
```

For Gmail, generate an App Password at https://myaccount.google.com/apppasswords

### 3. Run

```bash
# Recommended: run in system tray (hidden, persistent)
python main.py --tray

# Auto-start on every boot
python main.py --install
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `python main.py --tray` | Run hidden in system tray. Scans emails, auto-records meetings. Press Ctrl+Shift+M for dashboard. |
| `python main.py --install` | Enable auto-start on boot (Windows registry / macOS launchd). Recorder starts every time you turn on your computer. |
| `python main.py --uninstall` | Disable auto-start. |
| `python main.py --scan` | One-shot: scan emails once, schedule recordings, wait for them, exit. Good for testing. |
| `python main.py --schedule` | Continuous foreground mode with terminal output. Like --tray but visible. |
| `python main.py --record URL` | Record a meeting right now. Starts recording immediately. Add `--duration 3600` for 1 hour. |
| `python main.py --status` | Print status: auto-start, accounts, stats, upcoming meetings, hotkeys. |

## GUI Dashboard

Press **Ctrl+Shift+M** or click the tray icon to open:

| Tab | What You See |
|-----|-------------|
| **Upcoming Meetings** | Detected meetings from email, their status (scheduled/recording/recorded/failed), meeting stats, "Scan Now" button |
| **Record / Schedule** | Manually enter a meeting URL + date/time/duration to schedule a recording, or "Record Now" for immediate capture |
| **Settings** | Dropdown to select mic/speaker devices, change recording output path, save preferences |
| **History** | All past meetings with recording paths — double-click any row to open the recording folder |

## Platform-Specific Setup

### Windows (Speaker Capture)

Speaker audio capture uses WASAPI loopback via `pyaudiowpatch`. Works automatically on most systems.

If speaker capture fails:
1. Right-click speaker icon in taskbar > **Sound settings**
2. **More sound settings** > **Recording** tab
3. Right-click blank area > **Show Disabled Devices**
4. Right-click **Stereo Mix** > **Enable**

### macOS (Speaker Capture)

macOS requires a virtual audio device for system audio capture:

1. Install [BlackHole](https://existential.audio/blackhole/) (free, open-source)
2. Open **Audio MIDI Setup** > **+** > **Create Multi-Output Device**
3. Check your speakers + BlackHole 2ch
4. Set Multi-Output Device as system output
5. Set BlackHole device index in Settings tab

## Architecture

```
meeting-auto-recorder/
├── main.py                  # Entry point (--tray, --scan, --record, --install, --status)
├── src/
│   ├── config.py            # YAML config + user_prefs.yaml loader
│   ├── email_reader.py      # IMAP + ICS parsing, multi-account support
│   ├── meeting_scheduler.py # APScheduler jobs, manual scheduling, pause/resume
│   ├── meeting_recorder.py  # Wraps recordmymeeting library with config
│   ├── gui_dashboard.py     # Tkinter GUI (4 tabs, runs in background thread)
│   ├── tray_app.py          # System tray (pystray + pynput hotkeys)
│   ├── autostart.py         # Windows registry + macOS launchd
│   ├── notifier.py          # Cross-platform desktop notifications
│   └── db.py                # SQLite schema (meetings, scheduler_logs)
├── data/
│   ├── config.yaml          # Main configuration (hand-edited)
│   ├── user_prefs.yaml      # GUI-writable overrides (auto-generated)
│   ├── meetings.db          # SQLite database (auto-created)
│   └── recordings/          # Default output directory
└── requirements.txt
```

## Output Format

Each recorded meeting creates a session folder:

```
recordings/
└── 20260405_160000_Technical_Discussion/
    ├── microphone.wav    # Your voice
    ├── speaker.wav       # Interviewer/other participants (WASAPI loopback)
    ├── merged.wav        # Both channels mixed
    └── screen.mp4        # Screen recording at 10fps
```

**Key advantage**: Mic and speaker are saved as **separate files**, making it trivial to identify who said what — no speaker diarization needed.

## Supported Meeting Platforms

| Platform | Detection Method |
|----------|-----------------|
| Google Meet | ICS calendar invite + `meet.google.com` URL |
| Zoom | ICS + `zoom.us/j/` URL |
| Microsoft Teams | ICS + `teams.microsoft.com/l/meetup-join/` URL |
| Webex | ICS + `webex.com` URL |
| GoToMeeting | ICS + `gotomeeting.com` URL |

## Tech Stack

- **Python 3.11+**
- **recordmymeeting** — Audio/screen capture library (mic via PyAudio, speaker via pyaudiowpatch WASAPI loopback, screen via mss+OpenCV)
- **APScheduler** — Cron-based job scheduling
- **pystray** — System tray icon
- **pynput** — Cross-platform global hotkeys
- **icalendar** — ICS calendar parsing
- **aiosqlite** — Async SQLite
- **Tkinter** — GUI dashboard (no extra deps)
- **PyYAML** — Configuration

## Roadmap to Public Release

### What's Done
- Core recording pipeline (email > detect > schedule > record)
- GUI dashboard with all CRUD operations
- System tray with hotkeys
- Auto-start on boot
- Cross-platform support (Windows + macOS)
- SQLite tracking and deduplication
- Multiple email account support

### What's Needed for Public Release
- [ ] **PyPI package** — `pip install meeting-auto-recorder` with entry point
- [ ] **Installer** — Windows MSI/NSIS installer, macOS .dmg
- [ ] **First-run wizard** — GUI setup for email credentials on first launch
- [ ] **OAuth for Gmail** — Replace App Passwords with OAuth2 flow
- [ ] **Encryption** — Encrypt stored credentials at rest
- [ ] **Tests** — Unit tests for email parsing, scheduler, device detection
- [ ] **CI/CD** — GitHub Actions for testing + release builds
- [ ] **Documentation site** — MkDocs or similar
- [ ] **Linux support** — PulseAudio/PipeWire for speaker capture

## Related Projects

- **[interview-intelligence](https://github.com/sachincse/interview-intelligence)** — Analyzes recordings from this tool: transcription, Q&A extraction, answer rating, prep material generation
- **[recordmymeeting](https://github.com/sachincse/recordmymeeting)** — The underlying recording library

## License

MIT
