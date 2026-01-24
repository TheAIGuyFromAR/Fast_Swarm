"""
Commodore 64 Style Terminal GUI for Audit Supervisor
Authentic 8-bit aesthetic with:
- C64 color palette (16 colors)
- Low resolution (320x200) scaled up
- Character-based display (40x25 characters)
- PETSCII-style borders
- Scanline effect
- Big red STOP button

Cross-platform: Windows, Mac, Linux
"""

import math
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, List, Optional, Tuple

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False
    print("pygame not installed. Run: pip install pygame")


# ==============================================================================
# COMMODORE 64 COLOR PALETTE (Authentic!)
# ==============================================================================

# The C64 has exactly 16 colors
C64_BLACK       = (0, 0, 0)           # 0
C64_WHITE       = (255, 255, 255)     # 1
C64_RED         = (136, 0, 0)         # 2
C64_CYAN        = (170, 255, 238)     # 3
C64_PURPLE      = (204, 68, 204)      # 4
C64_GREEN       = (0, 204, 85)        # 5
C64_BLUE        = (0, 0, 170)         # 6
C64_YELLOW      = (238, 238, 119)     # 7
C64_ORANGE      = (221, 136, 85)      # 8
C64_BROWN       = (102, 68, 0)        # 9
C64_LIGHT_RED   = (255, 119, 119)     # 10
C64_DARK_GREY   = (51, 51, 51)        # 11
C64_GREY        = (119, 119, 119)     # 12
C64_LIGHT_GREEN = (170, 255, 102)     # 13
C64_LIGHT_BLUE  = (0, 136, 255)       # 14
C64_LIGHT_GREY  = (187, 187, 187)     # 15

# Semantic color assignments
BG_COLOR = C64_BLUE           # Classic C64 blue background
BORDER_COLOR = C64_LIGHT_BLUE # Border color
TEXT_COLOR = C64_LIGHT_BLUE   # Default text
BRIGHT_COLOR = C64_CYAN       # Highlighted text
DIM_COLOR = C64_BLUE          # Dimmed text (same as bg = invisible effect)
CURSOR_COLOR = C64_LIGHT_GREEN
ERROR_COLOR = C64_RED
WARNING_COLOR = C64_YELLOW
SYSTEM_COLOR = C64_YELLOW
HEADER_COLOR = C64_CYAN


# ==============================================================================
# PETSCII-STYLE CHARACTERS (Using Unicode box drawing as approximation)
# ==============================================================================

# Border characters (we'll draw these with code)
CHAR_HORIZ = "-"
CHAR_VERT = "|"
CHAR_CORNER_TL = "+"
CHAR_CORNER_TR = "+"
CHAR_CORNER_BL = "+"
CHAR_CORNER_BR = "+"


# ==============================================================================
# LOW-RES DISPLAY SETTINGS
# ==============================================================================

# C64 native resolution
NATIVE_WIDTH = 320
NATIVE_HEIGHT = 200
CHAR_WIDTH = 8   # 40 columns = 320 pixels
CHAR_HEIGHT = 8  # 25 rows = 200 pixels
COLS = 40
ROWS = 25

# Scale factor for modern displays
SCALE = 3
SCREEN_WIDTH = NATIVE_WIDTH * SCALE
SCREEN_HEIGHT = NATIVE_HEIGHT * SCALE


# ==============================================================================
# CHARACTER CELL DISPLAY
# ==============================================================================

@dataclass
class CharCell:
    """A single character cell on the screen."""
    char: str = " "
    fg_color: Tuple[int, int, int] = TEXT_COLOR
    bg_color: Tuple[int, int, int] = BG_COLOR
    blink: bool = False


