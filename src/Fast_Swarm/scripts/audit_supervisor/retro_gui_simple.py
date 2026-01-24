"""
Simple Green Monochrome Terminal GUI
Clean, fun, personality-filled audit supervisor interface.

No fancy graphics - just green text on black, like the good old days.
"""

import queue
import threading
import time
import random
from datetime import datetime
from typing import Callable, List, Optional, Tuple

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False
    print("pygame not installed. Run: pip install pygame")


# ==============================================================================
# COLORS
# ==============================================================================

BLACK = (0, 0, 0)
GREEN = (0, 200, 0)
GREEN_BRIGHT = (0, 255, 0)
GREEN_DIM = (0, 100, 0)
GREEN_GLOW = (50, 255, 50)
RED = (255, 50, 50)


# ==============================================================================
# FUN MESSAGES
# ==============================================================================

BOOT_SEQUENCE = [
    "",
    "  ========================================",
    "  =                                      =",
    "  =     CODE-O-MATIC 5000 (TM)           =",
    "  =     Audit Supervisor v1.0            =",
    "  =                                      =",
    "  =     'Finding bugs so you don't       =",
    "  =      have to!'                       =",
    "  =                                      =",
    "  ========================================",
    "",
]

AGENT_NAMES = [
    "Spider-Bot Alpha",
    "Code Crawler Prime",
    "Syntax Sniffer 3000",
    "Bug Hunter X",
    "Dead Code Detective",
    "Import Inspector",
    "Type Checker Turbo",
    "Doc Scanner Deluxe",
    "Architecture Analyzer",
    "Pattern Patrol",
]

