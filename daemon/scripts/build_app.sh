#!/bin/bash
# Build Amphigory Daemon as a macOS app bundle
# Works around py2app's incompatibility with pyproject.toml

set -e

cd "$(dirname "$0")/.."

echo "Building Amphigory Daemon..."

# Temporarily move pyproject.toml to avoid py2app conflicts
if [ -f pyproject.toml ]; then
    mv pyproject.toml pyproject.toml.bak
    trap 'mv pyproject.toml.bak pyproject.toml' EXIT
fi

# Clean previous build
rm -rf build dist

# Ensure we're using the venv
if [ -d .venv ]; then
    source .venv/bin/activate
fi

# Run py2app
python setup.py py2app

echo ""
echo "Build complete! App bundle at:"
echo "  dist/Amphigory Daemon.app"
echo ""
echo "To install:"
echo "  cp -r 'dist/Amphigory Daemon.app' /Applications/"
