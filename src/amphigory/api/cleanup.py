"""Cleanup API for managing ripped MKV files and inbox transcoded files."""

import os
import shutil
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, field_validator

router = APIRouter(prefix="/api/cleanup", tags=["cleanup"])


class FolderInfo(BaseModel):
    """Information about a folder."""
    name: str
    size: int  # bytes
    file_count: int
    age_days: int
    transcode_status: Optional[str] = None


class RippedListResponse(BaseModel):
    """Response for listing ripped folders."""
    folders: List[FolderInfo]
    total_size: int


class DeleteRequest(BaseModel):
    """Request to delete folders."""
    folders: List[str]

    @field_validator("folders")
    @classmethod
    def validate_folder_names(cls, v: List[str]) -> List[str]:
        """Validate folder names to prevent path traversal."""
        for name in v:
            validate_folder_name(name)
        return v


class DeleteResponse(BaseModel):
    """Response from delete operation."""
    deleted: int
    errors: List[str]


class MoveRequest(BaseModel):
    """Request to move folders to Plex library."""
    folders: List[str]
    destination: str  # "Movies", "TV-Shows", "Music"

    @field_validator("folders")
    @classmethod
    def validate_folder_names(cls, v: List[str]) -> List[str]:
        """Validate folder names to prevent path traversal."""
        for name in v:
            validate_folder_name(name)
        return v

    @field_validator("destination")
    @classmethod
    def validate_destination(cls, v: str) -> str:
        """Validate destination is one of the allowed values."""
        allowed = ["Movies", "TV-Shows", "Music"]
        if v not in allowed:
            raise ValueError(f"destination must be one of {allowed}")
        return v


class MoveResponse(BaseModel):
    """Response from move operation."""
    moved: int
    errors: List[str]


# Helper functions

def get_ripped_dir() -> Path:
    """Get ripped directory from environment."""
    return Path(os.environ.get("AMPHIGORY_RIPPED_DIR", "/media/ripped"))


def get_inbox_dir() -> Path:
    """Get inbox directory from environment."""
    return Path(os.environ.get("AMPHIGORY_INBOX_DIR", "/media/plex/inbox"))


def get_plex_dir() -> Path:
    """Get Plex directory from environment."""
    return Path(os.environ.get("AMPHIGORY_PLEX_DIR", "/media/plex/data"))


def validate_folder_name(name: str) -> None:
    """Validate folder name to prevent path traversal attacks.

    SECURITY: This is critical to prevent directory traversal attacks.
    Rejects any path containing .., /, or \\.

    Args:
        name: Folder name to validate

    Raises:
        ValueError: If name contains invalid characters
    """
    if ".." in name:
        raise ValueError("Folder name cannot contain '..'")
    if "/" in name:
        raise ValueError("Folder name cannot contain '/'")
    if "\\" in name:
        raise ValueError("Folder name cannot contain '\\'")
    if not name or name.strip() != name:
        raise ValueError("Folder name cannot be empty or have leading/trailing spaces")


def get_folder_size(path: Path) -> int:
    """Recursively calculate total size of all files in folder.

    Args:
        path: Path to folder

    Returns:
        Total size in bytes
    """
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except (OSError, PermissionError):
                    # Skip files we can't read
                    pass
    except (OSError, PermissionError):
        # Skip folders we can't read
        pass
    return total


def get_folder_age_days(path: Path) -> int:
    """Get age of folder in days since last modification.

    Args:
        path: Path to folder

    Returns:
        Age in days (rounded down)
    """
    try:
        mtime = path.stat().st_mtime
        age_seconds = datetime.now().timestamp() - mtime
        return int(age_seconds / 86400)  # Convert to days
    except (OSError, PermissionError):
        return 0


def count_files(path: Path) -> int:
    """Count all files recursively in folder.

    Args:
        path: Path to folder

    Returns:
        Number of files
    """
    count = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                count += 1
    except (OSError, PermissionError):
        # Skip folders we can't read
        pass
    return count


# API endpoints

