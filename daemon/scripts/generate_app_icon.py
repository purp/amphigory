#!/usr/bin/env python3
"""
Generate the application icon for Amphigory Daemon.

Creates a 1024x1024 PNG that can be converted to .icns
"""

from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Please install Pillow: pip install Pillow")
    exit(1)


RESOURCES_DIR = Path(__file__).parent.parent / "resources"


def create_app_icon():
    """Create a 1024x1024 app icon."""
    size = 1024
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background - rounded square
    padding = 80
    corner_radius = 180
    bg_color = (45, 52, 64, 255)  # Dark blue-gray

    # Draw rounded rectangle background
    draw.rounded_rectangle(
        [padding, padding, size - padding, size - padding],
        radius=corner_radius,
        fill=bg_color
    )

    # Draw disc icon in center (white/light color)
    disc_color = (236, 239, 244, 255)  # Light gray
    center = size // 2
    outer_radius = 300
    inner_radius = 80

    # Outer disc
    draw.ellipse(
        [center - outer_radius, center - outer_radius,
         center + outer_radius, center + outer_radius],
        fill=disc_color
    )

    # Inner hole
    draw.ellipse(
        [center - inner_radius, center - inner_radius,
         center + inner_radius, center + inner_radius],
        fill=bg_color
    )

    # Add some "grooves" for disc effect
    groove_color = (200, 210, 220, 255)
    for r in [150, 200, 250]:
        draw.ellipse(
            [center - r, center - r, center + r, center + r],
            outline=groove_color,
            width=2
        )

    return img


def main():
    RESOURCES_DIR.mkdir(parents=True, exist_ok=True)

    # Create PNG
    icon = create_app_icon()
    png_path = RESOURCES_DIR / "AppIcon.png"
    icon.save(png_path)
    print(f"Created {png_path}")

    # Create iconset directory with required sizes
    iconset_dir = RESOURCES_DIR / "AppIcon.iconset"
    iconset_dir.mkdir(exist_ok=True)

    sizes = [16, 32, 64, 128, 256, 512, 1024]
    for size in sizes:
        resized = icon.resize((size, size), Image.Resampling.LANCZOS)
        resized.save(iconset_dir / f"icon_{size}x{size}.png")
        if size <= 512:
            # @2x versions
            resized_2x = icon.resize((size * 2, size * 2), Image.Resampling.LANCZOS)
            resized_2x.save(iconset_dir / f"icon_{size}x{size}@2x.png")

    print(f"Created iconset at {iconset_dir}")
    print("\nTo create .icns file, run:")
    print(f"  iconutil -c icns {iconset_dir}")


if __name__ == "__main__":
    main()
