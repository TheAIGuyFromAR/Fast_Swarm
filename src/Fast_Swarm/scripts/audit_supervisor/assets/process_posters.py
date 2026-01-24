"""
Process poster images for the retro GUI.
- Crop the right poster to remove frame
- Pixelize both images (downscale + upscale with nearest neighbor)
- Save as PNG
"""

from PIL import Image
import os

# Target size for display in the GUI (poster area is ~180x250)
# We'll make them slightly larger for quality scaling
DISPLAY_WIDTH = 180
DISPLAY_HEIGHT = 250

# Pixel art block size (how chunky the pixels should look)
PIXEL_BLOCK = 4  # Each "pixel" will be 4x4 actual pixels

def pixelize(img: Image.Image, block_size: int = 4) -> Image.Image:
    """
    Pixelize an image by downscaling then upscaling with nearest neighbor.
    """
    # Calculate small size
    small_w = img.width // block_size
    small_h = img.height // block_size

    # Downscale (this averages colors)
    small = img.resize((small_w, small_h), Image.Resampling.LANCZOS)

    # Upscale with nearest neighbor (creates blocky pixels)
    pixelized = small.resize((img.width, img.height), Image.Resampling.NEAREST)

    return pixelized

def process_left_poster():
    """Process the left poster - crop ONE computer from the quad image!"""
    print("Processing left poster (cropping single computer)...")

    img = Image.open("poster_left.jpg")
    print(f"  Original quad size: {img.size}")

    # The image has 4 computers in a 2x2 grid
    # Original is 270x380, so each computer is roughly 135x190
    # Let's crop the top-left computer (the green one looks cool!)
    # Actually let's do bottom-right - the purple one has great vibes

    # Image is 270 wide, 380 tall
    # Bottom-right quadrant (purple/pink computer)
    left = 135
    top = 190
    right = 270
    bottom = 380

    cropped = img.crop((left, top, right, bottom))
    print(f"  Cropped single computer: {cropped.size}")

    # Scale up for display (this is pixel art, use NEAREST)
    # Target about 360 wide to look good on screen
    scale_factor = 3
    new_w = cropped.width * scale_factor
    new_h = cropped.height * scale_factor

    scaled = cropped.resize((new_w, new_h), Image.Resampling.NEAREST)
    print(f"  Scaled up: {scaled.size}")

    # Convert and save
    if scaled.mode != 'RGB':
        scaled = scaled.convert('RGB')

    scaled.save("poster_left.png", "PNG")
    print(f"  Saved: poster_left.png ({scaled.size})")

def process_right_poster():
    """Process the right poster (16-BIT RETRO GAMING SNES poster)."""
    print("Processing right poster...")

    img = Image.open("poster_right.jpg")
    print(f"  Original size: {img.size}")

    # Image is 668x800
    # The SNES poster is in a black frame on white wall
    # Need to crop JUST the poster art (inside the black frame)

    # Looking at image proportions:
    # The black frame has significant margins
    # Poster content (the actual SNES art) is roughly:
    left = 130      # Skip white wall + frame left edge
    top = 85        # Skip white wall + frame top
    right = 540     # Stop before frame right edge + wall
    bottom = 720    # Stop before frame bottom + wall

    cropped = img.crop((left, top, right, bottom))
    print(f"  Cropped poster art: {cropped.size}")

    # Scale up with NEAREST neighbor to get that pixel art crispness
    scale_factor = 2
    new_w = cropped.width * scale_factor
    new_h = cropped.height * scale_factor

    # Use NEAREST for crisp pixel scaling (like the left poster)
    scaled = cropped.resize((new_w, new_h), Image.Resampling.NEAREST)
    print(f"  Scaled up: {scaled.size}")

    # Convert and save
    if scaled.mode != 'RGB':
        scaled = scaled.convert('RGB')

    scaled.save("poster_right.png", "PNG")
    print(f"  Saved: poster_right.png ({scaled.size})")

if __name__ == "__main__":
    # Change to assets directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    print("=" * 50)
    print("POSTER PROCESSING FOR RETRO GUI")
    print("=" * 50)

    process_left_poster()
    print()
    process_right_poster()

    print()
    print("Done! Posters ready for the GUI.")