class CharacterDisplay:
    """
    40x25 character display like the C64.
    Renders to a low-res surface then scales up.
    """

    def __init__(self):
        # Character buffer (40 cols x 25 rows)
        self.buffer: List[List[CharCell]] = [
            [CharCell() for _ in range(COLS)]
            for _ in range(ROWS)
        ]

        # Native resolution surface
        self.native_surface = pygame.Surface((NATIVE_WIDTH, NATIVE_HEIGHT))

        # Create a simple 8x8 font
        self.font = pygame.font.Font(pygame.font.match_font('couriernew'), 8)

        # For authentic look, we could use a bitmap font
        # but system monospace at 8px is close enough

        self.cursor_x = 0
        self.cursor_y = 0
        self.cursor_visible = True
        self.cursor_blink_timer = 0

        # Scroll region
        self.scroll_top = 0
        self.scroll_bottom = ROWS - 1

    def clear(self, color: Tuple[int, int, int] = BG_COLOR):
        """Clear the screen."""
        for row in self.buffer:
            for cell in row:
                cell.char = " "
                cell.fg_color = TEXT_COLOR
                cell.bg_color = color
        self.cursor_x = 0
        self.cursor_y = 0

    def set_char(self, x: int, y: int, char: str,
                 fg: Tuple[int, int, int] = TEXT_COLOR,
                 bg: Tuple[int, int, int] = BG_COLOR):
        """Set a character at position."""
        if 0 <= x < COLS and 0 <= y < ROWS:
            self.buffer[y][x].char = char[0] if char else " "
            self.buffer[y][x].fg_color = fg
            self.buffer[y][x].bg_color = bg

    def print_at(self, x: int, y: int, text: str,
                 fg: Tuple[int, int, int] = TEXT_COLOR,
                 bg: Tuple[int, int, int] = BG_COLOR):
        """Print text at position."""
        for i, char in enumerate(text):
            if x + i < COLS:
                self.set_char(x + i, y, char, fg, bg)

    def print_line(self, text: str,
                   fg: Tuple[int, int, int] = TEXT_COLOR,
                   bg: Tuple[int, int, int] = BG_COLOR):
        """Print text at cursor, advance cursor."""
        for char in text:
            if char == '\n':
                self._newline()
            else:
                self.set_char(self.cursor_x, self.cursor_y, char, fg, bg)
                self.cursor_x += 1
                if self.cursor_x >= COLS:
                    self._newline()

    def println(self, text: str = "",
                fg: Tuple[int, int, int] = TEXT_COLOR,
                bg: Tuple[int, int, int] = BG_COLOR):
        """Print text and newline."""
        self.print_line(text, fg, bg)
        self._newline()

    def _newline(self):
        """Move to next line, scroll if needed."""
        self.cursor_x = 0
        self.cursor_y += 1
        if self.cursor_y > self.scroll_bottom:
            self._scroll_up()
            self.cursor_y = self.scroll_bottom

    def _scroll_up(self):
        """Scroll the display up one line."""
        for y in range(self.scroll_top, self.scroll_bottom):
            self.buffer[y] = self.buffer[y + 1].copy()
        # Clear bottom line
        self.buffer[self.scroll_bottom] = [CharCell() for _ in range(COLS)]

    def draw_box(self, x: int, y: int, width: int, height: int,
                 fg: Tuple[int, int, int] = TEXT_COLOR,
                 title: str = ""):
        """Draw a PETSCII-style box."""
        # Top border
        self.set_char(x, y, CHAR_CORNER_TL, fg)
        for i in range(1, width - 1):
            self.set_char(x + i, y, CHAR_HORIZ, fg)
        self.set_char(x + width - 1, y, CHAR_CORNER_TR, fg)

        # Title in top border
        if title:
            title_text = f" {title} "
            start = (width - len(title_text)) // 2
            for i, char in enumerate(title_text):
                self.set_char(x + start + i, y, char, HEADER_COLOR)

        # Sides
        for row in range(1, height - 1):
            self.set_char(x, y + row, CHAR_VERT, fg)
            self.set_char(x + width - 1, y + row, CHAR_VERT, fg)

        # Bottom border
        self.set_char(x, y + height - 1, CHAR_CORNER_BL, fg)
        for i in range(1, width - 1):
            self.set_char(x + i, y + height - 1, CHAR_HORIZ, fg)
        self.set_char(x + width - 1, y + height - 1, CHAR_CORNER_BR, fg)

    def update(self, dt: float):
        """Update animations."""
        self.cursor_blink_timer += dt
        if self.cursor_blink_timer >= 0.5:
            self.cursor_blink_timer = 0
            self.cursor_visible = not self.cursor_visible

    def render(self) -> pygame.Surface:
        """Render to native resolution surface."""
        self.native_surface.fill(BG_COLOR)

        for y, row in enumerate(self.buffer):
            for x, cell in enumerate(row):
                # Background
                if cell.bg_color != BG_COLOR:
                    pygame.draw.rect(
                        self.native_surface,
                        cell.bg_color,
                        (x * CHAR_WIDTH, y * CHAR_HEIGHT, CHAR_WIDTH, CHAR_HEIGHT)
                    )

                # Character
                if cell.char and cell.char != " ":
                    try:
                        char_surface = self.font.render(cell.char, False, cell.fg_color)
                        self.native_surface.blit(
                            char_surface,
                            (x * CHAR_WIDTH, y * CHAR_HEIGHT)
                        )
                    except:
                        pass  # Skip unprintable chars

        # Cursor
        if self.cursor_visible:
            pygame.draw.rect(
                self.native_surface,
                CURSOR_COLOR,
                (self.cursor_x * CHAR_WIDTH, self.cursor_y * CHAR_HEIGHT,
                 CHAR_WIDTH, CHAR_HEIGHT)
            )

        return self.native_surface


