"""Disc detection using macOS notifications."""

import logging
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
        return self

    @classmethod
    def alloc_with_callbacks(
        cls,
        on_insert: Callable[[str, str], None],
        on_eject: Callable[[str], None],
    ) -> "DiscDetector":
        """
        Create a DiscDetector with callbacks.

        Args:
            on_insert: Callback when disc inserted (device, volume_name)
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
        logger.info(f"handleMount_ called with notification: {notification}")
        try:
            user_info = notification.userInfo()
            logger.info(f"Mount notification userInfo: {user_info}")
            if not user_info:
                return

            # Get the mounted path
            path = user_info.get("NSWorkspaceVolumeURLKey")
            if path:
                path = str(path.path())
            else:
                path = user_info.get("NSDevicePath", "")

            # Check if this is an optical disc
            # Optical discs typically mount under /Volumes
            if not path.startswith("/Volumes/"):
                return

            # Try to determine if it's an optical disc
            volume_name = path.split("/")[-1] if path else ""

            # Get device path
            device = self._get_device_for_volume(path)
            if not device:
                return

            # Check if device is optical (rdisk with specific characteristics)
            if self._is_optical_device(device):
                logger.info(f"Optical disc inserted: {volume_name} at {device}")
                if self._on_insert:
                    self._on_insert(device, volume_name)

        except Exception as e:
            logger.error(f"Error handling mount notification: {e}")

    def handleUnmount_(self, notification) -> None:
        """Handle unmount notification from macOS."""
        try:
            user_info = notification.userInfo()
            if not user_info:
                return

            path = user_info.get("NSWorkspaceVolumeURLKey")
            if path:
                path = str(path.path())
            else:
                path = user_info.get("NSDevicePath", "")

            if not path.startswith("/Volumes/"):
                return

            device = self._get_device_for_volume(path)
            if device and self._is_optical_device(device):
                logger.info(f"Optical disc ejected from {device}")
                if self._on_eject:
                    self._on_eject(device)

        except Exception as e:
            logger.error(f"Error handling unmount notification: {e}")

    def _get_device_for_volume(self, volume_path: str) -> Optional[str]:
        """
        Get the device path for a mounted volume.

        Args:
            volume_path: Mount path (e.g., /Volumes/DISC_NAME)

        Returns:
            Device path (e.g., /dev/rdisk4) or None
        """
        import subprocess

        try:
            result = subprocess.run(
                ["diskutil", "info", volume_path],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
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
                            # Remove slice suffix if present
                            if "s" in device:
                                device = device.split("s")[0]
                        return device
        except Exception as e:
            logger.error(f"Error getting device for volume: {e}")

        return None

    def _is_optical_device(self, device: str) -> bool:
        """
        Check if a device is an optical drive.

        Args:
            device: Device path (e.g., /dev/rdisk4)

        Returns:
            True if optical drive
        """
        import subprocess

        try:
            # Use diskutil to check device type
            result = subprocess.run(
                ["diskutil", "info", device],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return False

            output = result.stdout.lower()
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
            return any(ind in output for ind in optical_indicators)

        except Exception as e:
            logger.error(f"Error checking if device is optical: {e}")
            return False

    def get_current_disc(self) -> Optional[Tuple[str, str]]:
        """
        Check if a disc is currently inserted.

        Returns:
            Tuple of (device, volume_name) if disc present, None otherwise
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
                    volume = self._get_volume_for_device(device)
                    if volume:
                        logger.info(f"Found optical disc: {volume} at {device}")
                        return (device, volume)

        except Exception as e:
            logger.error(f"Error checking for current disc: {e}")

        return None

    def _get_volume_for_device(self, device: str) -> Optional[str]:
        """Get the volume name for a device."""
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

            for line in result.stdout.split("\n"):
                if "Volume Name:" in line:
                    parts = line.split(":")
                    if len(parts) >= 2:
                        return parts[1].strip()

        except Exception as e:
            logger.error(f"Error getting volume for device: {e}")

        return None
