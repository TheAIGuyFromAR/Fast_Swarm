"""
Apple IIe Style Terminal GUI - 80s Teen Hacker Movie Scene
A nostalgic desk scene with Apple IIe computer, viewed over a chair back.

Features:
- 3D-ish desk scene with computer
- Apple IIe aesthetic (beige case, green phosphor)
- 80x24 character display
- Realistic CRT curvature and glow
- Keyboard with clickable emergency stop
- Looking over the back of a chair
- Two 80s posters on the wall
- 80s teen hacker movie atmosphere

Inspired by: WarGames, Real Genius, Weird Science

Cross-platform: Windows, Mac, Linux
Requires: pygame
"""

import math
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple
import random

try:
    import pygame
    import pygame.gfxdraw
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False
    print("pygame not installed. Run: pip install pygame")


# ==============================================================================
# SCENE DIMENSIONS
# ==============================================================================

WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 800

# Monitor screen area (where terminal renders)
SCREEN_CHARS_X = 80  # Apple IIe 80-column mode
SCREEN_CHARS_Y = 24
CHAR_WIDTH = 8
CHAR_HEIGHT = 16
SCREEN_WIDTH = SCREEN_CHARS_X * CHAR_WIDTH   # 640
SCREEN_HEIGHT = SCREEN_CHARS_Y * CHAR_HEIGHT  # 384

# Monitor/computer sprite position in scene
# Desk top is at y=520, keyboard/bottom of sprite should sit there
# Sprite is 1024px tall, scaled by 0.48 = ~491px, keyboard is near bottom (~y=800 in original)
# So position sprite so keyboard lands on desk: 520 - (800 * 0.48) = 520 - 384 = 136
MONITOR_X = 250
MONITOR_Y = 100  # Positions computer to sit on the desk
MONITOR_WIDTH = 720
MONITOR_HEIGHT = 540

# Screen position within monitor (with bezel)
SCREEN_X = MONITOR_X + 60
SCREEN_Y = MONITOR_Y + 60


# ==============================================================================
# APPLE II COLOR PALETTE
# ==============================================================================

# Scene colors
C_WALL = (45, 52, 54)           # Dark grey wall
C_DESK = (101, 67, 33)          # Wooden desk
C_DESK_SHADOW = (71, 47, 23)    # Desk shadow

# Monitor case colors (classic cream/off-white like real 80s monitors)
C_CASE_LIGHT = (235, 230, 215)  # Cream highlight
C_CASE_MID = (210, 200, 180)    # Warm off-white
C_CASE_DARK = (170, 160, 140)   # Shadow
C_CASE_VENT = (60, 55, 50)      # Vent slots
C_CASE_BEZEL = (35, 35, 40)     # Dark bezel around screen
C_CASE_INNER = (25, 25, 30)     # Inner screen frame

# Green phosphor monitor
C_PHOSPHOR_BG = (0, 15, 0)      # Very dark green
C_PHOSPHOR_DIM = (0, 40, 0)     # Dim green
C_PHOSPHOR = (0, 180, 0)        # Normal green
C_PHOSPHOR_BRIGHT = (0, 255, 0) # Bright green
C_PHOSPHOR_GLOW = (50, 255, 50) # Glowing green

# Keyboard colors
C_KEY_TOP = (180, 175, 165)     # Key top
C_KEY_SIDE = (120, 115, 105)    # Key side
C_KEY_TEXT = (40, 40, 40)       # Key legend

# Emergency button
C_ESTOP_RED = (200, 30, 30)
C_ESTOP_BRIGHT = (255, 60, 60)
C_ESTOP_DARK = (120, 20, 20)

# Chair colors
C_CHAIR_FABRIC = (45, 35, 65)       # Dark purple/blue fabric
C_CHAIR_FABRIC_LIGHT = (65, 55, 85)
C_CHAIR_METAL = (70, 70, 75)        # Metal frame

# 80s Poster colors
C_POSTER_BG1 = (20, 20, 50)         # Dark blue
C_POSTER_BG2 = (60, 20, 40)         # Dark magenta
C_POSTER_ACCENT1 = (255, 100, 200)  # Hot pink (synthwave)
C_POSTER_ACCENT2 = (100, 200, 255)  # Cyan (synthwave)
C_POSTER_NEON = (255, 50, 150)      # Neon pink
C_POSTER_GRID = (150, 80, 200)      # Purple grid
C_POSTER_FRAME = (30, 30, 35)       # Dark frame

# Ambient items
C_SODA_CAN = (200, 50, 50)          # Red soda can
C_PIZZA_BOX = (180, 140, 100)       # Cardboard


# ==============================================================================
# CRT SCREEN RENDERING
# ==============================================================================

