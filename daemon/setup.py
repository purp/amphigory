"""
Setup script for building Amphigory Daemon as a macOS app bundle.

Usage:
    python setup.py py2app

The resulting app will be in dist/Amphigory Daemon.app
"""

from pathlib import Path
from setuptools import setup

APP = ['src/amphigory_daemon/main.py']

# Collect all icon files
ICONS_DIR = Path('resources/icons')
ICON_FILES = [str(f) for f in ICONS_DIR.glob('*.png')] if ICONS_DIR.exists() else []

DATA_FILES = [
    ('resources/icons', ICON_FILES),
]

OPTIONS = {
    'argv_emulation': False,
    'iconfile': 'resources/AppIcon.icns',
    'plist': {
        'CFBundleName': 'Amphigory Daemon',
        'CFBundleDisplayName': 'Amphigory Daemon',
        'CFBundleIdentifier': 'com.amphigory.daemon',
        'CFBundleVersion': '0.1.0',
        'CFBundleShortVersionString': '0.1.0',
        'LSUIElement': True,  # Hide from Dock (menu bar app)
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '12.0',
    },
    'packages': [
        'rumps',
        'websockets',
        'httpx',
        'yaml',
        'Foundation',
        'AppKit',
        'amphigory_daemon',
    ],
    'includes': [
        'asyncio',
        'json',
        'logging',
        'pathlib',
        'dataclasses',
    ],
}

setup(
    name='Amphigory Daemon',
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
)
