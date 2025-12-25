# Post-Launch Followups

Items deferred to focus on getting to a fully functional system first.

## Scanning
- [ ] Disable "Scan Disk" button if the daemon is currently scanning the disc
- [ ] Provide a way to stop a scan that's currently running
- [ ] Recognize when a scan has taken too long and stop it

## Logging

- [ ] Webapp WebSocket logging not showing daemon_id on connect/disconnect (need to verify implementation)
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

## Future Enhancements

- [ ] Proactive scanning: daemon scans disc on insert, caches result for quick display on Disc Review page
- [ ] Show HandBrake preset for each track on Disc Review page, with dropdown to select different preset
- [ ] Track previews: grab 60 seconds of a track for quick preview transcoding
- [ ] Reinstate the app-level "Daemon Connected" badge in the webapp and use broadcast to keep all browser clients up-to-date

## Multi-User / Multi-Drive Configuration

If we ever want to support multiple daemons (multiple optical drives) or concurrent users:

- [ ] **Thread safety for scan cache**: Add locking to `_current_scan` in `disc.py` to prevent race conditions with concurrent requests
- [ ] **Per-daemon scan cache**: Change `_current_scan` from global to per-daemon dict keyed by `daemon_id`, so ejecting one drive doesn't clear the cache for another
- [ ] **Multi-user session state**: Consider moving scan cache to user sessions or database instead of webapp memory
- [ ] **Dashboard multi-drive display**: Show status for all connected drives, not just the first one with a disc
