"""Disc fingerprint generation for quick identification."""

import hashlib
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class FingerprintError(Exception):
    """Error generating disc fingerprint."""
    pass


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