# ==============================================================================
# STOP BUTTON (Pixel Art Style)
# ==============================================================================

class PixelStopButton:
    """8-bit style stop button."""

    def __init__(self, x: int, y: int, width: int = 8, height: int = 3):
        """Position in character coordinates."""
        self.char_x = x
        self.char_y = y
        self.width = width
        self.height = height
        self.pressed = False
        self.stopped = False

    def draw(self, display: CharacterDisplay):
        """Draw the button on the character display."""
        # Button background
        bg = C64_DARK_GREY if self.stopped else (C64_LIGHT_RED if self.pressed else C64_RED)
        fg = C64_WHITE if not self.stopped else C64_GREY

        # Draw button area
        for dy in range(self.height):
            for dx in range(self.width):
                display.set_char(self.char_x + dx, self.char_y + dy, " ", fg, bg)

        # STOP text centered
        text = "STOP"
        text_x = self.char_x + (self.width - len(text)) // 2
        text_y = self.char_y + self.height // 2
        display.print_at(text_x, text_y, text, fg, bg)

        # Border
        display.draw_box(
            self.char_x - 1, self.char_y - 1,
            self.width + 2, self.height + 2,
            C64_LIGHT_RED if self.pressed else C64_RED
        )

    def check_click(self, mouse_x: int, mouse_y: int) -> bool:
        """Check if click is on button (in native pixel coords)."""
        px = self.char_x * CHAR_WIDTH
        py = self.char_y * CHAR_HEIGHT
        pw = self.width * CHAR_WIDTH
        ph = self.height * CHAR_HEIGHT

        return (px <= mouse_x < px + pw and py <= mouse_y < py + ph)


# ==============================================================================
# MAIN C64 TERMINAL GUI
# ==============================================================================

