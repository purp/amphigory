# Automating DVD and Blu-ray Classification for Plex

Fully automated disc track classification remains an unsolved problem, but **combining duration-based heuristics with MakeMKV's metadata achieves 85-90% accuracy** for identifying main features. The most practical approach uses MakeMKV's CLI output parsing plus multi-factor scoring algorithms that weigh duration, chapter count, and audio track richness. No equivalent to MusicBrainz exists for video discs—the ecosystem is fragmented across proprietary solutions like My Movies and DVDFab, forcing implementations to rely on structural analysis rather than database lookups.

This matters because manual classification of disc contents is time-consuming, especially for large media libraries. The solution involves parsing MakeMKV's robot-mode output, applying weighted scoring, then renaming files using Plex's exact naming conventions for extras categorization.

---

## The disc database landscape is fragmented and limited

Unlike audio CDs with MusicBrainz and GraceNote, video discs lack any widely-adopted open database for track-level metadata. **My Movies (MyMovies.dk)** is the closest equivalent—it supports actual disc ID lookup for both DVD and Blu-ray, covering 500+ releases per major movie, but requires a paid API ($20+ VAT) or 2500 contribution points. GD3 (GetDigitalData) offered similar functionality but stopped updating its database, leaving newer releases without coverage.

The disc identification challenge compounds this problem. DVDs have no standardized unique identifier—various methods exist including Windows DVD ID (now broken by Windows 10's October 2018 driver change), libdvdread's MD5 hash of IFO files, and volume labels. Blu-rays have AACS Volume IDs, but these require decryption keys to read programmatically.

**Practical workaround**: Use barcode/UPC lookup instead of disc IDs. The UPCitemdb API provides free access to 678 million+ product entries, which can be cross-referenced with TMDB or OMDb using extracted titles:

```python
import requests

def lookup_movie_by_upc(upc):
    barcode_url = f"https://api.upcitemdb.com/prod/trial/lookup?upc={upc}"
    product = requests.get(barcode_url).json()
    
    if product.get('items'):
        title = product['items'][0]['title']
        tmdb_url = f"https://api.themoviedb.org/3/search/movie?query={title}&api_key=YOUR_KEY"
        return requests.get(tmdb_url).json()
    return None
```

---

## MakeMKV provides the richest programmatic metadata access

MakeMKV's command-line interface (`makemkvcon`) exposes comprehensive disc metadata through three structured output types when using robot mode (`-r`). **CINFO** provides disc-level data (disc type, title, volume name), **TINFO** contains per-title information (duration, chapters, file size, segment maps), and **SINFO** details individual streams (codec, resolution, audio channels, languages).

The most classification-relevant metadata fields include:

| Field ID | Name | Classification Use |
|----------|------|-------------------|
| 9 | Duration | Longest = likely main feature |
| 8 | Chapter count | More chapters = likely main feature |
| 14 | Audio channels | 6+ channels suggests main content |
| 16 | Source filename | Shows .mpls playlist number |
| 26 | Segment map | Identifies duplicate/composite titles |

**Key command for disc analysis** (no ripping required):
```bash
makemkvcon -r info disc:0
```

The `python-makemkv` library (archived but functional) provides clean structured output:

```python
from makemkv import MakeMKV

makemkv = MakeMKV('/dev/sr0')
disc_info = makemkv.info()

# Identify main feature by duration
main_title = max(disc_info['titles'], key=lambda t: t.get('duration', 0))
```

For manual parsing, MakeMKV outputs line-based CSV-like format:
```
CINFO:2,0,"Breaking Bad: Season 1: Disc 1"
TINFO:0,9,0,"0:58:06"
TINFO:0,8,0,"7"
SINFO:0,0,19,0,"1920x1080"
```

---

## Multi-factor scoring produces the most reliable classification

Community consensus points to a **weighted scoring algorithm** combining multiple heuristics rather than relying on any single indicator. The duration-based "longest title = main feature" approach achieves roughly 85-90% accuracy for standard movie discs but fails with TV series, extended editions, and playlist-obfuscated Blu-rays.

**Recommended classification algorithm**:

```python
def classify_disc_titles(titles: list) -> dict:
    """Multi-factor scoring for main feature detection."""
    max_duration = max(t['duration'] for t in titles)
    max_chapters = max(t['chapters'] for t in titles)
    max_audio = max(t['audio_count'] for t in titles)
    max_subs = max(t.get('subtitle_count', 0) for t in titles)
    
    scores = {}
    for title in titles:
        score = 0
        
        # Duration (40% weight) - strongest indicator
        if title['duration'] > 3600:  # > 1 hour
            score += 40 * (title['duration'] / max_duration)
        
        # Chapter count (25% weight)
        if title['chapters'] > 10:
            score += 25 * (title['chapters'] / max_chapters)
        
        # Audio track richness (20% weight)
        score += 20 * (title['audio_count'] / max_audio)
        
        # Subtitle count (15% weight)
        if max_subs > 0:
            score += 15 * (title.get('subtitle_count', 0) / max_subs)
        
        scores[title['id']] = score
    
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    
    return {
        'main_feature': ranked[0][0],
        'confidence': ranked[0][1] / 100,
        'extras': [t[0] for t in ranked[1:] 
                   if t[1] < ranked[0][1] * 0.5 and titles[t[0]]['duration'] > 120]
    }
```

**Segment deduplication** is critical for avoiding redundant rips. MakeMKV's segment map (TINFO field 26) shows which M2TS files comprise each title—titles sharing the same segments as the main feature are duplicates (different playlist orderings) and should be excluded. The MakeMKV-Title-Decoder project implements this logic.

For Blu-rays with playlist obfuscation (common on Lionsgate releases), MakeMKV can execute the disc's Java programs to identify the correct playlist, marking it as `(FPL_MainFeature)` in output. This requires Java Runtime Environment and achieves ~95% accuracy when available.

---

## Plex requires exact naming conventions for extras recognition

Plex supports **8 specific extras categories**, each requiring precise naming patterns. The system accepts two organization methods: inline naming (files alongside the movie with suffixes) or subdirectories (category-named folders).

**Inline suffixes** (all lowercase, hyphen required):
```
-behindthescenes    -deleted    -featurette    -interview
-scene              -short      -trailer       -other
```

**Subdirectory names** (Title Case with spaces):
```
Behind The Scenes    Deleted Scenes    Featurettes    Interviews
Scenes               Shorts            Trailers       Other
```

**Complete folder structure example**:
```
/Movies
  /Avatar (2009)
    Avatar (2009).mkv
    /Behind The Scenes
      Performance Capture.mkv
    /Deleted Scenes
      Bar Fight.mp4
    /Trailers
      Theatrical Trailer.mp4
```

Or using inline naming:
```
/Movies
  /Avatar (2009)
    Avatar (2009).mkv
    Performance Capture-behindthescenes.mkv
    Bar Fight-deleted.mp4
    Theatrical Trailer-trailer.mp4
```

**Critical requirements**: Enable "Use local Assets" in Plex library settings, and run "Refresh Metadata" after adding extras (scanning alone won't detect them). The hyphen before the suffix is mandatory—`Making Of - deleted.mkv` (with spaces) won't work.

---

## Disc structure patterns enable heuristic classification

DVD VIDEO_TS and Blu-ray BDMV structures follow documented specifications, though studios don't consistently organize content types in predictable locations. Understanding these structures enables programmatic analysis when database lookup fails.

**DVD structure analysis** uses libdvdread to parse IFO files:

```c
#include <dvdread/dvd_reader.h>
#include <dvdread/ifo_read.h>

dvd_reader_t *dvd = DVDOpen("/dev/sr0");
ifo_handle_t *vmg = ifoOpen(dvd, 0);  // Video Manager
int num_titles = vmg->tt_srpt->nr_of_srpts;

// Each VTS IFO contains: duration, chapter count, audio streams
for (int i = 1; i <= num_title_sets; i++) {
    ifo_handle_t *vts = ifoOpen(dvd, i);
    // Parse vts->vtsi_mat for video/audio attributes
}
```

**Blu-ray analysis** uses libbluray, which provides main title detection:

```c
#include <libbluray/bluray.h>

BLURAY *bd = bd_open("/dev/sr0", NULL);
uint32_t num_titles = bd_get_titles(bd, TITLES_RELEVANT, 120);

// libbluray's built-in main feature detection
uint32_t main_title = bd_get_main_title(bd);

// Manual analysis
for (uint32_t i = 0; i < num_titles; i++) {
    BLURAY_TITLE_INFO *ti = bd_get_title_info(bd, i, 0);
    printf("Title %d: duration=%lu, clips=%d, chapters=%d\n",
           i, ti->duration/90000, ti->clip_count, ti->chapter_count);
}
```

Pattern reliability varies by studio. Warner Bros and Universal generally use straightforward organization, while Lionsgate employs heavy playlist obfuscation that defeats duration-based detection without Java integration.

---

## Automatic Ripping Machine offers the most complete automation

The **Automatic Ripping Machine (ARM)** project on GitHub represents the most comprehensive open-source solution, integrating MakeMKV, HandBrake, and metadata APIs into an automated pipeline. Key configuration options:

```yaml
# arm.yaml
MAINFEATURE: true      # Only transcode main feature (movies)
EXTRAS_SUB: "extras"   # Preserve bonus content in subdirectory  
MINLENGTH: 600         # Minimum title length in seconds
RIPMETHOD: "mkv"       # Use MakeMKV for extraction
```

ARM's workflow: detects disc insertion via udev, queries OMDb API for movie/TV identification, applies HandBrake's `--main-feature` flag for movies (longest title heuristic), and rips all tracks for TV series since no reliable episode detection exists.

**Important limitation**: ARM acknowledges that "HandBrake correctly identifies main feature on movie DVDs, although not perfect. Does NOT handle TV shows well." TV series discs require post-processing with tools like FileBot that match durations against TheTVDB episode data.

For building custom automation, the decision tree should branch on media type:

1. **Movies**: Use multi-factor scoring, prefer MakeMKV's FPL_MainFeature when available
2. **TV Series**: Rip all titles above minimum length, match durations to episode database
3. **Protected Blu-rays**: Require Java Runtime for MakeMKV's playlist obfuscation handling

---

## Implementation blueprint for a complete solution

A practical implementation combines these components into a pipeline:

```python
import subprocess
import re
from pathlib import Path

class DiscClassifier:
    def __init__(self, device='/dev/sr0'):
        self.device = device
        self.titles = []
        
    def scan_disc(self):
        """Extract metadata using MakeMKV."""
        result = subprocess.run(
            ['makemkvcon', '-r', 'info', f'disc:{self.device}'],
            capture_output=True, text=True
        )
        self._parse_output(result.stdout)
        
    def _parse_output(self, output):
        for line in output.splitlines():
            if line.startswith('TINFO:'):
                # Parse title info: TINFO:title_idx,attr_id,code,"value"
                match = re.match(r'TINFO:(\d+),(\d+),\d+,"([^"]*)"', line)
                if match:
                    idx, attr, value = match.groups()
                    # Store duration (9), chapters (8), etc.
                    
    def classify(self):
        """Apply multi-factor scoring."""
        # Implementation from earlier algorithm
        return classify_disc_titles(self.titles)
        
    def rename_for_plex(self, movie_name, year, output_dir):
        """Organize files using Plex conventions."""
        classification = self.classify()
        base_path = Path(output_dir) / f"{movie_name} ({year})"
        
        # Main feature
        main_src = self.titles[classification['main_feature']]['file']
        main_dst = base_path / f"{movie_name} ({year}).mkv"
        
        # Extras - classify by duration and keywords
        for extra_idx in classification['extras']:
            extra = self.titles[extra_idx]
            category = self._detect_extra_type(extra)
            extra_dir = base_path / category
            extra_dir.mkdir(parents=True, exist_ok=True)
            # Copy/move to appropriate directory
            
    def _detect_extra_type(self, title):
        """Keyword-based extras classification."""
        name = title.get('name', '').lower()
        
        patterns = {
            'Behind The Scenes': r'(behind|making|how)',
            'Deleted Scenes': r'(deleted|alternate|extended)',
            'Featurettes': r'(featurette|feature)',
            'Interviews': r'(interview)',
            'Trailers': r'(trailer|teaser|promo)',
        }
        
        for category, pattern in patterns.items():
            if re.search(pattern, name):
                return category
        
        # Fall back to duration-based classification
        if title['duration'] < 300:  # < 5 min
            return 'Trailers'
        elif title['duration'] < 1200:  # < 20 min
            return 'Featurettes'
        return 'Other'
```

---

## Conclusion

Automated disc classification achieves practical accuracy through MakeMKV's metadata combined with weighted heuristics—duration as the primary factor (~40% weight), supplemented by chapter count, audio track richness, and segment deduplication. The main gaps are TV series discs (requiring episode database matching) and heavily protected Blu-rays (requiring Java integration).

For immediate implementation: install MakeMKV with Java Runtime, use the Automatic Ripping Machine project as a starting point, configure `MAINFEATURE: true` for movies, and build post-processing scripts that apply Plex's exact naming conventions. The **-behindthescenes**, **-deleted**, **-trailer** and related suffixes must be lowercase with no spaces around the hyphen. Monitor MakeMKV's `(FPL_MainFeature)` marker for best accuracy on protected discs, and maintain a personal database of disc-specific quirks for problematic releases from studios like Lionsgate.