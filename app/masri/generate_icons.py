"""
Masri Digital Compliance Platform — PWA Icon Generator

Generates placeholder PNG icons at standard PWA sizes (16, 32, 192, 512px).
Uses Pillow if available; otherwise generates minimal valid PNGs manually.

Output directory: app/static/img/icons/

Run directly:
    python -m app.masri.generate_icons
"""

import os
import struct
import zlib

# Icon sizes required for PWA manifest
ICON_SIZES = [16, 32, 192, 512]

# Masri brand blue
BRAND_COLOR = (0, 102, 204)  # #0066CC

# Output directory relative to this file's location
_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.dirname(_HERE)
OUTPUT_DIR = os.path.join(_APP_DIR, "static", "img", "icons")


def _generate_with_pillow(size: int, output_path: str):
    """Generate a branded icon using Pillow."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (size, size), (*BRAND_COLOR, 255))
    draw = ImageDraw.Draw(img)

    # Draw "M" letter in the center
    letter = "M"
    font_size = max(8, int(size * 0.55))

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except (IOError, OSError):
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except (IOError, OSError):
            font = ImageFont.load_default()

    # Center the text
    bbox = draw.textbbox((0, 0), letter, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (size - text_width) // 2
    y = (size - text_height) // 2 - bbox[1]

    draw.text((x, y), letter, fill=(255, 255, 255, 255), font=font)

    img.save(output_path, "PNG")


def _generate_minimal_png(size: int, output_path: str):
    """
    Generate a minimal valid PNG without Pillow.

    Creates a solid-color square with the brand color.
    """
    r, g, b = BRAND_COLOR

    # Build raw image data (RGBA rows with filter byte)
    raw_data = b""
    for _ in range(size):
        raw_data += b"\x00"  # filter byte (None)
        for _ in range(size):
            raw_data += struct.pack("BBBB", r, g, b, 255)

    def _make_chunk(chunk_type: bytes, data: bytes) -> bytes:
        chunk = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + chunk + crc

    # PNG signature
    png = b"\x89PNG\r\n\x1a\n"

    # IHDR chunk
    ihdr_data = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    png += _make_chunk(b"IHDR", ihdr_data)

    # IDAT chunk (compressed image data)
    compressed = zlib.compress(raw_data)
    png += _make_chunk(b"IDAT", compressed)

    # IEND chunk
    png += _make_chunk(b"IEND", b"")

    with open(output_path, "wb") as f:
        f.write(png)


def generate_icons():
    """Generate all PWA icons."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    use_pillow = False
    try:
        from PIL import Image
        use_pillow = True
    except ImportError:
        pass

    generated = []

    for size in ICON_SIZES:
        filename = f"icon-{size}x{size}.png"
        output_path = os.path.join(OUTPUT_DIR, filename)

        try:
            if use_pillow:
                _generate_with_pillow(size, output_path)
            else:
                _generate_minimal_png(size, output_path)
            generated.append(filename)
            print(f"  Generated: {filename} ({size}x{size})")
        except Exception as e:
            print(f"  FAILED: {filename} — {e}")

    print(f"\nGenerated {len(generated)} icons in {OUTPUT_DIR}")
    return generated


if __name__ == "__main__":
    print("Generating Masri PWA icons...")
    generate_icons()