class C64TerminalGUI:
    """
    Commodore 64 style terminal GUI.
    40x25 character display, 16 colors, authentic aesthetic.
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
        pygame.display.set_caption("*** FAST_SWARM AUDIT SUPERVISOR ***")

        # Create scaled display
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()

        # Character display
        self.display = CharacterDisplay()

        # Message buffer (for scrolling terminal area)
        self.messages: List[Tuple[str, Tuple[int, int, int]]] = []
        self.terminal_top = 3
        self.terminal_bottom = 20
        self.terminal_height = self.terminal_bottom - self.terminal_top

        # Input state
        self.input_text = ""
        self.input_active = True

        # Stop button
        self.stop_button = PixelStopButton(32, 2, 6, 3)

        # State
        self._running = False
        self._start_time: Optional[datetime] = None
        self._message_queue: queue.Queue = queue.Queue()

        # Status
        self.phase = "READY"
        self.agents_done = 0
        self.agents_total = 0
        self.health = "OK"

        # Initial display
        self._draw_chrome()
        self._show_boot_sequence()

    def _draw_chrome(self):
        """Draw the static UI chrome."""
        # Clear
        self.display.clear(BG_COLOR)

        # Title bar
        title = "*** FAST_SWARM AUDIT SUPERVISOR ***"
        self.display.print_at((COLS - len(title)) // 2, 0, title, C64_CYAN, BG_COLOR)

        # Terminal box
        self.display.draw_box(0, 2, 30, 20, C64_LIGHT_BLUE, " OUTPUT ")

        # Status box
        self.display.draw_box(0, 22, COLS, 3, C64_LIGHT_BLUE)

        # Input prompt
        self.display.print_at(1, 23, ">", C64_LIGHT_GREEN)

    def _show_boot_sequence(self):
        """Show C64-style boot message."""
        self._add_message("**** COMMODORE 64 BASIC V2 ****", C64_LIGHT_BLUE)
        self._add_message("64K RAM SYSTEM  38911 BASIC BYTES FREE", C64_LIGHT_BLUE)
        self._add_message("", TEXT_COLOR)
        self._add_message("READY.", C64_LIGHT_BLUE)
        self._add_message("LOAD \"AUDIT.PRG\",8,1", TEXT_COLOR)
        self._add_message("", TEXT_COLOR)
        self._add_message("SEARCHING FOR AUDIT.PRG", TEXT_COLOR)
        self._add_message("LOADING", TEXT_COLOR)
        self._add_message("READY.", C64_LIGHT_BLUE)
        self._add_message("RUN", TEXT_COLOR)
        self._add_message("", TEXT_COLOR)
        self._add_message("AUDIT SUPERVISOR V1.0", C64_CYAN)
        self._add_message("TYPE COMMANDS OR WAIT FOR AGENTS", C64_LIGHT_GREEN)
        self._add_message("", TEXT_COLOR)

    def _add_message(self, text: str, color: Tuple[int, int, int] = TEXT_COLOR):
        """Add a message to the terminal."""
        # Word wrap at 28 chars (terminal width)
        max_width = 28
        while len(text) > max_width:
            self.messages.append((text[:max_width], color))
            text = text[max_width:]
        self.messages.append((text, color))

        # Keep only what fits
        max_messages = self.terminal_height - 1
        if len(self.messages) > max_messages:
            self.messages = self.messages[-max_messages:]

    def _draw_terminal(self):
        """Draw the scrolling terminal area."""
        y = self.terminal_top
        for msg_text, msg_color in self.messages:
            self.display.print_at(1, y, msg_text.ljust(28), msg_color)
            y += 1
            if y >= self.terminal_bottom:
                break

        # Clear remaining lines
        while y < self.terminal_bottom:
            self.display.print_at(1, y, " " * 28, TEXT_COLOR)
            y += 1

    def _draw_status(self):
        """Draw status bar."""
        # Phase
        phase_text = f"PHASE:{self.phase[:8]}"
        self.display.print_at(1, 23, phase_text, C64_YELLOW)

        # Agents
        agents_text = f"AGENTS:{self.agents_done}/{self.agents_total}"
        self.display.print_at(14, 23, agents_text, C64_LIGHT_GREEN)

        # Health
        health_colors = {"OK": C64_LIGHT_GREEN, "WARN": C64_YELLOW, "CRIT": C64_RED}
        self.display.print_at(28, 23, f"[{self.health}]",
                             health_colors.get(self.health, C64_WHITE))

        # Time
        if self._start_time:
            elapsed = int((datetime.now() - self._start_time).total_seconds())
            mins, secs = divmod(elapsed, 60)
            time_text = f"{mins:02d}:{secs:02d}"
            self.display.print_at(34, 23, time_text, C64_LIGHT_GREY)

    def _draw_input(self):
        """Draw input line."""
        # Clear input area
        self.display.print_at(1, 24, " " * 38, TEXT_COLOR)

        # Prompt and text
        self.display.print_at(1, 24, ">", C64_LIGHT_GREEN)
        self.display.print_at(2, 24, self.input_text[:36], TEXT_COLOR)

        # Cursor position
        self.display.cursor_x = 2 + len(self.input_text)
        self.display.cursor_y = 24

    def _process_queue(self):
        """Process thread-safe message queue."""
        try:
            while True:
                msg = self._message_queue.get_nowait()
                msg_type = msg[0]

                if msg_type == "message":
                    self._add_message(msg[1], msg[2] if len(msg) > 2 else TEXT_COLOR)
                elif msg_type == "system":
                    ts = datetime.now().strftime("%H:%M")
                    self._add_message(f"[{ts}] {msg[1]}", C64_YELLOW)
                elif msg_type == "agent":
                    self._add_message(f"[{msg[1]}] {msg[2]}", C64_LIGHT_GREEN)
                elif msg_type == "error":
                    self._add_message(f"!ERROR! {msg[1]}", C64_RED)
                elif msg_type == "header":
                    self._add_message("=" * 28, C64_CYAN)
                    centered = msg[1].center(28)
                    self._add_message(centered, C64_CYAN)
                    self._add_message("=" * 28, C64_CYAN)
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
                # Convert to native coords
                native_x = event.pos[0] // SCALE
                native_y = event.pos[1] // SCALE

                if self.stop_button.check_click(native_x, native_y):
                    if not self.stop_button.stopped:
                        self.stop_button.pressed = True

            elif event.type == pygame.MOUSEBUTTONUP:
                if self.stop_button.pressed and not self.stop_button.stopped:
                    native_x = event.pos[0] // SCALE
                    native_y = event.pos[1] // SCALE

                    if self.stop_button.check_click(native_x, native_y):
                        self.stop_button.stopped = True
                        self._add_message("!!! EMERGENCY STOP !!!", C64_RED)
                        self._add_message("STOPPING ALL AGENTS...", C64_RED)
                        if self.on_stop:
                            self.on_stop()

                self.stop_button.pressed = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN:
                    if self.input_text.strip():
                        # Echo input
                        self._add_message(f">{self.input_text}", C64_LIGHT_GREEN)
                        text = self.input_text.strip()
                        self.input_text = ""
                        if self.on_user_input:
                            self.on_user_input(text)

                elif event.key == pygame.K_BACKSPACE:
                    self.input_text = self.input_text[:-1]

                elif event.unicode and event.unicode.isprintable():
                    if len(self.input_text) < 36:
                        self.input_text += event.unicode.upper()  # C64 style: uppercase

    def _render(self):
        """Render the display."""
        # Update character display
        self._draw_chrome()
        self._draw_terminal()
        self._draw_status()
        self._draw_input()
        self.stop_button.draw(self.display)

        # Render to native surface
        native = self.display.render()

        # Scale up with nearest neighbor (pixelated look)
        scaled = pygame.transform.scale(native, (SCREEN_WIDTH, SCREEN_HEIGHT))

        # Add scanlines for authentic CRT look
        for y in range(0, SCREEN_HEIGHT, SCALE * 2):
            pygame.draw.line(scaled, (0, 0, 0), (0, y), (SCREEN_WIDTH, y))

        self.screen.blit(scaled, (0, 0))
        pygame.display.flip()

    # ==========================================================================
    # PUBLIC API (Thread-Safe)
    # ==========================================================================

    def start(self):
        """Start the GUI (blocking)."""
        self._running = True
        self._start_time = datetime.now()

        while self._running:
            dt = self.clock.tick(30) / 1000.0  # 30 FPS for authentic feel

            self._process_queue()
            self._handle_events()
            self.display.update(dt)
            self._render()

        pygame.quit()

    def stop(self):
        """Stop the GUI."""
        self._running = False

    def write(self, text: str, color: Tuple[int, int, int] = TEXT_COLOR):
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
# DEMO
# ==============================================================================

def demo():
    """Demo the C64-style GUI."""
    import random

    def on_stop():
        print("STOP PRESSED!")

    def on_input(text):
        print(f"Input: {text}")
        if text == "HELP":
            gui.write_system("COMMANDS: HELP, STATUS, START")
        elif text == "STATUS":
            gui.write_system("ALL SYSTEMS NOMINAL")
        elif text == "START":
            gui.write_header("AUDIT STARTED")
            gui.set_phase("REVIEW")
        else:
            gui.write(f"?SYNTAX ERROR: {text}", C64_RED)

    gui = C64TerminalGUI(on_stop=on_stop, on_user_input=on_input)

    # Simulate agent messages
    def simulate():
        time.sleep(2)
        agents = ["1A", "1B", "1C", "2A"]
        messages = [
            "SCANNING FILES",
            "FOUND 23 MODULES",
            "ANALYZING DEPS",
            "DEAD CODE FOUND",
            "COVERAGE 67%",
        ]

        gui.write_header("AUDIT STARTED")
        gui.set_phase("SCAN")
        gui.set_agents(0, 8)

        for i in range(20):
            time.sleep(0.8)
            agent = random.choice(agents)
            msg = random.choice(messages)
            gui.write_agent(agent, msg)
            gui.set_agents(min(i // 3, 8), 8)

            if i == 8:
                gui.set_phase("SYNTH")
            if i == 15:
                gui.set_health("WARN")

    thread = threading.Thread(target=simulate, daemon=True)
    thread.start()

    gui.start()


if __name__ == "__main__":
    demo()
