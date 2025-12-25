# Post-Launch Followups

Items deferred to focus on getting to a fully functional system first.

## Drive operations
- [ ] Disable "Scan Disc" button (and other drive action buttons) if the drive is currently busy
- [ ] Provide a way to stop the currently running disk activity (scanning, ripping)
- [ ] Recognize when a scan has taken too long and stop it

## Logging

- [x] Webapp WebSocket logging showing daemon_id on connect/disconnect (completed in refactor)
- [ ] Log logging level on webapp and daemon startup
- [ ] Log logging level changes when config is updated

## Daemon
- [ ] Show current scan duration in menu instead of percentage complete

## Packaging

- [ ] Resolve py2app/Python 3.14 conflict (use Python 3.11 via pyenv or alternative tooling)

## Deployment / CI/CD

- [ ] Integrate into /opt/beehive-docker/docker-compose.yaml
- [ ] Optimize amphigory image build
- [ ] Get container image registry working properly
- [ ] Build container image and push to registry
- [ ] Auto-restart container when new image is pushed to registry (watchtower or similar)

## Recovery Handling

- [ ] **Re-rip optional**: Provide UI option to re-rip if user reinserts disc, but don't require it

## Database Protection

- [ ] **Automated backups**: Periodic SQLite database backups to a secondary location
- [ ] **Backup rotation**: Keep N recent backups, prune older ones
- [ ] **Redundancy**: Consider replicating database to NAS or cloud storage
- [ ] **Integrity checks**: Periodic PRAGMA integrity_check on database

## Future Enhancements

- [ ] Auto-eject disk when finished ripping tracks
- [ ] Unattended mode: the user can specify what sorts of tracks to process when a disk is inserted. 
    * On insert, the system rips all tracks, classifies, then transcodes and inserts according to user specifications. 
    * Tracks that are ripped but not processed further are kept for inspection later.
- [ ] Proactive scanning: daemon scans disc on insert, caches result for quick display on Disc Review page
- [ ] Show HandBrake preset for each track on Disc Review page, with dropdown to select different preset
- [ ] Track previews: grab 60 seconds of a track for quick preview transcoding
- [ ] Reinstate the app-level "Daemon Connected" badge in the webapp and use broadcast to keep all browser clients up-to-date
- [ ] Upload pics of media case back to get more info (barcode, copyright dates, formats, extra features, etc.) to aid in disc and track identification
- [ ] Connected Daemons "Last seen" time counts up in most significant relative unit until reset (e.g. "Last seen: 12s ago" counts up in seconds until 1 minute, then shows "Last seen: 1m ago" and counts up in minutes until 1 hour, etc.)
- [ ] Mark disc in library as one that we want to upgrade media, and add a "Shopping List" page that shows what we want upgrades to

## Multi-User / Multi-Drive Configuration

If we ever want to support multiple daemons (multiple optical drives) or concurrent users:

- [x] **Per-daemon scan cache**: Scan results now stored in OpticalDrive model on daemon side (completed in refactor)
- [ ] **Thread safety for scan cache**: Add locking to `_current_scan` in `disc.py` if needed for concurrent requests
- [ ] **Multi-user session state**: Consider moving scan cache to user sessions or database instead of webapp memory
- [ ] **Dashboard multi-drive display**: Show status for all connected drives, not just the first one with a disc
