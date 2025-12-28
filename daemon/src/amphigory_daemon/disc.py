"""Disc detection using macOS notifications."""

import logging
import subprocess
import time
from typing import Callable, Optional, Tuple

# PyObjC imports - only available on macOS
try:
    from AppKit import (
        NSWorkspace,
        NSWorkspaceDidMountNotification,
        NSWorkspaceDidUnmountNotification,
    )
    from Foundation import NSObject
    import objc
    HAS_PYOBJC = True
except ImportError:
    HAS_PYOBJC = False
    NSObject = object  # Fallback for non-macOS
    objc = None

logger = logging.getLogger(__name__)


class DiscDetector(NSObject):
    """
    Detects optical disc insertion and ejection using macOS notifications.

    Uses NSWorkspace notifications to detect mount/unmount events,
    then filters for optical discs (BD, DVD, CD).
    """

    def init(self):
        """Initialize NSObject. Required for PyObjC subclasses."""
        self = objc.super(DiscDetector, self).init()
        if self is None:
            return None
        self._on_insert = None
        self._on_eject = None
        self._running = False
        self._current_volume_path = None
        return self

    @classmethod
    def alloc_with_callbacks(
        cls,
        on_insert: Callable[[str, str, str], None],
        on_eject: Callable[[str], None],
    ) -> "DiscDetector":
        """
        Create a DiscDetector with callbacks.

        Args:
            on_insert: Callback when disc inserted (device, volume_name, volume_path)
            on_eject: Callback when disc ejected (device)

        Returns:
            Initialized DiscDetector instance
        """
        instance = cls.alloc().init()
        instance._on_insert = on_insert
        instance._on_eject = on_eject
        return instance

    def start(self) -> None:
        """Register for mount/unmount notifications."""
        logger.info(f"DiscDetector.start() called, HAS_PYOBJC={HAS_PYOBJC}")
        if not HAS_PYOBJC:
            logger.warning("PyObjC not available - disc detection disabled")
            return

        workspace = NSWorkspace.sharedWorkspace()
        notification_center = workspace.notificationCenter()
        logger.info(f"Got workspace and notification center: {notification_center}")

        # Register for mount notifications
        notification_center.addObserver_selector_name_object_(
            self,
            "handleMount:",
            NSWorkspaceDidMountNotification,
            None,
        )
        logger.info("Registered for mount notifications")

        # Register for unmount notifications
        notification_center.addObserver_selector_name_object_(
            self,
            "handleUnmount:",
            NSWorkspaceDidUnmountNotification,
            None,
        )
        logger.info("Registered for unmount notifications")

        self._running = True
        logger.info("Disc detection started successfully")

    def stop(self) -> None:
        """Unregister notifications."""
        if not HAS_PYOBJC or not self._running:
            return

        workspace = NSWorkspace.sharedWorkspace()
        notification_center = workspace.notificationCenter()
        notification_center.removeObserver_(self)

        self._running = False
        logger.info("Disc detection stopped")

    def handleMount_(self, notification) -> None:
        """Handle mount notification from macOS."""
        logger.debug(f"handleMount_ called with notification: {notification}")
        try:
            user_info = notification.userInfo()
            logger.debug(f"Mount notification userInfo: {user_info}")
            if not user_info:
                return

            # Get the mounted path
            path = user_info.get("NSWorkspaceVolumeURLKey")
            if path:
                path = str(path.path())
            else:
                path = user_info.get("NSDevicePath", "")
            logger.debug(f"Mount path extracted: {path}")

            # Check if this is an optical disc
            # Optical discs typically mount under /Volumes
            if not path.startswith("/Volumes/"):
                logger.debug(f"Ignoring mount - not under /Volumes: {path}")
                return

            # Try to determine if it's an optical disc
            volume_name = path.split("/")[-1] if path else ""
            logger.debug(f"Volume name: {volume_name}")

            # Get device path
            device = self._get_device_for_volume(path)
            logger.debug(f"Device for volume {path}: {device}")
            if not device:
                logger.debug(f"No device found for {path} - ignoring mount")
                return

            # Check if device is optical (rdisk with specific characteristics)
            is_optical = self._is_optical_device(device)
            logger.debug(f"Is {device} optical? {is_optical}")
            if is_optical:
                logger.info(f"Optical disc inserted: {volume_name} at {device}")
                self._current_volume_path = path
                if self._on_insert:
                    self._on_insert(device, volume_name, path)

        except Exception as e:
            logger.error(f"Error handling mount notification: {e}")

    def handleUnmount_(self, notification) -> None:
        """Handle unmount notification from macOS."""
        logger.debug(f"handleUnmount_ called with notification: {notification}")
        try:
            user_info = notification.userInfo()
            logger.debug(f"Unmount notification userInfo: {user_info}")
            if not user_info:
                return
            path = user_info.get("NSWorkspaceVolumeURLKey")
            if path:
                path = str(path.path())
            else:
                path = user_info.get("NSDevicePath", "")
            if not path.startswith("/Volumes/"):
                return
            # Check if this is our tracked optical disc
            if path == self._current_volume_path:
                logger.info(f"Optical disc ejected from {path}")
                self._current_volume_path = None
                if self._on_eject:
                    self._on_eject(path)
        except Exception as e:
            logger.error(f"Error handling unmount notification: {e}")

    def _run_diskutil(self, target: str, max_retries: int = 3) -> Optional[subprocess.CompletedProcess]:
        """
        Run diskutil info with retry logic for timeouts.

        Args:
            target: Volume path or device path to query
            max_retries: Number of attempts before giving up

        Returns:
            CompletedProcess on success, None on failure
        """
        for attempt in range(max_retries):
            try:
                result = subprocess.run(
                    ["diskutil", "info", target],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                return result
            except subprocess.TimeoutExpired:
                if attempt < max_retries - 1:
                    logger.debug(f"diskutil timeout for {target}, retrying ({attempt + 1}/{max_retries})")
                    time.sleep(1)
                else:
                    logger.warning(f"diskutil timed out after {max_retries} attempts for {target}")
            except Exception as e:
                logger.error(f"diskutil error for {target}: {e}")
                break
        return None

    def _get_device_for_volume(self, volume_path: str) -> Optional[str]:
        """
        Get the device path for a mounted volume.

        Args:
            volume_path: Mount path (e.g., /Volumes/DISC_NAME)

        Returns:
            Device path (e.g., /dev/rdisk4) or None
        """
        import re

        result = self._run_diskutil(volume_path)
        if not result or result.returncode != 0:
            return None

        for line in result.stdout.split("\n"):
            if "Device Node:" in line:
                # Line format: "   Device Node:              /dev/disk4s0"
                parts = line.split(":")
                if len(parts) >= 2:
                    device = parts[1].strip()
                    # Convert to raw device
                    if device.startswith("/dev/disk"):
                        device = device.replace("/dev/disk", "/dev/rdisk")
                        # Remove slice suffix if present (e.g., s0, s1)
                        device = re.sub(r's\d+$', '', device)
                    return device

        return None

    def _is_optical_device(self, device: str) -> bool:
        """
        Check if a device is an optical drive.

        Args:
            device: Device path (e.g., /dev/rdisk4)

        Returns:
            True if optical drive
        """
        result = self._run_diskutil(device)
        if not result or result.returncode != 0:
            if result:
                logger.debug(f"diskutil info {device} failed with code {result.returncode}")
            return False

        output = result.stdout.lower()
        logger.debug(f"diskutil info output for {device}:\n{result.stdout}")

        # Look for optical disc indicators
        optical_indicators = [
            "bd-rom",
            "bd-re",
            "dvd",
            "cd-rom",
            "cd-r",
            "optical",
            "blu-ray",
        ]
        found = [ind for ind in optical_indicators if ind in output]
        if found:
            logger.debug(f"Found optical indicators: {found}")
        return len(found) > 0

    def get_current_disc(self) -> Optional[Tuple[str, str, str]]:
        """
        Check if a disc is currently inserted.

        Returns:
            Tuple of (device, volume_name, volume_path) if disc present, None otherwise
        """
        import subprocess
        import re

        try:
            # List all disks
            result = subprocess.run(
                ["diskutil", "list"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return None

            # Find all disk identifiers (lines starting with /dev/disk)
            disk_pattern = re.compile(r"^/dev/(disk\d+)")
            disk_ids = []
            for line in result.stdout.split("\n"):
                match = disk_pattern.match(line)
                if match:
                    disk_ids.append(match.group(1))

            logger.debug(f"Found disks: {disk_ids}")

            # Check each disk to see if it's an optical drive
            for disk_id in disk_ids:
                device = f"/dev/r{disk_id}"
                if self._is_optical_device(device):
                    volume_info = self._get_volume_for_device(device)
                    if volume_info:
                        volume_name, volume_path = volume_info
                        logger.info(f"Found optical disc: {volume_name} at {device}, path: {volume_path}")
                        return (device, volume_name, volume_path)

        except Exception as e:
            logger.error(f"Error checking for current disc: {e}")

        return None

    def _get_volume_for_device(self, device: str) -> Optional[Tuple[str, str]]:
        """
        Get the volume name and path for a device.

        Returns:
            Tuple of (volume_name, volume_path) or None
        """
        import subprocess

        try:
            # Normalize device path
            disk_id = device.replace("/dev/r", "").replace("/dev/", "")

            result = subprocess.run(
                ["diskutil", "info", disk_id],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return None

            volume_name = None
            volume_path = None

            for line in result.stdout.split("\n"):
                if "Volume Name:" in line:
                    parts = line.split(":")
                    if len(parts) >= 2:
                        volume_name = parts[1].strip()
                elif "Mount Point:" in line:
                    parts = line.split(":")
                    if len(parts) >= 2:
                        volume_path = parts[1].strip()

            if volume_name and volume_path:
                return (volume_name, volume_path)

        except Exception as e:
            logger.error(f"Error getting volume for device: {e}")

        return None
