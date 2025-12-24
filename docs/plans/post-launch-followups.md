# Post-Launch Followups

Items deferred to focus on getting to a fully functional system first.

## Logging

- [ ] Webapp WebSocket logging not showing daemon_id on connect/disconnect (need to verify implementation)
- [ ] Log logging level on webapp and daemon startup
- [ ] Log logging level changes when config is updated

## Packaging

- [ ] Resolve py2app/Python 3.14 conflict (use Python 3.11 via pyenv or alternative tooling)

## Deployment / CI/CD

- [ ] Get container image registry working properly
- [ ] Build container image and push to registry
- [ ] Auto-restart container when new image is pushed to registry (watchtower or similar)

## Future Enhancements

(Add items here as they come up)
