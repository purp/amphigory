# Future: TV Show Support

Notes for when we tackle TV show disc handling.

## Key Differences from Movies

### No Reliable Episode Detection
- Unlike movies, TV show discs have **no reliable way to identify which track is which episode**
- ARM project acknowledges: "Does NOT handle TV shows well"
- Recommended approach: rip all tracks above minimum length, then match durations to episode database

### Duration Matching
- Query TheTVDB or TMDB for episode runtimes
- Match track durations to episode durations (within tolerance, e.g., ±2 minutes)
- Present matches to user for confirmation
- Handle edge cases:
  - Extended episodes
  - Multi-part episodes
  - "Previously on..." segments that add runtime
  - Different runtime in different regions

### Plex Naming Conventions
```
/TV Shows
  /Show Name (Year)
    /Season 01
      Show Name (Year) - s01e01 - Episode Title.mkv
      Show Name (Year) - s01e02 - Episode Title.mkv
    /Season 00        # Specials
      Show Name (Year) - s00e01 - Special Title.mkv
```

- Use `sXXeXX` format (e.g., `s01e05`)
- Specials go in Season 00
- Multi-episode files: `s01e05-e06`
- Date-based shows: `Show Name - 2024-12-25 - Episode Title.mkv`

### Database Fields (Already Added)
We've added these to the schema:
- `discs.media_type` - 'movie' or 'tv'
- `discs.show_name` - Series name
- `discs.tvdb_id` - TVDB identifier
- `tracks.season_number`
- `tracks.episode_number`
- `tracks.episode_end_number` - For multi-episode tracks
- `tracks.air_date` - For date-based shows

## UI Considerations

### Media Type Selection
- After disc scan, ask: "Is this a Movie or TV Show?"
- If TV: prompt for show name search
- Display season/episode grid for assignment

### Episode Assignment Interface
- Show tracks with durations
- Show episodes from TVDB/TMDB with expected durations
- Drag-and-drop or dropdown to assign track → episode
- Highlight duration mismatches
- Support "this track contains episodes X-Y"

### Season Detection
- Some discs are single-season
- Some are multi-season box sets
- Let user specify or auto-detect from episode count

## API Integration

### TheTVDB
- Better for TV metadata historically
- Has episode images and detailed metadata
- API requires subscription for full access
- Consider caching episode data locally

### TMDB
- Also has TV show support
- Same API we're using for movies
- May be sufficient for basic episode matching

## Episode Matching Algorithm

```python
def match_tracks_to_episodes(tracks, episodes, tolerance_seconds=120):
    """
    Match track durations to episode runtimes.

    Returns list of (track, episode, confidence) tuples.
    """
    matches = []

    for track in tracks:
        track_duration = track.duration_seconds

        best_match = None
        best_diff = float('inf')

        for episode in episodes:
            episode_duration = episode.runtime * 60  # Convert minutes to seconds
            diff = abs(track_duration - episode_duration)

            if diff < best_diff and diff <= tolerance_seconds:
                best_diff = diff
                best_match = episode

        if best_match:
            confidence = 'high' if best_diff < 30 else 'medium' if best_diff < 60 else 'low'
            matches.append((track, best_match, confidence))
        else:
            matches.append((track, None, 'none'))

    return matches
```

## Challenges to Consider

### Disc Variations
- Region-specific cuts (PAL vs NTSC runtime differences)
- Extended/director's cuts mixed with regular episodes
- "Disc 1 of 4" type releases

### Extras on TV Discs
- Behind the scenes for specific episodes
- Gag reels (usually per-season)
- Commentaries (alternate audio, not separate tracks usually)

### Box Sets
- Complete series boxes may span many discs
- Need to track which disc we're on
- Maintain state across multiple ripping sessions

## Contributing to Open Databases

Far future goal: contribute our scan data back to the community.

### TVDB Contributions
- Episode runtime corrections
- Disc-to-episode mappings
- Regional variant documentation

### TMDB Contributions
- Similar to TVDB
- Movie edition information (theatrical vs director's cut)
- Disc release metadata

### Our Own Database?
- Aggregate disc fingerprints → content mappings
- Share anonymized data with community
- Build "if you have this disc, these are the episodes" lookup
- Similar to CDDB/MusicBrainz model for CDs

## Implementation Order Suggestion

1. **Basic TV support** - media_type selection, show search, manual episode assignment
2. **Duration matching** - auto-suggest episode matches, user confirms
3. **Multi-disc tracking** - "Disc 2 of 4" awareness, session continuity
4. **Box set handling** - complete series workflow
5. **Community contributions** - far future
