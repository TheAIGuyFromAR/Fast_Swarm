"""
Retro Terminal GUI for Audit Supervisor - Pygame Version
Cross-platform (Windows, Mac, Linux)

Features:
- Green phosphor CRT-style display with scanlines and glow
- Big red octagon emergency stop button
- Message input to guide agents
- Scrolling agent messages with auto-scroll
- Interactive clarifying questions
"""

import math
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import pygame
    from pygame import gfxdraw
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False
    print("pygame not installed. Run: pip install pygame")


# ==============================================================================
# CONSTANTS & COLORS
# ==============================================================================

# CRT Green Phosphor Colors
C_BG_DARK = (5, 5, 5)
C_BG_MONITOR = (0, 17, 0)
C_GREEN_DIM = (0, 51, 0)
C_GREEN_NORMAL = (0, 170, 0)
C_GREEN_BRIGHT = (0, 255, 0)
C_GREEN_GLOW = (51, 255, 51)

# Chrome/Bezel Colors
C_CHROME_DARK = (26, 26, 26)
C_CHROME_MID = (42, 42, 42)
C_CHROME_LIGHT = (58, 58, 58)

# Emergency Stop Colors
C_RED_DARK = (102, 0, 0)
C_RED_NORMAL = (204, 0, 0)
C_RED_BRIGHT = (255, 0, 0)
C_RED_GLOW = (255, 51, 51)

# Status Colors
C_AMBER = (255, 170, 0)
C_WHITE = (255, 255, 255)
C_BLACK = (0, 0, 0)


# ==============================================================================
# MESSAGE TYPES
# ==============================================================================

@dataclass
class TerminalMessage:
    """A message to display in the terminal."""
    text: str
    color: Tuple[int, int, int] = C_GREEN_NORMAL
    prefix: str = ""
    prefix_color: Tuple[int, int, int] = C_GREEN_DIM
    timestamp: Optional[datetime] = None
    is_header: bool = False

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


# ==============================================================================
# CRT EFFECTS
# ==============================================================================

class CRTEffect:
    """Applies CRT monitor effects to a surface."""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self._create_scanline_overlay()
        self._create_vignette()

    def _create_scanline_overlay(self):
        """Create scanline effect overlay."""
        self.scanlines = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        for y in range(0, self.height, 2):
            pygame.draw.line(self.scanlines, (0, 0, 0, 30), (0, y), (self.width, y))

    def _create_vignette(self):
        """Create vignette (darkened corners) effect."""
        self.vignette = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        cx, cy = self.width // 2, self.height // 2
        max_dist = math.sqrt(cx * cx + cy * cy)

        for x in range(0, self.width, 4):
            for y in range(0, self.height, 4):
                dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
                alpha = int(min(80, (dist / max_dist) * 100))
                pygame.draw.rect(self.vignette, (0, 0, 0, alpha), (x, y, 4, 4))

    def apply(self, surface: pygame.Surface):
        """Apply CRT effects to a surface."""
        surface.blit(self.scanlines, (0, 0))
        surface.blit(self.vignette, (0, 0))


# ==============================================================================
# OCTAGON STOP BUTTON
# ==============================================================================

