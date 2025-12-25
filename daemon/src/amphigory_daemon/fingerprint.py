"""Disc fingerprint generation for quick identification."""

import hashlib
from pathlib import Path
from typing import Optional


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

    return hasher.hexdigest()


def _hash_dvd_structure(path: Path, hasher: hashlib._Hash) -> None:
    """Hash DVD structure (VIDEO_TS/*.IFO files)."""
    video_ts = path / "VIDEO_TS"
    if not video_ts.exists():
        raise FingerprintError("DVD structure not found (no VIDEO_TS)")

    # Hash all IFO files (small, contain disc structure)
    ifo_files = sorted(video_ts.glob("*.IFO"))
    if not ifo_files:
        raise FingerprintError("No IFO files found in VIDEO_TS")

    for ifo in ifo_files:
        hasher.update(f"file:{ifo.name}".encode())
        hasher.update(ifo.read_bytes())


def _hash_bluray_structure(path: Path, hasher: hashlib._Hash) -> None:
    """Hash Blu-ray structure (BDMV/PLAYLIST/*.mpls files)."""
    playlist_dir = path / "BDMV" / "PLAYLIST"
    if not playlist_dir.exists():
        raise FingerprintError("Blu-ray structure not found (no BDMV/PLAYLIST)")

    # Hash all MPLS files (playlists, small, define disc structure)
    mpls_files = sorted(playlist_dir.glob("*.mpls"))
    if not mpls_files:
        raise FingerprintError("No MPLS files found in BDMV/PLAYLIST")

    for mpls in mpls_files:
        hasher.update(f"file:{mpls.name}".encode())
        hasher.update(mpls.read_bytes())


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