class AppleIIScreen:
    """
    Apple IIe style 80x24 green phosphor screen.
    Renders with CRT effects: curvature, scanlines, glow.
    """

    def __init__(self):
        self.width = SCREEN_WIDTH
        self.height = SCREEN_HEIGHT

        # Character buffer
        self.buffer: List[List[Tuple[str, Tuple[int, int, int]]]] = [
            [(" ", C_PHOSPHOR) for _ in range(SCREEN_CHARS_X)]
            for _ in range(SCREEN_CHARS_Y)
        ]

        # Cursor
        self.cursor_x = 0
        self.cursor_y = 0
        self.cursor_visible = True
        self.cursor_blink = 0.0

        # Surfaces
        self.char_surface = pygame.Surface((self.width, self.height))
        self.effect_surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)

        # Font (monospace, slightly taller for Apple II look)
        try:
            self.font = pygame.font.Font(pygame.font.match_font('couriernew'), 14)
        except:
            self.font = pygame.font.SysFont('monospace', 14)

        # Pre-render scanlines
        self._create_scanlines()
        self._create_curvature_mask()

    def _create_scanlines(self):
        """Create scanline overlay."""
        self.scanlines = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        for y in range(0, self.height, 2):
            pygame.draw.line(self.scanlines, (0, 0, 0, 40), (0, y), (self.width, y))

    def _create_curvature_mask(self):
        """Create CRT curvature/vignette effect."""
        self.curvature = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        cx, cy = self.width // 2, self.height // 2

        for y in range(self.height):
            for x in range(0, self.width, 4):  # Sample every 4 pixels for speed
                # Distance from center (normalized)
                dx = (x - cx) / cx
                dy = (y - cy) / cy
                dist = math.sqrt(dx * dx + dy * dy)

                # Vignette darkening at edges
                alpha = int(min(60, dist * 80))
                pygame.draw.rect(self.curvature, (0, 0, 0, alpha), (x, y, 4, 1))

    def clear(self):
        """Clear the screen."""
        for row in self.buffer:
            for i in range(len(row)):
                row[i] = (" ", C_PHOSPHOR)
        self.cursor_x = 0
        self.cursor_y = 0

    def set_char(self, x: int, y: int, char: str, color: Tuple[int, int, int] = C_PHOSPHOR):
        """Set character at position."""
        if 0 <= x < SCREEN_CHARS_X and 0 <= y < SCREEN_CHARS_Y:
            self.buffer[y][x] = (char[0] if char else " ", color)

    def print_at(self, x: int, y: int, text: str, color: Tuple[int, int, int] = C_PHOSPHOR):
        """Print text at position."""
        for i, char in enumerate(text):
            if x + i < SCREEN_CHARS_X:
                self.set_char(x + i, y, char, color)

    def print_line(self, text: str, color: Tuple[int, int, int] = C_PHOSPHOR):
        """Print at cursor, advance."""
        for char in text:
            if char == '\n':
                self._newline()
            else:
                self.set_char(self.cursor_x, self.cursor_y, char, color)
                self.cursor_x += 1
                if self.cursor_x >= SCREEN_CHARS_X:
                    self._newline()

    def println(self, text: str = "", color: Tuple[int, int, int] = C_PHOSPHOR):
        """Print and newline."""
        self.print_line(text, color)
        self._newline()

    def _newline(self):
        """Move to next line, scroll if needed."""
        self.cursor_x = 0
        self.cursor_y += 1
        if self.cursor_y >= SCREEN_CHARS_Y:
            self._scroll()
            self.cursor_y = SCREEN_CHARS_Y - 1

    def _scroll(self):
        """Scroll up one line."""
        self.buffer.pop(0)
        self.buffer.append([(" ", C_PHOSPHOR) for _ in range(SCREEN_CHARS_X)])

    def update(self, dt: float):
        """Update animations."""
        self.cursor_blink += dt
        if self.cursor_blink >= 0.5:
            self.cursor_blink = 0
            self.cursor_visible = not self.cursor_visible

    def render(self) -> pygame.Surface:
        """Render the screen with CRT effects."""
        # Clear to phosphor background
        self.char_surface.fill(C_PHOSPHOR_BG)

        # Draw characters
        for y, row in enumerate(self.buffer):
            for x, (char, color) in enumerate(row):
                if char and char != " ":
                    # Character glow (subtle)
                    glow_color = (color[0] // 4, color[1] // 4, color[2] // 4)
                    glow = self.font.render(char, True, glow_color)
                    self.char_surface.blit(glow, (x * CHAR_WIDTH - 1, y * CHAR_HEIGHT))
                    self.char_surface.blit(glow, (x * CHAR_WIDTH + 1, y * CHAR_HEIGHT))

                    # Main character
                    char_surf = self.font.render(char, True, color)
                    self.char_surface.blit(char_surf, (x * CHAR_WIDTH, y * CHAR_HEIGHT))

        # Cursor
        if self.cursor_visible:
            cursor_rect = (
                self.cursor_x * CHAR_WIDTH,
                self.cursor_y * CHAR_HEIGHT,
                CHAR_WIDTH,
                CHAR_HEIGHT
            )
            pygame.draw.rect(self.char_surface, C_PHOSPHOR_BRIGHT, cursor_rect)

        # Apply CRT effects
        self.char_surface.blit(self.scanlines, (0, 0))
        self.char_surface.blit(self.curvature, (0, 0))

        return self.char_surface


# ==============================================================================
# DESK SCENE RENDERER
# ==============================================================================

class DeskScene:
    """
    Renders the desk scene with Apple IIe computer.
    """

    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        self.width = WINDOW_WIDTH
        self.height = WINDOW_HEIGHT

        # Pre-render static elements
        self._render_background()
        self._render_monitor_case()
        self._render_keyboard()
        self._render_vignette()

    def _render_background(self):
        """Render wall, posters, and desk - 80s teen hacker movie style."""
        self.background = pygame.Surface((self.width, self.height))

        # Wall (gradient - darker at top for moody atmosphere)
        for y in range(self.height):
            shade = max(0, min(255, 30 + y // 15))
            color = (shade - 15, shade - 10, shade + 5)  # Slight blue tint
            pygame.draw.line(self.background, color, (0, y), (self.width, y))

        # === POSTERS: Try to load image files, fall back to drawn ===
        poster_dir = Path(__file__).parent / "assets"
        left_poster = poster_dir / "poster_left.png"
        right_poster = poster_dir / "poster_right.png"

        # Left poster
        if left_poster.exists():
            self._draw_image_poster(40, 50, 180, 250, left_poster)
        else:
            self._draw_synthwave_poster(40, 50, 180, 250)

        # Right poster
        if right_poster.exists():
            self._draw_image_poster(1060, 50, 180, 250, right_poster)
        else:
            self._draw_hacker_poster(1060, 50, 180, 250)

        # Desk surface
        desk_top = 520
        pygame.draw.rect(self.background, C_DESK, (0, desk_top, self.width, self.height - desk_top))

        # Desk edge highlight
        pygame.draw.line(self.background, (130, 90, 50), (0, desk_top), (self.width, desk_top), 3)

        # Desk shadow gradient
        for i in range(20):
            pygame.draw.line(self.background, (C_DESK[0] - 20, C_DESK[1] - 15, C_DESK[2] - 10),
                           (0, desk_top + 3 + i), (self.width, desk_top + 3 + i))

        # Wood grain texture (subtle horizontal lines)
        for y in range(desk_top + 20, self.height, 8):
            grain_color = (C_DESK[0] + random.randint(-10, 10),
                          C_DESK[1] + random.randint(-10, 10),
                          C_DESK[2] + random.randint(-10, 10))
            pygame.draw.line(self.background, grain_color, (0, y), (self.width, y))

        # === AMBIENT 80s ITEMS ===
        self._draw_ambient_items()

    def _draw_synthwave_poster(self, x: int, y: int, w: int, h: int):
        """Draw a synthwave-style 80s poster with grid and sun."""
        # Frame
        pygame.draw.rect(self.background, C_POSTER_FRAME, (x - 3, y - 3, w + 6, h + 6))

        # Gradient background (purple to dark blue)
        for py in range(h):
            ratio = py / h
            r = int(C_POSTER_BG1[0] * (1 - ratio) + 20 * ratio)
            g = int(C_POSTER_BG1[1] * (1 - ratio) + 10 * ratio)
            b = int(C_POSTER_BG1[2] * (1 - ratio) + 60 * ratio)
            pygame.draw.line(self.background, (r, g, b), (x, y + py), (x + w, y + py))

        # Synthwave sun (striped circle at top)
        sun_cx = x + w // 2
        sun_cy = y + 60
        sun_r = 45
        for i in range(sun_r, 0, -1):
            # Gradient from yellow to hot pink
            ratio = i / sun_r
            color = (
                int(255 * ratio + 255 * (1 - ratio)),
                int(200 * ratio + 50 * (1 - ratio)),
                int(50 * ratio + 200 * (1 - ratio))
            )
            pygame.draw.circle(self.background, color, (sun_cx, sun_cy), i)

        # Sun stripes (horizontal lines through sun)
        for stripe_y in range(sun_cy - sun_r + 10, sun_cy + sun_r, 8):
            if stripe_y > sun_cy:
                pygame.draw.line(self.background, C_POSTER_BG1,
                               (sun_cx - sun_r, stripe_y), (sun_cx + sun_r, stripe_y), 3)

        # Perspective grid at bottom
        grid_top = y + 120
        grid_bottom = y + h - 10

        # Horizontal grid lines (converging to horizon)
        for i in range(8):
            gy = grid_top + int((grid_bottom - grid_top) * (i / 7) ** 1.5)
            pygame.draw.line(self.background, C_POSTER_GRID, (x + 5, gy), (x + w - 5, gy), 1)

        # Vertical grid lines (converging to center)
        horizon_y = grid_top
        for i in range(-4, 5):
            bottom_x = x + w // 2 + i * 20
            top_x = x + w // 2 + i * 5
            pygame.draw.line(self.background, C_POSTER_GRID,
                           (top_x, horizon_y), (bottom_x, grid_bottom), 1)

        # Neon text: "OUTRUN"
        try:
            font = pygame.font.SysFont('impact', 20)
            text = font.render("OUTRUN", True, C_POSTER_NEON)
            self.background.blit(text, (x + (w - text.get_width()) // 2, y + h - 35))
        except:
            pass

    def _draw_hacker_poster(self, x: int, y: int, w: int, h: int):
        """Draw an 80s hacker movie style poster."""
        # Frame
        pygame.draw.rect(self.background, C_POSTER_FRAME, (x - 3, y - 3, w + 6, h + 6))

        # Dark background with circuit-like pattern
        pygame.draw.rect(self.background, C_POSTER_BG2, (x, y, w, h))

        # Circuit board traces (random lines)
        for _ in range(15):
            px1 = x + random.randint(10, w - 10)
            py1 = y + random.randint(10, h - 60)
            px2 = px1 + random.randint(-40, 40)
            py2 = py1 + random.randint(20, 60)
            pygame.draw.line(self.background, (0, 80, 0), (px1, py1), (px2, py2), 1)
            # Node
            pygame.draw.circle(self.background, (0, 120, 0), (px1, py1), 3)

        # ASCII skull (simplified)
        skull_lines = [
            "  .---.  ",
            " / o o \\ ",
            " |  ^  | ",
            " | '-' | ",
            "  '---'  ",
        ]
        try:
            font = pygame.font.SysFont('couriernew', 14)
            skull_y = y + 30
            for line in skull_lines:
                text = font.render(line, True, C_POSTER_ACCENT2)
                self.background.blit(text, (x + (w - text.get_width()) // 2, skull_y))
                skull_y += 16
        except:
            pass

        # "HACK THE PLANET" text
        try:
            font = pygame.font.SysFont('impact', 16)
            text1 = font.render("HACK THE", True, C_POSTER_ACCENT1)
            text2 = font.render("PLANET", True, C_POSTER_ACCENT2)
            self.background.blit(text1, (x + (w - text1.get_width()) // 2, y + 140))
            self.background.blit(text2, (x + (w - text2.get_width()) // 2, y + 160))
        except:
            pass

        # Binary rain effect
        try:
            font = pygame.font.SysFont('couriernew', 10)
            for col in range(0, w, 12):
                for row in range(0, 50, 12):
                    if random.random() > 0.5:
                        char = random.choice(['0', '1'])
                        alpha = random.randint(50, 150)
                        text = font.render(char, True, (0, alpha, 0))
                        self.background.blit(text, (x + col + 5, y + h - 55 + row))
        except:
            pass

    def _draw_image_poster(self, x: int, y: int, w: int, h: int, image_path: Path):
        """Draw a poster from an image file, scaled to fit."""
        try:
            # Load image
            img = pygame.image.load(str(image_path))

            # Scale to fit poster area while maintaining aspect ratio
            img_w, img_h = img.get_size()
            scale = min(w / img_w, h / img_h)
            new_w = int(img_w * scale)
            new_h = int(img_h * scale)

            # Scale with nearest neighbor for pixel art look
            scaled = pygame.transform.scale(img, (new_w, new_h))

            # Center in poster area
            offset_x = x + (w - new_w) // 2
            offset_y = y + (h - new_h) // 2

            # Draw frame
            pygame.draw.rect(self.background, C_POSTER_FRAME, (x - 3, y - 3, w + 6, h + 6))

            # Draw poster background (in case image doesn't fill)
            pygame.draw.rect(self.background, (20, 20, 25), (x, y, w, h))

            # Blit the image
            self.background.blit(scaled, (offset_x, offset_y))

        except Exception as e:
            # Fallback to drawn poster if image fails
            print(f"Could not load poster image: {e}")
            self._draw_synthwave_poster(x, y, w, h)

    def _draw_ambient_items(self):
        """Draw 80s ambient items on the desk."""
        desk_top = 520

        # Soda can (left side)
        can_x, can_y = 60, desk_top - 50
        pygame.draw.ellipse(self.background, C_SODA_CAN, (can_x, can_y, 25, 10))
        pygame.draw.rect(self.background, C_SODA_CAN, (can_x, can_y + 5, 25, 40))
        pygame.draw.ellipse(self.background, (150, 40, 40), (can_x, can_y + 40, 25, 10))
        # Can label
        pygame.draw.rect(self.background, (255, 255, 255), (can_x + 5, can_y + 15, 15, 20))

        # Stack of floppy disks (right side)
        disk_x, disk_y = 1150, desk_top - 35
        for i in range(4):
            dy = disk_y - i * 4
            pygame.draw.rect(self.background, (30, 30, 35), (disk_x, dy, 50, 35))
            pygame.draw.rect(self.background, (200, 200, 200), (disk_x + 15, dy + 5, 20, 10))
            # Label colors
            label_colors = [(255, 200, 0), (100, 200, 255), (255, 100, 100), (100, 255, 100)]
            pygame.draw.rect(self.background, label_colors[i], (disk_x + 5, dy + 20, 40, 10))

        # Pizza box (partially visible on left)
        box_x, box_y = -30, desk_top - 30
        pygame.draw.rect(self.background, C_PIZZA_BOX, (box_x, box_y, 100, 25))
        pygame.draw.rect(self.background, (160, 120, 80), (box_x, box_y, 100, 5))

        # Pencil cup with pens
        cup_x, cup_y = 1100, desk_top - 60
        pygame.draw.rect(self.background, (60, 60, 70), (cup_x, cup_y, 30, 55))
        # Pens sticking out
        pygame.draw.line(self.background, (200, 50, 50), (cup_x + 8, cup_y - 15), (cup_x + 8, cup_y + 10), 3)
        pygame.draw.line(self.background, (50, 50, 200), (cup_x + 16, cup_y - 20), (cup_x + 16, cup_y + 10), 3)
        pygame.draw.line(self.background, (50, 180, 50), (cup_x + 22, cup_y - 10), (cup_x + 22, cup_y + 10), 3)

    def _render_monitor_case(self):
        """Load and display the pixel art computer sprite."""
        # Try to load the sprite image
        sprite_path = Path(__file__).parent / "assets" / "computer_sprite.png"

        if sprite_path.exists():
            # Load sprite with transparency
            sprite = pygame.image.load(str(sprite_path)).convert_alpha()

            # Scale to fit nicely on desk (original is 1536x1024)
            scale = 0.48  # Slightly larger for better visibility
            new_w = int(sprite.get_width() * scale)
            new_h = int(sprite.get_height() * scale)
            self.monitor_surface = pygame.transform.scale(sprite, (new_w, new_h))

            # Screen position within the sprite (measured from reference image)
            # In original 1536x1024: screen starts ~x=245, y=135, width ~395, height ~355
            # These measurements are from the blue screen area in the monitor
            screen_left = int(245 * scale)
            screen_top = int(135 * scale)
            screen_w = int(395 * scale)
            screen_h = int(355 * scale)

            self._screen_offset = (screen_left, screen_top)
            self._screen_size = (screen_w, screen_h)
            self._using_sprite = True
            self._sprite_scale = scale
        else:
            # Fallback to simple drawn version if sprite not found
            self._render_monitor_case_fallback()

    def _render_monitor_case_fallback(self):
        """Fallback drawn version if sprite not available."""
        self.monitor_surface = pygame.Surface((MONITOR_WIDTH, MONITOR_HEIGHT), pygame.SRCALPHA)

        # Simple beige monitor
        beige = (200, 192, 180)
        outline = (80, 75, 70)

        # Monitor body
        pygame.draw.rect(self.monitor_surface, beige, (40, 30, 420, 340))
        pygame.draw.rect(self.monitor_surface, outline, (40, 30, 420, 340), 3)

        # Screen area
        screen_left = 75
        screen_top = 65
        screen_w = 350
        screen_h = 240

        # Dark bezel
        pygame.draw.rect(self.monitor_surface, (30, 30, 35), (screen_left - 5, screen_top - 5, screen_w + 10, screen_h + 10))

        self._screen_offset = (screen_left, screen_top)
        self._screen_size = (screen_w, screen_h)
        self._using_sprite = False

    def _render_keyboard(self):
        """Set up keyboard and STOP button - sprite includes these visually."""
        # Check if using sprite (keyboard is included in sprite)
        if hasattr(self, '_using_sprite') and self._using_sprite:
            # Sprite includes keyboard visually - just set up the STOP button hitbox
            # STOP button position in original 1536x1024 image: roughly x=850, y=580
            scale = getattr(self, '_sprite_scale', 0.48)
            self.estop_rect = pygame.Rect(
                MONITOR_X + int(870 * scale),
                MONITOR_Y + int(560 * scale),
                int(200 * scale),
                int(170 * scale)
            )
            self.keyboard_surface = None  # No separate keyboard needed
        else:
            # Fallback: draw keyboard
            kb_width = 480
            kb_height = 120
            self.keyboard_surface = pygame.Surface((kb_width, kb_height), pygame.SRCALPHA)

            kb_body = (180, 175, 168)
            key_dark = (70, 70, 75)
            key_mid = (90, 90, 95)

            pygame.draw.rect(self.keyboard_surface, kb_body, (5, 5, kb_width - 10, kb_height - 10))
            pygame.draw.rect(self.keyboard_surface, (50, 50, 55), (5, 5, kb_width - 10, kb_height - 10), 2)

            # Simplified keys
            for row in range(4):
                for col in range(14):
                    x = 15 + row * 3 + col * 32
                    y = 15 + row * 22
                    if x + 28 > kb_width - 15:
                        break
                    pygame.draw.rect(self.keyboard_surface, key_dark, (x + 2, y + 2, 28, 18))
                    pygame.draw.rect(self.keyboard_surface, key_mid, (x, y, 28, 18))

            self.keyboard_x = MONITOR_X + 60
            self.keyboard_y = 530
            self.estop_rect = pygame.Rect(self.keyboard_x + kb_width + 40, self.keyboard_y + 10, 90, 90)

        # Pre-render chair back
        self._render_chair()

    def _render_chair(self):
        """Render the office chair back that we're looking over."""
        # Chair dimensions - big, in foreground
        chair_width = 400
        chair_height = 200

        self.chair_surface = pygame.Surface((chair_width, chair_height), pygame.SRCALPHA)

        # Chair back cushion (curved top, upholstered look)
        # Main back shape - curved top edge
        cushion_points = []

        # Build curved top
        for i in range(21):
            x = i * (chair_width // 20)
            # Parabolic curve - higher in middle
            curve = 30 * math.sin(math.pi * i / 20)
            y = 20 + curve
            cushion_points.append((x, int(y)))

        # Bottom straight edge
        cushion_points.append((chair_width, chair_height))
        cushion_points.append((0, chair_height))

        # Draw cushion with fabric texture
        pygame.draw.polygon(self.chair_surface, C_CHAIR_FABRIC, cushion_points)

        # Fabric texture - vertical lines suggesting upholstery
        for x in range(10, chair_width - 10, 15):
            height_at_x = 20 + 30 * math.sin(math.pi * x / chair_width)
            pygame.draw.line(self.chair_surface, C_CHAIR_FABRIC_LIGHT,
                           (x, int(height_at_x) + 5), (x, chair_height - 5), 1)

        # Highlight at top (light hitting the curve)
        for i in range(20):
            x = i * (chair_width // 20)
            curve = 30 * math.sin(math.pi * i / 20)
            y = 25 + curve
            pygame.draw.circle(self.chair_surface, C_CHAIR_FABRIC_LIGHT, (x + 10, int(y)), 2)

        # Metal frame sides (arms of chair visible)
        # Left arm
        pygame.draw.rect(self.chair_surface, C_CHAIR_METAL, (0, 40, 15, chair_height - 40))
        pygame.draw.rect(self.chair_surface, (90, 90, 95), (3, 40, 5, chair_height - 40))  # Highlight

        # Right arm
        pygame.draw.rect(self.chair_surface, C_CHAIR_METAL, (chair_width - 15, 40, 15, chair_height - 40))
        pygame.draw.rect(self.chair_surface, (90, 90, 95), (chair_width - 12, 40, 5, chair_height - 40))

        # Store position (bottom center of screen, large)
        self.chair_x = (WINDOW_WIDTH - chair_width) // 2
        self.chair_y = WINDOW_HEIGHT - chair_height + 60  # Partially off screen

    def render_estop(self, surface: pygame.Surface, pressed: bool, stopped: bool):
        """Render big red mushroom STOP button with hazard stripes - like the reference."""
        # Skip rendering if using sprite (button is in the image)
        # But we still detect clicks via estop_rect
        if hasattr(self, '_using_sprite') and self._using_sprite:
            # Just show visual feedback for pressed/stopped state
            if pressed or stopped:
                # Dim overlay on button area when pressed/stopped
                overlay = pygame.Surface((self.estop_rect.width, self.estop_rect.height), pygame.SRCALPHA)
                alpha = 100 if stopped else 50
                overlay.fill((0, 0, 0, alpha))
                surface.blit(overlay, (self.estop_rect.x, self.estop_rect.y))
            return

        x, y = self.estop_rect.x, self.estop_rect.y
        size = self.estop_rect.width

        # === HAZARD BASE (yellow/black stripes) ===
        base_height = 25
        base_y = y + size - base_height // 2

        # Yellow base rectangle
        pygame.draw.rect(surface, (50, 50, 55), (x - 10, base_y, size + 20, base_height))  # Dark backing
        pygame.draw.rect(surface, (220, 180, 0), (x - 8, base_y + 2, size + 16, base_height - 4))

        # Black diagonal hazard stripes
        stripe_width = 12
        for i in range(-2, size + 30, stripe_width * 2):
            points = [
                (x - 8 + i, base_y + 2),
                (x - 8 + i + stripe_width, base_y + 2),
                (x - 8 + i + stripe_width - 8, base_y + base_height - 4),
                (x - 8 + i - 8, base_y + base_height - 4),
            ]
            # Clip to base area
            pygame.draw.polygon(surface, (30, 30, 30), points)

        # Clip the stripes to the base
        pygame.draw.rect(surface, (50, 50, 55), (x - 15, base_y, 5, base_height))
        pygame.draw.rect(surface, (50, 50, 55), (x + size + 5, base_y, 10, base_height))

        # === BIG RED MUSHROOM BUTTON ===
        btn_cx = x + size // 2
        btn_cy = y + size // 2 - 5

        # Button colors
        if stopped:
            red_bright = (100, 30, 30)
            red_mid = (80, 25, 25)
            red_dark = (60, 20, 20)
            text_color = (80, 80, 80)
        elif pressed:
            red_bright = (255, 100, 100)
            red_mid = (230, 70, 70)
            red_dark = (180, 50, 50)
            text_color = (255, 255, 255)
        else:
            red_bright = (220, 50, 50)
            red_mid = (200, 40, 40)
            red_dark = (150, 30, 30)
            text_color = (255, 255, 255)

        # Button shadow (underneath)
        pygame.draw.ellipse(surface, (30, 30, 35), (btn_cx - 42, btn_cy + 5, 84, 50))

        # Button dome (3D mushroom shape with gradient)
        # Outer ring (dark)
        pygame.draw.ellipse(surface, red_dark, (btn_cx - 40, btn_cy - 15, 80, 55))
        # Middle ring
        pygame.draw.ellipse(surface, red_mid, (btn_cx - 36, btn_cy - 12, 72, 48))
        # Inner dome (bright)
        pygame.draw.ellipse(surface, red_bright, (btn_cx - 32, btn_cy - 8, 64, 40))

        # Highlight (top-left reflection)
        highlight_surf = pygame.Surface((30, 20), pygame.SRCALPHA)
        for i in range(10):
            alpha = max(0, 100 - i * 12)
            pygame.draw.ellipse(highlight_surf, (255, 255, 255, alpha),
                              (i, i, 30 - i*2, 20 - i*2))
        surface.blit(highlight_surf, (btn_cx - 25, btn_cy - 5))

        # === STOP TEXT ===
        try:
            font = pygame.font.SysFont('arial', 18, bold=True)
            text = font.render("STOP", True, text_color)
            text_x = btn_cx - text.get_width() // 2
            text_y = btn_cy + 5
            surface.blit(text, (text_x, text_y))
        except:
            pass

        # Outline around entire button assembly
        pygame.draw.rect(surface, (60, 60, 65), (x - 12, y - 5, size + 24, size + base_height), 2)

    def _render_vignette(self):
        """Pre-render cinematic vignette effect for 80s movie feel."""
        self.vignette_surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)

        # Darken edges progressively
        for i in range(50):
            alpha = int((50 - i) * 1.5)
            # Top edge
            pygame.draw.rect(self.vignette_surface, (0, 0, 0, alpha), (0, i, self.width, 1))
            # Bottom edge
            pygame.draw.rect(self.vignette_surface, (0, 0, 0, alpha), (0, self.height - i - 1, self.width, 1))
            # Left edge
            pygame.draw.rect(self.vignette_surface, (0, 0, 0, alpha), (i, 0, 1, self.height))
            # Right edge
            pygame.draw.rect(self.vignette_surface, (0, 0, 0, alpha), (self.width - i - 1, 0, 1, self.height))

        # Corner darkening (extra cinematic feel)
        corner_size = 150
        for x in range(corner_size):
            for y in range(corner_size):
                if x + y < corner_size:
                    alpha = int((corner_size - x - y) * 0.3)
                    # Top-left
                    self.vignette_surface.set_at((x, y), (0, 0, 0, min(alpha, 60)))
                    # Top-right
                    self.vignette_surface.set_at((self.width - x - 1, y), (0, 0, 0, min(alpha, 60)))
                    # Bottom-left
                    self.vignette_surface.set_at((x, self.height - y - 1), (0, 0, 0, min(alpha, 60)))
                    # Bottom-right
                    self.vignette_surface.set_at((self.width - x - 1, self.height - y - 1), (0, 0, 0, min(alpha, 60)))

    def draw(self, crt_screen: pygame.Surface):
        """Draw the complete scene - 80s pixel art computer setup."""
        # Background (wall, posters, desk, ambient items)
        self.screen.blit(self.background, (0, 0))

        # Monitor/computer sprite (includes tower, keyboard, STOP button if using sprite)
        self.screen.blit(self.monitor_surface, (MONITOR_X, MONITOR_Y))

        # CRT screen content - scale to fit the monitor's screen area
        screen_x = MONITOR_X + self._screen_offset[0]
        screen_y = MONITOR_Y + self._screen_offset[1]
        screen_w, screen_h = self._screen_size

        # Scale the CRT content to fit the screen area
        scaled_crt = pygame.transform.scale(crt_screen, (screen_w, screen_h))
        self.screen.blit(scaled_crt, (screen_x, screen_y))

        # Screen glow effect (subtle green glow around screen)
        glow_surf = pygame.Surface((screen_w + 20, screen_h + 20), pygame.SRCALPHA)
        pygame.draw.rect(glow_surf, (0, 60, 0, 15), (0, 0, screen_w + 20, screen_h + 20))
        self.screen.blit(glow_surf, (screen_x - 10, screen_y - 10))

        # Only draw separate keyboard if not using sprite
        if self.keyboard_surface is not None:
            self.screen.blit(self.keyboard_surface, (self.keyboard_x, self.keyboard_y))

        # Chair back in foreground (we're looking over it)
        self.screen.blit(self.chair_surface, (self.chair_x, self.chair_y))

        # Cinematic vignette overlay
        self.screen.blit(self.vignette_surface, (0, 0))


# ==============================================================================
# MAIN GUI CLASS
# ==============================================================================

class Apple2TerminalGUI:
    """
    Apple IIe desktop scene with terminal.
    """

    def __init__(
        self,
        on_stop: Optional[Callable] = None,
        on_user_input: Optional[Callable[[str], None]] = None,
    ):
        if not PYGAME_AVAILABLE:
            raise ImportError("pygame required: pip install pygame")

        self.on_stop = on_stop
        self.on_user_input = on_user_input

        pygame.init()
        pygame.display.set_caption("Fast_Swarm Audit Supervisor - Apple //e")

        self.screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        self.clock = pygame.time.Clock()

        # CRT Screen
        self.crt = AppleIIScreen()

        # Desk scene
        self.scene = DeskScene(self.screen)

        # Input state
        self.input_text = ""
        self.input_active = True

        # Stop button state
        self.stop_pressed = False
        self.stop_stopped = False

        # Message queue (thread-safe)
        self._message_queue: queue.Queue = queue.Queue()
        self._running = False
        self._start_time: Optional[datetime] = None

        # Status
        self.phase = "READY"
        self.agents_done = 0
        self.agents_total = 0
        self.health = "OK"

        # Terminal state - scrolling messages
        self.messages: List[Tuple[str, Tuple[int, int, int]]] = []
        self.terminal_start_row = 3
        self.terminal_end_row = 20

        # Boot sequence
        self._show_boot()

    def _show_boot(self):
        """Fun CODE-O-MATIC boot sequence with personality."""
        self._add_message("", C_PHOSPHOR)
        self._add_message("  ==========================================", C_PHOSPHOR_DIM)
        self._add_message("  =                                        =", C_PHOSPHOR_DIM)
        self._add_message("  =       CODE-O-MATIC 5000 (TM)           =", C_PHOSPHOR_BRIGHT)
        self._add_message("  =       Audit Supervisor v1.0            =", C_PHOSPHOR_BRIGHT)
        self._add_message("  =                                        =", C_PHOSPHOR_DIM)
        self._add_message("  =   'Finding bugs so you don't have to!' =", C_PHOSPHOR_DIM)
        self._add_message("  =                                        =", C_PHOSPHOR_DIM)
        self._add_message("  ==========================================", C_PHOSPHOR_DIM)
        self._add_message("", C_PHOSPHOR)
        self._add_message("  Welcome, Blake!", C_PHOSPHOR_BRIGHT)
        self._add_message("", C_PHOSPHOR)
        self._add_message("  I am the CODE-O-MATIC 5000 - your friendly", C_PHOSPHOR)
        self._add_message("  neighborhood code auditor.", C_PHOSPHOR)
        self._add_message("", C_PHOSPHOR)
        self._add_message("  I'm here to:", C_PHOSPHOR)
        self._add_message("    * Review your codebase", C_PHOSPHOR_DIM)
        self._add_message("    * Locate unused functions & dead files", C_PHOSPHOR_DIM)
        self._add_message("    * Find unimplemented features", C_PHOSPHOR_DIM)
        self._add_message("    * Check architecture vs documentation", C_PHOSPHOR_DIM)
        self._add_message("    * Hunt down those sneaky bugs!", C_PHOSPHOR_DIM)
        self._add_message("", C_PHOSPHOR)
        self._add_message("  Type START to begin.", C_PHOSPHOR_BRIGHT)
        self._add_message("", C_PHOSPHOR)

    def _add_message(self, text: str, color: Tuple[int, int, int] = C_PHOSPHOR):
        """Add message to terminal."""
        # Word wrap at 78 chars
        max_width = 78
        while len(text) > max_width:
            self.messages.append((text[:max_width], color))
            text = text[max_width:]
        self.messages.append((text, color))

        # Keep only visible amount
        max_messages = self.terminal_end_row - self.terminal_start_row
        if len(self.messages) > max_messages:
            self.messages = self.messages[-max_messages:]

    def _draw_screen_content(self):
        """Draw terminal content to CRT."""
        self.crt.clear()

        # Title bar
        title = " FAST_SWARM AUDIT SUPERVISOR "
        self.crt.print_at(0, 0, "=" * 80, C_PHOSPHOR_DIM)
        self.crt.print_at((80 - len(title)) // 2, 0, title, C_PHOSPHOR_BRIGHT)

        # Status line
        status = f" PHASE: {self.phase:12} | AGENTS: {self.agents_done:2}/{self.agents_total:2} | [{self.health}] "
        elapsed = ""
        if self._start_time:
            secs = int((datetime.now() - self._start_time).total_seconds())
            mins, s = divmod(secs, 60)
            elapsed = f" {mins:02d}:{s:02d}"
        self.crt.print_at(0, 1, status, C_PHOSPHOR)
        self.crt.print_at(70, 1, elapsed, C_PHOSPHOR_DIM)
        self.crt.print_at(0, 2, "-" * 80, C_PHOSPHOR_DIM)

        # Messages
        row = self.terminal_start_row
        for msg_text, msg_color in self.messages:
            self.crt.print_at(0, row, msg_text, msg_color)
            row += 1
            if row >= self.terminal_end_row:
                break

        # Input area
        self.crt.print_at(0, 21, "-" * 80, C_PHOSPHOR_DIM)
        self.crt.print_at(0, 22, "]" + self.input_text, C_PHOSPHOR_BRIGHT)

        # Position cursor
        self.crt.cursor_x = 1 + len(self.input_text)
        self.crt.cursor_y = 22

        # Footer
        self.crt.print_at(0, 23, " F1:HELP  F5:STATUS  F10:STOP                    ESC:QUIT ", C_PHOSPHOR_DIM)

    def _process_queue(self):
        """Process thread-safe message queue."""
        try:
            while True:
                msg = self._message_queue.get_nowait()
                msg_type = msg[0]

                if msg_type == "message":
                    self._add_message(msg[1], msg[2] if len(msg) > 2 else C_PHOSPHOR)
                elif msg_type == "system":
                    ts = datetime.now().strftime("%H:%M:%S")
                    self._add_message(f"[{ts}] {msg[1]}", C_PHOSPHOR_BRIGHT)
                elif msg_type == "agent":
                    self._add_message(f"[{msg[1]}] {msg[2]}", C_PHOSPHOR)
                elif msg_type == "error":
                    self._add_message(f"*** ERROR: {msg[1]} ***", C_PHOSPHOR_BRIGHT)
                elif msg_type == "header":
                    self._add_message("=" * 60, C_PHOSPHOR_DIM)
                    self._add_message(f" {msg[1]} ".center(60, "="), C_PHOSPHOR_BRIGHT)
                    self._add_message("=" * 60, C_PHOSPHOR_DIM)
                elif msg_type == "phase":
                    self.phase = msg[1]
                elif msg_type == "agents":
                    self.agents_done, self.agents_total = msg[1], msg[2]
                elif msg_type == "health":
                    self.health = msg[1]

        except queue.Empty:
            pass

    def _handle_events(self):
        """Handle pygame events."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._running = False

            elif event.type == pygame.MOUSEBUTTONDOWN:
                # Check emergency stop
                if self.scene.estop_rect.collidepoint(event.pos):
                    if not self.stop_stopped:
                        self.stop_pressed = True

            elif event.type == pygame.MOUSEBUTTONUP:
                if self.stop_pressed and not self.stop_stopped:
                    if self.scene.estop_rect.collidepoint(event.pos):
                        self.stop_stopped = True
                        self._add_message("*** EMERGENCY STOP ACTIVATED ***", C_PHOSPHOR_BRIGHT)
                        self._add_message("HALTING ALL OPERATIONS...", C_PHOSPHOR_BRIGHT)
                        if self.on_stop:
                            self.on_stop()
                self.stop_pressed = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self._running = False

                elif event.key == pygame.K_RETURN:
                    if self.input_text.strip():
                        text = self.input_text.strip().upper()
                        self._add_message(f"]{text}", C_PHOSPHOR_BRIGHT)
                        self.input_text = ""
                        self._handle_command(text)

                elif event.key == pygame.K_BACKSPACE:
                    self.input_text = self.input_text[:-1]

                elif event.key == pygame.K_F1:
                    self._handle_command("HELP")
                elif event.key == pygame.K_F5:
                    self._handle_command("STATUS")
                elif event.key == pygame.K_F10:
                    if not self.stop_stopped:
                        self.stop_stopped = True
                        self._add_message("*** EMERGENCY STOP ***", C_PHOSPHOR_BRIGHT)
                        if self.on_stop:
                            self.on_stop()

                elif event.unicode and event.unicode.isprintable():
                    if len(self.input_text) < 70:
                        self.input_text += event.unicode.upper()

    def _handle_command(self, cmd: str):
        """Handle user command with personality!"""
        if cmd == "HELP":
            self._add_message("", C_PHOSPHOR)
            self._add_message("  COMMANDS:", C_PHOSPHOR_BRIGHT)
            self._add_message("    START  - Begin the code audit", C_PHOSPHOR)
            self._add_message("    STATUS - Show current progress", C_PHOSPHOR)
            self._add_message("    STOP   - Emergency stop (recall spiders)", C_PHOSPHOR)
            self._add_message("    CLEAR  - Clear screen", C_PHOSPHOR)
            self._add_message("", C_PHOSPHOR)
        elif cmd == "STATUS":
            self._add_message("", C_PHOSPHOR)
            self._add_message(f"  Phase: {self.phase}", C_PHOSPHOR)
            self._add_message(f"  Active Spiders: {self.agents_done}/{self.agents_total}", C_PHOSPHOR)
            self._add_message(f"  System Health: [{self.health}]", C_PHOSPHOR)
            self._add_message("", C_PHOSPHOR)
        elif cmd == "CLEAR":
            self.messages.clear()
        elif cmd == "START":
            self._add_message("", C_PHOSPHOR)
            self._add_message("  *** INITIATING AUDIT SEQUENCE ***", C_PHOSPHOR_BRIGHT)
            self._add_message("", C_PHOSPHOR)
            self._add_message("  Spawning Code Crawlers...", C_PHOSPHOR)
            self._add_message("", C_PHOSPHOR)
            self._add_message("  GO SPIDERS GO !!!", C_PHOSPHOR_BRIGHT)
            self._add_message("", C_PHOSPHOR)
            if self.on_user_input:
                self.on_user_input(cmd)
        elif cmd == "STOP":
            self.stop_stopped = True
            self._add_message("", C_PHOSPHOR)
            self._add_message("  *** EMERGENCY STOP ***", C_PHOSPHOR_BRIGHT)
            self._add_message("  Recalling all spiders...", C_PHOSPHOR)
            self._add_message("", C_PHOSPHOR)
            if self.on_stop:
                self.on_stop()
        else:
            # Pass to callback
            if self.on_user_input:
                self.on_user_input(cmd)
            else:
                self._add_message(f"  Huh? I don't know '{cmd}'", C_PHOSPHOR_DIM)
                self._add_message("  Type HELP for commands.", C_PHOSPHOR_DIM)

    def _render(self):
        """Render the scene."""
        # Update and render CRT content
        self._draw_screen_content()
        crt_surface = self.crt.render()

        # Draw desk scene with CRT
        self.scene.draw(crt_surface)

        # Draw emergency stop button
        self.scene.render_estop(self.screen, self.stop_pressed, self.stop_stopped)

        pygame.display.flip()

    # ==========================================================================
    # PUBLIC API (Thread-Safe)
    # ==========================================================================

    def start(self):
        """Start GUI (blocking)."""
        self._running = True
        self._start_time = datetime.now()

        while self._running:
            dt = self.clock.tick(60) / 1000.0

            self._process_queue()
            self._handle_events()
            self.crt.update(dt)
            self._render()

        pygame.quit()

    def stop(self):
        """Stop GUI."""
        self._running = False

    def write(self, text: str, color: Tuple[int, int, int] = C_PHOSPHOR):
        """Write text (thread-safe)."""
        self._message_queue.put(("message", text, color))

    def write_agent(self, agent_id: str, message: str):
        """Write agent message (thread-safe)."""
        self._message_queue.put(("agent", agent_id, message))

    def write_system(self, message: str):
        """Write system message (thread-safe)."""
        self._message_queue.put(("system", message))

    def write_error(self, message: str):
        """Write error (thread-safe)."""
        self._message_queue.put(("error", message))

    def write_header(self, text: str):
        """Write header (thread-safe)."""
        self._message_queue.put(("header", text))

    def set_phase(self, phase: str):
        """Set phase (thread-safe)."""
        self._message_queue.put(("phase", phase))

    def set_agents(self, done: int, total: int):
        """Set agent counts (thread-safe)."""
        self._message_queue.put(("agents", done, total))

    def set_health(self, status: str):
        """Set health (thread-safe)."""
        self._message_queue.put(("health", status))


# ==============================================================================
# FUN SPIDER NAMES AND MESSAGES
# ==============================================================================

SPIDER_NAMES = [
    "Spider-Bot Alpha",
    "Code Crawler Prime",
    "Syntax Sniffer 3000",
    "Bug Hunter X",
    "Dead Code Detective",
    "Import Inspector",
]

SPIDER_ACTIONS = [
    "Crawling through files...",
    "Sniffing for dead code...",
    "Hunting rogue imports...",
    "Scanning for anomalies...",
    "Analyzing patterns...",
    "Checking coverage gaps...",
    "Inspecting documentation...",
    "Tracing dependencies...",
    "Mapping architecture...",
    "Detecting unused functions...",
]

SPIDER_FINDS = [
    "Found orphaned function!",
    "Spotted missing docstring!",
    "Detected circular import!",
    "Located dead code block!",
    "Found unused variable!",
    "Discovered type mismatch!",
]

SPIDER_CHEERS = [
    "Got 'em!",
    "Another one bites the dust!",
    "Target acquired!",
    "Nothing escapes the spider!",
    "Clean sweep!",
]


# ==============================================================================
# DEMO
# ==============================================================================

def demo():
    """Demo the Apple IIe style GUI with fun spider simulation."""
    import random

    def on_stop():
        print("STOP!")

    def simulate_audit(gui):
        """Simulate a fun audit when START is typed."""
        time.sleep(0.5)

        # Spawn spiders with fun names
        gui.write_system("Deploying spider agents...")
        time.sleep(0.3)
        for i, name in enumerate(SPIDER_NAMES):
            gui.write(f"  [SPAWN] {name} activated!", C_PHOSPHOR_BRIGHT)
            gui.set_agents(i + 1, len(SPIDER_NAMES))
            time.sleep(0.2)

        gui.write("", C_PHOSPHOR)
        gui.write("  All spiders deployed! Let the hunt begin...", C_PHOSPHOR_BRIGHT)
        gui.write("", C_PHOSPHOR)
        gui.set_phase("CRAWLING")

        # Simulate spider activity
        files_scanned = 0
        issues_found = 0
        for i in range(25):
            time.sleep(random.uniform(0.4, 0.9))

            spider = random.choice(SPIDER_NAMES)
            action = random.choice(SPIDER_ACTIONS)
            gui.write_agent(spider, action)

            files_scanned += random.randint(2, 8)

            # Sometimes find issues
            if random.random() > 0.6:
                issues_found += 1
                find = random.choice(SPIDER_FINDS)
                gui.write(f"  [!] {find}", C_PHOSPHOR_BRIGHT)
                time.sleep(0.2)
                cheer = random.choice(SPIDER_CHEERS)
                gui.write(f"      {cheer}", C_PHOSPHOR_DIM)

            # Phase changes
            if i == 8:
                gui.set_phase("ANALYZING")
                gui.write_system("Entering analysis phase...")
            if i == 16:
                gui.set_phase("SYNTHESIS")
                gui.write_system("Synthesizing findings...")

        # Complete
        gui.set_phase("COMPLETE")
        gui.write("", C_PHOSPHOR)
        gui.write("  ==========================================", C_PHOSPHOR_BRIGHT)
        gui.write("  =          AUDIT COMPLETE!               =", C_PHOSPHOR_BRIGHT)
        gui.write("  ==========================================", C_PHOSPHOR_BRIGHT)
        gui.write("", C_PHOSPHOR)
        gui.write(f"  Files Scanned: {files_scanned}", C_PHOSPHOR)
        gui.write(f"  Issues Found:  {issues_found}", C_PHOSPHOR)
        gui.write("", C_PHOSPHOR)
        gui.write("  Report saved to: audit_output/REPORT.md", C_PHOSPHOR)
        gui.write("", C_PHOSPHOR)
        gui.write("  Thanks for using CODE-O-MATIC 5000!", C_PHOSPHOR_BRIGHT)
        gui.write("  'Your code is now 100% more audited!'", C_PHOSPHOR_DIM)

    def on_input(text):
        if text == "START":
            thread = threading.Thread(target=simulate_audit, args=(gui,), daemon=True)
            thread.start()

    gui = Apple2TerminalGUI(on_stop=on_stop, on_user_input=on_input)
    gui.start()


if __name__ == "__main__":
    demo()