class OctagonStopButton:
    """Big red emergency stop button."""

    def __init__(self, x: int, y: int, size: int = 120):
        self.x = x
        self.y = y
        self.size = size
        self.is_pressed = False
        self.is_stopped = False
        self.hover = False

        # Calculate octagon points
        self.cx = x + size // 2
        self.cy = y + size // 2
        self.outer_points = self._get_octagon_points(self.cx, self.cy, size // 2 - 5)
        self.inner_points = self._get_octagon_points(self.cx, self.cy, size // 2 - 13)

    def _get_octagon_points(self, cx: int, cy: int, radius: int) -> List[Tuple[int, int]]:
        """Calculate octagon vertices."""
        points = []
        for i in range(8):
            angle = math.pi / 8 + i * math.pi / 4
            x = int(cx + radius * math.cos(angle))
            y = int(cy + radius * math.sin(angle))
            points.append((x, y))
        return points

    def draw(self, surface: pygame.Surface, font: pygame.font.Font):
        """Draw the button."""
        # Outer chrome ring
        pygame.draw.polygon(surface, C_CHROME_LIGHT, self.outer_points)
        pygame.draw.polygon(surface, C_CHROME_MID, self.outer_points, 2)

        # Main button face
        if self.is_stopped:
            color = C_RED_DARK
        elif self.is_pressed:
            color = C_RED_BRIGHT
        else:
            color = C_RED_NORMAL

        pygame.draw.polygon(surface, color, self.inner_points)
        pygame.draw.polygon(surface, C_RED_DARK, self.inner_points, 2)

        # STOP text
        text_color = C_WHITE if not self.is_stopped else (100, 100, 100)
        text = font.render("STOP", True, text_color)
        text_rect = text.get_rect(center=(self.cx, self.cy))
        surface.blit(text, text_rect)

        # Glow effect when pressed
        if self.is_pressed and not self.is_stopped:
            glow_points = self._get_octagon_points(self.cx, self.cy, self.size // 2 - 2)
            pygame.draw.polygon(surface, C_RED_GLOW, glow_points, 3)

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Handle mouse events. Returns True if button was activated."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._point_in_octagon(event.pos):
                self.is_pressed = True
                return False

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.is_pressed and not self.is_stopped:
                self.is_pressed = False
                if self._point_in_octagon(event.pos):
                    self.is_stopped = True
                    return True
            self.is_pressed = False

        elif event.type == pygame.MOUSEMOTION:
            self.hover = self._point_in_octagon(event.pos)

        return False

    def _point_in_octagon(self, pos: Tuple[int, int]) -> bool:
        """Check if point is inside the octagon."""
        # Simple circular approximation
        dx = pos[0] - self.cx
        dy = pos[1] - self.cy
        return math.sqrt(dx * dx + dy * dy) < self.size // 2 - 10

    def reset(self):
        """Reset the button."""
        self.is_stopped = False
        self.is_pressed = False


# ==============================================================================
# TEXT INPUT BOX
# ==============================================================================

class TextInputBox:
    """Text input field with CRT styling."""

    def __init__(self, x: int, y: int, width: int, height: int, font: pygame.font.Font):
        self.rect = pygame.Rect(x, y, width, height)
        self.font = font
        self.text = ""
        self.active = False
        self.cursor_visible = True
        self.cursor_timer = 0

    def handle_event(self, event: pygame.event.Event) -> Optional[str]:
        """Handle input events. Returns text if Enter pressed."""
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.active = self.rect.collidepoint(event.pos)

        elif event.type == pygame.KEYDOWN and self.active:
            if event.key == pygame.K_RETURN:
                result = self.text
                self.text = ""
                return result
            elif event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.unicode and event.unicode.isprintable():
                self.text += event.unicode

        return None

    def update(self, dt: float):
        """Update cursor blink."""
        self.cursor_timer += dt
        if self.cursor_timer >= 0.5:
            self.cursor_timer = 0
            self.cursor_visible = not self.cursor_visible

    def draw(self, surface: pygame.Surface):
        """Draw the input box."""
        # Background
        pygame.draw.rect(surface, C_BG_MONITOR, self.rect)

        # Border
        border_color = C_GREEN_NORMAL if self.active else C_GREEN_DIM
        pygame.draw.rect(surface, border_color, self.rect, 2)

        # Text
        if self.text:
            text_surface = self.font.render(self.text, True, C_GREEN_BRIGHT)
            surface.blit(text_surface, (self.rect.x + 5, self.rect.y + 5))

        # Cursor
        if self.active and self.cursor_visible:
            cursor_x = self.rect.x + 5 + self.font.size(self.text)[0]
            pygame.draw.line(surface, C_GREEN_BRIGHT,
                           (cursor_x, self.rect.y + 5),
                           (cursor_x, self.rect.y + self.rect.height - 5), 2)


# ==============================================================================
# SCROLLING TERMINAL
# ==============================================================================

class ScrollingTerminal:
    """CRT-style scrolling terminal display."""

    def __init__(self, x: int, y: int, width: int, height: int, font: pygame.font.Font):
        self.rect = pygame.Rect(x, y, width, height)
        self.font = font
        self.messages: List[TerminalMessage] = []
        self.scroll_offset = 0
        self.line_height = font.get_linesize() + 2
        self.max_visible_lines = height // self.line_height
        self.auto_scroll = True

        # CRT effect
        self.crt = CRTEffect(width, height)

    def add_message(self, message: TerminalMessage):
        """Add a message to the terminal."""
        self.messages.append(message)

        # Auto-scroll to bottom
        if self.auto_scroll:
            total_lines = len(self.messages)
            if total_lines > self.max_visible_lines:
                self.scroll_offset = total_lines - self.max_visible_lines

    def write(self, text: str, color: Tuple[int, int, int] = C_GREEN_NORMAL):
        """Write text to terminal."""
        self.add_message(TerminalMessage(text=text, color=color))

    def write_agent(self, agent_id: str, text: str):
        """Write agent message."""
        self.add_message(TerminalMessage(
            text=text,
            color=C_GREEN_NORMAL,
            prefix=f"[{agent_id}] ",
            prefix_color=C_GREEN_BRIGHT,
        ))

    def write_system(self, text: str):
        """Write system message."""
        self.add_message(TerminalMessage(
            text=text,
            color=C_GREEN_NORMAL,
            prefix="[SYSTEM] ",
            prefix_color=C_AMBER,
        ))

    def write_error(self, text: str):
        """Write error message."""
        self.add_message(TerminalMessage(
            text=text,
            color=C_RED_BRIGHT,
            prefix="[ERROR] ",
            prefix_color=C_RED_BRIGHT,
        ))

    def write_header(self, text: str):
        """Write a header."""
        self.add_message(TerminalMessage(
            text="=" * 50,
            color=C_GREEN_DIM,
            is_header=True,
        ))
        self.add_message(TerminalMessage(
            text=f" {text} ".center(50, "="),
            color=C_GREEN_GLOW,
            is_header=True,
        ))
        self.add_message(TerminalMessage(
            text="=" * 50,
            color=C_GREEN_DIM,
            is_header=True,
        ))

    def write_user(self, text: str):
        """Write user input."""
        self.add_message(TerminalMessage(
            text=text,
            color=C_GREEN_GLOW,
            prefix="[YOU] > ",
            prefix_color=C_GREEN_GLOW,
        ))

    def handle_event(self, event: pygame.event.Event):
        """Handle scroll events."""
        if event.type == pygame.MOUSEWHEEL:
            if self.rect.collidepoint(pygame.mouse.get_pos()):
                self.scroll_offset -= event.y * 3
                self.scroll_offset = max(0, min(self.scroll_offset,
                                               max(0, len(self.messages) - self.max_visible_lines)))
                self.auto_scroll = self.scroll_offset >= len(self.messages) - self.max_visible_lines - 1

    def draw(self, surface: pygame.Surface):
        """Draw the terminal."""
        # Create terminal surface
        term_surface = pygame.Surface((self.rect.width, self.rect.height))
        term_surface.fill(C_BG_MONITOR)

        # Draw messages
        y = 5
        start_idx = self.scroll_offset
        end_idx = min(start_idx + self.max_visible_lines + 1, len(self.messages))

        for i in range(start_idx, end_idx):
            if i >= len(self.messages):
                break

            msg = self.messages[i]

            # Timestamp
            if msg.timestamp and not msg.is_header:
                ts_text = f"[{msg.timestamp.strftime('%H:%M:%S')}] "
                ts_surface = self.font.render(ts_text, True, C_GREEN_DIM)
                term_surface.blit(ts_surface, (5, y))
                x_offset = ts_surface.get_width() + 5
            else:
                x_offset = 5

            # Prefix
            if msg.prefix:
                prefix_surface = self.font.render(msg.prefix, True, msg.prefix_color)
                term_surface.blit(prefix_surface, (x_offset, y))
                x_offset += prefix_surface.get_width()

            # Main text
            text_surface = self.font.render(msg.text, True, msg.color)
            term_surface.blit(text_surface, (x_offset, y))

            y += self.line_height

        # Apply CRT effects
        self.crt.apply(term_surface)

        # Draw to main surface with bezel
        pygame.draw.rect(surface, C_CHROME_MID,
                        (self.rect.x - 10, self.rect.y - 10,
                         self.rect.width + 20, self.rect.height + 20))
        pygame.draw.rect(surface, C_CHROME_DARK,
                        (self.rect.x - 5, self.rect.y - 5,
                         self.rect.width + 10, self.rect.height + 10))
        surface.blit(term_surface, self.rect.topleft)

    def clear(self):
        """Clear all messages."""
        self.messages.clear()
        self.scroll_offset = 0


# ==============================================================================
# STATUS BAR
# ==============================================================================

class StatusBar:
    """Status bar with indicators."""

    def __init__(self, x: int, y: int, width: int, height: int, font: pygame.font.Font):
        self.rect = pygame.Rect(x, y, width, height)
        self.font = font
        self.phase = "IDLE"
        self.agents_complete = 0
        self.agents_total = 0
        self.health = "healthy"
        self.elapsed_seconds = 0

    def draw(self, surface: pygame.Surface):
        """Draw the status bar."""
        # Background
        pygame.draw.rect(surface, C_CHROME_DARK, self.rect)

        # Phase
        phase_text = f"PHASE: {self.phase}"
        phase_surface = self.font.render(phase_text, True, C_GREEN_NORMAL)
        surface.blit(phase_surface, (self.rect.x + 10, self.rect.y + 5))

        # Agents
        agents_text = f"AGENTS: {self.agents_complete}/{self.agents_total}"
        agents_surface = self.font.render(agents_text, True, C_GREEN_NORMAL)
        surface.blit(agents_surface, (self.rect.x + 200, self.rect.y + 5))

        # Health
        health_colors = {
            "healthy": C_GREEN_BRIGHT,
            "degraded": C_AMBER,
            "critical": C_RED_BRIGHT,
        }
        health_indicators = {
            "healthy": "[OK]",
            "degraded": "[!!]",
            "critical": "[XX]",
        }
        health_color = health_colors.get(self.health, C_GREEN_NORMAL)
        health_text = f"{health_indicators.get(self.health, '[??]')} {self.health.upper()}"
        health_surface = self.font.render(health_text, True, health_color)
        surface.blit(health_surface, (self.rect.right - 150, self.rect.y + 5))

        # Time
        hours = self.elapsed_seconds // 3600
        minutes = (self.elapsed_seconds % 3600) // 60
        seconds = self.elapsed_seconds % 60
        time_text = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        time_surface = self.font.render(time_text, True, C_GREEN_DIM)
        surface.blit(time_surface, (self.rect.right - 250, self.rect.y + 5))


# ==============================================================================
# LED INDICATOR
# ==============================================================================

class LEDIndicator:
    """LED-style status indicator."""

    def __init__(self, x: int, y: int, label: str, color: Tuple[int, int, int] = C_GREEN_BRIGHT):
        self.x = x
        self.y = y
        self.label = label
        self.color = color
        self.on = True

    def draw(self, surface: pygame.Surface, font: pygame.font.Font):
        """Draw the LED."""
        # LED glow
        if self.on:
            gfxdraw.filled_circle(surface, self.x + 8, self.y + 8, 10,
                                 (*self.color[:3], 50))

        # LED body
        color = self.color if self.on else C_CHROME_MID
        gfxdraw.filled_circle(surface, self.x + 8, self.y + 8, 6, color)
        gfxdraw.aacircle(surface, self.x + 8, self.y + 8, 6, C_CHROME_LIGHT)

        # Label
        label_surface = font.render(self.label, True, C_GREEN_NORMAL)
        surface.blit(label_surface, (self.x + 25, self.y + 2))


# ==============================================================================
# MAIN GUI CLASS
# ==============================================================================

class RetroTerminalGUI:
    """
    Main retro terminal GUI using Pygame.
    Cross-platform: Windows, Mac, Linux.
    """

    def __init__(
        self,
        on_stop: Optional[Callable] = None,
        on_user_input: Optional[Callable[[str], None]] = None,
        width: int = 1000,
        height: int = 700,
    ):
        if not PYGAME_AVAILABLE:
            raise ImportError("pygame is required. Install with: pip install pygame")

        self.on_stop = on_stop
        self.on_user_input = on_user_input
        self.width = width
        self.height = height

        # State
        self._running = False
        self._start_time: Optional[datetime] = None
        self._message_queue: queue.Queue = queue.Queue()

        # Initialize pygame
        pygame.init()
        pygame.display.set_caption("FAST_SWARM AUDIT SUPERVISOR CONTROL TERMINAL")

        self.screen = pygame.display.set_mode((width, height))
        self.clock = pygame.time.Clock()

        # Fonts
        self.font_small = pygame.font.Font(pygame.font.match_font('couriernew', bold=False), 12)
        self.font_normal = pygame.font.Font(pygame.font.match_font('couriernew', bold=False), 14)
        self.font_bold = pygame.font.Font(pygame.font.match_font('couriernew', bold=True), 14)
        self.font_title = pygame.font.Font(pygame.font.match_font('couriernew', bold=True), 16)

        # Create UI components
        self._create_ui()

    def _create_ui(self):
        """Create all UI components."""
        # Terminal (main display)
        terminal_width = self.width - 220
        terminal_height = self.height - 150
        self.terminal = ScrollingTerminal(
            20, 50,
            terminal_width, terminal_height,
            self.font_normal
        )

        # Stop button
        self.stop_button = OctagonStopButton(
            self.width - 180, 80, 140
        )

        # LEDs
        led_x = self.width - 170
        self.leds = [
            LEDIndicator(led_x, 250, "PWR", C_GREEN_BRIGHT),
            LEDIndicator(led_x, 280, "RUN", C_AMBER),
            LEDIndicator(led_x, 310, "ERR", C_CHROME_MID),
        ]

        # Input box
        self.input_box = TextInputBox(
            120, self.height - 80,
            self.width - 250, 30,
            self.font_normal
        )

        # Send button rect (we'll draw it manually)
        self.send_button_rect = pygame.Rect(
            self.width - 120, self.height - 80, 80, 30
        )

        # Status bar
        self.status_bar = StatusBar(
            0, self.height - 35,
            self.width, 35,
            self.font_small
        )

        # Initial messages
        self.terminal.write_header("SYSTEM INITIALIZED")
        self.terminal.write_system("Audit Supervisor Control Terminal ready.")
        self.terminal.write_system("Press START to begin audit or type commands below.")
        self.terminal.write("", C_GREEN_DIM)

    def _process_queue(self):
        """Process messages from the thread-safe queue."""
        try:
            while True:
                msg_type, *args = self._message_queue.get_nowait()
                if msg_type == "write":
                    self.terminal.write(args[0], args[1] if len(args) > 1 else C_GREEN_NORMAL)
                elif msg_type == "agent":
                    self.terminal.write_agent(args[0], args[1])
                elif msg_type == "system":
                    self.terminal.write_system(args[0])
                elif msg_type == "error":
                    self.terminal.write_error(args[0])
                elif msg_type == "header":
                    self.terminal.write_header(args[0])
                elif msg_type == "phase":
                    self.status_bar.phase = args[0]
                elif msg_type == "agents":
                    self.status_bar.agents_complete = args[0]
                    self.status_bar.agents_total = args[1]
                elif msg_type == "health":
                    self.status_bar.health = args[0]
        except queue.Empty:
            pass

    def _handle_events(self):
        """Handle pygame events."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._running = False

            # Stop button
            if self.stop_button.handle_event(event):
                self.terminal.write_error("!!! EMERGENCY STOP ACTIVATED !!!")
                self.terminal.write_system("Sending stop signal to all agents...")
                self.leds[2].color = C_RED_BRIGHT  # ERR LED
                self.leds[2].on = True
                self.leds[1].on = False  # RUN LED off
                if self.on_stop:
                    self.on_stop()

            # Terminal scroll
            self.terminal.handle_event(event)

            # Input box
            result = self.input_box.handle_event(event)
            if result:
                self.terminal.write_user(result)
                if self.on_user_input:
                    self.on_user_input(result)

            # Send button click
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.send_button_rect.collidepoint(event.pos):
                    text = self.input_box.text.strip()
                    if text:
                        self.input_box.text = ""
                        self.terminal.write_user(text)
                        if self.on_user_input:
                            self.on_user_input(text)

    def _update(self, dt: float):
        """Update UI state."""
        self._process_queue()
        self.input_box.update(dt)

        # Update elapsed time
        if self._start_time:
            self.status_bar.elapsed_seconds = int((datetime.now() - self._start_time).total_seconds())

    def _draw(self):
        """Draw all UI components."""
        self.screen.fill(C_CHROME_DARK)

        # Title bar
        pygame.draw.rect(self.screen, C_CHROME_MID, (0, 0, self.width, 40))
        title = ">>> FAST_SWARM AUDIT SUPERVISOR CONTROL TERMINAL <<<"
        title_surface = self.font_title.render(title, True, C_GREEN_GLOW)
        title_rect = title_surface.get_rect(center=(self.width // 2, 20))
        self.screen.blit(title_surface, title_rect)

        # Terminal
        self.terminal.draw(self.screen)

        # Right panel background
        pygame.draw.rect(self.screen, C_CHROME_DARK,
                        (self.width - 200, 50, 190, self.height - 140))

        # Emergency label
        emergency_surface = self.font_bold.render("EMERGENCY", True, C_RED_BRIGHT)
        self.screen.blit(emergency_surface, (self.width - 165, 55))

        # Stop button
        self.stop_button.draw(self.screen, self.font_bold)

        # LEDs
        for led in self.leds:
            led.draw(self.screen, self.font_small)

        # Input area background
        pygame.draw.rect(self.screen, C_CHROME_MID,
                        (0, self.height - 95, self.width, 60))

        # Input label
        label_surface = self.font_bold.render("OPERATOR INPUT >", True, C_GREEN_BRIGHT)
        self.screen.blit(label_surface, (10, self.height - 75))

        # Input box
        self.input_box.draw(self.screen)

        # Send button
        btn_color = C_GREEN_DIM
        if self.send_button_rect.collidepoint(pygame.mouse.get_pos()):
            btn_color = C_GREEN_NORMAL
        pygame.draw.rect(self.screen, btn_color, self.send_button_rect)
        pygame.draw.rect(self.screen, C_GREEN_BRIGHT, self.send_button_rect, 2)
        send_text = self.font_bold.render("SEND", True, C_GREEN_BRIGHT)
        send_rect = send_text.get_rect(center=self.send_button_rect.center)
        self.screen.blit(send_text, send_rect)

        # Status bar
        self.status_bar.draw(self.screen)

        pygame.display.flip()

    # ==========================================================================
    # PUBLIC API (Thread-Safe)
    # ==========================================================================

    def start(self):
        """Start the GUI main loop (blocking)."""
        self._running = True
        self._start_time = datetime.now()

        while self._running:
            dt = self.clock.tick(60) / 1000.0  # 60 FPS, dt in seconds

            self._handle_events()
            self._update(dt)
            self._draw()

        pygame.quit()

    def stop(self):
        """Stop the GUI."""
        self._running = False

    def write(self, text: str, color: Tuple[int, int, int] = C_GREEN_NORMAL):
        """Write text (thread-safe)."""
        self._message_queue.put(("write", text, color))

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
        """Set current phase (thread-safe)."""
        self._message_queue.put(("phase", phase))

    def set_agents(self, complete: int, total: int):
        """Set agent counts (thread-safe)."""
        self._message_queue.put(("agents", complete, total))

    def set_health(self, status: str):
        """Set health status (thread-safe)."""
        self._message_queue.put(("health", status))


# ==============================================================================
# DEMO
# ==============================================================================

def demo():
    """Demo the pygame GUI."""
    import random

    def on_stop():
        print("STOP PRESSED!")

    def on_input(text):
        print(f"User input: {text}")
        gui.write_system(f"Received: {text}")

    gui = RetroTerminalGUI(on_stop=on_stop, on_user_input=on_input)

    # Simulate messages in a thread
    def simulate():
        time.sleep(1)
        agents = ["1A", "1B", "1C", "2A", "2B"]
        messages = [
            "Scanning files...",
            "Found 23 Python files",
            "Analyzing dependencies",
            "Processing Models/",
            "Dead code candidate found",
            "Reviewing Services/",
            "Test coverage: 67%",
            "Checking imports...",
            "Found circular dependency",
            "Parsing docstrings",
        ]

        gui.write_header("AUDIT STARTED")
        gui.set_phase("SECTION REVIEW")
        gui.set_agents(0, 8)

        for i in range(30):
            time.sleep(0.5)
            agent = random.choice(agents)
            msg = random.choice(messages)
            gui.write_agent(agent, msg)
            gui.set_agents(min(i // 4, 8), 8)

            if i == 10:
                gui.set_phase("SYNTHESIS")
            if i == 20:
                gui.set_phase("DOCUMENTATION")
                gui.set_health("degraded")

    thread = threading.Thread(target=simulate, daemon=True)
    thread.start()

    gui.start()


if __name__ == "__main__":
    demo()
