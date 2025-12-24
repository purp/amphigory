# Post-Launch Followups

Items deferred to focus on getting to a fully functional system first.

## Logging

- [ ] Webapp WebSocket logging not showing daemon_id on connect/disconnect (need to verify implementation)
- [ ] Log logging level on webapp and daemon startup
- [ ] Log logging level changes when config is updated

## Packaging

- [ ] Resolve py2app/Python 3.14 conflict (use Python 3.11 via pyenv or alternative tooling)

## Deployment / CI/CD

- [ ] Integrate into /opt/beehive-docker/docker-compose.yaml
- [ ] Optimize amphigory image build
- [ ] Get container image registry working properly
- [ ] Build container image and push to registry
- [ ] Auto-restart container when new image is pushed to registry (watchtower or similar)

## Future Enhancements

- [ ] Show HandBrake preset for each track on Disc Review page, with dropdown to select different preset
