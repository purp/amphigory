"""Disc fingerprint generation for quick identification."""

import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class FingerprintError(Exception):
    """Error generating disc fingerprint."""
    pass


def generate_fingerprint_from_drutil(
    disc_type: str,
    volume_name: Optional[str] = None,
) -> str:
    """
    Generate a fingerprint using drutil (no filesystem access required).

    Uses disc metadata from drutil status -xml:
    - blockCount (disc size in blocks) - unique per disc pressing
    - mediaType (DVD-ROM, BD-ROM, etc.)
    - sessionCount
    - trackCount
    - lastLeadOutStartAddress (end of content)
    - Per-track startAddress and size (from trackInfoList)

    Args:
        disc_type: "cd", "dvd", or "bluray"
        volume_name: Optional volume name to include

    Returns:
        Hex string fingerprint

    Raises:
        FingerprintError: If drutil fails
    """
    try:
        result = subprocess.run(
            ["drutil", "status", "-xml"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            raise FingerprintError(f"drutil status failed: {result.stderr}")

        # Parse key fields from XML
        output = result.stdout
        block_count = _extract_xml_attr(output, "usedSpace", "blockCount")
        media_type = _extract_xml_attr(output, "mediaType", "value")
        session_count = _extract_xml_attr(output, "sessionCount", "value")
        track_count = _extract_xml_attr(output, "trackCount", "value")
        lead_out = _extract_xml_attr(output, "lastLeadOutStartAddress", "msf")

        if not block_count:
            raise FingerprintError("Could not extract blockCount from drutil")

        # Build fingerprint from disc metadata
        hasher = hashlib.sha256()
        hasher.update(f"type:{disc_type}".encode())
        hasher.update(f"blocks:{block_count}".encode())
        if media_type:
            hasher.update(f"media:{media_type}".encode())
        if session_count:
            hasher.update(f"sessions:{session_count}".encode())
        if track_count:
            hasher.update(f"tracks:{track_count}".encode())
        if lead_out:
            hasher.update(f"leadout:{lead_out}".encode())

        # Include per-track info for additional uniqueness
        track_infos = _extract_track_infos(output)
        for i, (start, size) in enumerate(track_infos):
            hasher.update(f"track{i}:{start}:{size}".encode())

        if volume_name:
            # Strip whitespace to avoid fingerprint variations from padding
            hasher.update(f"volume:{volume_name.strip()}".encode())

        # Add human-readable prefix based on disc type
        prefix = _get_fingerprint_prefix(disc_type)
        fingerprint = f"{prefix}-{hasher.hexdigest()}"
        clean_volume = volume_name.strip() if volume_name else None
        logger.info(
            f"Generated drutil fingerprint: {fingerprint} "
            f"(blocks={block_count}, type={media_type}, sessions={session_count}, "
            f"tracks={len(track_infos)}, leadout={lead_out}, volume={clean_volume})"
        )
        return fingerprint

    except subprocess.TimeoutExpired:
        raise FingerprintError("drutil status timed out")
    except Exception as e:
        if isinstance(e, FingerprintError):
            raise
        raise FingerprintError(f"Failed to generate drutil fingerprint: {e}")


def _get_fingerprint_prefix(disc_type: str) -> str:
    """Get human-readable prefix for fingerprint based on disc type."""
    prefixes = {
        "dvd": "dvd",
        "bluray": "br",
        "cd": "cd",
        "uhd4k": "uhd",
    }
    return prefixes.get(disc_type, "disc")


def _extract_xml_attr(xml: str, element: str, attr: str) -> Optional[str]:
    """Extract an attribute value from a simple XML element."""
    import re
    pattern = rf'<{element}[^>]*{attr}="([^"]*)"'
    match = re.search(pattern, xml)
    return match.group(1) if match else None


def _extract_track_infos(xml: str) -> list[tuple[str, str]]:
    """Extract (startAddress, size) for each track from trackInfoList.

    Always uses blockAddress/blockCount (not msf) for consistency -
    cold drives may not report msf attributes, but block counts are
    always available.
    """
    import re
    tracks = []
    # Find all trackinfo blocks and extract startAddress and size
    trackinfo_pattern = r'<trackinfo>(.*?)</trackinfo>'
    for match in re.finditer(trackinfo_pattern, xml, re.DOTALL):
        block = match.group(1)
        # Always use block counts for consistency (msf may not be available on cold drives)
        start = _extract_xml_attr(block, "startAddress", "blockAddress")
        size = _extract_xml_attr(block, "size", "blockCount")
        if start and size:
            tracks.append((start, size))
    return tracks


def generate_fingerprint(
    volume_path: str,
    disc_type: str,
    volume_name: Optional[str] = None,
) -> str:
    """
    Generate a fingerprint for a disc.

    Fingerprints are designed to be:
    - Fast to generate (< 5 seconds)
    - Unique per disc pressing
    - Stable across reads

    Args:
        volume_path: Mount path (e.g., /Volumes/MOVIE)
        disc_type: "cd", "dvd", or "bluray"
        volume_name: Optional volume name to include

    Returns:
        Hex string fingerprint

    Raises:
        FingerprintError: If disc structure not found
    """
    hasher = hashlib.sha256()

    # Include disc type and volume name
    logger.debug(f"Fingerprint inputs: volume_path={volume_path}, disc_type={disc_type}, volume_name={volume_name}")
    hasher.update(f"type:{disc_type}".encode())
    if volume_name:
        hasher.update(f"volume:{volume_name}".encode())

    path = Path(volume_path)

    if disc_type == "dvd":
        _hash_dvd_structure(path, hasher)
    elif disc_type == "bluray":
        _hash_bluray_structure(path, hasher)
    elif disc_type == "cd":
        _hash_cd_structure(path, hasher, volume_name)
    else:
        raise FingerprintError(f"Unknown disc type: {disc_type}")

    fingerprint = hasher.hexdigest()
    logger.info(f"Generated fingerprint: {fingerprint[:16]}... for {disc_type} '{volume_name}'")
    return fingerprint


def _hash_dvd_structure(path: Path, hasher: hashlib._Hash) -> None:
    """Hash DVD structure (VIDEO_TS/*.IFO files)."""
    video_ts = path / "VIDEO_TS"
    if not video_ts.exists():
        raise FingerprintError("DVD structure not found (no VIDEO_TS)")

    # Hash all IFO files (small, contain disc structure)
    # Use case-insensitive glob for cross-platform compatibility
    ifo_files = sorted(video_ts.glob("*.[iI][fF][oO]"))
    if not ifo_files:
        raise FingerprintError("No IFO files found in VIDEO_TS")

    logger.debug(f"Hashing {len(ifo_files)} IFO files: {[f.name for f in ifo_files]}")
    for ifo in ifo_files:
        file_size = ifo.stat().st_size
        hasher.update(f"file:{ifo.name}".encode())
        hasher.update(ifo.read_bytes())
        logger.debug(f"  Hashed: {ifo.name} ({file_size} bytes)")


def _hash_bluray_structure(path: Path, hasher: hashlib._Hash) -> None:
    """Hash Blu-ray structure (BDMV/PLAYLIST/*.mpls files)."""
    playlist_dir = path / "BDMV" / "PLAYLIST"
    if not playlist_dir.exists():
        raise FingerprintError("Blu-ray structure not found (no BDMV/PLAYLIST)")

    # Hash all MPLS files (playlists, small, define disc structure)
    # Use case-insensitive glob for cross-platform compatibility
    mpls_files = sorted(playlist_dir.glob("*.[mM][pP][lL][sS]"))
    if not mpls_files:
        raise FingerprintError("No MPLS files found in BDMV/PLAYLIST")

    logger.debug(f"Hashing {len(mpls_files)} MPLS files: {[f.name for f in mpls_files]}")
    for mpls in mpls_files:
        file_size = mpls.stat().st_size
        hasher.update(f"file:{mpls.name}".encode())
        hasher.update(mpls.read_bytes())
        logger.debug(f"  Hashed: {mpls.name} ({file_size} bytes)")


def _hash_cd_structure(
    path: Path,
    hasher: hashlib._Hash,
    volume_name: Optional[str],
) -> None:
    """
    Hash CD structure.

    Note: Audio CDs don't have a filesystem we can easily read.
    For now, use volume name as a weak fingerprint.
    Future: Use discid library to read TOC.
    """
    # For now, just use volume name
    # This is a weak fingerprint but functional
    if volume_name:
        hasher.update(f"cd_volume:{volume_name}".encode())
    else:
        hasher.update(b"cd_unknown")
