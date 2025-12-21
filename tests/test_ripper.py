"""Tests for ripping service."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path


@pytest.mark.asyncio
async def test_rip_command_construction():
    """Test that rip commands are constructed correctly."""
    from amphigory.services.ripper import RipperService

    ripper = RipperService(output_dir=Path("/media/ripped"))

    cmd = ripper.build_rip_command(
        drive_index=0,
        title_index=5,
        output_dir=Path("/media/ripped/Test Movie (2024)"),
    )

    assert cmd[0] == "makemkvcon"
    assert "mkv" in cmd
    assert "disc:0" in cmd
    assert "5" in cmd  # title index
    assert "/media/ripped/Test Movie (2024)" in cmd


@pytest.mark.asyncio
async def test_parse_rip_progress():
    """Test parsing progress from MakeMKV output."""
    from amphigory.services.ripper import RipperService

    ripper = RipperService(output_dir=Path("/media/ripped"))

    # Sample progress line
    line = 'PRGV:100,200,500'
    progress = ripper.parse_progress(line)
    assert progress == 40  # 200/500 * 100

    line2 = 'PRGC:1,5,"Copying title 1"'
    progress2 = ripper.parse_progress(line2)
    # PRGC is current/total so 1/5 = 20%
    assert progress2 == 20
