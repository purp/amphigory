# Database Normalization Implementation Plan

**Status:** Ready for Implementation
**Date:** 2025-12-26
**Design:** [2025-12-26-database-normalization-design.md](./2025-12-26-database-normalization-design.md)

## Tasks

### Task 1: Add duration parsing utility
**File:** `src/amphigory/api/disc_repository.py`
**TDD:** Write test first for `parse_duration("1:39:56")` → 5996

- [ ] Test: parse_duration with hours:minutes:seconds
- [ ] Test: parse_duration with minutes:seconds only
- [ ] Test: parse_duration with seconds only
- [ ] Test: parse_duration with invalid input
- [ ] Implement parse_duration function

### Task 2: Add database migration for new columns
**File:** `src/amphigory/database.py`
**TDD:** Write migration test first

- [ ] Test: Migration adds makemkv_name column
- [ ] Test: Migration adds classification_confidence column
- [ ] Test: Migration adds classification_score column
- [ ] Test: Migration is idempotent (safe to run twice)
- [ ] Add migration to `_run_migrations()`

### Task 3: Implement track insertion helper
**File:** `src/amphigory/api/disc_repository.py`
**TDD:** Write test first

- [ ] Test: _insert_track creates row with all fields mapped
- [ ] Test: _insert_track handles missing optional fields
- [ ] Test: _insert_track parses duration correctly
- [ ] Test: _insert_track stores audio/subtitle as JSON
- [ ] Implement _insert_track function

### Task 4: Update save_disc_scan to populate tracks
**File:** `src/amphigory/api/disc_repository.py`
**TDD:** Write test first

- [ ] Test: save_disc_scan creates track rows
- [ ] Test: save_disc_scan clears old tracks on rescan
- [ ] Test: save_disc_scan handles empty tracks list
- [ ] Update save_disc_scan to call _insert_track for each track

### Task 5: Add get_tracks_for_disc query function
**File:** `src/amphigory/api/disc_repository.py`
**TDD:** Write test first

- [ ] Test: get_tracks_for_disc returns all tracks for disc_id
- [ ] Test: get_tracks_for_disc returns empty list for unknown disc
- [ ] Test: get_tracks_for_disc orders by track_number
- [ ] Implement get_tracks_for_disc function

### Task 6: Add migration for existing data
**File:** `src/amphigory/database.py`
**TDD:** Write test first

- [ ] Test: migrate_scan_data_to_tracks populates tracks from existing scan_data
- [ ] Test: migrate_scan_data_to_tracks skips discs without scan_data
- [ ] Test: migrate_scan_data_to_tracks is idempotent
- [ ] Implement migrate_scan_data_to_tracks function
- [ ] Add to _run_migrations() after column migrations

### Task 7: Update disc status endpoint to use tracks table
**File:** `src/amphigory/api/disc.py`
**TDD:** Write test first

- [ ] Test: /api/disc/status includes track count from tracks table
- [ ] Update endpoint to query tracks table

### Task 8: Integration test with real scan flow
**File:** `tests/test_integration.py`

- [ ] Test: Full scan → tracks populated → query tracks → correct data
- [ ] Test: Rescan same disc → old tracks cleared → new tracks inserted

## Execution Order

Tasks 1-3 are independent and can be done in parallel.
Task 4 depends on Tasks 1-3.
Task 5 is independent.
Task 6 depends on Tasks 2-4.
Tasks 7-8 depend on Task 4.

## Success Criteria

- [ ] All existing tests pass
- [ ] New tests cover all task items
- [ ] `tracks` table populated on every scan
- [ ] Existing `scan_data` still works (backward compatible)
- [ ] Migration handles existing databases
