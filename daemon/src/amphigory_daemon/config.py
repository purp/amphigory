"""Configuration management for Amphigory daemon."""

import json
from pathlib import Path
from typing import Optional

import httpx
import yaml

from .models import DaemonConfig, WebappConfig, webapp_config_from_dict


def load_local_config(config_file: Path) -> DaemonConfig:
    """
    Load daemon configuration from local YAML file.

    Args:
        config_file: Path to daemon.yaml

    Returns:
        DaemonConfig with webapp_url, webapp_basedir, and optional fields

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If required fields are missing
    """
    from datetime import datetime

    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")

    with open(config_file) as f:
        data = yaml.safe_load(f)

    if "webapp_url" not in data:
        raise ValueError("Missing required field: webapp_url")
    if "webapp_basedir" not in data:
        raise ValueError("Missing required field: webapp_basedir")

    # Parse updated_at if present
    updated_at = None
    if "updated_at" in data:
        if isinstance(data["updated_at"], datetime):
            updated_at = data["updated_at"]
        elif isinstance(data["updated_at"], str):
            updated_at = datetime.fromisoformat(data["updated_at"])

    return DaemonConfig(
        webapp_url=data["webapp_url"],
        webapp_basedir=data["webapp_basedir"],
        daemon_id=data.get("daemon_id"),
        makemkvcon_path=data.get("makemkvcon_path"),
        updated_at=updated_at,
    )


def save_local_config(config: DaemonConfig, config_file: Path) -> None:
    """
    Save daemon configuration to local YAML file.

    Args:
        config: DaemonConfig to save
        config_file: Path to daemon.yaml
    """
    config_file.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "webapp_url": config.webapp_url,
        "webapp_basedir": config.webapp_basedir,
    }

    # Only include optional fields if they have values
    if config.daemon_id is not None:
        data["daemon_id"] = config.daemon_id
    if config.makemkvcon_path is not None:
        data["makemkvcon_path"] = config.makemkvcon_path
    if config.updated_at is not None:
        data["updated_at"] = config.updated_at.isoformat()

    with open(config_file, "w") as f:
        yaml.dump(data, f, default_flow_style=False)


async def fetch_webapp_config(webapp_url: str) -> WebappConfig:
    """
    Fetch configuration from webapp's /config.json endpoint.

    Args:
        webapp_url: Base URL of the webapp

    Returns:
        WebappConfig parsed from response

    Raises:
        ConnectionError: If webapp is unreachable
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{webapp_url}/config.json")
            response.raise_for_status()
            data = response.json()
            return webapp_config_from_dict(data)
    except httpx.ConnectError as e:
        raise ConnectionError(f"Cannot connect to webapp: {e}") from e
    except httpx.HTTPStatusError as e:
        raise ConnectionError(f"Webapp returned error: {e}") from e


def cache_webapp_config(config: WebappConfig, cache_file: Path) -> None:
    """
    Cache webapp configuration to JSON file.

    Args:
        config: WebappConfig to cache
        cache_file: Path to cache file
    """
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "tasks_directory": config.tasks_directory,
        "websocket_port": config.websocket_port,
        "wiki_url": config.wiki_url,
        "heartbeat_interval": config.heartbeat_interval,
        "log_level": config.log_level,
        "makemkv_path": config.makemkv_path,
    }
    with open(cache_file, "w") as f:
        json.dump(data, f, indent=2)


def load_cached_config(cache_file: Path) -> Optional[WebappConfig]:
    """
    Load webapp configuration from cache file.

    Args:
        cache_file: Path to cached_config.json

    Returns:
        WebappConfig if cache exists, None otherwise
    """
    if not cache_file.exists():
        return None

    with open(cache_file) as f:
        data = json.load(f)
    return webapp_config_from_dict(data)


async def get_config(
    local_config_file: Path,
    cache_file: Path,
) -> tuple[DaemonConfig, WebappConfig]:
    """
    Load configuration from local file and webapp.

    Attempts to fetch from webapp first. Falls back to cache if webapp
    is unreachable. Updates cache on successful fetch.

    Args:
        local_config_file: Path to daemon.yaml
        cache_file: Path to cached_config.json

    Returns:
        Tuple of (DaemonConfig, WebappConfig)

    Raises:
        FileNotFoundError: If local config file doesn't exist
        ConnectionError: If webapp unreachable and no cache exists
    """
    daemon_config = load_local_config(local_config_file)

    try:
        webapp_config = await fetch_webapp_config(daemon_config.webapp_url)
        cache_webapp_config(webapp_config, cache_file)
        return daemon_config, webapp_config
    except ConnectionError:
        cached = load_cached_config(cache_file)
        if cached is not None:
            return daemon_config, cached
        raise ConnectionError(
            "Cannot connect to webapp and no cache exists. "
            "Ensure webapp is running or provide cached configuration."
        )
