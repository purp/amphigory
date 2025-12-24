#!/usr/bin/env python3
"""
Generate placeholder menu bar icons for Amphigory Daemon.

These are simple 18x18 PNG template icons. Replace with proper designs later.

Requires: pip install Pillow
"""

from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Please install Pillow: pip install Pillow")
    exit(1)


ICON_SIZE = 18
ICONS_DIR = Path(__file__).parent.parent / "resources" / "icons"


def create_base_icon(state: str) -> Image.Image:
    """Create a base icon for the given state."""
    img = Image.new('RGBA', (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # All icons use black color for template mode
    color = (0, 0, 0, 255)

    if state == "idle_empty":
        # Empty disc outline
        draw.ellipse([2, 2, 15, 15], outline=color, width=2)
        draw.ellipse([7, 7, 10, 10], fill=color)

    elif state == "idle_disc":
        # Filled disc
        draw.ellipse([2, 2, 15, 15], fill=color)
        draw.ellipse([7, 7, 10, 10], fill=(0, 0, 0, 0))

    elif state == "working":
        # Disc with activity indicator (partial fill)
        draw.ellipse([2, 2, 15, 15], fill=color)
        draw.ellipse([7, 7, 10, 10], fill=(0, 0, 0, 0))
        # Activity dot
        draw.ellipse([13, 13, 17, 17], fill=color)

    return img


def add_overlay(img: Image.Image, overlay: str) -> Image.Image:
    """Add an overlay indicator to the icon."""
    img = img.copy()
    draw = ImageDraw.Draw(img)

    # Overlay in bottom-right corner
    if overlay == "paused":
        # Pause bars (small)
        draw.rectangle([12, 12, 13, 17], fill=(0, 0, 0, 255))
        draw.rectangle([15, 12, 16, 17], fill=(0, 0, 0, 255))

    elif overlay == "disconnected":
        # X mark
        draw.line([12, 12, 17, 17], fill=(0, 0, 0, 255), width=2)
        draw.line([12, 17, 17, 12], fill=(0, 0, 0, 255), width=2)

    elif overlay == "error":
        # Exclamation point / warning triangle area
        draw.polygon([(14, 11), (11, 17), (17, 17)], outline=(0, 0, 0, 255))

    elif overlay == "needs_config":
        # Question mark area
        draw.ellipse([11, 11, 17, 17], outline=(0, 0, 0, 255))

    return img


def main():
    ICONS_DIR.mkdir(parents=True, exist_ok=True)

    base_states = ["idle_empty", "idle_disc", "working"]
    overlays = ["paused", "disconnected", "error", "needs_config"]

    generated = []

    # Generate base icons
    for state in base_states:
        img = create_base_icon(state)
        path = ICONS_DIR / f"{state}.png"
        img.save(path)
        generated.append(path.name)

        # Generate with single overlays
        for overlay in overlays:
            overlay_img = add_overlay(img, overlay)
            path = ICONS_DIR / f"{state}_{overlay}.png"
            overlay_img.save(path)
            generated.append(path.name)

        # Common combinations
        for combo in [("paused", "disconnected"), ("error", "disconnected")]:
            combo_img = img.copy()
            for overlay in sorted(combo):
                combo_img = add_overlay(combo_img, overlay)
            suffix = "_".join(sorted(combo))
            path = ICONS_DIR / f"{state}_{suffix}.png"
            combo_img.save(path)
            generated.append(path.name)

    print(f"Generated {len(generated)} icons in {ICONS_DIR}:")
    for name in sorted(generated):
        print(f"  {name}")


if __name__ == "__main__":
    main()
