# Building Amphigory Daemon

## Prerequisites

- macOS 12.0 or later
- Python 3.11+
- MakeMKV installed (for actual disc operations)

## Development Setup

```bash
cd daemon
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running from Source

```bash
source .venv/bin/activate
python -m amphigory_daemon.main
```

## Building the App Bundle

**Note:** py2app has known compatibility issues with Python 3.14 and modern setuptools.
For now, run from source (see above). App bundling will be improved in a future release.

If you want to try building anyway:

1. Install build dependencies:
   ```bash
   pip install py2app
   ```

2. Run the build script (works around pyproject.toml conflicts):
   ```bash
   ./scripts/build_app.sh
   ```

3. The app bundle will be at `dist/Amphigory Daemon.app`

**Alternative:** For reliable packaging, consider using Python 3.11 in a separate venv.

## Installation

1. Copy `dist/Amphigory Daemon.app` to `/Applications/`

2. First launch:
   - Double-click the app
   - Grant any necessary permissions when prompted
   - The daemon icon will appear in your menu bar

## Auto-Start at Login

To have Amphigory Daemon start automatically when you log in:

1. Copy the launchd plist:
   ```bash
   cp resources/com.amphigory.daemon.plist ~/Library/LaunchAgents/
   ```

2. Load it:
   ```bash
   launchctl load ~/Library/LaunchAgents/com.amphigory.daemon.plist
   ```

To disable auto-start:
```bash
launchctl unload ~/Library/LaunchAgents/com.amphigory.daemon.plist
rm ~/Library/LaunchAgents/com.amphigory.daemon.plist
```

## Regenerating Icons

If you need to regenerate the placeholder icons:

```bash
pip install Pillow
python scripts/generate_icons.py
python scripts/generate_app_icon.py
iconutil -c icns resources/AppIcon.iconset -o resources/AppIcon.icns
```

## Troubleshooting

### App won't start
- Check logs: `tail -f /tmp/amphigory-daemon.log`
- Ensure MakeMKV is installed at one of: `/opt/homebrew/bin/makemkvcon`, `/usr/local/bin/makemkvcon`, or `/Applications/MakeMKV.app/Contents/MacOS/makemkvcon`

### Menu bar icon doesn't appear
- The app runs as a menu bar app (no Dock icon)
- Look for the disc icon in the menu bar near the clock
- If not visible, check Activity Monitor for "Amphigory Daemon"

### Permission issues
- First run may require granting "Accessibility" permissions in System Preferences > Security & Privacy
- Disc access may require "Full Disk Access" permissions