@router.get("/ripped", response_model=RippedListResponse)
async def list_ripped_folders() -> RippedListResponse:
    """List all folders in ripped directory with metadata."""
    ripped_dir = get_ripped_dir()

    if not ripped_dir.exists():
        return RippedListResponse(folders=[], total_size=0)

    folders = []
    total_size = 0

    try:
        for item in ripped_dir.iterdir():
            if item.is_dir():
                size = get_folder_size(item)
                folders.append(FolderInfo(
                    name=item.name,
                    size=size,
                    file_count=count_files(item),
                    age_days=get_folder_age_days(item),
                    transcode_status=None,  # Could be enhanced to check for .mkv files
                ))
                total_size += size
    except (OSError, PermissionError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to list ripped directory: {e}")

    # Sort by name
    folders.sort(key=lambda f: f.name)

    return RippedListResponse(folders=folders, total_size=total_size)


@router.delete("/ripped", response_model=DeleteResponse)
async def delete_ripped_folders(request: DeleteRequest) -> DeleteResponse:
    """Delete selected folders from ripped directory.

    SECURITY: All folder names are validated to prevent path traversal.
    """
    ripped_dir = get_ripped_dir()
    deleted = 0
    errors = []

    for folder_name in request.folders:
        # Path traversal validation already done in Pydantic model
        folder_path = ripped_dir / folder_name

        # Additional safety check: ensure resolved path is within ripped_dir
        try:
            resolved = folder_path.resolve()
            if not resolved.is_relative_to(ripped_dir.resolve()):
                errors.append(f"{folder_name}: path traversal attempt blocked")
                continue
        except (OSError, ValueError) as e:
            errors.append(f"{folder_name}: invalid path - {e}")
            continue

        if not folder_path.exists():
            errors.append(f"{folder_name}: does not exist")
            continue

        if not folder_path.is_dir():
            errors.append(f"{folder_name}: not a directory")
            continue

        try:
            shutil.rmtree(folder_path)
            deleted += 1
        except (OSError, PermissionError) as e:
            errors.append(f"{folder_name}: failed to delete - {e}")

    return DeleteResponse(deleted=deleted, errors=errors)


@router.get("/inbox", response_model=RippedListResponse)
async def list_inbox_folders() -> RippedListResponse:
    """List all folders in inbox directory with metadata."""
    inbox_dir = get_inbox_dir()

    if not inbox_dir.exists():
        return RippedListResponse(folders=[], total_size=0)

    folders = []
    total_size = 0

    try:
        for item in inbox_dir.iterdir():
            if item.is_dir():
                size = get_folder_size(item)
                folders.append(FolderInfo(
                    name=item.name,
                    size=size,
                    file_count=count_files(item),
                    age_days=get_folder_age_days(item),
                ))
                total_size += size
    except (OSError, PermissionError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to list inbox directory: {e}")

    # Sort by name
    folders.sort(key=lambda f: f.name)

    return RippedListResponse(folders=folders, total_size=total_size)


@router.post("/inbox/move", response_model=MoveResponse)
async def move_inbox_to_plex(request: MoveRequest) -> MoveResponse:
    """Move folders from inbox to Plex library.

    SECURITY: All folder names and destination are validated to prevent path traversal.
    """
    inbox_dir = get_inbox_dir()
    plex_dir = get_plex_dir()
    dest_dir = plex_dir / request.destination

    # Ensure destination directory exists
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to create destination: {e}")

    moved = 0
    errors = []

    for folder_name in request.folders:
        # Path traversal validation already done in Pydantic model
        src_path = inbox_dir / folder_name
        dest_path = dest_dir / folder_name

        # Additional safety checks: ensure resolved paths are within expected directories
        try:
            resolved_src = src_path.resolve()
            resolved_dest = dest_path.resolve()

            if not resolved_src.is_relative_to(inbox_dir.resolve()):
                errors.append(f"{folder_name}: source path traversal attempt blocked")
                continue

            if not resolved_dest.is_relative_to(plex_dir.resolve()):
                errors.append(f"{folder_name}: destination path traversal attempt blocked")
                continue
        except (OSError, ValueError) as e:
            errors.append(f"{folder_name}: invalid path - {e}")
            continue

        if not src_path.exists():
            errors.append(f"{folder_name}: does not exist in inbox")
            continue

        if not src_path.is_dir():
            errors.append(f"{folder_name}: not a directory")
            continue

        if dest_path.exists():
            errors.append(f"{folder_name}: already exists in destination")
            continue

        try:
            shutil.move(str(src_path), str(dest_path))
            moved += 1
        except (OSError, PermissionError) as e:
            errors.append(f"{folder_name}: failed to move - {e}")

    return MoveResponse(moved=moved, errors=errors)


# HTML endpoints for HTMX

def format_size(bytes_size: int) -> str:
    """Format bytes as human-readable size.

    Args:
        bytes_size: Size in bytes

    Returns:
        Human-readable size string (e.g., "1.5 GB")
    """
    if bytes_size == 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]
    k = 1024
    i = 0
    size = float(bytes_size)

    while size >= k and i < len(units) - 1:
        size /= k
        i += 1

    return f"{size:.1f} {units[i]}"


def format_age(age_days: int) -> str:
    """Format age in days as human-readable string.

    Args:
        age_days: Age in days

    Returns:
        Human-readable age string
    """
    if age_days == 0:
        return "Today"
    elif age_days == 1:
        return "1 day"
    elif age_days < 7:
        return f"{age_days} days"
    elif age_days < 30:
        weeks = age_days // 7
        return f"{weeks} week{'s' if weeks > 1 else ''}"
    elif age_days < 365:
        months = age_days // 30
        return f"{months} month{'s' if months > 1 else ''}"
    else:
        years = age_days // 365
        return f"{years} year{'s' if years > 1 else ''}"


@router.get("/ripped/html", response_class=HTMLResponse)
async def list_ripped_folders_html() -> str:
    """List all folders in ripped directory as HTML rows for HTMX."""
    ripped_dir = get_ripped_dir()

    if not ripped_dir.exists():
        return '<tr><td colspan="5" class="loading">No folders found</td></tr>'

    folders = []

    try:
        for item in ripped_dir.iterdir():
            if item.is_dir():
                size = get_folder_size(item)
                folders.append(FolderInfo(
                    name=item.name,
                    size=size,
                    file_count=count_files(item),
                    age_days=get_folder_age_days(item),
                ))
    except (OSError, PermissionError) as e:
        return f'<tr><td colspan="5" class="error">Error: {e}</td></tr>'

    # Sort by name
    folders.sort(key=lambda f: f.name)

    if not folders:
        return '<tr><td colspan="5" class="loading">No folders found</td></tr>'

    # Generate HTML rows
    rows = []
    for folder in folders:
        rows.append(f'''<tr>
    <td class="col-select">
        <input type="checkbox" data-folder="{folder.name}" data-size="{folder.size}"
               onchange="toggleFolder(this, 'ripped', '{folder.name}', {folder.size})">
    </td>
    <td>{folder.name}</td>
    <td>{format_size(folder.size)}</td>
    <td>{folder.file_count} file{'s' if folder.file_count != 1 else ''}</td>
    <td>{format_age(folder.age_days)}</td>
</tr>''')

    return '\n'.join(rows)


@router.get("/inbox/html", response_class=HTMLResponse)
async def list_inbox_folders_html() -> str:
    """List all folders in inbox directory as HTML rows for HTMX."""
    inbox_dir = get_inbox_dir()

    if not inbox_dir.exists():
        return '<tr><td colspan="5" class="loading">No folders found</td></tr>'

    folders = []

    try:
        for item in inbox_dir.iterdir():
            if item.is_dir():
                size = get_folder_size(item)
                folders.append(FolderInfo(
                    name=item.name,
                    size=size,
                    file_count=count_files(item),
                    age_days=get_folder_age_days(item),
                ))
    except (OSError, PermissionError) as e:
        return f'<tr><td colspan="5" class="error">Error: {e}</td></tr>'

    # Sort by name
    folders.sort(key=lambda f: f.name)

    if not folders:
        return '<tr><td colspan="5" class="loading">No folders found</td></tr>'

    # Generate HTML rows
    rows = []
    for folder in folders:
        rows.append(f'''<tr>
    <td class="col-select">
        <input type="checkbox" data-folder="{folder.name}" data-size="{folder.size}"
               onchange="toggleFolder(this, 'inbox', '{folder.name}', {folder.size})">
    </td>
    <td>{folder.name}</td>
    <td>{format_size(folder.size)}</td>
    <td>{folder.file_count} file{'s' if folder.file_count != 1 else ''}</td>
    <td>{format_age(folder.age_days)}</td>
</tr>''')

    return '\n'.join(rows)
