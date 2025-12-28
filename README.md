# Amphigory

**Apple MakeMKV Plex Handbrake I Guess Other Random letters Yielded the rest**

Automated optical media ripping and transcoding for Plex. Insert a disc, review tracks, and queue them for ripping - all from a web interface.

## Architecture

Amphigory uses a split architecture to work around Docker Desktop for Mac's inability to access optical drives:

```
┌─────────────────────────────────────────────────────────────────┐
│                     macOS Host                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │               Amphigory Daemon (menu bar app)                ││
│  │  - OpticalDrive model (single source of truth)              ││
│  │  - Detects disc insert/eject                                ││
│  │  - Generates disc fingerprints for identification           ││
│  │  - Runs MakeMKV for scanning and ripping                    ││
│  │  - Writes ripped files to shared storage                    ││
│  │  - Bidirectional WebSocket with webapp                      ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ WebSocket + Shared Storage
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Docker Container                             │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │               Amphigory Webapp (FastAPI)                     ││
│  │  - Web UI for disc review and track selection               ││
│  │  - Task queue management                                    ││
│  │  - Database-backed disc/track storage (SQLite)              ││
│  │  - Queries daemon for drive state via WebSocket             ││
│  │  - HandBrakeCLI for transcoding                             ││
│  │  - Integrates with Plex media server                        ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

- **OpticalDrive Model**: The daemon maintains an `OpticalDrive` dataclass as the single source of truth for drive state (empty, disc inserted, scanning, scanned, ripping). The webapp queries this state via WebSocket instead of maintaining its own copy.

- **Fingerprint System**: When a disc is inserted, the daemon generates a lightweight fingerprint (<5 sec) based on disc structure:
  - DVDs: Hash of VIDEO_TS/*.IFO files
  - Blu-rays: Hash of BDMV/PLAYLIST/*.mpls files
  - CDs: Volume name (future: TOC hash)

  This allows instant recognition of known discs without re-scanning.

- **Bidirectional WebSocket**: The daemon pushes events (disc inserted, scan complete) to the webapp, and the webapp can query the daemon (get drive status, list drives). This replaces the previous one-way event model.

- **Database Schema**: The webapp stores disc and track metadata in SQLite with a `fingerprint` column (unique index) for quick lookups.

## Features

- **Disc Detection**: Automatic detection when optical media is inserted
- **Disc Fingerprinting**: Fast identification of known discs without re-scanning
- **Track Scanning**: MakeMKV-powered disc scanning with track classification
- **Track Selection**: Web UI for selecting which tracks to rip
- **Task Queue**: Queue multiple rip tasks with progress monitoring
- **Database Storage**: Persistent disc and track metadata with fingerprint-based lookups
- **Transcoding**: HandBrakeCLI integration for format conversion (post-launch)
- **Plex Integration**: Automatic organization for Plex media server (post-launch)

## Requirements

### macOS Host
- macOS 12.0+
- Python 3.11+
- MakeMKV installed
- Optical drive

### Docker Container
- Docker Desktop for Mac
- Port 6199 available

## Quick Start

### 1. Start the Webapp (Docker)

```bash
# Build and run the container
docker-compose -f docker-compose.amphigory.yaml up -d

# Or integrate with existing beehive-docker setup
```

The webapp will be available at http://localhost:6199

### 2. Start the Daemon (macOS)

```bash
cd daemon
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Run the daemon
python -m amphigory_daemon.main
```

The daemon will appear in your menu bar. See `daemon/BUILD.md` for app bundling instructions.

### 3. Configure the Daemon

On first launch, the daemon will prompt for:
- **Webapp URL**: http://localhost:6199
- **Data Directory**: Shared storage path (e.g., /Volumes/Media Drive 1/Ripped)

## Usage

1. **Insert a disc** - The daemon detects it and reports to the webapp
2. **Open http://localhost:6199/disc** - Review disc contents
3. **Select tracks** - Choose which tracks to rip
4. **Click "Rip Selected Tracks"** - Tasks are queued for the daemon
5. **Monitor progress** at http://localhost:6199/queue

## Directory Structure

```
/data/
├── tasks/
│   ├── queued/      # Tasks waiting for daemon
│   ├── in_progress/ # Currently processing
│   └── complete/    # Finished tasks with results
└── amphigory.db     # SQLite database

/media/ripped/       # Ripped MKV files
/media/plex/inbox/   # Files awaiting organization
/media/plex/data/    # Organized Plex library
```

## Configuration

### Environment Variables (Webapp)

| Variable | Default | Description |
|----------|---------|-------------|
| `AMPHIGORY_DATA` | `/data` | Data directory path |
| `AMPHIGORY_CONFIG` | `/config` | Configuration directory |
| `AMPHIGORY_RIPPED_DIR` | `/media/ripped` | Where ripped files go |
| `AMPHIGORY_INBOX_DIR` | `/media/plex/inbox` | Plex inbox directory |
| `AMPHIGORY_PLEX_DIR` | `/media/plex/data` | Plex library directory |

### Daemon Configuration

Stored in `~/.config/amphigory/daemon.yaml`:

```yaml
webapp_url: "http://localhost:6199"
webapp_basedir: "/Volumes/Media Drive 1/Ripped"
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/disc/status` | GET | Current disc status from daemon |
| `/api/disc/scan` | POST | Create a scan task |
| `/api/disc/scan-result` | GET | Get latest scan results |
| `/api/disc/lookup-fingerprint` | GET | Look up disc by fingerprint |
| `/api/drives` | GET | List all connected optical drives |
| `/api/drives/{drive_id}` | GET | Get specific drive status |
| `/api/tasks` | GET | List all tasks |
| `/api/tasks/scan` | POST | Create scan task |
| `/api/tasks/rip` | POST | Create rip task |
| `/api/tasks/{id}` | GET | Get task status |
| `/ws` | WebSocket | Bidirectional real-time updates |

## Development

```bash
# Webapp
cd /path/to/amphigory
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/

# Daemon
cd daemon
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/
```

## Post-Launch Roadmap

See `docs/plans/post-launch-followups.md` for planned improvements:
- Autoeject after ripping
- Unattended mode (auto-rip on disc insert)
- Library and Cleanup pages
- Wiki integration
- Safari layout fixes
- App bundle packaging improvements

## Acknowledgments

- **[csandman's MakeMKV CLI Guide](https://gist.github.com/csandman/ad221b9014cf88c29ccfa604d8507790)** - Invaluable reference for `makemkvcon` command-line options and automation techniques. The `disc:9999` trick for fast drive enumeration came from here.

## License

MIT