SPIDER_MESSAGES = [
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

COMPLETION_MESSAGES = [
    "Another file bites the dust!",
    "Got 'em!",
    "Target acquired and analyzed.",
    "Mission accomplished.",
    "Clean sweep complete.",
    "Nothing escapes the spider!",
]


# ==============================================================================
# SIMPLE TERMINAL GUI
# ==============================================================================

class SimpleTerminalGUI:
    """
    Simple green monochrome terminal with personality.
    """

    def __init__(
        self,
        on_stop: Optional[Callable] = None,
        on_user_input: Optional[Callable[[str], None]] = None,
        user_name: str = "Blake",
    ):
        if not PYGAME_AVAILABLE:
            raise ImportError("pygame required: pip install pygame")

        self.on_stop = on_stop
        self.on_user_input = on_user_input
        self.user_name = user_name

        pygame.init()
        pygame.display.set_caption("CODE-O-MATIC 5000 - Audit Supervisor")

        # Window setup
        self.width = 1024
        self.height = 768
        self.screen = pygame.display.set_mode((self.width, self.height))
        self.clock = pygame.time.Clock()

        # Font - classic monospace
        try:
            self.font = pygame.font.Font(pygame.font.match_font('couriernew'), 16)
            self.font_large = pygame.font.Font(pygame.font.match_font('couriernew'), 20)
        except:
            self.font = pygame.font.SysFont('monospace', 16)
            self.font_large = pygame.font.SysFont('monospace', 20)

        self.line_height = 20
        self.char_width = 10

        # Terminal state
        self.lines: List[Tuple[str, Tuple[int, int, int]]] = []
        self.max_lines = (self.height - 100) // self.line_height
        self.input_text = ""
        self.cursor_visible = True
        self.cursor_timer = 0.0

        # Message queue (thread-safe)
        self._message_queue: queue.Queue = queue.Queue()
        self._running = False

        # Status
        self.phase = "BOOTING"
        self.spiders_active = 0
        self.files_scanned = 0
        self.issues_found = 0
        self.stopped = False

        # Boot sequence
        self._boot()

    def _boot(self):
        """Fun boot sequence."""
        for line in BOOT_SEQUENCE:
            self._add_line(line, GREEN_BRIGHT)

        self._add_line("")
        self._add_line(f"  Welcome, {self.user_name}!", GREEN_BRIGHT)
        self._add_line("")
        self._add_line("  I am the CODE-O-MATIC 5000 - your friendly", GREEN)
        self._add_line("  neighborhood code auditor.", GREEN)
        self._add_line("")
        self._add_line("  I'm here to:", GREEN)
        self._add_line("    - Review your codebase", GREEN_DIM)
        self._add_line("    - Locate unused functions", GREEN_DIM)
        self._add_line("    - Find dead files", GREEN_DIM)
        self._add_line("    - Spot unimplemented features", GREEN_DIM)
        self._add_line("    - Check documentation gaps", GREEN_DIM)
        self._add_line("    - Hunt down those sneaky bugs", GREEN_DIM)
        self._add_line("")
        self._add_line("  Type START to begin the audit.", GREEN_BRIGHT)
        self._add_line("  Type HELP for commands.", GREEN_DIM)
        self._add_line("")

    def _add_line(self, text: str, color: Tuple[int, int, int] = GREEN):
        """Add a line to the terminal."""
        # Handle long lines
        max_chars = (self.width - 40) // self.char_width
        while len(text) > max_chars:
            self.lines.append((text[:max_chars], color))
            text = "  " + text[max_chars:]
        self.lines.append((text, color))

        # Scroll if needed
        if len(self.lines) > self.max_lines:
            self.lines = self.lines[-self.max_lines:]

    def _process_queue(self):
        """Process thread-safe message queue."""
        try:
            while True:
                msg = self._message_queue.get_nowait()
                msg_type = msg[0]

                if msg_type == "line":
                    self._add_line(msg[1], msg[2] if len(msg) > 2 else GREEN)
                elif msg_type == "spider":
                    agent_name = msg[1]
                    status = msg[2]
                    self._add_line(f"  [{agent_name}] {status}", GREEN)
                elif msg_type == "phase":
                    self.phase = msg[1]
                elif msg_type == "stats":
                    self.spiders_active = msg[1]
                    self.files_scanned = msg[2]
                    self.issues_found = msg[3]
                elif msg_type == "complete":
                    agent = msg[1]
                    self._add_line(f"  [{agent}] {random.choice(COMPLETION_MESSAGES)}", GREEN_BRIGHT)

        except queue.Empty:
            pass

    def _handle_events(self):
        """Handle pygame events."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self._running = False

                elif event.key == pygame.K_RETURN:
                    if self.input_text.strip():
                        cmd = self.input_text.strip().upper()
                        self._add_line(f"> {self.input_text}", GREEN_BRIGHT)
                        self.input_text = ""
                        self._handle_command(cmd)

                elif event.key == pygame.K_BACKSPACE:
                    self.input_text = self.input_text[:-1]

                elif event.unicode and event.unicode.isprintable():
                    if len(self.input_text) < 60:
                        self.input_text += event.unicode

    def _handle_command(self, cmd: str):
        """Handle user commands."""
        if cmd == "HELP":
            self._add_line("")
            self._add_line("  COMMANDS:", GREEN_BRIGHT)
            self._add_line("    START  - Begin the code audit", GREEN)
            self._add_line("    STATUS - Show current progress", GREEN)
            self._add_line("    STOP   - Emergency stop", GREEN)
            self._add_line("    CLEAR  - Clear screen", GREEN)
            self._add_line("    QUIT   - Exit", GREEN)
            self._add_line("")

        elif cmd == "START":
            if not self.stopped:
                self._add_line("")
                self._add_line("  *** INITIATING AUDIT SEQUENCE ***", GREEN_BRIGHT)
                self._add_line("")
                self._add_line("  Spawning Code Crawlers...", GREEN)
                self._add_line("")
                self._add_line("  GO SPIDERS GO !!!", GREEN_BRIGHT)
                self._add_line("")
                if self.on_user_input:
                    self.on_user_input("START")

        elif cmd == "STATUS":
            self._add_line("")
            self._add_line(f"  Phase: {self.phase}", GREEN)
            self._add_line(f"  Active Spiders: {self.spiders_active}", GREEN)
            self._add_line(f"  Files Scanned: {self.files_scanned}", GREEN)
            self._add_line(f"  Issues Found: {self.issues_found}", GREEN)
            self._add_line("")

        elif cmd == "STOP":
            self.stopped = True
            self._add_line("")
            self._add_line("  *** EMERGENCY STOP ***", RED)
            self._add_line("  Recalling all spiders...", RED)
            self._add_line("")
            if self.on_stop:
                self.on_stop()

        elif cmd == "CLEAR":
            self.lines.clear()

        elif cmd == "QUIT":
            self._running = False

        else:
            self._add_line(f"  Unknown command: {cmd}", GREEN_DIM)
            self._add_line("  Type HELP for available commands.", GREEN_DIM)

    def _render(self):
        """Render the terminal."""
        # Clear screen
        self.screen.fill(BLACK)

        # Draw header bar
        pygame.draw.rect(self.screen, GREEN_DIM, (0, 0, self.width, 30))
        title = self.font.render(f"CODE-O-MATIC 5000 | Phase: {self.phase} | Spiders: {self.spiders_active} | Files: {self.files_scanned} | Issues: {self.issues_found}", True, BLACK)
        self.screen.blit(title, (10, 5))

        # Draw terminal lines
        y = 40
        for text, color in self.lines:
            if text:
                line_surf = self.font.render(text, True, color)
                self.screen.blit(line_surf, (20, y))
            y += self.line_height

        # Draw input area
        input_y = self.height - 50
        pygame.draw.line(self.screen, GREEN_DIM, (0, input_y - 10), (self.width, input_y - 10), 1)

        # Prompt
        prompt = self.font.render("> " + self.input_text, True, GREEN_BRIGHT)
        self.screen.blit(prompt, (20, input_y))

        # Cursor
        if self.cursor_visible:
            cursor_x = 20 + self.font.size("> " + self.input_text)[0]
            pygame.draw.rect(self.screen, GREEN_BRIGHT, (cursor_x, input_y, 10, 18))

        # Footer
        footer = self.font.render("ESC: Quit | Type command and press ENTER", True, GREEN_DIM)
        self.screen.blit(footer, (20, self.height - 25))

        # CRT effect - subtle scanlines
        for y in range(0, self.height, 3):
            pygame.draw.line(self.screen, (0, 0, 0), (0, y), (self.width, y))

        pygame.display.flip()

    # ==========================================================================
    # PUBLIC API (Thread-Safe)
    # ==========================================================================

    def start(self):
        """Start GUI (blocking)."""
        self._running = True

        while self._running:
            dt = self.clock.tick(60) / 1000.0

            # Cursor blink
            self.cursor_timer += dt
            if self.cursor_timer >= 0.5:
                self.cursor_timer = 0
                self.cursor_visible = not self.cursor_visible

            self._process_queue()
            self._handle_events()
            self._render()

        pygame.quit()

    def stop(self):
        """Stop GUI."""
        self._running = False

    def write(self, text: str, color: Tuple[int, int, int] = GREEN):
        """Write line (thread-safe)."""
        self._message_queue.put(("line", text, color))

    def write_spider(self, agent_name: str, status: str):
        """Write spider status (thread-safe)."""
        self._message_queue.put(("spider", agent_name, status))

    def write_complete(self, agent_name: str):
        """Write spider completion (thread-safe)."""
        self._message_queue.put(("complete", agent_name))

    def set_phase(self, phase: str):
        """Set phase (thread-safe)."""
        self._message_queue.put(("phase", phase))

    def set_stats(self, spiders: int, files: int, issues: int):
        """Set stats (thread-safe)."""
        self._message_queue.put(("stats", spiders, files, issues))


# ==============================================================================
# DEMO
# ==============================================================================

def demo():
    """Demo the simple terminal."""

    def on_stop():
        print("STOP!")

    def on_input(text):
        if text == "START":
            # Start simulated audit
            thread = threading.Thread(target=simulate_audit, args=(gui,), daemon=True)
            thread.start()

    gui = SimpleTerminalGUI(on_stop=on_stop, on_user_input=on_input, user_name="Blake")
    gui.start()


def simulate_audit(gui: SimpleTerminalGUI):
    """Simulate an audit for demo purposes."""
    time.sleep(1)

    # Spawn spiders
    for i, name in enumerate(AGENT_NAMES[:6]):
        gui.write(f"  [SPAWN] {name} activated!", GREEN_BRIGHT)
        gui.set_stats(i + 1, 0, 0)
        time.sleep(0.3)

    gui.write("")
    gui.write("  All spiders deployed! Let the hunt begin...", GREEN_BRIGHT)
    gui.write("")
    gui.set_phase("SCANNING")

    # Simulate scanning
    files = 0
    issues = 0
    for _ in range(30):
        time.sleep(random.uniform(0.3, 0.8))

        agent = random.choice(AGENT_NAMES[:6])
        msg = random.choice(SPIDER_MESSAGES)
        gui.write_spider(agent, msg)

        files += random.randint(1, 5)
        if random.random() > 0.7:
            issues += 1
            gui.write(f"  [!] Found issue: {random.choice(['Dead code', 'Missing doc', 'Unused import', 'Type error'])}", GREEN_BRIGHT)

        gui.set_stats(6, files, issues)

    # Complete
    gui.set_phase("COMPLETE")
    gui.write("")
    gui.write("  ========================================", GREEN_BRIGHT)
    gui.write("  =       AUDIT COMPLETE                 =", GREEN_BRIGHT)
    gui.write("  ========================================", GREEN_BRIGHT)
    gui.write("")
    gui.write(f"  Files Scanned: {files}", GREEN)
    gui.write(f"  Issues Found: {issues}", GREEN)
    gui.write("")
    gui.write("  Report saved to: audit_output/REPORT.md", GREEN)
    gui.write("")
    gui.write("  Thanks for using CODE-O-MATIC 5000!", GREEN_BRIGHT)
    gui.write("  'Your code is now 100% more audited!'", GREEN_DIM)


if __name__ == "__main__":
    demo()
