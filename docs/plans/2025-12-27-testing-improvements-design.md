# Testing Improvements Design

## Overview

Add integration tests for core workflows and Playwright E2E smoke tests.

## Integration Tests

### TestRipTranscodeChain

Tests the task dependency chain:
1. Create completed rip task with output file path
2. Verify transcode task becomes runnable (input exists)
3. Simulate transcode completion
4. Verify output in transcoded directory

### TestDiscToLibraryFlow

Tests the full processing flow:
1. Seed database with disc and tracks
2. POST `/api/tasks/process` with track selections
3. Verify rip + transcode task pairs created in order
4. Mark tasks complete
5. Verify disc appears in Library API

### Approach

- Mock file existence (no real media)
- Real SQLite database (tmp_path)
- Real task queue (JSON files in tmp_path)
- No daemon required - testing webapp logic

## Playwright E2E Tests

### Structure

```
tests/e2e/
  conftest.py      # browser, page, test server fixtures
  test_smoke.py    # page load tests
```

### Test Server

- uvicorn subprocess on random port
- Minimal seeded database
- Teardown after tests

### Smoke Tests

1. Dashboard `/` loads
2. Disc Review `/disc` loads
3. Library `/library` loads, filters visible
4. Queue `/queue` loads
5. Cleanup `/cleanup` loads, tabs visible
6. Settings `/settings` loads, fields visible

### Dependencies

- pytest-playwright in dev dependencies
- Requires `playwright install chromium`

## Out of Scope

- Wiki integration tests (tasks skipped)
- Cleanup workflow integration tests
- Playwright interaction tests (future)
- Real media file processing
